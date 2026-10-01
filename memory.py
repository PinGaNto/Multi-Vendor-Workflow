"""Month-over-month memory: vendor quality history and creator score history (CSV files in memory/)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

VENDOR_COLS = ["month", "vendor", "current_score", "blended_score", "tier", "usable_coverage", "completeness",
               "freshness", "validity", "implausible_values", "rows"]


class VendorHistory:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.df = pd.read_csv(self.path) if self.path.exists() else pd.DataFrame(columns=VENDOR_COLS)

    def historical(self, vendor: str, month: str, months: int = 6, decay: float = 0.7):
        """Decay-weighted mean of the vendor's own CURRENT scores from earlier months (most recent counts most)."""
        h = self.df[(self.df["vendor"] == vendor) & (self.df["month"] < month)].sort_values("month").tail(months)
        if h.empty:
            return None, 0, []
        w = np.array([decay ** k for k in range(len(h))][::-1])
        score = float(np.dot(w, h["current_score"].astype(float)) / w.sum())
        return round(score, 4), len(h), list(zip(h["month"], h["current_score"].astype(float).round(4)))

    def reliability(self, vendor: str, month: str, audit_path: Path, cfg: dict) -> dict:
        """Rolling reliability over the last N months (default 3):
             w_qa x average monthly QA score  +  w_review x review accuracy
           review accuracy = share of reviewed disputes involving this vendor where its value/account was kept.
           With no reviewed disputes in the window, reliability = the QA average."""
        rc = cfg.get("reliability", {})
        n = rc.get("window_months", 3)
        h = self.df[(self.df["vendor"] == vendor) & (self.df["month"] < month)].sort_values("month").tail(n)
        if h.empty:
            return {"score": None, "months": 0, "qa_avg": None, "review_accuracy": None, "disputes": 0, "trend": []}
        qa_avg = float(h["current_score"].astype(float).mean())
        kept = involved = 0
        if Path(audit_path).exists():
            a = pd.read_csv(audit_path)
            a = a[a["month"].astype(str).isin(set(h["month"].astype(str)))]
            for r in a.to_dict("records"):
                try:
                    vals = json.loads(r["original_values"])
                except (TypeError, ValueError):
                    continue
                if vendor not in vals or r["decision"] in ("EXCLUDE", "REJECT_MATCH", "EXCLUDED_UNRESOLVED"):
                    continue
                involved += 1
                src = str(r.get("final_source", ""))
                if r["decision"] == "CONFIRM_MATCH" or vendor in src.split(", ") or src == vendor:
                    kept += 1
                elif r["decision"] == "MANUAL_VALUE":
                    try:
                        mv, vv = float(r["manual_value"]), float(vals[vendor])
                        kept += abs(mv - vv) / max(abs(mv), 1e-9) <= 0.05
                    except (TypeError, ValueError):
                        pass
        acc = kept / involved if involved else None
        wq, wr = rc.get("qa_score_weight", 0.7), rc.get("review_accuracy_weight", 0.3)
        score = qa_avg if acc is None else wq * qa_avg + wr * acc
        return {"score": round(score, 4), "months": len(h), "qa_avg": round(qa_avg, 4),
                "review_accuracy": None if acc is None else round(acc, 4), "disputes": involved,
                "trend": list(zip(h["month"], h["current_score"].astype(float).round(4)))}

    def record(self, month: str, profiles: dict):
        rows = [{"month": month, "vendor": n, "current_score": p.current_score, "blended_score": p.score,
                 "tier": p.tier or "excluded", "usable_coverage": p.usable_coverage, "completeness": p.completeness,
                 "freshness": p.freshness, "validity": p.validity, "implausible_values": p.implausible_values,
                 "rows": p.rows} for n, p in profiles.items()]
        self.df = pd.concat([self.df[self.df["month"] != month], pd.DataFrame(rows)], ignore_index=True)
        self.df = self.df.sort_values(["month", "vendor"]).reset_index(drop=True)

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.df.to_csv(self.path, index=False)


class CreatorHistory:
    """One row per month x creator x channel (platform 'all' = the creator's averaged pillar scores)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.df = pd.read_csv(self.path, dtype={"month": str}) if self.path.exists() else pd.DataFrame()

    def record(self, month: str, p):
        ch = p.scored_ch.reset_index()
        keep = ["creator_id", "platform", "follower_count", "size_band", *p.metrics, *[f"{m}__pct" for m in p.metrics]]
        rows = ch[keep].copy()
        filled = pd.concat([p.filled(p.scored_ch, f) for f in p.ch_required], axis=1).all(axis=1)
        rows["complete"] = filled.values
        allrows = p.creator_scores.reset_index().rename(columns={m: f"{m}__pct" for m in p.metrics})
        allrows["platform"] = "all"
        allrows["complete"] = allrows["creator_id"].isin(set(p.leaderboard["creator_id"]))
        new = pd.concat([rows, allrows[["creator_id", "platform", "complete", "primary_role",
                                        *[f"{m}__pct" for m in p.metrics]]]], ignore_index=True)
        new.insert(0, "month", month)
        old = self.df[self.df["month"] != month] if not self.df.empty else self.df
        self.df = pd.concat([old, new], ignore_index=True).sort_values(["creator_id", "platform", "month"])

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.df.to_csv(self.path, index=False)
