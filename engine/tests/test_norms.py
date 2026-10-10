from dataclasses import replace

from sylo_spec.models import Documents
from sylo_spec.scenarios import DIVERTED_ORDER, LEGIT_ORDER

from sylo import texts
from sylo.norms import NormsEngine, load_pack

ENGINE = NormsEngine()


def test_r4_is_excluded_for_both_orders_by_the_export_proceeds_rule():
    for order in (LEGIT_ORDER, DIVERTED_ORDER):
        r4 = ENGINE.evaluate(order).route("R4")
        assert r4.status == "EXCLUDED"
        assert r4.excluded_by == "GH_FX_EXPORT_PROCEEDS_NOMINATED_BANK"
        assert r4.reason == texts.EXCLUSION_REASONS["GH_FX_EXPORT_PROCEEDS_NOMINATED_BANK"]
        assert "Act 723" in r4.legal_ref
        assert {"ruleId": "GH_WALLET_DAILY_CAP", "result": "FAIL"} in r4.checks


def test_other_routes_pass():
    result = ENGINE.evaluate(LEGIT_ORDER)
    assert [r.route.id for r in result.routes if r.status == "PASS"] == ["R1", "R2", "R3"]


def test_signal_r1_only_for_the_diverted_order():
    assert ENGINE.evaluate(LEGIT_ORDER).signals == []
    signals = ENGINE.evaluate(DIVERTED_ORDER).signals
    assert [s["code"] for s in signals] == ["R1"]
    assert signals[0]["text"] == "The requested account is not Savanna Shea's nominated export account."


def test_tax_notices_are_present():
    references = [n["reference"] for n in ENGINE.evaluate(LEGIT_ORDER).tax_notices]
    assert references == ["FR-GH-DTC-1993", "DAC8"]


def test_route_hops_follow_the_creditor_account():
    legit_r3 = ENGINE.evaluate(LEGIT_ORDER).route("R3").hops
    assert [h["to"] for h in legit_r3] == ["bank_fr", "casp_eu", "vasp_gh", "bank_gh", "supplier_ssx"]
    assert [h["kind"] for h in legit_r3] == ["bank", "bank", "chain", "bank", "bank"]
    diverted_r3 = ENGINE.evaluate(DIVERTED_ORDER).route("R3").hops
    assert [h["to"] for h in diverted_r3] == ["bank_fr", "casp_eu", "vasp_gh", "mule_bank"]


def test_missing_loc_reference_needs_a_document_and_excludes_bank_routes():
    order = LEGIT_ORDER.model_copy(update={"documents": Documents(invoice_ref="SSE-2026-118", loc_ref=None)})
    result = ENGINE.evaluate(order)
    assert all(r.status == "EXCLUDED" for r in result.routes)
    assert {"ruleId": "GH_FX_EXPORT_PROCEEDS_NOMINATED_BANK", "result": "NEEDS_DOCUMENT"} in result.route("R1").checks


def test_an_unknown_check_fails_safe():
    pack = load_pack()
    broken = replace(pack, rules=tuple(replace(r, check="not_a_real_check") if r.id == "EU_TRAVEL_RULE" else r for r in pack.rules))
    r3 = NormsEngine(broken).evaluate(LEGIT_ORDER).route("R3")
    assert r3.status == "EXCLUDED" and r3.excluded_by == "EU_TRAVEL_RULE"


def test_event_data_shape():
    data = ENGINE.evaluate(DIVERTED_ORDER).to_event_data()
    assert data["packVersion"] == "FR-GH@2026-10-10"
    assert {r["routeId"] for r in data["routes"]} == {"R1", "R2", "R3", "R4"}
