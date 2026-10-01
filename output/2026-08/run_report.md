# Vendor QA & waterfall run — 2026-08

Files: Aug request.xlsx → request list; Book1.xlsx → vendor_c; creator_data_0812.xlsx → vendor_a; social_export_aug.xlsx → vendor_b

Requested: **800 creators, 1889 channels** (instagram 628, tiktok 636, youtube 625).

## 1. Vendor QA (requested channels only)

| Vendor | Tier | Score | Fresh coverage | Completeness | Freshness | Validity | The Pulse computable | The Lens computable | The Hub computable |
|---|---|---|---|---|---|---|---|---|---|
| vendor_b | 1 | 0.842 | 64.4% | 89.2% | 87.7% | 99.7% | 88% | 80% | 76% |
| vendor_a | 2 | 0.840 | 51.1% | 96.3% | 94.0% | 99.9% | 96% | 96% | 90% |
| vendor_c | 3 | 0.656 | 32.2% | 72.4% | 59.6% | 98.9% | 69% | 72% | 21% |

## 2. Waterfall progression

| | after T1 (vendor_b) | after T2 (vendor_a) | after T3 (vendor_c) |
|---|---|---|---|
| display_name * | 89.8% | 98.1% | 98.5% |
| country * | 90.1% | 97.8% | 98.1% |
| contact_email | 74.1% | 95.1% | 96.0% |
| category | 85.4% | 97.0% | 97.4% |
| handle * | 61.6% | 85.2% | 88.8% |
| follower_count * | 60.3% | 84.2% | 87.7% |
| The Pulse (90d Reach Rate) * | 56.1% | 81.5% | 84.9% |
| The Lens (90d Growth Rate) * | 51.5% | 79.0% | 83.3% |
| The Hub (90d Meaningful Engagement Rate) * | 51.6% | 77.9% | 78.9% |
| creators needing 3 channels (465) complete | 3.9% | 32.9% | 36.3% |
| creators needing 2 channels (159) complete | 11.3% | 41.5% | 44.6% |
| creators needing 1 channel (176) complete | 29.5% | 61.4% | 64.8% |
| **creators complete** | **11.0%** | **40.9%** | **44.2%** |

## 3. Top creators per pillar

**The Pulse** (Attention): Creator 1133 99, Creator 85 99, Creator 711 98, Creator 1332 96, Creator 41 95

**The Lens** (Affiliation): Creator 1490 100, Creator 234 99, Creator 785 99, Creator 598 98, Creator 348 98

**The Hub** (Action): Creator 515 98, Creator 869 98, Creator 425 98, Creator 1133 98, Creator 623 97

## 4. Agent decision log

- **recognise** → vendor_c: Book1.xlsx → vendor_c (matched 88%; next best vendor_a 0%)
- **learn** → note: vendor_c sent new column(s) we don't use: notes
- **recognise** → vendor_a: creator_data_0812.xlsx → vendor_a (matched 90%; next best vendor_b 0%)
- **recognise** → vendor_b: social_export_aug.xlsx → vendor_b (matched 90%; next best vendor_a 0%)
- **request** → accept: 800 creators, 1889 channels requested (instagram 628, tiktok 636, youtube 625); 465 need 3 channels, 159 need 2 channels, 176 need 1 channel
- **history** → blend: vendor_c: this month 0.67; 1-month reliability 0.56 (QA average 0.66, review accuracy 31% over 13 reviewed dispute(s); up) → blended 0.66 at 15% reliability weight
- **qa** → note: vendor_c doesn't supply saves_90d; metrics that need it can't come from vendor_c (except where a platform override doesn't use it)
- **qa** → flag: vendor_c: 23 metric values outside plausible bounds were rejected
- **history** → blend: vendor_a: this month 0.85; 1-month reliability 0.76 (QA average 0.85, review accuracy 56% over 16 reviewed dispute(s); up) → blended 0.84 at 15% reliability weight
- **history** → blend: vendor_b: this month 0.86; 1-month reliability 0.76 (QA average 0.85, review accuracy 57% over 21 reviewed dispute(s); up) → blended 0.84 at 15% reliability weight
- **qa** → flag: vendor_b: 140 metric values rejected because rounded counts could move them by more than 5%; a lower tier fills them if it can
- **tiering** → tier 1: score 0.84: fresh coverage 64% of requested channels (strongest on tiktok 77%), freshness 88%, metrics computable: The Pulse 88%, The Lens 80%, The Hub 76%
- **tiering** → tier 2: score 0.84: fresh coverage 51% of requested channels (strongest on youtube 85%), freshness 94%, metrics computable: The Pulse 96%, The Lens 96%, The Hub 90%
- **tiering** → tier 3: score 0.66: fresh coverage 32% of requested channels (strongest on youtube 35%), freshness 60%, metrics computable: The Pulse 69%, The Lens 72%, The Hub 21%
- **gate tier 1** → use vendor_b: first tier
- **assess after tier 1** → continue: 11.0% of creators complete, 37.4% of requested channels complete
- **gate tier 2** → use vendor_a: 7 required item(s) below target (display_name, country, handle, follower_count, reach_rate, growth_rate, meaningful_eng_rate); vendor_a can fill 2780 open cells (60.2%)
- **assess after tier 2** → continue: 40.9% of creators complete, 68.0% of requested channels complete
- **gate tier 3** → use vendor_c: 5 required item(s) below target (handle, follower_count, reach_rate, growth_rate, meaningful_eng_rate); vendor_c can fill 312 open cells (17.0%)
- **assess after tier 3** → done: 44.2% of creators complete, 70.5% of requested channels complete
- **qa** → 31 blocked: CROSS_VENDOR_DISCREPANCY (RED) 23; IDENTITY_MATCH_UNCERTAIN (RED) 8; IDENTITY_CONFLICT_RESOLVED (YELLOW) 4; OUTLIER_SOURCE_EXCLUDED (YELLOW) 10; PRIMARY_SOURCE_MISSING (YELLOW) 748
- **review** → 31 decision(s) applied: 0 blocked item(s) still open

## 5. Residual gaps

445 creators still miss at least one required item — see `gaps.csv`.
