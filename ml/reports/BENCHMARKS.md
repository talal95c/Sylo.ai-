# Benchmark journal

All evaluation data are synthetic. Passes 1–4 document the prior baselines; Pass 5 retrained once for the bank-change feature and reports the resulting metrics without further tuning.

## Block 1 — System 2 CaseWriter

- Command: `cd ml && RUN_LIVE=1 uv run pytest tests/test_case_live.py`.
- Dataset: scene 2, 20 injection variants.
- Runtime: 75.18 s. Validator pass rate 50%; fallback rate 50%; accepted-less-strict count 0; latency p50/p95 3,673/4,131 ms.
- Scene 2 cache: live `mistral-small-latest` result.
- Decision: the CaseWriter is advisory only; invalid or less-strict output falls back to the deterministic template.

## Block 2 — evaluation harness

### Model history

| Pass | Command / data | Key result | Decision |
|---|---|---|---|
| 1 | `uv run python -m sylo_risk.train`; seed A, 150,000 rows | 100% recall; `t_med=5e-324`; trivial separation | Judged a leak; rebuild the populations and history. Runtime was not recorded. |
| 2 | `uv run python -m sylo_risk.report`; full seeds A/B/C | T1/T2/T3 remained at 100%; same diagnosis | No further tuning loop; revise populations and scoring. Runtime was not recorded. |
| 3 | Full seeds A/B/C; frozen raw-probability thresholds | `t_med=0.0406830`, `t_high=0.4682278`; A-val/Brier raw / isotonic: 0.00248 / 0.00231; B: 0.00276 / 0.00280, recall all 95.40%, T1 91.78%, evasive T1 72.59%, T2 96.00%, T3 98.22%, T4 96.00%, FPR 1.04%, HIGH precision 89.45%; C: 0.00277 / 0.00272, recall all 95.13%, T1 87.78%, evasive T1 75.56%, T2 97.67%, T3 98.67%, T4 98.33%, FPR 0.79%, HIGH precision 91.25% | Accepted as the honest frozen integration baseline; no further tuning in that pass. Runtime was not recorded. |

The pass-3 A-val results were: recall all 96.15%, T1 89.09%, evasive T1 68.42%, T2 100%, T3 98.33%, T4 96.36%, FPR 1.00%, and HIGH precision 90.40%.

## Pass 4 — skew + rule + degraded fixes

- Command: `make eval SEED=B`; 150,000 payments per seed (B and C), 30 days; runtime 511.5 s. “Before” is the prior full-engine report (`347aa6e`). No retraining; frozen thresholds remain `t_med=0.0406830`, `t_high=0.4682278`.

| Metric | Before B | Pass 4 B | Before C | Pass 4 C |
|---|---:|---:|---:|---:|
| Recall all | 94.60% | 98.20% | 95.40% | 98.87% |
| T1 | 100.00% | 100.00% | 100.00% | 100.00% |
| T1 evasive | 100.00% | 100.00% | 100.00% | 100.00% |
| T2 | 97.33% | 97.67% | 99.00% | 98.00% |
| T3 | 98.44% | 98.22% | 98.44% | 98.67% |
| T4 | 78.00% | 96.00% | 80.33% | 98.33% |
| Precision HIGH+ | 93.73% | 89.45% | 86.92% | 91.25% |
| FPR MEDIUM+ | 17.30% | 6.79% | 19.01% | 8.37% |
| FPR hard negatives | 64.76% | 47.56% | 64.47% | 47.00% |
| STP | 82.70% | 93.21% | 80.99% | 91.63% |
| p95 | 0.726 ms | 0.659 ms | 0.716 ms | 0.672 ms |
| Degraded permissivePct (rules-only / no history) | 1.175% / 0.413% | 0.757% / 0.148% | not measured | 0.746% / 0.122% |

- Degraded details (all `neverLooser=false`): B model missing recall/FPR/permissivePct 77.20%/16.04%/0.757%; history missing 99.53%/17.00%/0.148%. C: model missing 76.80%/17.45%/0.746%; history missing 99.67%/18.41%/0.122%. The nonzero permissive rates are reported without tuning; pass 3 degraded metrics were evaluated on B only.
- B legitimate MEDIUM+ holds: 10,077 of 148,500 (6.79%). Guarantee rules R-PV-01 and/or R-FL-01: 8,035 (79.74% of holds); other rules: 1,287 (12.77%); model-only: 755 (7.49%).
- Pass 4 95% CIs: B recall all 97.41–98.83%, HIGH precision 87.55–91.21%, MEDIUM+ FPR 6.66–6.92%, hard-negative FPR 46.13–49.02%; C 98.23–99.34%, 89.55–92.90%, 8.24–8.51%, 45.56–48.38%, respectively.
- Decision: keep the model frozen, document the feature-parity and rule fixes, and report remaining hard-negative FPR and nonzero degraded permissive rates as measured.

## Pass 5 — strict degraded + bank-change feature

- Command: `make eval SEED=B`; both B and C scored at 150,000 payments each over 30 days. Runtime: 490.4 s.
- Retrained artifact: `gbm-20261011`; `t_med=0.0445733`, `t_high=0.4510719`; raw/isotonic Brier on A-val: 0.002397 / 0.002256. Combined model artifacts are 1,627,852 bytes; model score remains capped below 90.

| Metric | Pass 4 B | Pass 5 B | Pass 4 C | Pass 5 C |
|---|---:|---:|---:|---:|
| Recall all | 98.20% | 98.13% | 98.87% | 99.00% |
| T1 | 100.00% | 100.00% | 100.00% | 100.00% |
| T1 evasive | 100.00% | 100.00% | 100.00% | 100.00% |
| T2 | 97.67% | 99.67% | 98.00% | 99.67% |
| T3 | 98.22% | 98.44% | 98.67% | 98.22% |
| T4 | 96.00% | 93.33% | 98.33% | 98.00% |
| Precision HIGH+ | 89.45% | 89.86% | 91.25% | 91.62% |
| FPR MEDIUM+ | 6.79% | 6.72% | 8.37% | 8.32% |
| FPR hard negatives | 47.56% | 47.58% | 47.00% | 47.02% |
| STP | 93.21% | 93.28% | 91.63% | 91.68% |
| p95 | 0.659 ms | 0.733 ms | 0.672 ms | 0.644 ms |
| Degraded risk `permissivePct` (model missing / history missing) | 0.757% / 0.148% | 0.352% / 0.0047% | 0.746% / 0.122% | 0.376% / 0.0133% |

- Pass 5 95% CIs: B recall all 97.38–98.79%, HIGH precision 88.08–91.43%, MEDIUM+ FPR 6.59–6.85%, hard-negative FPR 46.17–49.04%; C 98.46–99.47%, 89.95–93.15%, 8.18–8.45%, 45.59–48.40%. Typology confidence intervals are recorded in `metrics.json`.

| Seed | Degraded mode | Recall all | FPR MEDIUM+ | Risk `permissivePct` | Action `permissiveActionPct` | HIGH→MED / HIGH→LOW / MED→LOW | `neverLooser` |
|---|---|---:|---:|---:|---:|---:|---|
| B | Model missing (strict rules only) | 100.00% | 43.00% | 0.352% | 0.107% | 522 / 0 / 6 | false |
| B | History missing | 100.00% | 100.00% | 0.0047% | 0.188% | 7 / 0 / 0 | false |
| C | Model missing (strict rules only) | 100.00% | 43.26% | 0.376% | 0.101% | 554 / 1 / 9 | false |
| C | History missing | 100.00% | 100.00% | 0.0133% | 0.172% | 20 / 0 / 0 | false |

All nonzero risk-tier permissiveness remains reported; no tuning was done to hide it. Legitimate B MEDIUM+ holds: 9,983 of 148,500 (6.72%); guarantee rules R-PV-01 and/or R-FL-01: 8,035 (80.49% of holds), other rules: 1,287 (12.89%), model only: 661 (6.62%).

| Seed | Model-only baseline without feature: recall all / T1 evasive / HIGH precision / FPR | Earlier offline feature experiment (same order) | Pass 5 retrained model-only (same order) |
|---|---|---|---|
| B | 95.40% / 72.59% / 89.45% / 1.04% | 96.47% / 80.74% / 90.66% / 1.09% | 96.20% / 80.00% / 89.86% / 1.06% |
| C | 95.13% / 75.56% / 91.25% / 0.79% | 96.80% / 84.44% / 92.34% / 0.84% | 96.60% / 84.00% / 91.62% / 0.83% |

The baseline and earlier feature-on columns are from the read-only experiment; Pass 5 is `modelOnlyMetrics` from this evaluation. Golden cases remain legit 25/LOW (`oobResolvable=True`) and diverted 77/HIGH (`oobResolvable=True`). The exact gate passed on both B and C: total recall stayed within 0.3 pp of Pass 4, T1 and T1-evasive recall remained 100%, MEDIUM+ FPR stayed within +0.5 pp, and both golden cases retained their required decisions. **Decision: keep the feature and report the measured results; no post-evaluation tuning.**

## B2.1 clusters

- Command: `cd ml && uv run python -m sylo_risk.eval_clusters`; 150,000 original payments on each of seeds B and C. The seeded evaluation-only augmentation adds 30 old popular suppliers (4–15 payers) and 30 young popular accounts (3–6 payers) per seed; no training data or Pass 5 model metrics are changed. RNG: `np.random.default_rng(SEEDS[seed] + 1_000_003)` (B: 21,261,005; C: 21,261,006).
- Detector: NetworkX payer→account graph in rolling two-day windows; flag at ≥3 payers and account age <120 days or <10 successful payments. Suspicious accounts merge on a shared payer or shared holder/border-region bank.
- `paymentsToDetect` counts campaign payments through the first detection day; the source frame is daily, so this is a day-boundary index, not intra-day latency. Runtime includes the detector and isolated-institution baseline.

| Seed | T3 campaigns detected | Payments-to-detect p50 / p90 | False clusters: original legit / old suppliers / young popular | Isolated-institution detection | Isolated payments-to-detect p50 / p90 | T3 payer fan-in p50 | Runtime |
|---|---:|---:|---:|---:|---:|---:|---:|
| B | 30/30 (100.0%) | 7 / 10.1 | 0 / 0 / 30 | 30/30 (100.0%) | 11.5 / 16.1 | 14 | 4.51 s |
| C | 30/30 (100.0%) | 7.5 / 10.2 | 0 / 0 / 30 | 29/30 (96.7%) | 10 / 15.2 | 15 | 4.49 s |

The synthetic T3 fan-in is easy to detect: median 14–15 distinct payers per campaign, well above the three-payer threshold. The young-popular hard negatives trigger all 30 false clusters per seed; old popular suppliers and original legitimate transactions trigger none. This is a measured limit, not evidence that the detector separates real mule activity from legitimate account growth. `metrics.json` contains the seed-level results and rates.

- Engine window detector (`WindowClusterDetector`, main 5971aaa): ≥3 payments into young/thin accounts at a border bank; offline benchmark unchanged.

The risk package had institution-to-region mappings but no regional coordinates. Coarse one-decimal region representative centroids were added; output points are region-level only and never use institution coordinates. The engine's `WindowClusterDetector` is covered by the scene 3 engine test, not by this offline benchmark.

## Pass 6 — T1 evasion

- Command: `cd engine && uv run --extra model python -m sylo_risk.evasion --seed B`; the frozen `gbm-20261011` model and thresholds were used. Each level bootstraps 2,000 rows with replacement from seed B's 450 T1 rows. The prior-payment levels are set on observed aggregate fields, not simulated events.

| Level | Definition | Recall MEDIUM+ | Recall HIGH+ | HIGH + OOB escrow | Action ≥HIGH | Model-only MEDIUM+ |
|---|---|---:|---:|---:|---:|---:|
| E0 | Current T1 | 100.00% | 76.45% | 19.85% | 56.60% | 92.95% |
| E1 | Trusted `verified_registry` provenance | 92.95% | 76.45% | 19.85% | 56.60% | 92.95% |
| E2 | E1; age ≥90 days, ≥3 successful payments (aggregate), not payee-owned, previous nominated account remains in history (`history_count` ≥1) | 92.65% | 75.30% | 19.85% | 55.45% | 92.65% |
| E3 | E2; payee owns account and `last_account_id` is that account, with `history_count` ≥1 | 75.50% | 51.50% | 13.75% | 37.75% | 67.35% |

E0–E3 fired rule counts (top five per level; counts can overlap):

| Level | Fired rules |
|---|---|
| E0 | R-PV-01: 2,000; R-FL-01: 1,522; R-NM-01: 1,286; R-FL-03: 982; R-FL-02: 14 |
| E1 | R-NM-01: 1,286; R-FL-03: 982; R-FL-02: 14 |
| E2 | R-NM-01: 1,286; R-FL-03: 982 |
| E3 | R-NM-01: 1,286 |

The five most common E3 positive SHAP reason features (top three per payment, not gated by the user-facing score threshold) were `log1p_successful_payments` (2,000), `norm_R1` (915), `name_match` (901), `log1p_account_age_days` (807), and `domain_lookalike` (784).

Seed B prevalence estimates:

| Threshold | Fraud TPR | Legitimate FPR | Prevalence | Precision | Legitimate holds / fraud caught |
|---|---:|---:|---:|---:|---:|
| MEDIUM+ | 98.13% | 6.72% | 1% | 12.85% | 6.78 |
| MEDIUM+ | 98.13% | 6.72% | 0.1% | 1.44% | 68.44 |
| MEDIUM+ | 98.13% | 6.72% | 0.01% | 0.15% | 684.97 |
| HIGH+ | 73.87% | 0.0842% | 1% | 89.86% | 0.11 |
| HIGH+ | 73.87% | 0.0842% | 0.1% | 46.76% | 1.14 |
| HIGH+ | 73.87% | 0.0842% | 0.01% | 8.07% | 11.39 |

MEDIUM+ TPR/FPR cite `metrics.json#/metrics/recallAll` and `#/metrics/fprMediumPlus`. `metrics.json` has no legitimate HIGH+ FPR, so HIGH+ TPR/FPR were counted from seed B's existing labels and frozen full-engine tiers using `evaluate._score_engine` (1,108/1,500 frauds and 125/148,500 legitimate payments at HIGH+; no retraining). All figures are synthetic-evaluation measurements, not production efficacy. Full per-level metrics, rules, SHAP examples, formulas, and source paths are in `evasion.json`.


## Evaluation harness — B / C

- Command: `make eval SEED=B`.
- Dataset: 150,000 payments per seed, 30 days.
- Runtime: 628.4 s.
- B: recall T1/all 100.00%/98.13%; precision HIGH 89.86%; FPR MEDIUM+ 6.72%; hard-negative FPR 47.58%; p95 2.604 ms.
- C: recall T1/all 100.00%/99.00%; precision HIGH 91.62%; FPR MEDIUM+ 8.32%; hard-negative FPR 47.02%; p95 2.587 ms.
- Decision: retain the frozen model; report B/C metrics and confidence intervals without retuning.
