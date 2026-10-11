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
    assert data["packVersion"] == "FR-GH@2026-10-11"
    assert {r["routeId"] for r in data["routes"]} == {"R1", "R2", "R3", "R4"}


def _with_listed(*countries):
    pack = load_pack()
    rules = tuple(replace(r, params={"listed": list(countries)}) if r.id == "EU_HIGH_RISK_EDD" else r for r in pack.rules)
    return NormsEngine(replace(pack, rules=rules))


def test_the_high_risk_rule_passes_on_the_demo_corridor_and_is_checked_on_every_route():
    result = ENGINE.evaluate(DIVERTED_ORDER)
    for route in result.routes:
        assert {"ruleId": "EU_HIGH_RISK_EDD", "result": "PASS"} in route.checks
    assert "R4" not in result.signal_codes


def test_a_route_through_a_listed_country_needs_a_due_diligence_file():
    result = _with_listed("GB").evaluate(LEGIT_ORDER)
    r1 = result.route("R1")  # the only route with a London correspondent
    assert r1.status == "EXCLUDED" and r1.excluded_by == "EU_HIGH_RISK_EDD"
    assert {"ruleId": "EU_HIGH_RISK_EDD", "result": "NEEDS_DOCUMENT"} in r1.checks and "2016/1675" in r1.legal_ref
    assert r1.reason == texts.EXCLUSION_REASONS["EU_HIGH_RISK_EDD"]
    assert [r.route.id for r in result.routes if r.status == "PASS"] == ["R2", "R3"]


def test_signal_r4_when_the_account_is_in_a_listed_country_and_the_payee_is_elsewhere():
    engine = _with_listed("GH")
    assert "R4" not in engine.evaluate(DIVERTED_ORDER).signal_codes  # the payee is in Ghana too
    elsewhere = DIVERTED_ORDER.model_copy(update={"creditor": DIVERTED_ORDER.creditor.model_copy(update={"country": "CI"})})
    signal = next(s for s in engine.evaluate(elsewhere).signals if s["code"] == "R4")
    assert signal["ruleId"] == "EU_HIGH_RISK_EDD" and "held in GH" in signal["text"]


def test_an_institution_missing_from_the_registry_fails_the_high_risk_check(monkeypatch):
    from sylo import norms

    known = dict(norms.institution_countries())
    known.pop("corr_uk")
    monkeypatch.setattr(norms, "institution_countries", lambda: known)
    r1 = ENGINE.evaluate(LEGIT_ORDER).route("R1")
    assert r1.status == "EXCLUDED" and {"ruleId": "EU_HIGH_RISK_EDD", "result": "FAIL"} in r1.checks


def test_the_payee_name_check_scope_asks_for_the_out_of_band_check_and_excludes_nothing():
    result = ENGINE.evaluate(LEGIT_ORDER)
    assert [c["ruleId"] for c in result.controls] == ["EU_VOP_SCOPE"]
    assert "out-of-band check" in result.controls[0]["text"] and "2024/886" in result.controls[0]["legalRef"]
    assert result.to_event_data()["controls"] == result.controls
    assert all({"ruleId": "EU_VOP_SCOPE", "result": "PASS"} in r.checks for r in result.routes)
    assert [r.route.id for r in result.routes if r.status == "PASS"] == ["R1", "R2", "R3"]
