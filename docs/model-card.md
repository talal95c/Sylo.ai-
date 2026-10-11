# Lane B model card

## Purpose and scope

Lane B provides an advisory fraud-risk score for synthetic cross-border business-payment scenarios. It is intended for demonstrations, controlled testing, and analyst decision support. It is not evidence of production performance and must not independently approve, release, or route a payment. Decisions remain subject to payment controls and human oversight.

Out of scope: consumer credit, customer eligibility, autonomous payment release, real-world fraud-rate claims, and use on real customer data without separate validation and governance.

## Data and model

Training uses synthetic seed A; evaluation uses synthetic seeds B and C. The recorded evaluation set has 150000 payments over 30 days. <!-- metrics.json: /dataset/payments, /dataset/days -->

The synthetic generator covers typologies T1–T4 and legitimate payments. <!-- metrics.json: /byTypology/0/typology, /byTypology/1/typology, /byTypology/2/typology, /byTypology/3/typology -->

The model is LightGBM with isotonic calibration, monotonic feature constraints, and SHAP-based reason text. The model score is capped at 89. <!-- metrics.json: /modelPolicy/scoreCap -->

The frozen model version is `gbm-20261011`. <!-- metrics.json: /modelVersion -->

Frozen thresholds: MEDIUM `0.04457334309526271` and HIGH `0.4510718837561716`. <!-- metrics.json: /frozenThresholds/t_med, /frozenThresholds/t_high -->

Seed-A retraining reproduced the frozen thresholds and calibrated predictions exactly on the seed-B comparison set. The normalized LightGBM tree text also differs, so the artifact-byte difference is not metadata-only; the original artifacts remain in use.

## Synthetic evaluation

These are synthetic results only; they should not be interpreted as estimates of performance on real payments.

| Seed | AUC | Total recall | HIGH precision | MEDIUM+ FPR | STP |
|---|---:|---:|---:|---:|---:|
| B | `0.9984556790123458` <!-- metrics.json: /metrics/auc --> | `0.9813333333333333` <!-- metrics.json: /metrics/recallAll --> | `0.8986212489862125` <!-- metrics.json: /metrics/precisionHigh --> | `0.06722558922558923` <!-- metrics.json: /metrics/fprMediumPlus --> | `0.9327744107744108` <!-- metrics.json: /metrics/stpRate --> |
| C | `0.9988092772166106` <!-- metrics.json: /outOfDistribution/auc --> | `0.99` <!-- metrics.json: /outOfDistribution/recallAll --> | `0.916243654822335` <!-- metrics.json: /outOfDistribution/precisionHigh --> | `0.08315151515151516` <!-- metrics.json: /outOfDistribution/fprMediumPlus --> | `0.9168484848484848` <!-- metrics.json: /outOfDistribution/stpRate --> |

Typology recall is reported separately for T1–T4; per-typology counts, intervals, and values are in `ml/reports/metrics.json`. <!-- metrics.json: /byTypology -->

The offline `NetworkXClusterDetector` benchmark detects `30/30` campaigns for each seed, with `0` false clusters among original legitimate payments for both seeds. The engine uses a separate `WindowClusterDetector`; its runtime behavior is not measured by the offline benchmark. <!-- metrics.json: /clusters/results/B/campaignsDetected, /clusters/results/B/campaignCount, /clusters/results/C/campaignsDetected, /clusters/results/C/campaignCount, /clusters/results/B/falseClusters/legit, /clusters/results/C/falseClusters/legit -->

The cluster benchmark also records `30` young-popular legitimate false clusters per seed; popular-supplier false clusters are `0` for both seeds. These are evaluation-only hard negatives, not evidence of deployment behavior. <!-- metrics.json: /clusters/results/B/falseClusters/youngPopular, /clusters/results/C/falseClusters/youngPopular, /clusters/results/B/falseClusters/popularSupplier, /clusters/results/C/falseClusters/popularSupplier -->

## Baselines and ablations

On seed B, logistic regression records total recall `0.9833333333333333` and MEDIUM+ FPR `0.06871380471380471`; rules-only records total recall `0.398` and MEDIUM+ FPR `0.06277441077441077`. These are synthetic comparators, not production benchmarks. <!-- metrics.json: /baselines/0/recallAll, /baselines/0/fprMediumPlus, /baselines/2/recallAll, /baselines/2/fprMediumPlus -->

The feature-family ablation that drops B records total recall `0.8626666666666667` and MEDIUM+ FPR `0.07003367003367003`, compared with the full synthetic model above. <!-- metrics.json: /ablations/0/recallAll, /ablations/0/fprMediumPlus -->

## Degraded operation and advisory components

If the model is missing, strict rules-only mode reports `neverLooser=false`. Residual risk-tier permissiveness is `0.00352` for B and `0.00376` for C; action-tier permissiveness is `0.0010733333333333333` for B and `0.0010066666666666666` for C. These residuals are reported rather than tuned away. <!-- metrics.json: /degraded/0/neverLooser, /degraded/0/permissivePct, /degraded/0/permissiveActionPct, /degraded/2/neverLooser, /degraded/2/permissivePct, /degraded/2/permissiveActionPct -->

For seed B, `9983` of `148500` legitimate payments were held. Guarantee rules account for `8035` holds, other rules for `1287`, and the model alone for `661`. <!-- metrics.json: /legitimateHoldBreakdown/heldCount, /legitimateHoldBreakdown/legitimateCount, /legitimateHoldBreakdown/byCause/guarantee/count, /legitimateHoldBreakdown/byCause/otherRules/count, /legitimateHoldBreakdown/byCause/modelOnly/count -->

Jev text screening and the Mistral case writer are advisory only. Invoice and email content is untrusted data; text screening may add cautionary evidence or withhold a document from Mistral, but neither component makes a payment decision or releases funds.

## Limitations, oversight, and transparency

The data are synthetic and use same-family seed generation. In particular, synthetic mule campaigns concentrate payer fan-in and are comparatively easy to detect. The cluster output uses coarse region centroids, not account locations. Reported FPR, recall, and STP depend on synthetic typology definitions and thresholds; they do not establish real-world effectiveness.

The project records scored events, fired rules, route/action outcomes, model version, and case references for review. Analysts must review holds and proposed cluster breakers; breaker activation and payment release remain under existing human-controlled workflows. The interface labels synthetic activity, and the README and benchmark report expose model modes, evaluation caveats, and degraded behavior.

The stated regulatory position is that the project is a fraud-detection system within the EU AI Act Annex III fraud-detection carve-out, rather than a creditworthiness assessment. <!-- metrics.json: /compliance/euAiActFraudDetectionCarveOut --> This is a project position, not legal advice or a determination of regulatory status; competent counsel should review the actual deployment and use.
