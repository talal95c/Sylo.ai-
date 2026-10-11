# Benchmark journal

All evaluation data are synthetic. Model iterations are historical; the final artifact was frozen after pass 3.

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
| 3 | Full seeds A/B/C; frozen raw-probability thresholds | `t_med=0.0406830`, `t_high=0.4682278`; A-val/Brier raw / isotonic: 0.00248 / 0.00231; B: 0.00276 / 0.00280, recall all 95.40%, T1 91.78%, evasive T1 72.59%, T2 96.00%, T3 98.22%, T4 96.00%, FPR 1.04%, HIGH precision 89.45%; C: 0.00277 / 0.00272, recall all 95.13%, T1 87.78%, evasive T1 75.56%, T2 97.67%, T3 98.67%, T4 98.33%, FPR 0.79%, HIGH precision 91.25% | Accepted as the honest frozen model; no more tuning. Runtime was not recorded. |

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
