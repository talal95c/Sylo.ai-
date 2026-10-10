"""`ModelRisk`: the model-based implementation of `sylo_spec.ports.RiskPort` (Lane B, v1)."""

from sylo_spec.models import PaymentOrder, RiskContext, RiskResult


class ModelRisk:
    """Calibrated gradient-boosted model. Until Lane B implements it, the engine uses its rules.

    Contract (see `sylo_spec.ports.RiskPort` and `sylo_spec.conformance.run_risk_conformance`):
    - `name`: the model version, e.g. "gbm-2026-10-11".
    - `score(order, ctx)` returns a `RiskResult` with a calibrated score 0–100, the band tier,
      `floor_tier = LOW` (rule floors come from the engine) and the top reasons in plain English.
    - A model can only make a decision stricter: the engine takes max(rule floor, model band).
    """

    name = "model-v1"

    def __init__(self) -> None:
        raise NotImplementedError("Lane B implements ModelRisk in v1 (docs/roadmap-and-lanes.md, B1.4)")

    def score(self, order: PaymentOrder, ctx: RiskContext) -> RiskResult:  # pragma: no cover - stub
        raise NotImplementedError
