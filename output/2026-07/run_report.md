# Vendor QA & waterfall run — 2026-07

Files: creator_request_2026-07.xlsx → request list; vendorA_2026-07.xlsx → vendor_a; vendorB_jul_export.xlsx → vendor_b; vendorC_202607.xlsx → vendor_c

Requested: **800 creators, 1920 channels** (instagram 637, tiktok 643, youtube 640).

## 1. Vendor QA (requested channels only)

| Vendor | Tier | Score | Fresh coverage | Completeness | Freshness | Validity | The Pulse computable | The Lens computable | The Hub computable |
|---|---|---|---|---|---|---|---|---|---|
| vendor_a | 1 | 0.850 | 48.5% | 96.4% | 95.5% | 99.8% | 96% | 97% | 90% |
| vendor_b | 2 | 0.847 | 62.8% | 89.3% | 85.5% | 99.7% | 90% | 78% | 76% |
| vendor_c | 3 | 0.661 | 29.7% | 73.0% | 54.0% | 99.0% | 70% | 74% | 21% |

## 2. Waterfall progression

| | after T1 (vendor_a) | after T2 (vendor_b) | after T3 (vendor_c) |
|---|---|---|---|
| display_name * | 85.2% | 97.4% | 98.4% |
| country * | 84.9% | 97.6% | 98.8% |
| contact_email | 78.4% | 93.1% | 95.0% |
| category | 83.2% | 96.5% | 97.9% |
| handle * | 47.6% | 83.3% | 87.5% |
| follower_count * | 47.4% | 82.5% | 86.8% |
| The Pulse (90d Reach Rate) * | 46.5% | 80.5% | 84.5% |
| The Lens (90d Growth Rate) * | 46.8% | 75.8% | 80.9% |
| The Hub (90d Meaningful Engagement Rate) * | 44.7% | 75.1% | 76.3% |
| creators needing 3 channels (480) complete | 6.0% | 29.8% | 33.3% |
| creators needing 2 channels (160) complete | 11.9% | 32.5% | 39.4% |
| creators needing 1 channel (160) complete | 40.0% | 66.9% | 71.2% |
| **creators complete** | **14.0%** | **37.8%** | **42.1%** |

## 3. Top creators per pillar

**The Pulse** (Attention): Creator 711 100, Creator 85 99, Creator 699 99, Creator 1332 97, Creator 480 96

**The Lens** (Affiliation): Creator 1490 100, Creator 1006 99, Creator 952 97, Creator 1053 97, Creator 872 97

**The Hub** (Action): Creator 116 99, Creator 425 98, Creator 515 98, Creator 1029 98, Creator 87 97

## 4. Agent decision log

- **recognise** → vendor_a: vendorA_2026-07.xlsx → vendor_a (matched 100%; next best vendor_b 0%)
- **recognise** → vendor_b: vendorB_jul_export.xlsx → vendor_b (matched 100%; next best vendor_a 0%)
- **recognise** → vendor_c: vendorC_202607.xlsx → vendor_c (matched 100%; next best vendor_a 0%)
- **request** → accept: 800 creators, 1920 channels requested (instagram 637, tiktok 643, youtube 640); 480 need 3 channels, 160 need 2 channels, 160 need 1 channel
- **history** → no history: vendor_a: first month on record, scored on this month only (0.85)
- **history** → no history: vendor_b: first month on record, scored on this month only (0.85)
- **qa** → flag: vendor_b: 162 metric values rejected because rounded counts could move them by more than 5%; a lower tier fills them if it can
- **history** → no history: vendor_c: first month on record, scored on this month only (0.66)
- **qa** → note: vendor_c doesn't supply saves_90d; metrics that need it can't come from vendor_c (except where a platform override doesn't use it)
- **qa** → flag: vendor_c: 34 metric values outside plausible bounds were rejected
- **tiering** → tier 1: score 0.85: fresh coverage 48% of requested channels (strongest on youtube 84%), freshness 95%, metrics computable: The Pulse 96%, The Lens 97%, The Hub 90%
- **tiering** → tier 2: score 0.85: fresh coverage 63% of requested channels (strongest on instagram 76%), freshness 85%, metrics computable: The Pulse 90%, The Lens 78%, The Hub 76%
- **tiering** → tier 3: score 0.66: fresh coverage 30% of requested channels (strongest on tiktok 30%), freshness 54%, metrics computable: The Pulse 70%, The Lens 74%, The Hub 21%
- **gate tier 1** → use vendor_a: first tier
- **assess after tier 1** → continue: 14.0% of creators complete, 41.7% of requested channels complete
- **gate tier 2** → use vendor_b: 7 required item(s) below target (display_name, country, handle, follower_count, reach_rate, growth_rate, meaningful_eng_rate); vendor_b can fill 3543 open cells (62.5%)
- **assess after tier 2** → continue: 37.8% of creators complete, 65.7% of requested channels complete
- **gate tier 3** → use vendor_c: 5 required item(s) below target (handle, follower_count, reach_rate, growth_rate, meaningful_eng_rate); vendor_c can fill 405 open cells (19.3%)
- **assess after tier 3** → done: 42.1% of creators complete, 68.8% of requested channels complete
- **qa** → 25 blocked: CROSS_VENDOR_DISCREPANCY (RED) 19; IDENTITY_MATCH_UNCERTAIN (RED) 6; IDENTITY_CONFLICT_RESOLVED (YELLOW) 5; OUTLIER_SOURCE_EXCLUDED (YELLOW) 4; PRIMARY_SOURCE_MISSING (YELLOW) 849
- **review** → 25 decision(s) applied: 0 blocked item(s) still open

## 5. Residual gaps

462 creators still miss at least one required item — see `gaps.csv`.
