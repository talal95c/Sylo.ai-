import inspect

from sylo_spec.models import Tier
from sylo_spec.scenarios import DIVERTED_ORDER, LEGIT_ORDER

from sylo.norms import NormsEngine
from sylo.router import choose_route, route_cost, route_cost_breakdown

ENGINE = NormsEngine()
MODEL = ENGINE.pack.route_model
AMOUNT = 85_000.0


def _decision(order, tier, oob_resolvable=False):
    return choose_route(ENGINE.evaluate(order), tier, AMOUNT, MODEL, oob_resolvable)


def test_route_scores_to_two_decimals():
    pack = ENGINE.pack
    assert round(route_cost(pack.route("R1"), AMOUNT, MODEL), 2) == 1834.40
    assert round(route_cost(pack.route("R3"), AMOUNT, MODEL), 2) == 855.81
    assert round(route_cost(pack.route("R2"), AMOUNT, MODEL), 2) == 2640.03


def test_cost_breakdown_sums_to_route_score_and_includes_excluded_route_costs():
    r1 = route_cost_breakdown(ENGINE.pack.route("R1"), AMOUNT, MODEL)
    assert r1["fxMarginEur"] == 1700.0
    assert r1["cashCostEur"] + r1["timeCostEur"] + r1["failureCostEur"] == r1["totalCostEur"]
    assert r1["totalCostEur"] == round(route_cost(ENGINE.pack.route("R1"), AMOUNT, MODEL), 2)

    decision = _decision(LEGIT_ORDER, Tier.LOW)
    r4 = next(score for score in decision.scores if score["routeId"] == "R4")
    assert r4["s"] is None and r4["excludedBy"] == "GH_FX_EXPORT_PROCEEDS_NOMINATED_BANK"
    assert r4["name"] == "Mobile wallet remittance"
    assert r4["etaLabel"] == "minutes" and r4["etaMinutes"] == 10.0
    assert r4["feesEur"] == 1275.0 and r4["fxMarginEur"] == 1700.0 and r4["cashCostEur"] == 2975.0
    assert r4["recipientGetsGhs"] == 1374450.0


def test_low_picks_r3_directly():
    decision = _decision(LEGIT_ORDER, Tier.LOW)
    assert decision.route.id == "R3" and decision.settlement == "DIRECT"
    assert [(score["routeId"], score["s"], score["excludedBy"]) for score in decision.scores] == [
        ("R1", 1834.4, None),
        ("R2", 2640.03, None),
        ("R3", 855.81, None),
        ("R4", None, "GH_FX_EXPORT_PROCEEDS_NOMINATED_BANK"),
    ]
    assert all(
        {"name", "etaLabel", "etaMinutes", "feesEur", "fxMarginEur", "cashCostEur", "recipientGetsGhs"}
        <= score.keys()
        for score in decision.scores
    )
    data = decision.to_event_data()
    assert data["cost"] == {
        "feesEur": 170.0,
        "fxMarginEur": 680.0,
        "timeCostEur": 1.56,
        "failureCostEur": 4.25,
        "cashCostEur": 850.0,
        "totalCostEur": 855.81,
    }
    assert data["etaMinutes"] == 120.0 and data["midRateEurGhs"] == 16.5
    assert data["recipientGetsGhs"] == 1391280.0
    assert decision.price_of_safety == 0.0 and decision.fees_eur == 170.0
    assert decision.reason == (
        "R3 is the cheapest compliant route: €856 all-in (fees, FX margin and delay) against €1,834 via SWIFT. "
        "R4 is excluded by Ghana's export-proceeds rule."
    )


def test_medium_allows_only_holding_routes():
    decision = _decision(DIVERTED_ORDER, Tier.MEDIUM)
    assert decision.route.id == "R3" and decision.settlement == "ONCHAIN_ESCROW"
    r2 = next(s for s in decision.scores if s["routeId"] == "R2")
    assert r2["excludedBy"] == "TIER_MEDIUM_REQUIRES_CONDITIONAL_SETTLEMENT"
    assert decision.reason == (
        "Risk is MEDIUM, so only routes that can hold the money are allowed (R1 bank hold, R3 escrow). "
        "R3 is the cheapest: €856 against €1,834. Price of safety: €0."
    )


def test_high_and_critical_get_no_route():
    for tier in (Tier.HIGH, Tier.CRITICAL):
        assert _decision(DIVERTED_ORDER, tier).route is None


def test_high_oob_resolvable_uses_conditional_routes():
    decision = _decision(DIVERTED_ORDER, Tier.HIGH, oob_resolvable=True)
    assert decision.tier == Tier.MEDIUM
    assert decision.route.id == "R3" and decision.settlement == "ONCHAIN_ESCROW"


def test_high_without_oob_and_critical_with_oob_have_no_route():
    assert _decision(DIVERTED_ORDER, Tier.HIGH, oob_resolvable=False).route is None
    assert _decision(DIVERTED_ORDER, Tier.CRITICAL, oob_resolvable=True).route is None


def test_fraud_risk_is_not_an_input_of_the_route_score():
    assert "tier" not in inspect.signature(route_cost).parameters
    low = {s["routeId"]: s["s"] for s in _decision(LEGIT_ORDER, Tier.LOW).scores}
    medium = {s["routeId"]: s["s"] for s in _decision(LEGIT_ORDER, Tier.MEDIUM).scores}
    assert low == medium
