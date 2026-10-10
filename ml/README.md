# `/ml` — Lane B: risk and data

**Owner:** Lane B. In v0 this package is a skeleton: `ModelRisk()` raises `NotImplementedError` and the conformance test is skipped.

## Interface to implement

`sylo_risk.ModelRisk` implements `sylo_spec.ports.RiskPort`:

```python
class ModelRisk:
    name: str  # e.g. "model-v1"
    def score(self, order: PaymentOrder, ctx: RiskContext) -> RiskResult: ...
```

- The engine combines it with its own rules (`RISK_MODE=model`): `floorTier` and `rulesFired` come from the rules, `score` and extra reasons from the model, and the final tier is `max(floorTier, band(score))`. **The model can only make a decision stricter.**
- If importing or constructing `ModelRisk` fails, the engine falls back to rules only and shows "risk" as degraded in the banner.
- Golden cases: `sylo_spec.scenarios.golden_case("legit")` must come out LOW, `golden_case("diverted")` at least MEDIUM with at least three reasons.
- Synthetic data only. Datasets go in `ml/data/` and model binaries in `ml/models/*.bin` (both git-ignored).

## Run

```bash
cd ml
uv sync
uv run pytest            # runs sylo_spec.conformance.run_risk_conformance(ModelRisk())
```

## Tasks

See [`docs/roadmap-and-lanes.md`](../docs/roadmap-and-lanes.md), Lane B (B1.x for v1).
