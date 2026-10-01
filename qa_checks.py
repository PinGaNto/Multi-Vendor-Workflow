"""Creator-level QA: identity matching, cross-vendor discrepancy, source fallback, historical anomalies.

Every finding is a Flag with a machine-readable reason code. Its severity (GREEN / YELLOW / RED) comes from
config.yaml -> qa_rules.severity, so a rule can be tightened or relaxed without code changes.
RED flags hold back only the affected creator-channel or metric; everything else carries on.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from itertools import combinations

import numpy as np
import pandas as pd

ACTIONS = {
    "IDENTITY_MATCH_UNCERTAIN": "Check the accounts on the platform. CONFIRM_MATCH if they're the same creator, "
                                "SELECT_VENDOR_x to keep only the vendor with the right account, or REJECT_MATCH / EXCLUDE.",
    "CROSS_VENDOR_DISCREPANCY": "Check the creator's profile. SELECT_VENDOR_x for the right value, MANUAL_VALUE to "
                                "enter the correct figure, or EXCLUDE to leave it out this month.",
    "IDENTITY_CONFLICT_RESOLVED": "No action needed. Spot-check if the dropped vendor often disagrees.",
    "OUTLIER_SOURCE_EXCLUDED": "No action needed. Watch for repeat outliers from the same vendor.",
    "PRIMARY_SOURCE_MISSING": "No action needed. Tracked to monitor vendor coverage.",
    "HISTORICAL_ANOMALY": "No action needed. Worth a look if the creator is being shortlisted.",
}


@dataclass
class Flag:
    id: str
    creator_id: str
    platform: str
    field: str
    code: str
    severity: str
    values: dict = field(default_factory=dict)          # vendor -> value (or previous/current for history)
    discrepancy: float | None = None
    source_used: str = ""
    explanation: str = ""
    action: str = ""
    status: str = "open"                                 # open | auto | resolved
    dependents: list = field(default_factory=list)       # fields held back together with this one
    decision: str = ""
    manual_value: float | None = None
    final_value: object = None
    final_source: str = ""
    reviewer: str = ""
    note: str = ""
    reviewed_at: str = ""


class FlagBook:
    def __init__(self, cfg):
        self.cfg = cfg
        self.flags: list[Flag] = []
        self._n = 0

    def add(self, creator_id, platform, fld, code, **kw) -> Flag:
        self._n += 1
        sev = self.cfg["qa_rules"]["severity"].get(code, "YELLOW")
        f = Flag(id=f"Q{self._n:05d}", creator_id=creator_id, platform=platform, field=fld, code=code, severity=sev,
                 action=ACTIONS.get(code, ""), status="open" if sev == "RED" else "auto", **kw)
        self.flags.append(f)
        return f

    def remove_code(self, code):
        self.flags = [f for f in self.flags if f.code != code]

    def open_red(self) -> list[Flag]:
        return [f for f in self.flags if f.severity == "RED" and f.status == "open"]

    def frame(self) -> pd.DataFrame:
        cols = list(Flag.__dataclass_fields__)
        return pd.DataFrame([asdict(f) for f in self.flags], columns=cols)

    def creator_status(self) -> dict:
        """Worst open severity per creator (resolved RED counts as YELLOW: it was reviewed)."""
        rank = {"GREEN": 0, "YELLOW": 1, "RED": 2}
        out = {}
        for f in self.flags:
            sev = "YELLOW" if (f.severity == "RED" and f.status == "resolved") else f.severity
            if rank[sev] > rank.get(out.get(f.creator_id, "GREEN"), 0):
                out[f.creator_id] = sev
        return out


# ------------------------------------------------------------------------------------------- identity
def norm_handle(v) -> str | None:
    """'@Name', 'name', 'https://www.instagram.com/name/' and 'https://www.tiktok.com/@name' -> 'name'."""
    if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NA:
        return None
    s = str(v).strip().lower()
    if not s:
        return None
    if "/" in s:
        s = [part for part in re.split(r"[/?#]", s) if part][-1]
    return s.lstrip("@")


def identity_check(p) -> tuple[set, set]:
    """Compare strong identifiers across vendors for every requested creator-channel.
    Returns (excluded vendor rows {(vendor, creator_id, platform)}, blocked pairs {(creator_id, platform)})."""
    rules = p.cfg["qa_rules"]["identity"]
    req = set(map(tuple, p.req_pairs[[p.key, "platform"]].to_numpy()))
    seen = {}                                            # (cid, plat) -> {vendor: normalised handle}
    for name, df in p.vendor_frames.items():
        for cid, plat, h in zip(df[p.key], df["platform"], df["handle"]):
            if (cid, plat) in req and norm_handle(h):
                seen.setdefault((cid, plat), {})[name] = norm_handle(h)
    excluded, blocked = set(), set()
    for (cid, plat), hs in seen.items():
        distinct = set(hs.values())
        if len(distinct) <= 1:
            continue
        counts = pd.Series(list(hs.values())).value_counts()
        top, n_top = counts.index[0], counts.iloc[0]
        if rules.get("majority_resolves", True) and n_top >= 2 and n_top > len(hs) / 2:
            odd = [v for v, h in hs.items() if h != top]
            for v in odd:
                excluded.add((v, cid, plat))
            p.flags.add(cid, plat, "identity", "IDENTITY_CONFLICT_RESOLVED", values=dict(hs),
                        source_used=", ".join(v for v, h in hs.items() if h == top),
                        explanation=f"{n_top} vendors agree the account is @{top}; {', '.join(odd)} reported "
                                    f"{', '.join('@' + hs[v] for v in odd)} and was not used for this channel.")
        else:
            blocked.add((cid, plat))
            for v in hs:
                excluded.add((v, cid, plat))
            p.flags.add(cid, plat, "identity", "IDENTITY_MATCH_UNCERTAIN", values=dict(hs),
                        explanation="Vendors report different accounts for this creator-channel ("
                                    + "; ".join(f"{v}: @{h}" for v, h in hs.items())
                                    + "), with no majority. None of their data is used until reviewed.")
    return excluded, blocked


# ------------------------------------------------------------------------------------------- discrepancy
def differs(a, b, rule) -> float:
    if rule.get("mode") == "absolute":
        return abs(a - b)
    big = max(abs(a), abs(b))
    return 0.0 if big == 0 else abs(a - b) / big


def dependents_of(p, fld) -> list:
    """Metrics whose formula uses this field (so they can't be trusted if the field is disputed)."""
    out = []
    for m, spec in p.metrics.items():
        forms = [spec["formula"], *(spec.get("by_platform") or {}).values()]
        if any(re.search(rf"\b{re.escape(fld)}\b", f) for f in forms):
            out.append(m)
    return out


def consensus_groups(vals: dict, rule) -> tuple[list, float]:
    """Largest set of vendors whose values are all within threshold of each other, and the max spread."""
    names = list(vals)
    spread = max((differs(vals[a], vals[b], rule) for a, b in combinations(names, 2)), default=0.0)
    best = []
    for k in range(len(names), 1, -1):
        for combo in combinations(names, k):
            if all(differs(vals[a], vals[b], rule) <= rule["threshold"] for a, b in combinations(combo, 2)):
                best = list(combo)
                break
        if best:
            break
    return best, spread


def discrepancy_check(p, apply: bool = True, only_pairs: set | None = None):
    """Compare each vendor's fresh, valid value for the same creator-channel; resolve or block.
    apply=False only measures vendor consistency (used in vendor QA before tiering)."""
    rules = p.cfg["qa_rules"]["discrepancy"]
    tier_of = {n: i for i, n in enumerate(getattr(p, "tiers", []), start=1)}
    if not hasattr(p, "outlier_excl"):
        p.outlier_excl = {}                                         # (cid, plat) -> {field: vendors dropped as outliers}
    consistency = {v: [0, 0] for v in p.vendor_frames}             # vendor -> [agree, compared]
    for fld, rule in rules["fields"].items():
        tables = {v: pd.to_numeric(ch[fld], errors="coerce") for v, (cr, ch) in p.prepared.items() if fld in ch}
        frame = pd.DataFrame(tables)
        for (cid, plat), row in frame.iterrows():
            if only_pairs is not None and (cid, plat) not in only_pairs:
                continue
            dropped = p.outlier_excl.get((cid, plat), {}).get(fld, set()) if apply else set()
            vals = {v: float(x) for v, x in row.items() if pd.notna(x) and v not in dropped}
            if apply and dropped:                                   # value computed from an overruled input
                cur = p.out_ch.at[(cid, plat), f"{fld}__source"] if (cid, plat) in p.out_ch.index else None
                if cur in dropped:
                    alt = sorted(vals, key=lambda v: tier_of.get(v, 9))
                    p.out_ch.at[(cid, plat), fld] = vals[alt[0]] if alt else pd.NA
                    p.out_ch.at[(cid, plat), f"{fld}__source"] = alt[0] if alt else f"EXCLUDED: computed from an outlier ({cur})"
            if len(vals) < 2:
                continue
            group, spread = consensus_groups(vals, rule)
            for v in vals:                                          # vendor consistency (agrees with someone)
                consistency[v][1] += 1
                if any(differs(vals[v], vals[o], rule) <= rule["threshold"] for o in vals if o != v):
                    consistency[v][0] += 1
            if not apply or len(group) == len(vals):
                continue                                            # everyone within tolerance: accept quietly
            if (cid, plat) in p.blocked_pairs or fld in p.blocked_fields.get((cid, plat), {}):
                continue                                            # already held back (identity, or with its input)
            fmt = (lambda x: f"{x:,.0f}") if fld == "follower_count" else (lambda x: f"{x:.3f}")
            shown = "; ".join(f"{v} {fmt(x)}" for v, x in sorted(vals.items(), key=lambda kv: tier_of.get(kv[0], 9)))
            unit = "pts" if rule.get("mode") == "absolute" else ""
            spread_txt = f"{spread * 100:.1f} pts" if unit else f"{spread:.0%}"
            thr_txt = f"{rule['threshold'] * 100:.0f} pts" if unit else f"{rule['threshold']:.0%}"
            if rules.get("majority_resolves", True) and len(group) >= 2 and len(group) > len(vals) / 2:
                use = min(group, key=lambda v: tier_of.get(v, 9))
                outliers = [v for v in vals if v not in group]
                cur_src = p.out_ch.at[(cid, plat), f"{fld}__source"]
                if cur_src in outliers or pd.isna(p.out_ch.at[(cid, plat), fld]):
                    p.out_ch.at[(cid, plat), fld] = p.prepared[use][1].at[(cid, plat), fld]
                    p.out_ch.at[(cid, plat), f"{fld}__source"] = use
                for dep in dependents_of(p, fld):                   # the outlier's metrics built on this field go too
                    p.outlier_excl.setdefault((cid, plat), {}).setdefault(dep, set()).update(outliers)
                p.flags.add(cid, plat, fld, "OUTLIER_SOURCE_EXCLUDED", values=vals, discrepancy=round(spread, 4),
                            source_used=use,
                            explanation=f"{', '.join(group)} agree within {thr_txt}; {', '.join(outliers)} differ "
                                        f"({shown}). Used {use} (highest tier among the agreeing vendors)"
                                        + (f", not Tier 1 {p.tiers[0]}, because it's the outlier." if p.tiers and p.tiers[0] in outliers
                                           else ", not the outlier."))
            else:
                deps = dependents_of(p, fld) if rules.get("block_dependents", True) else []
                f = p.flags.add(cid, plat, fld, "CROSS_VENDOR_DISCREPANCY", values=vals, discrepancy=round(spread, 4),
                                source_used=str(p.out_ch.at[(cid, plat), f"{fld}__source"]), dependents=deps,
                                explanation=f"Vendors disagree by {spread_txt} (threshold {thr_txt}): {shown}. No credible majority, so the value is "
                                            f"held back rather than defaulting to the highest tier"
                                            + (f"; {', '.join(deps)} (computed from it) held back too." if deps else "."))
                for col in [fld, *deps]:
                    p.out_ch.at[(cid, plat), col] = pd.NA
                    p.out_ch.at[(cid, plat), f"{col}__source"] = f"BLOCKED: {f.id}"
                    p.blocked_fields.setdefault((cid, plat), {})[col] = f.id
    return {v: round(a / n, 4) if n else 1.0 for v, (a, n) in consistency.items()}


# ------------------------------------------------------------------------------------------- fallback
def fallback_check(p):
    if not p.tiers:
        return
    t1 = p.tiers[0]
    fields = p.cfg["qa_rules"]["fallback"]["warn_fields"]
    t1_raw = p.vendor_frames[t1]
    has_row = set(zip(t1_raw[p.key], t1_raw["platform"]))
    fresh_rows = set(zip(t1_raw.loc[p._is_fresh(t1_raw), p.key], t1_raw.loc[p._is_fresh(t1_raw), "platform"]))
    t1_ch = p.prepared[t1][1]
    for (cid, plat), r in p.out_ch.iterrows():
        used = {}
        for f in fields:
            src = r.get(f"{f}__source")
            if isinstance(src, str) and src not in (t1,) and not src.startswith(("n/a", "BLOCKED", "EXCLUDED")):
                used[f] = src
        if not used:
            continue
        if (t1, cid, plat) in p.excluded_rows:
            why = f"{t1}'s record was excluded by the identity check"
        elif (cid, plat) not in has_row:
            why = f"{t1} has no record for this channel"
        elif (cid, plat) not in fresh_rows:
            why = f"{t1}'s record is stale"
        else:
            why = f"{t1}'s record lacks a valid value for " + ", ".join(
                f for f in used if pd.isna(t1_ch.at[(cid, plat), f])) if (cid, plat) in t1_ch.index else f"{t1} lacks it"
        p.flags.add(cid, plat, ", ".join(used), "PRIMARY_SOURCE_MISSING", values={f: s for f, s in used.items()},
                    source_used=", ".join(sorted(set(used.values()))),
                    explanation=f"{why}; filled from {', '.join(sorted(set(used.values())))} (fallback).")


# ------------------------------------------------------------------------------------------- history
def history_check(p):
    rules = p.cfg["qa_rules"]["history"]["fields"]
    h = p.creator_history.df
    if h.empty:
        return
    prev = h[(h["month"].astype(str) < p.month) & (h["platform"] != "all")]
    if prev.empty:
        return
    last = prev.sort_values("month").groupby(["creator_id", "platform"]).tail(1).set_index(["creator_id", "platform"])
    for (cid, plat), r in p.out_ch.iterrows():
        if (cid, plat) not in last.index:
            continue
        for fld, rule in rules.items():
            cur, before = pd.to_numeric(r.get(fld), errors="coerce"), pd.to_numeric(last.at[(cid, plat), fld], errors="coerce")
            if pd.isna(cur) or pd.isna(before) or before <= 0:
                continue
            change = cur / before - 1
            if change > rule["max_increase"] or change < -rule["max_decrease"]:
                fmt = (lambda x: f"{x:,.0f}") if fld == "follower_count" else (lambda x: f"{x:.2f}")
                p.flags.add(cid, plat, fld, "HISTORICAL_ANOMALY",
                            values={"previous_month": last.at[(cid, plat), "month"], "previous": float(before), "current": float(cur)},
                            discrepancy=round(float(change), 4), source_used=str(r.get(f"{fld}__source")),
                            explanation=f"{fld} moved {change:+.0%} vs {last.at[(cid, plat), 'month']} "
                                        f"({fmt(before)} → {fmt(cur)}). Kept: big swings can be genuine (viral content, events).")
