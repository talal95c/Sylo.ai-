# `/ml` — Lane B: risk and data

**Owner:** Lane B. This package provides the seeded simulator, shared feature pipeline, calibrated LightGBM model, and `ModelRisk`.

## Interface

`sylo_risk.ModelRisk` implements `sylo_spec.ports.RiskPort`:

```python
class ModelRisk:
    name: str  # e.g. "gbm-20261011"
    def score(self, order: PaymentOrder, ctx: RiskContext) -> RiskResult: ...
```

- The engine combines it with its own rules (`RISK_MODE=model`): `floorTier` and `rulesFired` come from the rules, `score` and extra reasons from the model, and the final tier is `max(floorTier, band(score))`. **The model can only make a decision stricter.**
- If importing or constructing `ModelRisk` fails, the engine falls back to rules only and shows "risk" as degraded in the banner.
- Golden cases: `sylo_spec.scenarios.golden_case("legit")` must come out LOW, `golden_case("diverted")` at least MEDIUM with at least three reasons.
- Synthetic data only. Datasets and integrity cases go in `ml/data/`; the compact trained model and metadata are committed under `ml/models/`.

## Run

```bash
cd ml
uv sync
uv run python -m sylo_risk.sim --seed A --out data/
uv run python -m sylo_risk.sim --seed B --small --out data/
uv run python -m sylo_risk.train --data data/payments-A.csv.gz
uv run pytest
```

The simulator writes compressed CSV plus 100 integrity examples per I1–I3. `--small` generates 20,000 rows. Training uses days 1–20, isotonic calibration and threshold selection use days 21–25. Seed-A payer/payee history is stored alongside the model; no payment IDs are special-cased.

## Tasks

See [`docs/roadmap-and-lanes.md`](../docs/roadmap-and-lanes.md), Lane B (B1.x for v1).
