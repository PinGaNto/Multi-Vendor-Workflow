"""Recognise which vendor a file came from, and learn each vendor's naming patterns month over month.

The registry (memory/vendor_registry.json) stores per vendor:
  columns          our field -> every column name this vendor has used for it (seeded from config.yaml)
  updated_col      the column(s) holding the record date
  platform_values  how the vendor spells platforms (IG / TT / YT, YouTube, ...)
  filename_tokens  words seen in the vendor's file names
  months_seen      months this vendor's files were processed

Recognition score per vendor (0-1):
  0.75 x header match  (how many of the vendor's known column names appear, and how much of the file they explain)
  0.15 x platform spellings match
  0.10 x file-name words match
A file is assigned when the best score >= 0.55 and beats the runner-up by >= 0.15; otherwise it's flagged.
Renamed columns: a field whose known names are all absent is matched to an unclaimed column by name similarity
(65%) and value type (35%: number / date / text). Matches >= 0.6 are accepted and remembered.
"""
from __future__ import annotations

import difflib
import json
import re
from pathlib import Path

import pandas as pd

MONTH_WORDS = {"jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
               "xlsx", "csv", "xls", "export", "data", "file", "copy", "final"}
NUMERIC_RULES = {"non_negative_int", "int"}


def norm(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def tokens(filename: str) -> set:
    return {t for t in re.split(r"[^a-z]+", Path(filename).stem.lower()) if len(t) > 2 and t not in MONTH_WORDS}


def value_type(series: pd.Series) -> str:
    s = series.dropna().astype(str).str.strip()
    s = s[s != ""].head(200)
    if s.empty:
        return "empty"
    if pd.to_numeric(s, errors="coerce").notna().mean() > 0.8:
        return "number"
    if pd.to_datetime(s, errors="coerce", format="mixed").notna().mean() > 0.8:
        return "date"
    return "text"


class VendorRegistry:
    def __init__(self, path: Path, cfg: dict):
        self.path = Path(path)
        self.cfg = cfg
        seed = self._seed(cfg)
        if self.path.exists():
            self.data = json.loads(self.path.read_text())
            for v, s in seed.items():                       # a vendor added to config later gets seeded
                self.data.setdefault(v, s)
                for f, names in s["columns"].items():
                    self.data[v]["columns"].setdefault(f, names)
        else:
            self.data = seed
        self.field_rules = {**cfg["fields"]["creator"], **cfg["fields"]["channel"], **cfg.get("metric_inputs", {})}

    @staticmethod
    def _seed(cfg):
        out = {}
        for v, spec in cfg["vendors"].items():
            cols = {}
            for src, field in spec["column_map"].items():
                cols.setdefault(field, []).append(src)
            out[v] = {"columns": cols, "updated_col": [spec["last_updated_col"]], "platform_values": [],
                      "filename_tokens": [], "months_seen": [], "learned": []}
        return out

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2))

    # ---------------------------------------------------------------- what kind of file is it?
    def is_request(self, df: pd.DataFrame, key: str, platforms: list, aliases: dict, sheet_names: list) -> bool:
        cols = {norm(c) for c in df.columns}
        if norm(key) not in cols:
            return False
        if any(norm(v["updated_col"][0]) in cols for v in self.data.values()):
            return False
        plat_cols = {norm(p) for p in platforms} | {norm(a) for a in aliases}
        return "Request" in sheet_names or "platform" in cols or bool(cols & plat_cols)

    def _type_expected(self, field: str) -> str:
        if field == "_last_updated":
            return "date"
        rule = self.field_rules.get(field, {}).get("rule")
        if rule in NUMERIC_RULES or field in ("followers_prev",):
            return "number"
        return "text"

    def score(self, vendor: str, df: pd.DataFrame, filename: str) -> dict:
        v = self.data[vendor]
        known = {norm(n) for names in v["columns"].values() for n in names} | {norm(n) for n in v["updated_col"]}
        heads = {norm(c) for c in df.columns}
        hit = known & heads
        header = 0.5 * len(hit) / max(len(known), 1) + 0.5 * len(hit) / max(len(heads), 1)
        parts, weights = [header], [0.75]
        plat_col = next((c for c in df.columns if norm(c) in {norm(n) for n in v["columns"].get("platform", [])}), None)
        if v["platform_values"] and plat_col is not None:
            seen = set(df[plat_col].dropna().astype(str).unique())
            known_vals = set(v["platform_values"])
            parts.append(len(seen & known_vals) / max(len(seen | known_vals), 1))
            weights.append(0.15)
        if v["filename_tokens"]:
            parts.append(1.0 if tokens(filename) & set(v["filename_tokens"]) else 0.0)
            weights.append(0.10)
        total = sum(p * w for p, w in zip(parts, weights)) / sum(weights)
        return {"score": round(total, 3), "header": round(header, 3), "matched_columns": len(hit)}

    def identify(self, df: pd.DataFrame, filename: str) -> dict:
        scores = {v: self.score(v, df, filename) for v in self.data}
        ranked = sorted(scores.items(), key=lambda kv: -kv[1]["score"])
        best, second = ranked[0], ranked[1] if len(ranked) > 1 else (None, {"score": 0})
        ok = best[1]["score"] >= 0.55 and best[1]["score"] - second[1]["score"] >= 0.15
        return {"vendor": best[0] if ok else None, "best_guess": best[0], "confidence": best[1]["score"],
                "runner_up": second[0], "runner_up_score": second[1]["score"],
                "scores": {k: s["score"] for k, s in scores.items()}}

    # ---------------------------------------------------------------- map this file's columns to our fields
    def resolve_columns(self, vendor: str, df: pd.DataFrame) -> dict:
        v = self.data[vendor]
        by_norm = {norm(c): c for c in df.columns}
        mapping, learned, missing = {}, [], []
        claimed = set()
        wanted = dict(v["columns"])
        wanted["_last_updated"] = v["updated_col"]
        for field, names in wanted.items():               # exact (normalised) name matches first
            col = next((by_norm[norm(n)] for n in names if norm(n) in by_norm), None)
            if col is not None:
                mapping[col] = field
                claimed.add(col)
        unresolved = [f for f in wanted if f not in mapping.values()]
        known_elsewhere = {norm(n) for vv in self.data.values() for names in vv["columns"].values() for n in names}
        types = {c: value_type(df[c]) for c in df.columns if c not in claimed}
        candidates = []
        for field in unresolved:
            exp = self._type_expected(field)
            refs = [norm(n) for n in wanted[field]] + [norm(field)]
            for col, t in types.items():
                name_sim = max(difflib.SequenceMatcher(None, norm(col), r).ratio() for r in refs)
                type_ok = 1.0 if t == exp else (0.5 if t == "empty" else 0.0)
                candidates.append((0.65 * name_sim + 0.35 * type_ok, field, col, round(name_sim, 2), t))
        for sc, field, col, name_sim, t in sorted(candidates, reverse=True):     # greedy, one column per field
            if field in mapping.values() or col in claimed or sc < 0.6:
                continue
            mapping[col] = field
            claimed.add(col)
            learned.append({"field": field, "column": col, "score": round(sc, 2), "was": wanted[field]})
        missing = [f for f in wanted if f not in mapping.values()]
        unused = [c for c in df.columns if c not in claimed and norm(c) not in known_elsewhere]
        return {"mapping": mapping, "learned": learned, "missing": missing, "unused": unused}

    # ---------------------------------------------------------------- remember this month
    def learn(self, vendor: str, month: str, df: pd.DataFrame, filename: str, resolved: dict):
        v = self.data[vendor]
        for item in resolved["learned"]:
            target = v["updated_col"] if item["field"] == "_last_updated" else v["columns"].setdefault(item["field"], [])
            if item["column"] not in target:
                target.append(item["column"])
                v["learned"].append({"month": month, **{k: item[k] for k in ("field", "column", "score")}})
        plat_col = next((c for c, f in resolved["mapping"].items() if f == "platform"), None)
        if plat_col is not None:
            v["platform_values"] = sorted(set(v["platform_values"]) | set(df[plat_col].dropna().astype(str).unique()))
        v["filename_tokens"] = sorted(set(v["filename_tokens"]) | tokens(filename))
        if month not in v["months_seen"]:
            v["months_seen"] = sorted(v["months_seen"] + [month])
