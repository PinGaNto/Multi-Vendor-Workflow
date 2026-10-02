# Creator Vendor QA + Tiered Waterfall Fill — prototype

Each run starts from a **creator request list** (which creators, which of their Instagram / TikTok / YouTube
channels). The pipeline QAs three vendor Excel files against that request only, ranks the vendors into
Tier 1/2/3, fills the data tier by tier, re-checks coverage after each tier, then scores every creator on
three pillars and outputs a filled Excel workbook plus a leaderboard.

| Pillar | Theme | Metric (90 days) | Formula |
|---|---|---|---|
| **The Pulse** | Attention | Reach Rate | views / followers |
| **The Lens** | Affiliation | Growth Rate | net new followers / previous total followers |
| **The Hub** | Action | Meaningful Engagement Rate | (comments + shares + saves) / total engagement |

## Run (monthly)
    pip install pandas pyyaml openpyxl streamlit
    streamlit run app.py                              # Workflow Control Center (upload or Generate Demo Data)
    python pipeline.py --inbox data/inbox/2026-10     # command line: one month's folder -> output/2026-10/
    python run_monthly.py [--reset]                   # every month in data/inbox/ in order (rebuilds memory)
    python generate_mock_data.py                      # sample Jul–Sep drops (replace with real files)

## Website
GitHub Pages serves `docs/index.html`: https://pinganto.github.io/Multi-Vendor-Workflow/ (the latest month's leaderboard with the Control Center on top). After a new month is finalized, run `python publish_site.py`, then commit and push `docs/`.

## Workflow Control Center
The Control Center sits **at the top of the leaderboard page** (`creator_leaderboard.html`, above the board) and also runs as a Streamlit app. Both follow the same steps.

**On the leaderboard page** (no install, runs in the browser): pick the month → upload the request list and vendor files (.xlsx/.csv) or press **Generate Demo Data** → **Start QA & Processing** → QA results (GREEN / YELLOW / RED creators, vendor scores with 3-month reliability, tiers, warnings) → **Human review** (a Decision per blocked item, Apply; a confirmed match is re-checked) → **Finalize & build leaderboard**, which rebuilds the board, channel boards and creator profiles below from the run. CSV downloads (leaderboard, filled channel data, QA flags + audit) appear after finalizing. **Reset Demo** returns to the published board. In-page runs are not saved: they use the settings, vendor-recognition registry and memory snapshot embedded when the page was built. The engine (`web/engine.js`) is a JavaScript port of the Python pipeline; `python tests/test_parity.py` runs both on the same demo files and memory and checks that flags, vendor scores, tiers, review outcomes and every creator score match.

**Streamlit app** (`streamlit run app.py`) → **1 Inputs** → **2 QA & Processing** → **3 Human Review** → **4 Finalize** → **5 Leaderboard / Reports**.
- **Inputs:** upload the month's files (any names). Each lands in an input slot (Requested creator list / Vendor A / B / C), recognised by content.
- **Generate Demo Data** (secondary button beside the uploader) creates a complete **Synthetic Demo Data** set and loads it into the same slots: a request list (100 creators, 60% needing all three channels), Vendor A/B/C files (200–300 records each, each vendor in its own format) and 3 months of synthetic history. From there the steps are exactly the same as with real files. Demo runs use `demo_workspace/` for memory and outputs, so the real `memory/` is never touched. Uploading real files replaces the demo inputs.
- **Seeded scenarios** (always present; which creators and their values are random each time): 8 clean creators (GREEN); 6 channels where Tier 1 lacks a field → fallback (YELLOW); 4 material discrepancies (RED); 2 Tier 1 outliers overruled by two agreeing vendors (YELLOW); 3 identity mismatches (RED); 2 identity conflicts resolved by majority (YELLOW); 4 historical anomalies (YELLOW); vendor quality A > B > C in 3 months of history and reviewed disputes. The "Seeded QA scenarios" panel lists them for the presenter. Every file has an *About* sheet and a `SYNTHETIC_DEMO_` file name; creators are invented ("Amber Otter (demo)", `@demo_…` handles, `DEMO-` IDs).
- **Human review in the app:** pick a Decision per blocked row and Apply (or use the Excel form offline). **Finalize & build leaderboard** appears once nothing is blocked.
- **Reset Demo** clears inputs, QA results, review decisions and generated outputs (the demo workspace), ready to start again.
- CLI equivalents: `python demo_data.py [--seed N]` and `python demo_data.py --reset`.

## Review agent (human review step)
Each blocked (RED) item has a **Review agent** panel. *Investigate with agent* (or *Investigate all*) hands the item to Claude together with six investigation tools that run on this month's data; Claude decides which to call and in what order, then replies with a decision from the allowed list, a confidence (high / medium / low), a one-line summary and the evidence it found. **Use suggestion** fills in the Decision; the reviewer still presses Apply, and the audit trail records whether the suggestion was followed or overridden.

| Tool | What it returns |
|---|---|
| `get_vendor_records` | Each vendor's raw record for the creator-channel: handle, counts, record date / age / freshness, rounding, computed metrics |
| `get_history` | Previous months' follower count, reach and scores, and the month-over-month change each vendor's value implies |
| `check_record_consistency` | Whether a vendor's own numbers hang together (implied previous total and growth) and how reach and engagement per view compare with the platform median |
| `find_handle_elsewhere` | Which creator IDs / platforms a handle appears under in any vendor file (a handle attached to another creator signals a mix-up) |
| `get_creator_profile` | The creator's handles on every platform and vendor, display names, country |
| `get_vendor_track_record` | A vendor's QA score parts, consistency with the other vendors, 3-month reliability and review accuracy (tie-breaker only) |

The agent runs on the Claude-hosted page, on the viewer's own Claude account (the first use asks permission). Where Claude isn't available (e.g. the GitHub Pages copy), *Show evidence* still runs the same tools and lists what they found. The agent works only from the vendor files and stored history; it can't check the live platform. In the demo, the vendor that is wrong in a discrepancy alternates between Vendor A and B, so always siding with Tier 1 doesn't pass. Code: `web/investigate.js`.

## Vendor Reliability (rolling 3 months)
`3-month reliability = 70% × average monthly QA score + 30% × review accuracy` (review accuracy = share of reviewed disputes involving the vendor where the reviewer kept its value or account; QA average alone if there were no disputes). Tiering uses **85% this month + 15% reliability**. Window and weights: `config.yaml → qa.reliability`, `qa.history_weight`. Shown on the Vendor QA tab of the workbook and the app's *Vendor reliability* tab.

## What it learns, month over month (memory/)
- **Vendor recognition** (`vendor_registry.json`): each file is matched to a vendor by its column names (75%), platform spellings like IG/TT/YT (15%) and past file-name words (10%). It needs a 55% match and a 15-point lead over the next vendor; otherwise the file is flagged and you assign it. If a vendor renames a column, the new name is matched by name similarity and value type (number / date / text), accepted at 60% or above, logged, and remembered for next month.
- **Vendor quality history** (`vendor_history.csv`) and **review audit** (`review_audit.csv`): feed the rolling 3-month Vendor Reliability score above, so one bad month moves a vendor less than a sustained decline.
- **Creator history** (`creator_history.csv`): every requested creator's channel scores per month. On the leaderboard page, click any creator to open a profile with this month's channels (or why one isn't filled) and month-by-month Pulse / Lens / Hub charts per channel, with a table view.

## QA, flags and human review
**Principle:** automate the obvious cases, document unusual but acceptable ones, escalate only ambiguous or materially conflicting ones. A problem with one creator never stops the batch.

**Sequence:** import → standardise → match creators → evaluate vendors → fill with fallback → cross-vendor QA →
historical checks → **QA report** → human review of BLOCKED items → finalize master → percentiles / scores → leaderboard.

| Reason code | Severity | When | What happens |
|---|---|---|---|
| `IDENTITY_MATCH_UNCERTAIN` | RED | Vendors report different accounts (handle / profile URL, normalised) for a creator-channel and no majority agrees | None of that channel's data is merged until reviewed |
| `IDENTITY_CONFLICT_RESOLVED` | YELLOW | 2+ vendors agree on the account | Odd vendor out is not used for that channel |
| `CROSS_VENDOR_DISCREPANCY` | RED | Values differ beyond the threshold with no credible majority | Disputed metric (and metrics computed from it) held back; the highest tier is **not** picked by default |
| `OUTLIER_SOURCE_EXCLUDED` | YELLOW | 2 vendors agree, 1 is an outlier (even Tier 1) | Agreeing value used (highest tier among them) |
| `PRIMARY_SOURCE_MISSING` | YELLOW | Tier 1 had no record / stale / invalid / excluded | Lower tier used; fallback source recorded |
| `HISTORICAL_ANOMALY` | YELLOW | Change vs last month beyond limits (followers > +200% or < −50%) | Kept (could be viral); previous, current and % change recorded |

Display names are never used to match. Thresholds (followers 25% relative, reach 30%, growth 5 points, meaningful engagement 30%), majority rules, severities, history limits and the gate mode are all in `config.yaml → qa_rules / review`. Vendor **consistency** (how often a vendor agrees with the others) is part of the vendor score.

**Review loop:** stage 1 writes `output/<month>/qa_report_<month>.xlsx`, which has a Summary tab, a *Blocked — review* form with one row per RED item (vendor values, discrepancy, source info, explanation, recommended action, a Decision dropdown, Manual value and Reviewer), a Warnings tab and a Reason codes tab. Fill it in, then run
`python review.py --month 2026-09 --decisions <file>` (or upload it on the app). Decisions: CONFIRM_MATCH, REJECT_MATCH, SELECT_VENDOR_A/B/C, MANUAL_VALUE, EXCLUDE. Only the affected records are reprocessed. A confirmed match is re-checked for discrepancies. Partial reviews are fine, and anything without a decision stays open. Every decision is appended to `memory/review_audit.csv` with the original values, reason, decision, final value and source, reviewer and UTC timestamp.

**Leaderboard gate:** `strict` (default) builds no leaderboard while any RED item is open; `exclude_unresolved` leaves them out and continues. Either way, unresolved items never enter the master data or the percentile calculations.

**Known limit:** a wrong value reported by only one vendor can't be caught by the cross-vendor check; only the historical check (if it's a big jump) can catch it. In the sample, 12 of 1,532 follower counts were single-source and wrong.

`python demo_review.py --month 2026-09` is a **simulated reviewer for the sample data only** (it uses the sample answer key); `python run_monthly.py --reset --demo-review` runs Jul–Sep end to end.

## How the metrics are built
- **One vendor record per metric.** A metric's inputs (e.g. views and followers) always come from the same vendor record, so figures from different vendors and snapshot dates are never mixed into one ratio. The metric is then filled tier by tier like any other value, and its source vendor is recorded.
- **Bad data is rejected, not averaged in.** Values outside a plausible range (e.g. reach above 100x) are rejected. If a vendor rounds its counts so much that the metric could move by more than 5% (Vendor B's follower counts are rounded to 10, so growth for a slow-growing account is mostly rounding), the value is rejected and the next tier fills it.
- **Scores are 0–100 percentiles** among the requested channels in this run:
  - *The Pulse* is compared within platform, because TikTok views run far higher than Instagram views.
  - *The Lens* is compared within platform **and follower-size band** (nano / micro / mid / macro), because small accounts grow faster. A band with fewer than 8 peers falls back to the whole platform.
  - *The Hub* is compared within platform. **Hidden likes** would inflate the rate, so the Hub metric is marked n/a for those accounts: it's not counted as missing, and the creator's Hub score uses their other channels. **YouTube doesn't publish saves**, so its formula leaves saves out.
- A creator's pillar score is the average of their requested channels' percentiles. **Primary role** is their highest pillar.

## Request list (`creator_request_template.xlsx`)
One row per creator: `creator_id`, optional `creator_name`, and **Y** under each channel needed.
Channels that aren't requested never count against completeness or a vendor's score. A long format
(`creator_id`, `platform`) also works.

## Pipeline stages
0. Request → 1. Ingest & map (renames, platform names, unit and country fixes, derived inputs, hidden-likes flag) →
2. QA on requested scope (coverage, completeness incl. whether each metric is computable, freshness, validity,
implausible and imprecise values) → 3. Tiering → 4. Waterfall (gate → prepare → fill → assess) → 5. Scoring → 6. Outputs.
Every decision is logged with the reason and numbers behind it.

## Outputs
- `output/<month>/creator_fill_<month>.xlsx`: Summary (incl. which file was recognised as which vendor) · Leaderboard (creators: the three scores, ranks and primary role as live formulas) · Instagram / TikTok / YouTube (one leaderboard per platform, ranking each filled channel on its own, even if the creator's other channels are still missing) · Channels (raw metric, percentile, peer group and source per channel) · Creators · Metric Definitions · Vendor QA (this month, past months, blended score) · Vendor History (scores by month + what was learned) · Creator History · Waterfall · Gaps (with reasons) · Decision Log
- `creator_leaderboard.html`: the Workflow Control Center at the top, then Pulse / Lens / Hub tabs × All channels / Instagram / TikTok / YouTube boards, with filters by size band, country, primary role and confidence; each board shows the top 10 and bottom 10 with the middle ranks behind an expand button; channel rows whose creator has other channels still missing are marked "other channels pending"
- `qa_report_<month>.xlsx` (stage 1 review form; final version after review), `qa_flags.csv` (machine-readable flags)
- CSVs, `run_report.md`, `run_summary.json`

## Adapting to real vendors
Edit `config.yaml` only: platforms, fields, metric inputs, metric formulas / bounds / platform overrides,
size bands, vendor column maps, transforms, `derive` expressions, rounding `precision`, QA weights and thresholds.
