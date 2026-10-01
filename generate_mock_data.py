"""Generate three monthly drops (Jul–Sep 2026) into data/inbox/<YYYY-MM>/.

Each drop holds a creator request list and three vendor files with UNHELPFUL file names, so the pipeline has to
recognise vendors by content. Creators evolve month to month (so profiles have history), vendor quality varies,
and in September vendor B renames two columns (schema drift the pipeline should learn).
Replace with real monthly drops; nothing else depends on this script.
"""
import random
import shutil
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from request_template import write_request

ROOT = Path(__file__).parent
DATA = ROOT / "data"
INBOX = DATA / "inbox"
CFG = yaml.safe_load((ROOT / "config.yaml").read_text())
PLATFORMS = CFG["platforms"]
MONTHS = ["2026-07", "2026-08", "2026-09"]
MONTH_END = {"2026-07": date(2026, 7, 31), "2026-08": date(2026, 8, 31), "2026-09": date(2026, 9, 30)}
COUNTRIES = {"US": "United States", "GB": "United Kingdom", "CA": "Canada", "BR": "Brazil", "IN": "India",
             "DE": "Germany", "FR": "France", "JP": "Japan", "MX": "Mexico", "KR": "South Korea"}
CATS = ["gaming", "beauty", "fitness", "food", "tech", "travel", "music", "education", "comedy", "finance"]
REACH_MEDIAN = {"tiktok": 3.0, "youtube": 1.2, "instagram": 0.6}
N = 1500

rng = random.Random(7)
npr = np.random.default_rng(7)

# ---------------------------------------------------------------- stable creator + channel base traits
creators = pd.DataFrame({
    "creator_id": [f"CR{i:05d}" for i in range(N)],
    "display_name": [f"Creator {i}" for i in range(N)],
    "country": [rng.choice(list(COUNTRIES)) for _ in range(N)],
    "contact_email": [f"creator{i}@mail.example" for i in range(N)],
    "category": [rng.choice(CATS) for _ in range(N)],
})
base = []
for i, cid in enumerate(creators.creator_id):
    for p in rng.sample(PLATFORMS, k=rng.choices([1, 2, 3], weights=[2, 3, 5])[0]):
        f0 = int(npr.lognormal(10.8, 1.5))
        base.append({"creator_id": cid, "platform": p, "handle": f"@creator{i}_{p}", "f0": f0,
                     "g": float(np.clip(npr.normal(0.06, 0.07) + 0.6 / np.log10(max(f0, 100)) ** 2, -0.25, 2.5)),
                     "reach": float(npr.lognormal(np.log(REACH_MEDIAN[p]), 0.7)),
                     "er": float(npr.uniform(0.02, 0.09)), "mix": npr.dirichlet([16, 1.2, 0.8, 1.0 if p != "youtube" else 1e-4]),
                     "hidden": p == "instagram" and rng.random() < 0.12})
base = pd.DataFrame(base)
have = base.groupby("creator_id")["platform"].apply(list).to_dict()


VIRAL = set(base.sample(6, random_state=77).index)        # channels that go viral in September (x8 followers)


def truth_for(month_idx: int) -> pd.DataFrame:
    """Channel stats for a month: traits drift a little each month so scores move."""
    r = np.random.default_rng(100 + month_idx)
    rows = []
    for idx, b in zip(base.index, base.itertuples(index=False)):
        g = float(np.clip(b.g + r.normal(0, 0.03), -0.3, 3))
        followers = int(b.f0 * (1 + b.g / 3) ** month_idx)
        prev = int(round(followers / (1 + g)))
        if month_idx == 2 and idx in VIRAL:                  # genuine viral growth: a real change, not bad data
            prev = int(b.f0 * (1 + b.g / 3))
            followers = prev * 8
        views = int(followers * b.reach * r.lognormal(0, 0.25))
        eng = int(views * b.er * r.lognormal(0, 0.15))
        mix = r.dirichlet(np.array(b.mix) * 40 + 1e-3)
        likes, comments, shares, saves = (int(eng * m) for m in mix)
        rows.append({"creator_id": b.creator_id, "platform": b.platform, "handle": b.handle,
                     "follower_count": followers, "net_new_followers_90d": followers - prev, "views_90d": views,
                     "likes_90d": likes, "comments_90d": comments, "shares_90d": shares,
                     "saves_90d": saves if b.platform != "youtube" else None, "likes_hidden": b.hidden})
    return pd.DataFrame(rows).merge(creators, on="creator_id")


# ---------------------------------------------------------------- the request: mostly the same creators each month
def base_request():
    all_three = [c for c, ps in have.items() if len(ps) == 3]
    full = pd.Series(all_three).sample(480, random_state=1).tolist()
    pool = [c for c in creators.creator_id if c not in set(full)]
    two = pd.Series([c for c in pool if len(have[c]) >= 2]).sample(160, random_state=2).tolist()
    one = pd.Series([c for c in pool if c not in set(two)]).sample(160, random_state=3).tolist()
    req = {c: list(PLATFORMS) for c in full}
    for c in two:
        req[c] = rng.sample(have[c], 2)
    for c in one:
        req[c] = rng.sample(have[c], 1)
    return req


REQ = base_request()


def month_request(month_idx: int) -> list:
    r = random.Random(500 + month_idx)
    req = dict(REQ)
    if month_idx:                                     # swap ~5% of creators each month
        out = r.sample(sorted(req), 40)
        spare = [c for c in creators.creator_id if c not in req]
        for c_old, c_new in zip(out, r.sample(spare, 40)):
            del req[c_old]
            req[c_new] = r.sample(have[c_new], r.randint(1, len(have[c_new])))
    rows = [{"creator_id": c, "creator_name": f"Creator {int(c[2:])}", "channels": ch} for c, ch in req.items()]
    r.shuffle(rows)
    return rows


# ---------------------------------------------------------------- vendor writers
def stamp(r, end, stale_share):
    age = r.randint(120, 400) if r.random() < stale_share else r.randint(0, 80)
    return (end - timedelta(days=age)).isoformat()


STATS = ["follower_count", "net_new_followers_90d", "views_90d", "likes_90d", "comments_90d", "shares_90d", "saves_90d"]


def sample_vendor(truth, cover, nulls, stale, bad_email, dup, seed, end, conflict_rate=0.012, mixup_rate=0.0):
    r = random.Random(seed)
    nr = np.random.default_rng(seed)
    df = truth[[r.random() < cover[p] for p in truth.platform]].copy()
    # 1) methodology / refresh-timing differences: every vendor is a little off (should be tolerated)
    for col in ["follower_count", "views_90d", "likes_90d", "comments_90d", "shares_90d", "saves_90d"]:
        v = pd.to_numeric(df[col], errors="coerce")
        df[col] = (v * nr.normal(1, 0.015, len(df))).round().astype("Int64").astype(object).where(v.notna(), None)
    # 2) material conflicts: a vendor's follower count is far off for a few creators
    bad = df.sample(frac=conflict_rate, random_state=seed + 7).index
    df.loc[bad, "follower_count"] = [int(f * (r.uniform(0.5, 0.65) if r.random() < .5 else r.uniform(1.5, 1.9)))
                                     if f is not None else None for f in df.loc[bad, "follower_count"]]
    # 3) identity mix-ups: the row is labelled as one creator but carries another creator's account and stats
    if mixup_rate:
        for i in df.sample(frac=mixup_rate, random_state=seed + 9).index:
            same = truth[(truth.platform == df.at[i, "platform"]) & (truth.creator_id != df.at[i, "creator_id"])]
            other = same.iloc[r.randrange(len(same))]
            for col in ["handle", *STATS, "likes_hidden"]:
                df.at[i, col] = other[col]
    for col in ["handle", "follower_count", "display_name", "country", "contact_email", "category",
                "net_new_followers_90d", "views_90d", "likes_90d", "comments_90d", "shares_90d", "saves_90d"]:
        m = np.array([r.random() < nulls.get(col, nulls.get("stats", 0)) for _ in range(len(df))])
        df[col] = df[col].astype(object)
        df.loc[m, col] = None
    df.loc[df["likes_hidden"].to_numpy(), "likes_90d"] = "hidden"
    bad = np.array([r.random() < bad_email for _ in range(len(df))])
    df.loc[bad & df["contact_email"].notna().to_numpy(), "contact_email"] = "unknown"
    df["ts"] = [stamp(r, end, stale) for _ in range(len(df))]
    return pd.concat([df, df.sample(frac=dup, random_state=seed + 1)]).sample(frac=1, random_state=seed)


def write_a(truth, end, q, path, seed):
    a = sample_vendor(truth, {"youtube": .88, "instagram": .40, "tiktok": .30},
                      {"contact_email": .10, "category": .05, "follower_count": .02, "stats": .02}, q, .02, 0, seed, end,
                      conflict_rate=0.010)
    a["platform"] = a["platform"].map({"youtube": "YouTube", "instagram": "Instagram", "tiktok": "TikTok"})
    a.rename(columns={"creator_id": "cid", "handle": "account", "follower_count": "followers",
                      "net_new_followers_90d": "net_new_90d", "display_name": "name", "country": "country_code",
                      "contact_email": "email", "category": "niche", "ts": "updated_at"})[
        ["cid", "platform", "account", "followers", "net_new_90d", "views_90d", "likes_90d", "comments_90d",
         "shares_90d", "saves_90d", "name", "country_code", "email", "niche", "updated_at"]].to_excel(path, index=False)


def write_b(truth, end, q, path, seed, renamed=False):
    b = sample_vendor(truth, {"instagram": .88, "tiktok": .88, "youtube": .45},
                      {"contact_email": .30, "category": .15, "follower_count": .05, "country": .05, "handle": .03,
                       "stats": .06}, q, .05, .01, seed, end, mixup_rate=0.004)
    r = random.Random(seed + 3)
    base_url = {"instagram": "https://www.instagram.com/{}/", "tiktok": "https://www.tiktok.com/@{}", "youtube": "https://youtube.com/@{}"}
    b["handle"] = [base_url[p].format(h.lstrip("@")) if isinstance(h, str) and r.random() < .2 else h
                   for h, p in zip(b["handle"], b["platform"])]           # some handles arrive as profile URLs
    b["platform"] = b["platform"].map({"instagram": "IG", "tiktok": "TT", "youtube": "YT"})
    b["country"] = b["country"].map(lambda c: COUNTRIES.get(c) if c else None)
    prev = [None if pd.isna(f) or pd.isna(n) else f - n for f, n in zip(b["follower_count"], b["net_new_followers_90d"])]
    b["audience_90d_ago_k"] = [None if v is None else round(v / 1000, 2) for v in prev]
    b["follower_count"] = b["follower_count"].map(lambda f: round(f / 1000, 2) if pd.notna(f) else None)
    cols = {"creator_id": "creator_ref", "platform": "channel", "handle": "username", "follower_count": "audience_k",
            "views_90d": "plays_90d", "likes_90d": "hearts", "comments_90d": "comment_count",
            "shares_90d": "share_count", "saves_90d": "bookmarks", "display_name": "full_name",
            "country": "country_name", "contact_email": "contact", "category": "vertical", "ts": "refreshed"}
    if renamed:                                       # September: vendor B renames two columns
        cols.update({"views_90d": "video_plays_90d", "comments_90d": "comments_total"})
    out = b.rename(columns=cols)
    order = [cols["creator_id"], cols["platform"], cols["handle"], "audience_k", "audience_90d_ago_k",
             cols["views_90d"], cols["likes_90d"], cols["comments_90d"], cols["shares_90d"], cols["saves_90d"],
             cols["display_name"], cols["country"], cols["contact_email"], cols["category"], cols["ts"]]
    out[order].to_excel(path, index=False)


def write_c(truth, end, q, path, seed, extra_col=False):
    c = sample_vendor(truth, {p: .55 for p in PLATFORMS},
                      {"contact_email": .45, "category": .35, "follower_count": .15, "country": .15, "handle": .10,
                       "stats": .15}, q, .12, .04, seed, end, conflict_rate=0.015, mixup_rate=0.01)
    r = random.Random(seed)
    c["display_name"] = c["display_name"].map(lambda n: n.lower() if isinstance(n, str) and r.random() < .3 else n)
    c["platform"] = c["platform"].map(lambda p: r.choice([p, p.upper(), p.capitalize()]))
    bad = c.sample(frac=.03, random_state=seed).index
    c.loc[bad, "views_90d"] = c.loc[bad, "follower_count"].map(lambda f: None if pd.isna(f) else int(f) * 500)
    c["country"] = c["country"].map(lambda x: x.lower() if isinstance(x, str) else x)
    out = c.rename(columns={"creator_id": "id", "platform": "network", "handle": "handle_name", "follower_count": "subs",
                            "net_new_followers_90d": "growth_90d", "views_90d": "views", "likes_90d": "likes",
                            "comments_90d": "comments", "shares_90d": "shares", "display_name": "creator",
                            "country": "geo", "contact_email": "mail", "category": "genre", "ts": "as_of"})
    cols = ["id", "network", "handle_name", "subs", "growth_90d", "views", "likes", "comments", "shares",
            "creator", "geo", "mail", "genre", "as_of"]
    if extra_col:
        out["notes"] = ""
        cols.append("notes")
    out[cols].to_excel(path, index=False)


# Vendor quality per month = share of stale records (A slips in Sep, B has a bad Sep, C stays patchy)
PLAN = {
    "2026-07": {"names": ["vendorA_2026-07.xlsx", "vendorB_jul_export.xlsx", "vendorC_202607.xlsx"],
                "request": "creator_request_2026-07.xlsx", "stale": (.05, .15, .45)},
    "2026-08": {"names": ["creator_data_0812.xlsx", "social_export_aug.xlsx", "Book1.xlsx"],
                "request": "Aug request.xlsx", "stale": (.05, .12, .40)},
    "2026-09": {"names": ["drop_2.xlsx", "drop_3.xlsx", "drop_1.xlsx"],
                "request": "request.xlsx", "stale": (.15, .30, .45)},
}

if __name__ == "__main__":
    if INBOX.exists():
        shutil.rmtree(INBOX)
    for i, month in enumerate(MONTHS):
        d = INBOX / month
        d.mkdir(parents=True)
        end = MONTH_END[month]
        truth = truth_for(i)
        truth.to_csv(DATA / f"_truth_{month}.csv", index=False)       # only for testing the prototype
        plan = PLAN[month]
        sa, sb, sc = plan["stale"]
        write_a(truth, end, sa, d / plan["names"][0], 10 + i)
        write_b(truth, end, sb, d / plan["names"][1], 20 + i, renamed=(month == "2026-09"))
        write_c(truth, end, sc, d / plan["names"][2], 30 + i, extra_col=(month == "2026-08"))
        req = month_request(i)
        write_request(d / plan["request"], PLATFORMS, req, blank_rows=0)
        n = pd.Series([len(r["channels"]) for r in req]).value_counts().sort_index(ascending=False).to_dict()
        print(f"{month}: {len(req)} creators requested {n} | files: {sorted(p.name for p in d.iterdir())}")
