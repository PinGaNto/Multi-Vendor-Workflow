"""Vendor QA -> tiering -> waterfall fill -> Pulse / Lens / Hub scoring, scoped to a per-run creator request list.

Stages
  0. Request          : read the uploaded request list (which creators, which channels)
  1. Ingest & map     : read each vendor file, rename columns, normalise platforms, fix formats, derive inputs
  2. QA & score       : measured ONLY on requested creator + channel pairs, including whether each vendor
                        can supply the three metrics
  3. Tiering          : rank vendors by score; drop vendors under the quality floor
  4. Waterfall        : for tier 1..N: gate -> prepare (drop stale/invalid, compute metrics inside each vendor
                        record, dedupe) -> fill empty cells / metrics only -> re-assess -> stop or continue
  5. Scoring          : per channel, percentile of each metric within its platform (growth also within
                        follower-size band); per creator, the average over requested channels -> Pulse, Lens, Hub
  6. Report           : Excel workbook, leaderboard page, CSVs, markdown + JSON run report

Usage:  python pipeline.py [--config config.yaml]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
COUNTRY_NAMES = {"united states": "US", "united kingdom": "GB", "canada": "CA", "brazil": "BR", "india": "IN",
                 "germany": "DE", "france": "FR", "japan": "JP", "mexico": "MX", "south korea": "KR"}
NO = {"", "n", "no", "0", "false", "-", "—"}
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


# ----------------------------------------------------------------------------- io
def read_table(path: Path, sheet=0) -> pd.DataFrame:
    """Read an Excel sheet or CSV as text, keeping literal values like 'n/a' so rules can flag them."""
    path = Path(path)
    if path.suffix.lower() in {".xlsx", ".xlsm", ".xls"}:
        if isinstance(sheet, str) and sheet not in pd.ExcelFile(path).sheet_names:
            sheet = 0
        df = pd.read_excel(path, sheet_name=sheet, dtype=object, keep_default_na=False, na_values=[""])
        return df.apply(lambda col: col.map(lambda v: v if pd.isna(v) else
                                            (v.isoformat() if hasattr(v, "isoformat") else
                                             (str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)))))
    return pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""])


# ----------------------------------------------------------------------------- rules & transforms
def is_valid(value, rule) -> bool:
    if value is None or value is pd.NA or (isinstance(value, float) and pd.isna(value)):
        return False
    if rule == "non_empty":
        return str(value).strip() != ""
    if rule == "iso2":
        return bool(re.fullmatch(r"[A-Z]{2}", str(value)))
    if rule == "email":
        return bool(EMAIL_RE.match(str(value)))
    if rule in ("non_negative_int", "int"):
        try:
            f = float(value)
            return f == int(f) and (rule == "int" or f >= 0)
        except (TypeError, ValueError, OverflowError):
            return False
    if isinstance(rule, dict) and "one_of" in rule:
        return value in rule["one_of"]
    raise ValueError(f"Unknown rule {rule}")


def apply_transform(series: pd.Series, spec) -> pd.Series:
    if spec == "lowercase":
        return series.map(lambda v: v.lower() if isinstance(v, str) else v)
    if spec == "uppercase":
        return series.map(lambda v: v.upper() if isinstance(v, str) else v)
    if spec == "country_name_to_iso2":
        return series.map(lambda v: COUNTRY_NAMES.get(v.strip().lower(), v) if isinstance(v, str) else v)
    if isinstance(spec, dict) and "multiply" in spec:
        return pd.to_numeric(series, errors="coerce").mul(spec["multiply"]).round()
    raise ValueError(f"Unknown transform {spec}")


def fmt_metric(v, display) -> str:
    if v is None or pd.isna(v):
        return ""
    if display == "multiple":
        return f"{v:.1f}x"
    if display == "percent_signed":
        return f"{v:+.1%}"
    return f"{v:.1%}"


# ----------------------------------------------------------------------------- data classes
@dataclass
class VendorProfile:
    name: str
    rows: int
    rows_not_needed: int
    duplicate_rate: float
    coverage: float
    usable_coverage: float
    completeness: float
    freshness: float
    validity: float
    format_fixes: int
    field_completeness: dict
    platform_coverage: dict
    implausible_values: int = 0
    consistency: float = 1.0
    score: float = 0.0
    tier: int | None = None
    excluded_reason: str | None = None
    current_score: float = 0.0
    history_score: float | None = None
    history_months: int = 0
    history_trend: list = field(default_factory=list)
    qa_avg_3m: float | None = None
    review_accuracy: float | None = None
    disputes_reviewed: int = 0


@dataclass
class Agent:
    """Decision layer. Rule-based here; each decision is logged with its evidence so an LLM
    reviewer (or a human) can be added at the same decision points later."""
    log: list = field(default_factory=list)

    def decide(self, step: str, observation: dict, decision: str, reason: str):
        self.log.append({"step": step, "observation": observation, "decision": decision, "reason": reason})
        print(f"[agent] {step}: {decision} — {reason}")


# ----------------------------------------------------------------------------- pipeline
class Pipeline:
    def __init__(self, cfg_path: Path = ROOT / "config.yaml", inbox: Path | None = None, files: list | None = None,
                 month: str | None = None, out_dir: Path | None = None, memory_dir: Path | None = None,
                 assign: dict | None = None, auto_finalize: bool = True):
        """inbox: a folder holding this month's drop (request list + vendor files, any file names).
        files: alternatively, a list of file paths (the upload app). assign: {file name: vendor} manual overrides.
        month: 'YYYY-MM' (defaults to the inbox folder name, else the current month)."""
        self.cfg = yaml.safe_load(Path(cfg_path).read_text())
        paths = list(files or [])
        if inbox:
            paths += sorted(f for f in Path(inbox).iterdir() if f.suffix.lower() in {".xlsx", ".xls", ".csv"}
                            and not f.name.startswith(("~$", ".")))
        self.input_paths = [Path(f) for f in paths]
        self.assign = assign or {}
        self.auto_finalize = auto_finalize
        guess = Path(inbox).name if inbox and re.fullmatch(r"\d{4}-\d{2}", Path(inbox).name) else None
        self.month = month or guess or date.today().strftime("%Y-%m")
        self.run_date = pd.Period(self.month, "M").end_time.normalize()          # freshness measured at month end
        self.out_dir = Path(out_dir or ROOT / "output" / self.month)
        mem = Path(memory_dir or ROOT / self.cfg.get("memory_dir", "memory"))
        from memory import CreatorHistory, VendorHistory
        from vendor_registry import VendorRegistry
        self.registry = VendorRegistry(mem / "vendor_registry.json", self.cfg)
        self.vendor_history = VendorHistory(mem / "vendor_history.csv")
        self.creator_history = CreatorHistory(mem / "creator_history.csv")
        self.files = {}
        from qa_checks import FlagBook
        self.flags = FlagBook(self.cfg)
        self.excluded_rows: set = set()        # (vendor, creator_id, platform) rows not used (identity check / review)
        self.blocked_pairs: set = set()        # (creator_id, platform) held back for identity review
        self.blocked_fields: dict = {}         # (creator_id, platform) -> {field: flag id} held back for review
        self.status = "new"
        self.tiers = []
        self.key = self.cfg["key"]
        self.platforms = self.cfg["platforms"]
        self.aliases = {p: p for p in self.platforms}
        self.aliases.update({str(k).lower(): v for k, v in self.cfg.get("platform_aliases", {}).items()})
        self.cr_fields = self.cfg["fields"]["creator"]
        self.ch_fields = self.cfg["fields"]["channel"]
        self.fields = {**self.cr_fields, **self.ch_fields}
        self.inputs = self.cfg.get("metric_inputs", {})
        self.metrics = self.cfg.get("metrics", {})
        self.cr_required = [f for f, s in self.cr_fields.items() if s["required"]]
        self.ch_required = [f for f, s in self.ch_fields.items() if s["required"]] + \
                           [m for m, s in self.metrics.items() if s.get("required")]
        self.required = self.cr_required + self.ch_required
        self.ch_values = list(self.ch_fields) + list(self.metrics)          # what gets filled per channel
        self.sla = self.cfg["qa"]["freshness_sla_days"]
        self.agent = Agent()
        self.vendor_frames: dict[str, pd.DataFrame] = {}
        self.profiles: dict[str, VendorProfile] = {}

    def norm_platform(self, v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        s = str(v).strip().lower()
        return self.aliases.get(s, s)

    # 0a. recognise this month's files --------------------------------------------
    def recognise(self):
        self.recognition = []
        self.vendor_inputs = {}
        req = []
        for f in self.input_paths:
            df = read_table(f, "Request")
            sheets = pd.ExcelFile(f).sheet_names if f.suffix.lower() != ".csv" else []
            if self.registry.is_request(df, self.key, self.platforms, self.aliases, sheets):
                req.append(f)
                self.recognition.append({"file": f.name, "kind": "request list", "vendor": "", "confidence": 1.0})
                continue
            df = read_table(f)
            idr = self.registry.identify(df, f.name)
            vendor = self.assign.get(f.name) or idr["vendor"]
            row = {"file": f.name, "kind": "vendor file", "vendor": vendor or "", "confidence": idr["confidence"],
                   "scores": idr["scores"], "manual": f.name in self.assign}
            if vendor is None:
                self.agent.decide("recognise", {"file": f.name, **idr}, "flag",
                                  f"couldn't tell which vendor sent {f.name} (closest: {idr['best_guess']} "
                                  f"{idr['confidence']:.2f}, then {idr['runner_up']} {idr['runner_up_score']:.2f}); "
                                  f"skipped. Assign it manually to use it.")
                row["kind"] = "unrecognised"
                self.recognition.append(row)
                continue
            if vendor in self.vendor_inputs:
                prev = self.vendor_inputs[vendor]
                if idr["confidence"] <= prev["confidence"]:
                    self.agent.decide("recognise", {"file": f.name}, "flag",
                                      f"{f.name} also looks like {vendor}; kept {prev['path'].name} (stronger match)")
                    row["kind"] = "duplicate"
                    self.recognition.append(row)
                    continue
            resolved = self.registry.resolve_columns(vendor, df)
            self.vendor_inputs[vendor] = {"path": f, "df": df, "confidence": idr["confidence"], "resolved": resolved}
            row.update({"learned": resolved["learned"], "missing": resolved["missing"], "unused": resolved["unused"]})
            self.recognition.append(row)
            how = "assigned manually" if f.name in self.assign else f"matched {idr['confidence']:.0%}"
            self.agent.decide("recognise", {"file": f.name, "vendor": vendor, **idr}, f"{vendor}",
                              f"{f.name} → {vendor} ({how}; next best {idr['runner_up']} {idr['runner_up_score']:.0%})")
            for l in resolved["learned"]:
                self.agent.decide("learn", {"vendor": vendor, **l}, "new column name",
                                  f"{vendor} now calls {l['field']} '{l['column']}' (was {', '.join(l['was'])}); "
                                  f"matched by name and value type ({l['score']:.0%}) and remembered")
            if resolved["missing"]:
                self.agent.decide("learn", {"vendor": vendor, "missing": resolved["missing"]}, "flag",
                                  f"{vendor}'s file has no column for {', '.join(resolved['missing'])}")
            if resolved["unused"]:
                self.agent.decide("learn", {"vendor": vendor, "unused": resolved["unused"]}, "note",
                                  f"{vendor} sent new column(s) we don't use: {', '.join(resolved['unused'])}")
        if not req:
            raise ValueError("No creator request list found among the files. Include the filled request template.")
        if len(req) > 1:
            raise ValueError(f"More than one request list found: {[f.name for f in req]}. Keep one per month.")
        if not self.vendor_inputs:
            raise ValueError("None of the files could be matched to a vendor.")
        self.files["request"] = req[0]
        missing_vendors = [v for v in self.cfg["vendors"] if v not in self.vendor_inputs]
        if missing_vendors:
            self.agent.decide("recognise", {"missing": missing_vendors}, "note",
                              f"no file this month from {', '.join(missing_vendors)}; running without it")

    # 0. request ----------------------------------------------------------------
    def load_request(self):
        raw = read_table(self.files["request"], self.cfg["request"].get("sheet", 0))
        raw.columns = [str(c).strip() for c in raw.columns]
        if self.key not in raw.columns:
            raise ValueError(f"Request list needs a '{self.key}' column. Found: {list(raw.columns)}")
        raw = raw[raw[self.key].notna() & (raw[self.key].astype(str).str.strip() != "")].copy()
        raw[self.key] = raw[self.key].astype(str).str.strip()
        if raw.empty:
            raise ValueError("The request list has no creators. Add one row per creator on the Request sheet.")
        if "platform" in [c.lower() for c in raw.columns]:                       # long format
            pcol = next(c for c in raw.columns if c.lower() == "platform")
            pairs = pd.DataFrame({self.key: raw[self.key], "platform": raw[pcol].map(self.norm_platform)})
        else:                                                                   # wide format: Y per channel
            pcols = {c: self.norm_platform(c) for c in raw.columns if self.norm_platform(c) in self.platforms}
            if not pcols:
                raise ValueError(f"Request list has no channel columns. Expected some of {self.platforms}.")
            long = raw.melt(id_vars=[self.key], value_vars=list(pcols), var_name="col", value_name="mark")
            long = long[long["mark"].map(lambda v: not pd.isna(v) and str(v).strip().lower() not in NO)]
            pairs = pd.DataFrame({self.key: long[self.key], "platform": long["col"].map(pcols)})
        unknown = sorted(set(pairs["platform"].dropna()) - set(self.platforms))
        pairs = pairs[pairs["platform"].isin(self.platforms)].drop_duplicates()
        if pairs.empty:
            raise ValueError("The request list has no channels marked. Put Y under the channels you need.")
        self.req_pairs = pairs.sort_values([self.key, "platform"]).reset_index(drop=True)
        self.req_creators = pd.Index(self.req_pairs[self.key].unique(), name=self.key)
        self.req_pair_index = pd.MultiIndex.from_frame(self.req_pairs)
        no_channel = sorted(set(raw[self.key]) - set(self.req_creators))
        mix = self.req_pairs["platform"].value_counts().reindex(self.platforms, fill_value=0).to_dict()
        self.request_mix = {k: int(v) for k, v in mix.items()}
        shape = self.req_pairs.groupby(self.key).size().value_counts().sort_index(ascending=False)
        self.request_shape = {int(k): int(v) for k, v in shape.items()}      # {channels requested: creators}
        self.agent.decide("request", {"creators": len(self.req_creators), "channels": len(self.req_pairs),
                                      "by_platform": self.request_mix, "creators_without_channels": no_channel[:20],
                                      "unknown_platforms": unknown},
                          "accept", f"{len(self.req_creators)} creators, {len(self.req_pairs)} channels requested ("
                          + ", ".join(f"{p} {n}" for p, n in self.request_mix.items() if n) + "); "
                          + ", ".join(f"{v} need {k} channel{'s' if k > 1 else ''}" for k, v in self.request_shape.items())
                          + (f"; {len(no_channel)} creators had no channel marked and were skipped" if no_channel else "")
                          + (f"; ignored unknown channels {unknown}" if unknown else ""))

    # 1. ingest & map -------------------------------------------------------------
    def ingest(self):
        for name, inp in self.vendor_inputs.items():
            v = self.cfg["vendors"][name]
            raw, mapping = inp["df"], inp["resolved"]["mapping"]
            for need in (self.key, "platform", "_last_updated"):
                if need not in mapping.values():
                    raise ValueError(f"{name}: no column found for {need} in {inp['path'].name}. Columns: {list(raw.columns)}")
            df = raw.rename(columns=mapping)
            df["_last_updated"] = pd.to_datetime(df["_last_updated"], errors="coerce", format="mixed")
            df[self.key] = df[self.key].astype(str).str.strip()
            normed = df["platform"].map(self.norm_platform)
            fixes = int((df["platform"].astype(str) != normed.astype(str)).sum())
            df["platform"] = normed
            for col, spec in self.cfg.get("transforms", {}).get(name, {}).items():
                before = df[col].copy()
                df[col] = apply_transform(df[col], spec)
                fixes += int((before.astype(str) != df[col].astype(str)).sum())
            prec = v.get("precision") or {}
            for col, expr in (v.get("derive") or {}).items():
                names = [n for n in IDENT.findall(expr) if n in df.columns]
                num = df[names].apply(pd.to_numeric, errors="coerce")
                df[col] = num.eval(expr)
                fixes += int(df[col].notna().sum())
                if any(n in prec for n in names):        # rounding errors add up in sums and differences
                    prec[col] = sum(prec.get(n, 0) for n in names)
            # hidden like counts arrive as text; keep them as a flag, not as a bad number
            if "likes_90d" in df.columns:
                df["likes_hidden"] = df["likes_90d"].astype(str).str.strip().str.lower().eq("hidden")
                df.loc[df["likes_hidden"], "likes_90d"] = None
            else:
                df["likes_hidden"] = False
            for f in [*self.fields, *self.inputs]:
                if f not in df.columns:
                    df[f] = None
            err_cols = []
            for col, e in prec.items():
                if col in [*self.fields, *self.inputs]:
                    df[f"_abs_err_{col}"] = float(e)
                    err_cols.append(f"_abs_err_{col}")
            df = df[[self.key, "platform", *self.fields, *self.inputs, "likes_hidden", "_last_updated", *err_cols]].copy()
            df.attrs["format_fixes"] = fixes
            df.attrs["missing_inputs"] = [f for f in self.inputs if f not in raw.rename(columns=mapping).columns
                                          and f not in (v.get("derive") or {})]
            self.vendor_frames[name] = df

    def _is_fresh(self, df):
        return (self.run_date - df["_last_updated"]).dt.days <= self.sla

    def _clean(self, df: pd.DataFrame) -> pd.DataFrame:
        """Null out values that break their rule (fields and metric inputs)."""
        df = df.copy()
        for f, s in {**self.fields, **self.inputs}.items():
            df[f] = df[f].where(df[f].map(lambda v, r=s["rule"]: is_valid(v, r)))
        return df

    def _metrics(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute each metric inside each vendor record. Adds <metric> and _diag_<metric> columns."""
        df = df.copy()
        for m, spec in self.metrics.items():
            val = pd.Series(np.nan, index=df.index)
            diag = pd.Series("ok", index=df.index, dtype=object)
            for plat, rows in df.groupby("platform"):
                formula = (spec.get("by_platform") or {}).get(plat, spec["formula"])
                names = sorted(set(IDENT.findall(formula)))
                num = rows[names].apply(pd.to_numeric, errors="coerce")
                with np.errstate(divide="ignore", invalid="ignore"):
                    v = num.eval(formula).replace([np.inf, -np.inf], np.nan)
                miss = num.isna()
                d = miss.apply(lambda r: "missing " + ", ".join(c for c in names if r[c]) if r.any() else "ok", axis=1)
                if spec.get("needs_visible_likes"):
                    d = d.where(~rows["likes_hidden"], "likes hidden")
                lo, hi = spec.get("bounds", [-np.inf, np.inf])
                out = v.notna() & ((v < lo) | (v > hi))
                d = d.where(~out, "implausible value")
                # rounding check: relative error of each input (abs error / |value|); errors add for a ratio
                rel = pd.Series(0.0, index=rows.index)
                for n in names:
                    if f"_abs_err_{n}" in rows.columns:
                        rel = rel + rows[f"_abs_err_{n}"] / num[n].abs().replace(0, np.nan)
                imprecise = v.notna() & (rel.fillna(np.inf) > self.cfg["qa"].get("max_rounding_error", 0.05))
                d = d.where(~imprecise | (d != "ok"), "imprecise (rounded counts)")
                v = v.where(d == "ok")
                val.loc[rows.index], diag.loc[rows.index] = v, d
            df[m], df[f"_diag_{m}"] = val, diag
        return df

    # 2. QA & score (requested scope only) ----------------------------------------
    def qa(self):
        w = self.cfg["qa"]["weights"]
        req = set(map(tuple, self.req_pairs[[self.key, "platform"]].to_numpy()))
        req_by_p = self.req_pairs.groupby("platform").size()
        for name, df in self.vendor_frames.items():
            pair = list(zip(df[self.key], df["platform"]))
            in_scope = pd.Series([p in req for p in pair], index=df.index)
            fresh = self._is_fresh(df)
            rel_ch = df[in_scope]
            rel_cr = df[df[self.key].isin(self.req_creators)]
            have = set(zip(rel_ch[self.key], rel_ch["platform"]))
            rf = rel_ch[fresh[in_scope]]
            have_fresh = set(zip(rf[self.key], rf["platform"]))
            scored = self._metrics(self._clean(rel_ch))
            fc = {f: round(float(rel_cr[f].notna().mean()), 4) if len(rel_cr) else 0.0 for f in self.cr_fields}
            fc.update({f: round(float(rel_ch[f].notna().mean()), 4) if len(rel_ch) else 0.0 for f in self.ch_fields})
            fc.update({m: round(float(scored[m].notna().mean()), 4) if len(scored) else 0.0 for m in self.metrics})
            prof_consistency = self.consistency.get(name, 1.0)
            vh = sum(rel_ch[f].map(lambda v, r=s["rule"]: is_valid(v, r)).sum()
                     for f, s in {**self.ch_fields, **self.inputs}.items()) + \
                sum(rel_cr[f].map(lambda v, r=s["rule"]: is_valid(v, r)).sum() for f, s in self.cr_fields.items())
            nn = sum(rel_ch[f].notna().sum() for f in [*self.ch_fields, *self.inputs]) + \
                sum(rel_cr[f].notna().sum() for f in self.cr_fields)
            implausible = int(sum((scored[f"_diag_{m}"] == "implausible value").sum() for m in self.metrics))
            imprecise = int(sum((scored[f"_diag_{m}"] == "imprecise (rounded counts)").sum() for m in self.metrics))
            pc = {p: round(sum(1 for k in have_fresh if k[1] == p) / req_by_p[p], 4) for p in req_by_p.index}
            prof = VendorProfile(
                name=name, rows=len(df), rows_not_needed=int((~in_scope).sum()),
                duplicate_rate=round(1 - len(set(pair)) / len(df), 4) if len(df) else 0.0,
                coverage=round(len(have) / len(req), 4), usable_coverage=round(len(have_fresh) / len(req), 4),
                completeness=round(sum(fc[f] for f in self.required) / len(self.required), 4),
                freshness=round(float(fresh[in_scope].mean()), 4) if len(rel_ch) else 0.0,
                validity=round(float(vh - implausible) / nn, 4) if nn else 0.0, format_fixes=df.attrs["format_fixes"],
                field_completeness=fc, platform_coverage=pc, implausible_values=implausible,
                consistency=prof_consistency)
            prof.current_score = round(sum(getattr(prof, k) * wt for k, wt in w.items()), 4)
            hw = self.cfg["qa"].get("history_weight", 0.15)
            rel = self.vendor_history.reliability(name, self.month, Path(self.registry.path).parent / "review_audit.csv",
                                                  self.cfg["qa"])
            hist, n_hist, trend = rel["score"], rel["months"], rel["trend"]
            prof.history_score, prof.history_months, prof.history_trend = hist, n_hist, trend
            prof.qa_avg_3m, prof.review_accuracy, prof.disputes_reviewed = rel["qa_avg"], rel["review_accuracy"], rel["disputes"]
            prof.score = round((1 - hw) * prof.current_score + hw * hist, 4) if hist is not None else prof.current_score
            self.profiles[name] = prof
            if hist is None:
                self.agent.decide("history", {"vendor": name}, "no history",
                                  f"{name}: first month on record, scored on this month only ({prof.current_score:.2f})")
            else:
                direction = "down" if prof.current_score < hist - 0.02 else "up" if prof.current_score > hist + 0.02 else "steady"
                acc = (f", review accuracy {prof.review_accuracy:.0%} over {prof.disputes_reviewed} reviewed dispute(s)"
                       if prof.review_accuracy is not None else ", no reviewed disputes")
                self.agent.decide("history", {"vendor": name, "trend": trend}, "blend",
                                  f"{name}: this month {prof.current_score:.2f}; {n_hist}-month reliability {hist:.2f} "
                                  f"(QA average {prof.qa_avg_3m:.2f}{acc}; {direction}) → blended {prof.score:.2f} "
                                  f"at {hw:.0%} reliability weight")
            if df.attrs["missing_inputs"]:
                self.agent.decide("qa", {"vendor": name, "missing_inputs": df.attrs["missing_inputs"]}, "note",
                                  f"{name} doesn't supply {', '.join(df.attrs['missing_inputs'])}; metrics that need "
                                  f"it can't come from {name} (except where a platform override doesn't use it)")
            if imprecise:
                self.agent.decide("qa", {"vendor": name, "imprecise_values": imprecise}, "flag",
                                  f"{name}: {imprecise} metric values rejected because rounded counts could move them "
                                  f"by more than {self.cfg['qa'].get('max_rounding_error', 0.05):.0%}; "
                                  f"a lower tier fills them if it can")
            if implausible:
                self.agent.decide("qa", {"vendor": name, "implausible_values": implausible}, "flag",
                                  f"{name}: {implausible} metric values outside plausible bounds were rejected")

    # 3. tiering ------------------------------------------------------------------
    def assign_tiers(self):
        floor = self.cfg["qa"]["min_score_to_use"]
        tier = 1
        for p in sorted(self.profiles.values(), key=lambda p: p.score, reverse=True):
            if p.score < floor:
                p.excluded_reason = f"score {p.score:.2f} below floor {floor}"
                self.agent.decide("tiering", {"vendor": p.name, "score": p.score}, "exclude", p.excluded_reason)
                continue
            p.tier = tier
            best = max(p.platform_coverage, key=p.platform_coverage.get) if p.platform_coverage else "-"
            mcomp = ", ".join(f"{self.metrics[m]['pillar']} {p.field_completeness[m]:.0%}" for m in self.metrics)
            self.agent.decide("tiering", {"vendor": p.name, "score": p.score, "platform_coverage": p.platform_coverage},
                              f"tier {tier}",
                              f"score {p.score:.2f}: fresh coverage {p.usable_coverage:.0%} of requested channels "
                              f"(strongest on {best} {p.platform_coverage.get(best, 0):.0%}), freshness "
                              f"{p.freshness:.0%}, metrics computable: {mcomp}")
            tier += 1
        self.tiers = [p.name for p in sorted(self.profiles.values(), key=lambda p: p.tier or 99) if p.tier]

    # 4. waterfall ----------------------------------------------------------------
    def _prepare(self, name: str, respect_exclusions: bool = True):
        """Tier prep: drop excluded rows (identity check), stale records and invalid cells, compute metrics, dedupe."""
        df = self.vendor_frames[name].sort_values("_last_updated")
        if respect_exclusions and self.excluded_rows:
            keep = [(name, k, pl) not in self.excluded_rows for k, pl in zip(df[self.key], df["platform"])]
            df = df[keep]
        if not self.cfg["waterfall"]["allow_stale_values"]:
            df = df[self._is_fresh(df)]
        df = self._metrics(self._clean(df))
        diag = [f"_diag_{m}" for m in self.metrics]
        ch = df.drop_duplicates([self.key, "platform"], keep="last").set_index([self.key, "platform"])[self.ch_values + diag]
        cr = df.groupby(self.key)[list(self.cr_fields)].last()
        return cr.reindex(self.req_creators), ch.reindex(self.req_pair_index)

    @staticmethod
    def filled(tbl: pd.DataFrame, f: str) -> pd.Series:
        """A value counts as filled if present, or marked not applicable (e.g. Hub for hidden likes)."""
        src = tbl.get(f"{f}__source")
        na = src.astype(str).str.startswith("n/a") if src is not None else False
        return tbl[f].notna() | na

    def _assess(self) -> dict:
        cr, ch = self.out_cr, self.out_ch
        fill = {f: round(float(cr[f].notna().mean()), 4) for f in self.cr_fields}
        fill.update({f: round(float(self.filled(ch, f).mean()), 4) for f in self.ch_values})
        ch_ok = pd.concat([self.filled(ch, f) for f in self.ch_required], axis=1).all(axis=1)
        by_p = {k: round(float(v), 4) for k, v in ch_ok.groupby(level="platform").mean().items()}
        chans_ok = ch_ok.groupby(level=self.key).all()
        creators_ok = cr[self.cr_required].notna().all(axis=1) & chans_ok.reindex(cr.index, fill_value=False)
        n_req = ch_ok.groupby(level=self.key).size().reindex(cr.index)
        by_n = {int(k): round(float(v), 4) for k, v in creators_ok.groupby(n_req).mean().items()}
        return {"creators_complete_by_n_channels": by_n,"field_fill_rate": fill, "channels_complete": round(float(ch_ok.mean()), 4),
                "channels_complete_by_platform": by_p, "creators_complete": round(float(creators_ok.mean()), 4),
                "open_cells": int(cr[list(self.cr_fields)].isna().sum().sum()
                                  + sum((~self.filled(ch, f)).sum() for f in self.ch_values))}

    def waterfall(self):
        wf = self.cfg["waterfall"]
        self.out_cr = pd.DataFrame(index=self.req_creators)
        self.out_ch = pd.DataFrame(index=self.req_pair_index)
        for tbl, flds in [(self.out_cr, list(self.cr_fields)), (self.out_ch, self.ch_values)]:
            for f in flds:
                tbl[f] = pd.Series(pd.NA, index=tbl.index, dtype=object)
                tbl[f"{f}__source"] = pd.Series(pd.NA, index=tbl.index, dtype=object)
        self.tier_results = []
        state = self._assess()

        for i, name in enumerate(self.tiers, start=1):
            short = {f: state["field_fill_rate"][f] for f in self.required
                     if state["field_fill_rate"][f] < wf["required_field_target"]}
            if i > 1 and not short:
                self.agent.decide(f"gate tier {i}", {"required_fill": state["field_fill_rate"]}, "stop",
                                  f"all required fields and metrics >= {wf['required_field_target']:.0%}; "
                                  f"{name} not needed")
                break
            cr_v, ch_v = self.prepared[name]
            gain = {f: int((self.out_cr[f].isna() & cr_v[f].notna()).sum()) for f in self.cr_fields}
            gain.update({f: int((~self.filled(self.out_ch, f) & ch_v[f].notna()).sum()) for f in self.ch_values})
            gain_rate = sum(gain.values()) / max(state["open_cells"], 1)
            if i > 1 and gain_rate < wf["min_expected_gain"]:
                self.agent.decide(f"gate tier {i}", {"expected_fillable_cells": gain}, "skip",
                                  f"{name} would fill only {gain_rate:.2%} of open cells")
                continue
            self.agent.decide(f"gate tier {i}",
                              {"below_target": short or "n/a (first tier)", "expected_fillable_cells": gain},
                              f"use {name}", "first tier" if i == 1 else
                              f"{len(short)} required item(s) below target ({', '.join(short)}); {name} can fill "
                              f"{sum(gain.values())} open cells ({gain_rate:.1%})")
            for tbl, src, flds in [(self.out_cr, cr_v, list(self.cr_fields)), (self.out_ch, ch_v, self.ch_values)]:
                for f in flds:
                    m = ~self.filled(tbl, f) & src[f].notna()
                    tbl.loc[m, f] = src.loc[m, f]
                    tbl.loc[m, f"{f}__source"] = name
            for mtr in self.metrics:     # hidden likes: metric not applicable, not missing
                na = ~self.filled(self.out_ch, mtr) & ch_v[f"_diag_{mtr}"].eq("likes hidden")
                self.out_ch.loc[na, f"{mtr}__source"] = f"n/a (likes hidden, {name})"
            before, state = state, self._assess()
            self.tier_results.append({"tier": i, "vendor": name, "cells_filled": gain, "before": before, "after": state})
            more = any(state["field_fill_rate"][f] < wf["required_field_target"] for f in self.required)
            self.agent.decide(f"assess after tier {i}",
                              {"creators_complete": state["creators_complete"],
                               "channels_complete_by_platform": state["channels_complete_by_platform"]},
                              "continue" if more and i < len(self.tiers) else "done",
                              f"{state['creators_complete']:.1%} of creators complete, "
                              f"{state['channels_complete']:.1%} of requested channels complete")
        self.final = state

    # 5. scoring ------------------------------------------------------------------
    def size_band(self, followers):
        if followers is None or pd.isna(followers):
            return None
        bands = sorted(self.cfg["size_bands"].items(), key=lambda kv: kv[1])
        return [b for b, lo in bands if float(followers) >= lo][-1]

    def score(self):
        """Percentile of each metric among requested channels on the same platform (and size band where set)."""
        ch = self.out_ch.copy()
        ch["size_band"] = ch["follower_count"].map(self.size_band)
        plat = ch.index.get_level_values("platform")
        min_peers = self.cfg.get("min_peers_for_band", 8)
        self.peer_groups = {}
        for m, spec in self.metrics.items():
            v = pd.to_numeric(ch[m], errors="coerce")
            pct = pd.Series(np.nan, index=ch.index)
            group = pd.Series("", index=ch.index, dtype=object)
            for p in self.platforms:
                on_p = (plat == p) & v.notna()
                if spec.get("compare_within_size_band"):
                    for band, idx in ch[on_p].groupby("size_band").groups.items():
                        if len(idx) >= min_peers:
                            pct.loc[idx] = v.loc[idx].rank(pct=True) * 100
                            group.loc[idx] = f"{p} · {band}"
                    left = on_p & pct.isna()
                    if left.any():   # bands too small to compare within
                        pct.loc[left] = v[on_p].rank(pct=True)[left[on_p]] * 100
                        group.loc[left] = f"{p} (band too small)"
                elif on_p.any():
                    pct.loc[on_p] = v[on_p].rank(pct=True) * 100
                    group.loc[on_p] = p
            ch[f"{m}__pct"] = pct.round(1)
            ch[f"{m}__peers"] = group
        self.scored_ch = ch
        cols = [f"{m}__pct" for m in self.metrics]
        cr = ch[cols].groupby(level=self.key).mean().round(1)
        cr.columns = list(self.metrics)
        pillars = {m: s["pillar"] for m, s in self.metrics.items()}
        has = cr[list(self.metrics)].notna().any(axis=1)
        cr["primary_role"] = cr[list(self.metrics)].fillna(-1).idxmax(axis=1).map(pillars).where(has)
        self.creator_scores = cr

    # 6. outputs ------------------------------------------------------------------
    def build_leaderboard(self) -> pd.DataFrame:
        """Creators whose details and every requested channel (incl. metrics) are complete."""
        conf = {1: "High", 2: "Medium", 3: "Low"}
        tier_of = {n: i for i, n in enumerate(self.tiers, start=1)}
        ch = self.scored_ch.reset_index()
        filled = pd.concat([self.filled(ch, f) for f in self.ch_required], axis=1).all(axis=1)
        ok_ch = filled.groupby(ch[self.key]).all()
        ok = self.out_cr[self.cr_required].notna().all(axis=1) & ok_ch.reindex(self.out_cr.index, fill_value=False)
        ch = ch[ch[self.key].isin(ok[ok].index)].copy()
        src_cols = [f"{c}__source" for c in ["follower_count", *self.metrics]]
        ch["worst_tier"] = ch[src_cols].apply(lambda r: max(tier_of.get(s, 3) for s in r
                                                         if not str(s).startswith("n/a")), axis=1)
        lb = self.out_cr.loc[ok[ok].index, list(self.cr_fields)].copy()
        g = ch.groupby(self.key)
        lb["channels"] = g["platform"].apply(lambda s: [p for p in self.platforms if p in set(s)])
        lb["total_followers"] = g["follower_count"].apply(lambda s: int(sum(float(x) for x in s)))
        lb["confidence"] = g["worst_tier"].max().map(lambda t: conf.get(t, "Low"))
        lb["sources"] = g.apply(lambda d: ", ".join(sorted({s for c in src_cols for s in d[c]
                                                            if not str(s).startswith("n/a")})), include_groups=False)
        detail = {}
        for k, d in g:
            detail[k] = {r["platform"]: {"handle": r["handle"], "followers": int(float(r["follower_count"])),
                                         "band": r["size_band"],
                                         **{m: None if pd.isna(r[m]) else float(r[m]) for m in self.metrics},
                                         **{f"{m}__pct": None if pd.isna(r[f"{m}__pct"]) else float(r[f"{m}__pct"])
                                            for m in self.metrics}}
                         for _, r in d.iterrows()}
        lb["detail"] = pd.Series(detail)
        lb = lb.join(self.creator_scores)
        return lb.reset_index().sort_values(list(self.metrics)[0], ascending=False).reset_index(drop=True)

    def build_channel_leaderboard(self) -> pd.DataFrame:
        """One row per COMPLETE requested channel, so a channel ranks even if the creator's other channels don't."""
        conf = {1: "High", 2: "Medium", 3: "Low"}
        tier_of = {n: i for i, n in enumerate(self.tiers, start=1)}
        ch = self.scored_ch
        ok = pd.concat([self.filled(ch, f) for f in self.ch_required], axis=1).all(axis=1)
        out = ch[ok].reset_index().join(self.out_cr[list(self.cr_fields)], on=self.key)
        src_cols = [f"{c}__source" for c in ["follower_count", *self.metrics]]
        real = lambda r: [s for s in r if not str(s).startswith("n/a")]
        out["confidence"] = out[src_cols].apply(lambda r: conf.get(max(tier_of.get(s, 3) for s in real(r)), "Low"), axis=1)
        out["sources"] = out[src_cols].apply(lambda r: ", ".join(sorted(set(real(r)))), axis=1)
        out["follower_count"] = out["follower_count"].astype(float).astype(int)
        pct = out[[f"{m}__pct" for m in self.metrics]]
        pct.columns = list(self.metrics)
        has = pct.notna().any(axis=1)
        out["primary_role"] = pct.fillna(-1).idxmax(axis=1).map({m: s["pillar"] for m, s in self.metrics.items()}).where(has)
        out["creator_complete"] = out[self.key].isin(set(self.leaderboard[self.key]))
        return out.sort_values(["platform", f"{list(self.metrics)[0]}__pct"], ascending=[True, False]).reset_index(drop=True)

    def build_gaps(self) -> pd.DataFrame:
        """One row per missing required item, with the reason it could not be filled."""
        rows = []
        any_pairs, fresh_pairs, any_cr, fresh_cr = {}, {}, {}, {}
        metric_diag = {}                                   # (key, platform, metric) -> {diag: [vendors]}
        for name, df in self.vendor_frames.items():
            fresh = self._is_fresh(df)
            for k, p, f in zip(df[self.key], df["platform"], fresh):
                any_pairs.setdefault((k, p), set()).add(name)
                any_cr.setdefault(k, set()).add(name)
                if f:
                    fresh_pairs.setdefault((k, p), set()).add(name)
                    fresh_cr.setdefault(k, set()).add(name)
            scored = self._metrics(self._clean(df[fresh]))
            for m in self.metrics:
                for k, p, d in zip(scored[self.key], scored["platform"], scored[f"_diag_{m}"]):
                    metric_diag.setdefault((k, p, m), {}).setdefault(d, []).append(name)

        def base_reason(has, fresh, what):
            if not has:
                return f"No vendor has this {what}"
            if not fresh:
                return "Only stale data (" + ", ".join(sorted(has)) + ")"
            return None

        for k, r in self.out_cr.iterrows():
            miss = [f for f in self.cr_required if pd.isna(r[f])]
            if miss:
                rows.append({self.key: k, "level": "creator", "platform": "", "missing": ", ".join(miss),
                             "reason": base_reason(any_cr.get(k), fresh_cr.get(k), "creator")
                             or "Field empty or invalid in fresh data"})
        filled = pd.concat({f: self.filled(self.out_ch, f) for f in self.ch_required}, axis=1)
        for (k, p), r in self.out_ch.iterrows():
            miss = [f for f in self.ch_required if not filled.at[(k, p), f]]
            if not miss:
                continue
            held = [str(r.get(f"{f}__source")) for f in miss if str(r.get(f"{f}__source")).startswith(("BLOCKED", "EXCLUDED"))]
            if held:
                fid = held[0].split(": ", 1)[1].split(" ")[0]
                code = next((fl.code for fl in self.flags.flags if fl.id == fid), "")
                state = "Excluded at review" if held[0].startswith("EXCLUDED") else "Held back for review"
                rows.append({self.key: k, "level": "channel", "platform": p,
                             "missing": ", ".join(self.metrics[f]["label"] if f in self.metrics else f for f in miss),
                             "reason": f"{state}: {code} ({fid})"})
                continue
            reason = base_reason(any_pairs.get((k, p)), fresh_pairs.get((k, p)), "channel")
            if reason is None:
                parts = []
                fmiss = [f for f in miss if f in self.ch_fields]
                if fmiss:
                    parts.append(f"{', '.join(fmiss)} empty or invalid")
                for m in [f for f in miss if f in self.metrics]:
                    diags = {d: v for d, v in metric_diag.get((k, p, m), {}).items() if d != "ok"}
                    why = "; ".join(f"{d} ({', '.join(v)})" for d, v in diags.items()) or "not computable"
                    parts.append(f"{self.metrics[m]['pillar']}: {why}")
                reason = " | ".join(parts)
            rows.append({self.key: k, "level": "channel", "platform": p,
                         "missing": ", ".join(self.metrics[f]["label"] if f in self.metrics else f for f in miss),
                         "reason": reason})
        return pd.DataFrame(rows, columns=[self.key, "level", "platform", "missing", "reason"])

    # 5a. creator-level QA (after the waterfall, before anything is final) --------------
    def creator_qa(self):
        from qa_checks import discrepancy_check, fallback_check, history_check
        for (cid, plat) in self.blocked_pairs:                     # identity-blocked channels: nothing merged
            fid = next((f.id for f in self.flags.flags if f.code == "IDENTITY_MATCH_UNCERTAIN"
                        and f.creator_id == cid and f.platform == plat), "")
            for col in self.ch_values:
                self.out_ch.at[(cid, plat), col] = pd.NA
                self.out_ch.at[(cid, plat), f"{col}__source"] = f"BLOCKED: {fid}"
                self.blocked_fields.setdefault((cid, plat), {})[col] = fid
        discrepancy_check(self)
        fallback_check(self)
        history_check(self)
        self.final = self._assess()
        counts = self.flags.frame().groupby(["severity", "code"]).size().to_dict() if self.flags.flags else {}
        self.agent.decide("qa", {"flags": {f"{k[0]}:{k[1]}": int(v) for k, v in counts.items()}},
                          f"{len(self.flags.open_red())} blocked",
                          "; ".join(f"{k[1]} ({k[0]}) {v}" for k, v in sorted(counts.items())) or "no QA issues")

    def state_path(self) -> Path:
        return self.out_dir / "state.pkl"

    def save_state(self):
        import pickle
        self.out_dir.mkdir(parents=True, exist_ok=True)
        with open(self.state_path(), "wb") as fh:
            pickle.dump(self, fh)

    @staticmethod
    def load_state(month: str, out_dir: Path | None = None) -> "Pipeline":
        import pickle
        path = Path(out_dir or ROOT / "output" / month) / "state.pkl"
        if not path.exists():
            raise FileNotFoundError(f"No saved run for {month} at {path}. Run the month first.")
        with open(path, "rb") as fh:
            return pickle.load(fh)

    def gate_open(self) -> bool:
        return not self.flags.open_red() or self.cfg["review"].get("leaderboard_gate", "strict") == "exclude_unresolved"

    # 5b. stage-1 outputs: QA report + review form; finalize straight away if nothing is blocked ----
    def report(self):
        from review import write_qa_report
        od = self.out_dir
        od.mkdir(parents=True, exist_ok=True)
        self.vendor_history.record(self.month, self.profiles)      # vendor evaluation doesn't wait for review
        for name, inp in self.vendor_inputs.items():
            self.registry.learn(name, self.month, inp["df"], inp["path"].name, inp["resolved"])
        self.vendor_history.save(); self.registry.save()
        self.flags.frame().to_csv(od / "qa_flags.csv", index=False)
        self.status = "ready" if self.gate_open() else "awaiting_review"
        self.qa_report_path = write_qa_report(self, od / f"qa_report_{self.month}.xlsx")
        self.save_state()
        n_red = len(self.flags.open_red())
        if self.status == "awaiting_review":
            print(f"\nQA: {n_red} blocked item(s) need review before the leaderboard is built.\n"
                  f"  1. Open {self.qa_report_path} → 'Blocked — review' tab, fill Decision (+ Manual value).\n"
                  f"  2. python review.py --month {self.month} --decisions {self.qa_report_path}")
        elif self.auto_finalize:
            self.finalize()

    # 6. finalize: master dataset → scores → leaderboard (only once the gate is open) -------------
    def finalize(self):
        from excel_report import write_workbook
        from leaderboard_html import write_leaderboard_html
        from qa_checks import history_check
        from review import write_qa_report
        if not self.gate_open():
            raise RuntimeError(f"{len(self.flags.open_red())} blocked item(s) still open; resolve them first.")
        for f in self.flags.open_red():                              # exclude_unresolved mode
            f.status, f.decision = "resolved", "EXCLUDED_UNRESOLVED"
        self.flags.remove_code("HISTORICAL_ANOMALY")                 # re-check on the final values
        history_check(self)
        od = self.out_dir
        self.final = self._assess()
        self.score()
        self.leaderboard = self.build_leaderboard()
        self.channel_board = self.build_channel_leaderboard()
        self.gaps = self.build_gaps()
        self.creators_with_gaps = int(self.gaps[self.key].nunique()) if len(self.gaps) else 0
        self.out_cr.reset_index().to_csv(od / "filled_creators.csv", index=False)
        self.scored_ch.reset_index().to_csv(od / "filled_channels.csv", index=False)
        self.gaps.to_csv(od / "gaps.csv", index=False)
        self.flags.frame().to_csv(od / "qa_flags.csv", index=False)
        self.creator_history.record(self.month, self)
        self.creator_history.save()
        self.status = "finalized"
        self.qa_report_path = write_qa_report(self, od / f"qa_report_{self.month}.xlsx")
        self.workbook_path = write_workbook(self, od / f"creator_fill_{self.month}.xlsx")
        self.leaderboard_path = write_leaderboard_html(self, od / "creator_leaderboard.html")
        summary = {"month": self.month, "status": self.status, "request_mix": self.request_mix,
                   "vendor_qa": {n: p.__dict__ for n, p in self.profiles.items()},
                   "tiers": self.tiers, "tier_results": self.tier_results, "final": self.final,
                   "flags": self.flags.frame()["code"].value_counts().to_dict() if self.flags.flags else {},
                   "creators_with_gaps": self.creators_with_gaps, "agent_log": self.agent.log}
        (od / "run_summary.json").write_text(json.dumps(summary, indent=2, default=str))
        (od / "run_report.md").write_text(self._markdown())
        self.save_state()
        print(f"\nFinalized {self.month}: outputs in {od}")

    def _markdown(self) -> str:
        label = lambda f: self.metrics[f]["pillar"] + " (" + self.metrics[f]["label"] + ")" if f in self.metrics else f
        L = [f"# Vendor QA & waterfall run — {self.month}", "",
             "Files: " + "; ".join(f"{r['file']} → {r['vendor'] or r['kind']}" for r in self.recognition), "",
             f"Requested: **{len(self.req_creators)} creators, {len(self.req_pairs)} channels** "
             f"({', '.join(f'{p} {n}' for p, n in self.request_mix.items() if n)}).", "",
             "## 1. Vendor QA (requested channels only)", "",
             "| Vendor | Tier | Score | Fresh coverage | Completeness | Freshness | Validity | "
             + " | ".join(self.metrics[m]["pillar"] + " computable" for m in self.metrics) + " |",
             "|---" * (7 + len(self.metrics)) + "|"]
        for p in sorted(self.profiles.values(), key=lambda p: -p.score):
            L.append(f"| {p.name} | {p.tier or 'excluded'} | {p.score:.3f} | {p.usable_coverage:.1%} | "
                     f"{p.completeness:.1%} | {p.freshness:.1%} | {p.validity:.1%} | "
                     + " | ".join(f"{p.field_completeness[m]:.0%}" for m in self.metrics) + " |")
        L += ["", "## 2. Waterfall progression", "",
              "| | " + " | ".join(f"after T{t['tier']} ({t['vendor']})" for t in self.tier_results) + " |",
              "|---|" + "---|" * len(self.tier_results)]
        for f in [*self.cr_fields, *self.ch_values]:
            L.append(f"| {label(f)}{' *' if f in self.required else ''} | " +
                     " | ".join(f"{t['after']['field_fill_rate'][f]:.1%}" for t in self.tier_results) + " |")
        for n, cnt in self.request_shape.items():
            L.append(f"| creators needing {n} channel{'s' if n > 1 else ''} ({cnt}) complete | " + " | ".join(
                f"{t['after']['creators_complete_by_n_channels'].get(n, 0):.1%}" for t in self.tier_results) + " |")
        L.append("| **creators complete** | " +
                 " | ".join(f"**{t['after']['creators_complete']:.1%}**" for t in self.tier_results) + " |")
        L += ["", "## 3. Top creators per pillar", ""]
        for m, s in self.metrics.items():
            top = self.leaderboard.sort_values(m, ascending=False).head(5)
            L.append(f"**{s['pillar']}** ({s['theme']}): " +
                     ", ".join(f"{r['display_name']} {r[m]:.0f}" for _, r in top.iterrows()))
            L.append("")
        L += ["## 4. Agent decision log", ""]
        L += [f"- **{e['step']}** → {e['decision']}: {e['reason']}" for e in self.agent.log]
        L += ["", "## 5. Residual gaps", "",
              f"{self.creators_with_gaps} creators still miss at least one required item — see `gaps.csv`."]
        return "\n".join(L) + "\n"

    def run(self):
        """Stage 1 (automated): import → standardise → match creators → evaluate vendors → fill with fallback →
        cross-vendor QA → historical checks → QA report. Finalizes straight away if nothing is blocked."""
        from qa_checks import discrepancy_check, identity_check
        self.recognise(); self.load_request(); self.ingest()
        self.excluded_rows, self.blocked_pairs = identity_check(self)
        self.prepared = {v: self._prepare(v) for v in self.vendor_frames}
        self.consistency = discrepancy_check(self, apply=False)
        self.qa(); self.assign_tiers(); self.waterfall(); self.creator_qa(); self.report()
        return self


def run_uploaded(files: list, month: str, out_dir: Path | None = None, assign: dict | None = None,
                 memory_dir: Path | None = None, auto_finalize: bool = True,
                 cfg_path: Path = ROOT / "config.yaml") -> Pipeline:
    """Entry point for the app: any file names; vendors are recognised automatically."""
    import pipeline as _module
    return _module.Pipeline(cfg_path, files=files, month=month, out_dir=out_dir, assign=assign,
                            memory_dir=memory_dir, auto_finalize=auto_finalize).run()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Run one month: python pipeline.py --inbox data/inbox/2026-09")
    ap.add_argument("--inbox", required=True, help="folder with this month's request list + vendor files")
    ap.add_argument("--month", help="YYYY-MM (defaults to the folder name)")
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    a = ap.parse_args()
    import pipeline as _module      # run from the module (not __main__) so the saved state can be reloaded later
    _module.Pipeline(Path(a.config), inbox=Path(a.inbox), month=a.month).run()
