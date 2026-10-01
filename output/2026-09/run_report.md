# Vendor QA & waterfall run — 2026-09

Files: drop_1.xlsx → vendor_c; drop_2.xlsx → vendor_a; drop_3.xlsx → vendor_b; request.xlsx → request list

Requested: **800 creators, 1884 channels** (instagram 628, tiktok 632, youtube 624).

## 1. Vendor QA (requested channels only)

| Vendor | Tier | Score | Fresh coverage | Completeness | Freshness | Validity | The Pulse computable | The Lens computable | The Hub computable |
|---|---|---|---|---|---|---|---|---|---|
| vendor_a | 1 | 0.817 | 44.9% | 96.6% | 86.1% | 99.9% | 96% | 96% | 92% |
| vendor_b | 2 | 0.788 | 52.0% | 89.6% | 71.2% | 99.7% | 90% | 80% | 77% |
| vendor_c | 3 | 0.654 | 30.6% | 72.5% | 56.5% | 98.9% | 70% | 72% | 20% |

## 2. Waterfall progression

| | after T1 (vendor_a) | after T2 (vendor_b) | after T3 (vendor_c) |
|---|---|---|---|
| display_name * | 79.6% | 95.6% | 96.9% |
| country * | 79.5% | 95.1% | 96.2% |
| contact_email | 73.9% | 89.5% | 92.0% |
| category | 78.8% | 93.8% | 95.8% |
| handle * | 43.6% | 74.7% | 81.4% |
| follower_count * | 44.0% | 74.8% | 81.0% |
| The Pulse (90d Reach Rate) * | 43.0% | 72.8% | 77.6% |
| The Lens (90d Growth Rate) * | 42.9% | 69.8% | 76.2% |
| The Hub (90d Meaningful Engagement Rate) * | 41.9% | 68.3% | 69.8% |
| creators needing 3 channels (461) complete | 4.6% | 20.2% | 22.8% |
| creators needing 2 channels (162) complete | 19.8% | 34.6% | 37.0% |
| creators needing 1 channel (177) complete | 37.9% | 57.6% | 61.6% |
| **creators complete** | **15.0%** | **31.4%** | **34.2%** |

## 3. Top creators per pillar

**The Pulse** (Attention): Creator 85 100, Creator 699 99, Creator 1332 99, Creator 114 98, Creator 770 98

**The Lens** (Affiliation): Creator 1006 99, Creator 318 97, Creator 1398 96, Creator 313 95, Creator 1246 95

**The Hub** (Action): Creator 1345 99, Creator 448 99, Creator 668 97, Creator 342 96, Creator 515 96

## 4. Agent decision log

- **recognise** → vendor_c: drop_1.xlsx → vendor_c (matched 90%; next best vendor_a 0%)
- **recognise** → vendor_a: drop_2.xlsx → vendor_a (matched 90%; next best vendor_b 0%)
- **recognise** → vendor_b: drop_3.xlsx → vendor_b (matched 80%; next best vendor_a 0%)
- **learn** → new column name: vendor_b now calls views_90d 'video_plays_90d' (was plays_90d); matched by name and value type (85%) and remembered
- **learn** → new column name: vendor_b now calls comments_90d 'comments_total' (was comment_count); matched by name and value type (78%) and remembered
- **request** → accept: 800 creators, 1884 channels requested (instagram 628, tiktok 632, youtube 624); 461 need 3 channels, 162 need 2 channels, 177 need 1 channel
- **history** → blend: vendor_c: this month 0.67; 2-month reliability 0.58 (QA average 0.67, review accuracy 39% over 36 reviewed dispute(s); up) → blended 0.65 at 15% reliability weight
- **qa** → note: vendor_c doesn't supply saves_90d; metrics that need it can't come from vendor_c (except where a platform override doesn't use it)
- **qa** → flag: vendor_c: 26 metric values outside plausible bounds were rejected
- **history** → blend: vendor_a: this month 0.82; 2-month reliability 0.78 (QA average 0.85, review accuracy 60% over 30 reviewed dispute(s); up) → blended 0.82 at 15% reliability weight
- **qa** → flag: vendor_a: 1 metric values outside plausible bounds were rejected
- **history** → blend: vendor_b: this month 0.79; 2-month reliability 0.75 (QA average 0.85, review accuracy 52% over 46 reviewed dispute(s); up) → blended 0.79 at 15% reliability weight
- **qa** → flag: vendor_b: 138 metric values rejected because rounded counts could move them by more than 5%; a lower tier fills them if it can
- **tiering** → tier 1: score 0.82: fresh coverage 45% of requested channels (strongest on youtube 78%), freshness 86%, metrics computable: The Pulse 96%, The Lens 96%, The Hub 92%
- **tiering** → tier 2: score 0.79: fresh coverage 52% of requested channels (strongest on instagram 64%), freshness 71%, metrics computable: The Pulse 90%, The Lens 80%, The Hub 77%
- **tiering** → tier 3: score 0.65: fresh coverage 31% of requested channels (strongest on tiktok 32%), freshness 57%, metrics computable: The Pulse 70%, The Lens 72%, The Hub 20%
- **gate tier 1** → use vendor_a: first tier
- **assess after tier 1** → continue: 15.0% of creators complete, 38.6% of requested channels complete
- **gate tier 2** → use vendor_b: 7 required item(s) below target (display_name, country, handle, follower_count, reach_rate, growth_rate, meaningful_eng_rate); vendor_b can fill 3200 open cells (52.8%)
- **assess after tier 2** → continue: 31.4% of creators complete, 60.1% of requested channels complete
- **gate tier 3** → use vendor_c: 5 required item(s) below target (handle, follower_count, reach_rate, growth_rate, meaningful_eng_rate); vendor_c can fill 533 open cells (18.8%)
- **assess after tier 3** → done: 34.2% of creators complete, 62.4% of requested channels complete
- **qa** → 25 blocked: CROSS_VENDOR_DISCREPANCY (RED) 14; IDENTITY_MATCH_UNCERTAIN (RED) 11; HISTORICAL_ANOMALY (YELLOW) 5; IDENTITY_CONFLICT_RESOLVED (YELLOW) 7; OUTLIER_SOURCE_EXCLUDED (YELLOW) 6; PRIMARY_SOURCE_MISSING (YELLOW) 793
- **review** → 25 decision(s) applied: 0 blocked item(s) still open

## 5. Residual gaps

523 creators still miss at least one required item — see `gaps.csv`.
