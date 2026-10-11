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

### Current evaluation

The full B/C run appends dataset sizes, measured runtime, headline metrics, and the decision here.


## Evaluation harness — B / C

- Command: `make eval SEED=B`.
- Dataset: 150,000 payments per seed, 30 days.
- Runtime: 351.7 s.
- B: recall T1/all 100.00%/94.60%; precision HIGH 93.73%; FPR MEDIUM+ 17.30%; hard-negative FPR 64.76%; p95 0.726 ms.
- C: recall T1/all 100.00%/95.40%; precision HIGH 86.92%; FPR MEDIUM+ 19.01%; hard-negative FPR 64.47%; p95 0.716 ms.
- Frozen raw-probability thresholds: `t_med=0.0406830`, `t_high=0.4682278`.
- Typology recall B (T1/T2/T3/T4): 100.00%/97.33%/98.44%/78.00%; T1-evasive 100.00%. C: 100.00%/99.00%/98.44%/80.33%; T1-evasive 100.00%.
- B: AUC 0.99796; STP 82.70%; value stopped 98.76%; diversion 0.0127%; precision at top 0.5% (`k=750`) 99.33%.
- C: AUC 0.99771; STP 80.99%; value stopped 99.05%; diversion 0.0100%; precision at top 0.5% (`k=750`) 95.07%.
- 95% CIs (1,000 row resamples, seed 0), B: recall all 93.33–95.74%, T1/T1-evasive 100%, T2 95.20–98.96%, T3 97.08–99.54%, T4 73.06–82.51%; HIGH precision 92.17–95.21%; MEDIUM+ FPR 17.11–17.49%; hard-negative FPR 63.44–66.18%; precision@750 98.53–99.87%.
- 95% CIs, C: recall all 94.41–96.40%, T1/T1-evasive 100%, T2 97.86–100%, T3 97.27–99.51%, T4 75.74–84.70%; HIGH precision 84.81–88.86%; MEDIUM+ FPR 18.81–19.22%; hard-negative FPR 63.18–65.81%; precision@750 93.07–96.80%.
- B baselines (recall all / HIGH precision / MEDIUM+ FPR / AUC): logistic regression 94.33% / 95.33% / 17.54% / 0.99497; LightGBM without B/G 86.00% / 95.48% / 17.70% / 0.96630; rules-only 61.40% / 100.00% / 17.00% / 0.72207.
- Ablations (recall all / T1-evasive / MEDIUM+ FPR / AUC): drop B 90.87% / 100% / 17.65% / 0.97684; V 98.33% / 100% / 17.43% / 0.99808; P 98.07% / 100% / 17.41% / 0.99806; G 98.67% / 100% / 17.43% / 0.99803; H 94.13% / 100% / 17.42% / 0.99648; S 93.20% / 100% / 17.49% / 0.99719; R 97.33% / 100% / 17.39% / 0.99801.
- Degraded B: model missing/rules-only recall 61.40%, MEDIUM+ FPR 17.00%, `permissivePct=1.175%`; history missing recall 82.13%, FPR 18.07%, `permissivePct=0.413%`.
- Integrity replay refused 100/100 I1, 100/100 I2, and 100/100 I3 cases.
- Limits: synthetic project-generated data; value-stopped assumes flagged identity-risk transfers are held until the real supplier denies out of band; C is shifted but same-family; latency is measured single-threaded on this VM.
- Decision: retain the frozen model and report the high B/C and hard-negative false-positive rates without retuning.
