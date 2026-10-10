from sylo.ports_loader import CombinedRisk
from sylo.risk_rules import RulesRisk
from sylo_spec.conformance import run_risk_conformance
from sylo_spec.models import RiskReason, RiskResult, Tier
from sylo_spec.ports import RiskPort
from sylo_spec.scenarios import golden_case


def test_rules_risk_passes_the_risk_conformance_suite():
    assert isinstance(RulesRisk(), RiskPort)
    run_risk_conformance(RulesRisk())


class _FakeModel:
    name = "fake-model"

    def __init__(self, score):
        self._score = score

    def score(self, order, ctx):
        return RiskResult(score=self._score, tier=Tier.LOW, floor_tier=Tier.LOW, reasons=[RiskReason(ref="N", text="model reason")], model=self.name)


def test_a_model_can_only_make_the_decision_stricter():
    order, ctx = golden_case("diverted")
    # The model says "safe" (score 5): the rule floor keeps the payment at MEDIUM.
    lenient = CombinedRisk(RulesRisk(), _FakeModel(5)).score(order, ctx)
    assert lenient.tier == Tier.MEDIUM and lenient.floor_tier == Tier.MEDIUM and lenient.model == "fake-model"
    assert "R-PV-01" in lenient.rules_fired and lenient.reasons[-1].text == "model reason"
    # The model says "very risky" (score 93): the tier goes up to CRITICAL.
    strict = CombinedRisk(RulesRisk(), _FakeModel(93)).score(order, ctx)
    assert strict.tier == Tier.CRITICAL
