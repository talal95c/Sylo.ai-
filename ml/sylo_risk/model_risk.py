"""ModelRisk: calibrated fraud model behind RiskPort (Lane B builds it in v1)."""

from __future__ import annotations

from sylo_spec.models import PaymentOrder, RiskContext, RiskResult


class ModelRisk:
    name = "model-v1"

    def __init__(self) -> None:
        raise NotImplementedError("Lane B implements ModelRisk in v1 (docs/roadmap-and-lanes.md, B1.4)")

    def score(self, order: PaymentOrder, ctx: RiskContext) -> RiskResult:
        raise NotImplementedError
