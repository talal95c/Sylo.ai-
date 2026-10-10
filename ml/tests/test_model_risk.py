from sylo_spec.models import Tier
from sylo_spec.scenarios import golden_case

from sylo_risk import ModelRisk
from sylo_risk.features import raw_from_order
from sylo_risk.model_risk import _oob_resolvable


def test_golden_scenarios_have_expected_risk_ordering():
    risk = ModelRisk()
    legit_order, legit_ctx = golden_case("legit")
    diverted_order, diverted_ctx = golden_case("diverted")

    legit = risk.score(legit_order, legit_ctx)
    diverted = risk.score(diverted_order, diverted_ctx)

    assert legit.score < 40
    assert legit.tier == Tier.LOW
    assert legit.reasons == []
    assert diverted.score >= 40
    assert len(diverted.reasons) >= 3
    assert diverted.oob_resolvable is True


def test_identical_input_has_identical_result():
    risk = ModelRisk()
    order, context = golden_case("diverted")

    assert risk.score(order, context) == risk.score(order, context)


def test_oob_resolvability_excludes_payer_session_signal_and_critical_scores():
    order, context = golden_case("diverted")
    raw = raw_from_order(order, context)

    assert _oob_resolvable(raw, 89)
    assert not _oob_resolvable(raw, 90)
    assert not _oob_resolvable({**raw, "pair_payments_24h": 1.0}, 89)
    assert not _oob_resolvable({**raw, "amount_vs_history": 3.1}, 89)
    assert not _oob_resolvable({**raw, "under_cap": 1.0}, 89)
    assert not _oob_resolvable(raw, 89, sanctions_hit=True)
    assert not risk_result_with_session_signal(order, context)


def risk_result_with_session_signal(order, context):
    risk = ModelRisk()
    session = context.payer_session.model_copy(update={"sim_swap_72h": True})
    return risk.score(
        order, context.model_copy(update={"payer_session": session})
    ).oob_resolvable
