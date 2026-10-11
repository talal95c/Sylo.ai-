"""Pack 2, Lagos -> Accra (PRD Appendix A, P1-8): a second corridor is one pack file and one profile."""

from sylo_spec.models import Tier

from sylo.norms import NormsEngine, load_pack
from sylo.orchestrator import ActionNotAllowed, corridor_demo
from sylo.router import choose_route

import pytest

from .conftest import make_orchestrator

PACK = load_pack("NG-GH")
ENGINE, PAYER, ORDER = corridor_demo("lagos-accra")


def decide(tier=Tier.LOW):
    return choose_route(ENGINE.evaluate(ORDER), tier, ORDER.amount.as_float, PACK.route_model, symbol=PACK.symbol)


def test_the_pack_brings_its_own_rails_currency_authorities_and_demo_order():
    assert PACK.pack_version == "NG-GH@2026-10-11" and (PACK.currency, PACK.symbol) == ("USD", "$")
    assert [r.name for r in PACK.routes] == [
        "SWIFT correspondent (USD)",
        "PAPSS",
        "USD stablecoin through licensed partners",
        "Mobile money hub",
    ]
    assert PACK.authorities() == {
        "NG": {"country": "Nigeria", "supervisor": "Central Bank of Nigeria (CBN)", "fiu": "Nigerian Financial Intelligence Unit (NFIU)"},
        "GH": {"country": "Ghana", "supervisor": "Bank of Ghana", "fiu": "Financial Intelligence Centre (FIC)"},
    }
    assert {r.id for r in PACK.rules} == {
        "GH_FX_EXPORT_PROCEEDS_NOMINATED_BANK", "GH_WALLET_DAILY_CAP", "GH_VASP_LICENSED", "NG_VASP_REGISTERED", "NG_BVN_WATCHLIST",
    }
    assert PACK.countries()["bank_ng"] == "NG" and PACK.countries()["bank_gh"] == "GH"
    assert (ORDER.corridor, ORDER.amount.currency, PAYER.name) == ("NG-GH", "USD", "Lekki Foods Ltd")


def test_fees_follow_each_rail_fixed_part_percentage_and_caps():
    fees = {r.id: round(r.fees(25_000.0), 2) for r in PACK.routes}
    assert fees == {"R1": 1150.0, "R2": 50.0, "R3": 747.5, "R4": 1000.0}  # PAPSS: 3% capped at $50
    assert PACK.route("R2").fees(100.0) == 5.0  # ... and never under $5


def test_ghana_s_rules_are_reused_and_exclude_the_mobile_money_route():
    result = ENGINE.evaluate(ORDER)
    assert [r.route.id for r in result.routes if r.status == "PASS"] == ["R1", "R2", "R3"]
    wallet = result.route("R4")
    assert wallet.excluded_by == "GH_FX_EXPORT_PROCEEDS_NOMINATED_BANK"
    assert {"ruleId": "GH_WALLET_DAILY_CAP", "result": "FAIL"} in wallet.checks  # $25,000 is GHS 275,000
    stablecoin = result.route("R3")
    assert {c["ruleId"] for c in stablecoin.checks} >= {"GH_VASP_LICENSED", "NG_VASP_REGISTERED", "NG_BVN_WATCHLIST"}
    assert [h["to"] for h in stablecoin.hops] == ["bank_ng", "vasp_ng", "vasp_gh", "bank_gh", "supplier_ssx"]
    assert result.signals == [] and [n["reference"] for n in result.tax_notices] == ["NFIU-STR"]


def test_the_same_router_picks_papss_and_at_medium_only_the_routes_that_can_hold_the_money():
    low = decide()
    assert low.route.id == "R2" and low.settlement == "DIRECT"
    assert "$" in low.reason and "€" not in low.reason and "via SWIFT" in low.reason
    medium = decide(Tier.MEDIUM)
    assert medium.route.id == "R3" and medium.settlement == "ONCHAIN_ESCROW"
    assert {s["routeId"]: s["excludedBy"] for s in medium.scores}["R2"] == "TIER_MEDIUM_REQUIRES_CONDITIONAL_SETTLEMENT"
    assert medium.price_of_safety > 0  # here safety has a price: PAPSS cannot hold the money
    assert decide(Tier.HIGH).route is None


def test_a_name_on_the_watchlist_excludes_every_route():
    listed = ORDER.model_copy(update={"debtor": ORDER.debtor.model_copy(update={"name": "Harmattan Relay Ventures"})})
    result = ENGINE.evaluate(listed)
    assert all(r.status == "EXCLUDED" for r in result.routes)
    assert result.route("R2").excluded_by == "NG_BVN_WATCHLIST"


def test_the_engine_quotes_the_second_corridor_without_any_code_for_it():
    orchestrator = make_orchestrator()
    quote = orchestrator.quote("lagos-accra")
    assert quote["corridor"] == "NG-GH" and quote["currency"] == "USD" and quote["paymentId"] == "PAY-2026-0201"
    assert not quote["executable"] and quote["route"]["chosen"] == "R2" and quote["risk"]["tier"] == "LOW"
    assert set(quote["authorities"]) == {"NG", "GH"} and "NFIU" in quote["authorities"]["NG"]["fiu"]
    assert [a["id"] for a in quote["approval"]["required"]] == ["adaeze", "tunde"]
    assert [r["rail"] for r in quote["rails"]][1] == "PAPSS" and len(quote["routes"]) == 4
    with pytest.raises(ActionNotAllowed, match="pricing only"):
        orchestrator.submit(quote_id=quote["quoteId"])
    home = orchestrator.quote("legit")
    assert home["corridor"] == "FR-GH" and home["currency"] == "EUR" and set(home["authorities"]) == {"FR", "GH"}
    assert orchestrator.bus.events == []


def test_the_first_corridor_is_unchanged_by_the_generalisation():
    pack = load_pack()
    assert pack.fx_eur_ghs == 16.5 and (pack.currency, pack.symbol) == ("EUR", "€") and pack.demo is None
    assert {r.id: r.fees(85_000.0) for r in pack.routes} == {"R1": 80.0, "R2": 935.0, "R3": 170.0, "R4": 1275.0}
    assert all(r.token == "EURC" for r in pack.routes)
