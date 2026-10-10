from sylo_spec.models import Tier
from sylo_spec.scenarios import golden_case

from sylo_risk import ModelRisk


def test_golden_scenarios_have_expected_risk_ordering():
    risk = ModelRisk()
    legit_order, legit_ctx = golden_case("legit")
    diverted_order, diverted_ctx = golden_case("diverted")

    legit = risk.score(legit_order, legit_ctx)
    diverted = risk.score(diverted_order, diverted_ctx)

    assert legit.score < 40
    assert legit.tier == Tier.LOW
    assert diverted.score >= 40
    assert len(diverted.reasons) >= 3


def test_identical_input_has_identical_result():
    risk = ModelRisk()
    order, context = golden_case("diverted")

    assert risk.score(order, context) == risk.score(order, context)
