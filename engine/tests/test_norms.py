from sylo import norms, texts
from sylo_spec import scenarios as sc


def _evaluate(name):
    order = sc.order(name)
    return norms.evaluate(order, sc.account(order.creditor.account_id), sc.payee(order.creditor.payee_id), sc.SUPPLIER_INSTITUTION_ID)


def test_r4_is_excluded_for_both_orders_with_the_rule_and_its_legal_reference():
    for name in sc.SCENARIOS:
        result = _evaluate(name)
        statuses = {e.route.id: e.status for e in result.routes}
        assert statuses == {"R1": "PASS", "R2": "PASS", "R3": "PASS", "R4": "EXCLUDED"}
        r4 = result.route("R4")
        assert r4.excluded_by == "GH_FX_EXPORT_PROCEEDS_NOMINATED_BANK"  # the first failing rule
        assert r4.reason == texts.EXCLUDED_WALLET_EXPORT_PROCEEDS
        assert "Act 723" in r4.legal_ref
        failed = {c["ruleId"] for c in r4.checks if c["result"] != "PASS"}
        assert failed == {"GH_FX_EXPORT_PROCEEDS_NOMINATED_BANK", "GH_WALLET_DAILY_CAP"}


def test_signal_r1_only_for_the_diverted_order_and_it_excludes_nothing():
    assert _evaluate("legit").signal_codes == []
    diverted = _evaluate("diverted")
    assert diverted.signal_codes == ["R1"]
    assert diverted.signals[0]["text"] == "The requested account is not Savanna Shea's nominated export account."
    assert diverted.signals[0]["ruleId"] == "GH_FX_EXPORT_PROCEEDS_NOMINATED_BANK"
    assert [e.route.id for e in diverted.routes if e.passed] == ["R1", "R2", "R3"]


def test_tax_notices_are_information_only():
    for name in sc.SCENARIOS:
        result = _evaluate(name)
        assert [n["reference"] for n in result.tax_notices] == ["FR-GH-DTC-1993", "DAC8"]
        assert result.tax_notices[0]["text"] == texts.TAX_NO_WITHHOLDING


def test_hops_follow_the_pack_and_the_creditor_account():
    legit, diverted = _evaluate("legit"), _evaluate("diverted")
    path = lambda e: [e.hops[0].src] + [h.dst for h in e.hops]
    assert path(legit.route("R3")) == ["payer_rhone", "bank_fr", "casp_eu", "vasp_gh", "bank_gh", "supplier_ssx"]
    assert path(diverted.route("R3")) == ["payer_rhone", "bank_fr", "casp_eu", "vasp_gh", "mule_bank"]
    assert [h.kind for h in legit.route("R3").hops] == ["bank", "bank", "chain", "bank", "bank"]
    assert path(legit.route("R4")) == ["payer_rhone", "remit_fr", "momo_gh"]  # the money would end in a wallet
    assert path(diverted.route("R1")) == ["payer_rhone", "bank_fr", "corr_uk", "mule_bank"]


def test_a_missing_loc_reference_excludes_bank_routes_and_unknown_checks_fail():
    order = sc.order("legit").model_copy(update={"loc_ref": None})
    result = norms.evaluate(order, sc.account(order.creditor.account_id), sc.payee(order.creditor.payee_id))
    assert all(not e.passed for e in result.routes)
    assert result.route("R1").reason == texts.EXCLUDED_MISSING_LOC
    assert norms._run("no_such_check", None) == norms.FAIL
