import inspect

from sylo_spec.models import Tier
from sylo_spec.scenarios import DIVERTED_ORDER, LEGIT_ORDER

from sylo.norms import NormsEngine
from sylo.router import choose_route, route_cost

ENGINE = NormsEngine()
MODEL = ENGINE.pack.route_model
AMOUNT = 85_000.0


def _decision(order, tier, oob_resolvable=False):
    return choose_route(ENGINE.evaluate(order), tier, AMOUNT, MODEL, oob_resolvable)


def test_route_scores_to_two_decimals():
    pack = ENGINE.pack
    assert round(route_cost(pack.route("R1"), AMOUNT, MODEL), 2) == 216.00
    assert round(route_cost(pack.route("R3"), AMOUNT, MODEL), 2) == 179.21
    assert round(route_cost(pack.route("R2"), AMOUNT, MODEL), 2) == 941.73


def test_low_picks_r3_directly():
    decision = _decision(LEGIT_ORDER, Tier.LOW)
    assert decision.route.id == "R3" and decision.settlement == "DIRECT"
    assert decision.scores == [
        {"routeId": "R1", "s": 216.0, "excludedBy": None},
        {"routeId": "R2", "s": 941.73, "excludedBy": None},
        {"routeId": "R3", "s": 179.21, "excludedBy": None},
        {"routeId": "R4", "s": None, "excludedBy": "GH_FX_EXPORT_PROCEEDS_NOMINATED_BANK"},
    ]
    assert decision.price_of_safety == 0.0 and decision.fees_eur == 170.0
    assert decision.reason == (
        "R3 is the cheapest compliant route: €179 all-in against €216 via SWIFT. "
        "R4 is excluded by Ghana's export-proceeds rule."
    )


def test_medium_allows_only_holding_routes():
    decision = _decision(DIVERTED_ORDER, Tier.MEDIUM)
    assert decision.route.id == "R3" and decision.settlement == "ONCHAIN_ESCROW"
    r2 = next(s for s in decision.scores if s["routeId"] == "R2")
    assert r2["excludedBy"] == "TIER_MEDIUM_REQUIRES_CONDITIONAL_SETTLEMENT"
    assert decision.reason == (
        "Risk is MEDIUM, so only routes that can hold the money are allowed (R1 bank hold, R3 escrow). "
        "R3 is the cheapest: €179 against €216. Price of safety: €0."
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
