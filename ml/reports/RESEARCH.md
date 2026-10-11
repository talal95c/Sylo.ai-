# Lane B — research pass (features, decision policy, architecture)

Synthetic data only (seeds A/B/C from `sylo_risk.sim`). Model-only numbers below are **not** the
end-to-end engine numbers (rules floor + guarantee are added on top, see `BENCHMARKS.md`).
Every experiment trains/thresholds on seed A (days ≤20 / 21–25) and reports frozen on B and C.
Scripts and raw outputs: `ml/experiments/*.py|json`.

## Sources screened

| Source | Idea | Verdict |
|---|---|---|
| Bahnsen, Aouada, Ottersten — *Ensemble of example-dependent cost-sensitive decision trees* (arXiv:1505.04637, 2015) | decide on expected loss `p × amount`, not on `p` | tested (R1) |
| Vovk & Petej — *Venn-Abers predictors* (arXiv:1211.0025) | calibrated probability *interval*; use the upper bound to be stricter | not tested: isotonic already calibrated (Brier logged in model.json); interval adds latency for little demo value |
| *Graph-Transformer fraud detection … conformal risk control* (arXiv:2609.14234, 2026); *Temporal graph prototype-conditioned conformal prediction* (arXiv:2608.15768, 2026) | guarantee a miss-rate bound per typology | noted: our `t_med` is already a validation-quantile threshold; a conformal wrapper would only formalise it |
| *Finding money launderers using heterogeneous graph neural networks* (arXiv:2307.13499, 2023); *DELATOR* (arXiv:2205.10293, 2022) | graph features for mule networks | used as design input for B2.1 (lightweight connected components, no GNN at hackathon scale) |
| EU Reg. 2024/886 (VoP) and the BEC/APP sources in `docs/ia-securite-references.md` | a change of bank details is the central BEC/APP pattern | tested (R3) — **strongest result** |
| BEC literature (arXiv:2007.02415, 2309.14166) | compromised genuine mailbox defeats domain checks | confirmed by R2 |

## R1 — amount-aware (expected-loss) hold policy

C tuned on A-val to match the current analyst budget, then frozen.

| Seed | Policy | Holds | FPR legit | Recall (count) | Value stopped | T1 | T4 |
|---|---|---|---|---|---|---|---|
| B | `p ≥ t_med` (current) | 2 974 | 1.04 % | 95.40 % | 96.58 % | 91.78 % | 96.00 % |
| B | `p × amount ≥ C` (2 334 €) | 2 869 | 1.02 % | 90.73 % | 96.89 % | 92.67 % | **69.67 %** |
| B | hybrid `t_med OR p × amount ≥ 3 031 €` | 3 221 | 1.20 % | 95.80 % | 97.19 % | 92.89 % | 96.00 % |
| C | current | 2 600 | 0.79 % | 95.13 % | 95.48 % | 87.78 % | 98.33 % |
| C | expected loss | 3 330 | 1.30 % | 93.73 % | 97.19 % | 92.44 % | 83.00 % |
| C | hybrid | 3 153 | 1.15 % | 96.40 % | 97.01 % | 91.11 % | 98.33 % |

Finding: pure expected loss is *looser* on structuring (T4 sits just under 10 k€ by design) → rejected.
The hybrid is never looser by construction, but buys +0.4–1.3 pp recall for +0.16–0.36 pp FPR. **Not adopted** (FPR budget ≤1 %); kept as a policy knob.

## R2 — what the model misses on T1

37 of 450 T1 on B score under `t_med`; **all 37 are evasive**: genuine supplier domain
(compromised mailbox, `domain_lookalike=0`, `sender_domain_differs` 11 % vs 89 % for caught T1),
account often already paid 1–3 times. End-to-end T1 recall stays 100 % because the
score-independent guarantee `R-PV-01` (new bank details from an untrusted channel ⇒ out-of-band check) catches them.
This is the measured argument for keeping the guarantee independent of the score.

## R3 — “bank details changed since the pair's last payment” feature

Share of rows where the account differs from the pair's previous payment (seed B):
legit 2.5 %, hard negatives 34 % (mostly `bank_change`), T1 98.4 %, missed T1 97.3 %, T2 99 %, T3 0 %.

Same recipe, baseline reproduces the shipped model exactly (`t_med` 0.0406830).

| Seed | Model | AUC | Recall | T1 | T1 evasive | T2 | T4 | FPR legit | FPR hard neg | Precision HIGH |
|---|---|---|---|---|---|---|---|---|---|---|
| B | baseline | 0.99827 | 95.40 % | 91.78 % | 72.59 % | 96.00 % | 96.00 % | 1.04 % | 10.98 % | 89.45 % |
| B | + account_changed | 0.99848 | 96.47 % | 94.22 % | **80.74 %** | 99.33 % | 94.33 % | 1.09 % | 15.69 % | **90.66 %** |
| C | baseline | 0.99843 | 95.13 % | 87.78 % | 75.56 % | 97.67 % | 98.33 % | 0.79 % | 12.40 % | 91.25 % |
| C | + account_changed | 0.99883 | 96.80 % | 92.22 % | **84.44 %** | 99.67 % | 98.33 % | 0.84 % | 18.13 % | 92.34 % |

Finding: +8 to +9 pp on evasive T1, +1.1 to +1.7 pp overall, precision HIGH crosses the 90 % target on B, FPR legit +0.05 pp.
Cost: more holds on genuine bank changes (hard negatives) — which is exactly the case the out-of-band
check is designed for (oobResolvable, escrow, not a block). T4 −1.7 pp on B (noise-level, 5 of 300).
**Adopt as candidate v2 feature** after the train/engine parity fix lands: needs `PairHistory.last_account_id`
in the context (added to spec, additive), the feature in `features.py`, a parity test, retrain and a full re-eval.

## Caveats

- Synthetic generator: the bank-change signal is strong partly because the simulator models it; real
  payee-amendment data would be noisier (legit bank changes are more frequent in some sectors).
- Model-only metrics; the end-to-end effect must be measured through `make eval` (rules + guarantee + OOB action tier).
