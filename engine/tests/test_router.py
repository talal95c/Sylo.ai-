import inspect

from sylo import norms, router
from sylo_spec import scenarios as sc
from sylo_spec.models import Tier


def _norms(name):
    order = sc.order(name)
    return norms.evaluate(order, sc.account(order.creditor.account_id), sc.payee(order.creditor.payee_id), sc.SUPPLIER_INSTITUTION_ID)


def _scores(decision):
    return {s["routeId"]: (s["s"], s["excludedBy"]) for s in decision.scores}


def test_low_picks_r3_with_the_expected_scores():
    decision = router.select_route(_norms("legit"), Tier.LOW, 85_000.0, norms.load_pack())
    assert decision.selected.route.id == "R3"
    assert _scores(decision) == {
        "R1": (216.00, None),
        "R2": (941.73, None),
        "R3": (179.21, None),
        "R4": (None, "GH_FX_EXPORT_PROCEEDS_NOMINATED_BANK"),
    }
    assert (decision.cost_eur, decision.swift_cost_eur, decision.price_of_safety_eur) == (179.21, 216.00, 0.0)
    assert decision.reason == (
        "R3 is the cheapest compliant route: €179 all-in against €216 via SWIFT. "
        "R4 is excluded by Ghana's export-proceeds rule."
    )
    event = decision.to_event(85_000.0)
    assert (event["feesEur"], event["etaLabel"], event["settlement"]) == (170.0, "≈ 2 h", "ONCHAIN_ESCROW")


def test_medium_only_allows_routes_that_can_hold_the_money():
    decision = router.select_route(_norms("diverted"), Tier.MEDIUM, 85_000.0, norms.load_pack())
    assert decision.selected.route.id == "R3"
    assert _scores(decision)["R2"] == (941.73, "TIER_MEDIUM_REQUIRES_CONDITIONAL_SETTLEMENT")
    assert _scores(decision)["R1"] == (216.00, None)
    assert decision.price_of_safety_eur == 0.0
    assert decision.reason == (
        "Risk is MEDIUM, so only routes that can hold the money are allowed (R1 bank hold, R3 escrow). "
        "R3 is the cheapest: €179 against €216. Price of safety: €0."
    )


def test_high_and_critical_have_no_route():
    for tier in (Tier.HIGH, Tier.CRITICAL):
        decision = router.select_route(_norms("diverted"), tier, 85_000.0, norms.load_pack())
        assert decision.selected is None
        assert all(s["excludedBy"] for s in decision.scores)


def test_fraud_risk_is_never_an_input_of_the_route_score():
    # The score function takes the route, the amount, the weights and the operational route risk. Nothing else.
    assert list(inspect.signature(router.route_score).parameters) == ["evaluation", "amount_eur", "weights", "route_risk"]
    pack = norms.load_pack()
    legit, diverted = _norms("legit"), _norms("diverted")
    for route_id in ("R1", "R2", "R3"):
        low = router.route_score(legit.route(route_id), 85_000.0, pack.weights)
        medium = router.route_score(diverted.route(route_id), 85_000.0, pack.weights)
        assert low == medium  # same rail, same amount: the same score whatever the fraud tier
    # A higher tier can remove routes; it never changes the score of the ones that remain.
    low = router.select_route(legit, Tier.LOW, 85_000.0, pack)
    medium = router.select_route(legit, Tier.MEDIUM, 85_000.0, pack)
    assert {s["routeId"]: s["s"] for s in low.scores} == {s["routeId"]: s["s"] for s in medium.scores}
