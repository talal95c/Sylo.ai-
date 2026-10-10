# /ml — Lane B (risk and data)

**Owner:** Lane B. **Package:** `sylo-risk` (`sylo_risk`). **Status in v0:** skeleton.

## What to implement (v1)

`sylo_risk.ModelRisk` implements `sylo_spec.ports.RiskPort`:

```python
class RiskPort(Protocol):
    name: str
    def score(self, order: PaymentOrder, ctx: RiskContext) -> RiskResult: ...
```

- Calibrated score 0–100, band tier (0–39 LOW, 40–69 MEDIUM, 70–89 HIGH, 90–100 CRITICAL), `floor_tier = LOW`,
  top three reasons in plain English, `model = "gbm-<date>"`.
- The engine keeps its rules: final tier = max(rule floor, model band). A model can only make a decision stricter.
- Golden cases: `sylo_spec.scenarios.golden_case("legit")` must score below 40, `golden_case("diverted")` between 40 and 69.

## How to check

```bash
cd ml && uv sync && uv run pytest        # test_conformance.py is skipped while ModelRisk raises NotImplementedError
RISK_MODE=model make engine              # the engine falls back to rules and shows "degraded: risk" if the import fails
```

## Tasks

See [`docs/roadmap-and-lanes.md`](../docs/roadmap-and-lanes.md): B1.0 (metrics schema), B1.1 (simulator),
B1.2 (features), B1.3 (model, calibration, thresholds), B1.4 (`ModelRisk`), B1.5 (first evaluation), then v2.

Generated data goes to `ml/data/` (git-ignored); commit a model artifact only if it is under 5 MB.
