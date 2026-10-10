from sylo.risk_rules import RulesRisk, band
from sylo_spec.models import Tier
from sylo_spec.scenarios import golden_case


def test_legit_is_low_with_two_positive_reasons():
    result = RulesRisk().score(*golden_case("legit"))
    assert (result.score, result.tier, result.floor_tier, result.rules_fired) == (10, Tier.LOW, Tier.LOW, [])
    assert [(r.ref, r.text) for r in result.reasons] == [
        ("B", "Known supplier: 14 successful payments to this nominated account since 2024."),
        ("V", "Bank details come from the verified supplier registry."),
    ]


def test_diverted_is_medium_64_with_four_rules_sorted_by_weight():
    result = RulesRisk().score(*golden_case("diverted"))
    assert (result.score, result.tier, result.floor_tier) == (64, Tier.MEDIUM, Tier.MEDIUM)
    assert result.rules_fired == ["R-PV-01", "R-FL-01", "R-FL-03", "R-NM-01"]
    assert [r.ref for r in result.reasons] == ["V", "B", "B", "R"]
    assert [r.text for r in result.reasons] == [
        "The new bank details came from an emailed invoice, not from Savanna Shea's verified records.",
        "This is the first payment ever to this account, and it is for EUR 85,000.",
        "The account holder 'K. MENSAH VENTURES' does not match the supplier 'Savanna Shea Exports Ltd' (name match 0.38).",
        "Ghanaian rules require export payments to reach the exporter's nominated bank. This account is not it.",
    ]
    assert result.model == "rules-v0"


def test_bands_and_extra_rules():
    assert [band(s) for s in (0, 39, 40, 69, 70, 89, 90, 100)] == [
        Tier.LOW, Tier.LOW, Tier.MEDIUM, Tier.MEDIUM, Tier.HIGH, Tier.HIGH, Tier.CRITICAL, Tier.CRITICAL,
    ]
    order, ctx = golden_case("diverted")
    young = ctx.model_copy(update={"account_age_hours": 20.0})
    result = RulesRisk().score(order, young)
    assert "R-FL-02" in result.rules_fired and result.score == 74 and result.tier == Tier.HIGH
    sanctioned = ctx.model_copy(update={"norm_signals": ["SANCTIONS"]})
    blocked = RulesRisk().score(order, sanctioned)
    assert (blocked.score, blocked.tier, blocked.rules_fired) == (95, Tier.CRITICAL, ["R-HB-01"])


def test_a_rule_floor_holds_even_when_the_score_is_low():
    # Untrusted provenance alone: score 30 (LOW band) but the floor keeps the tier at MEDIUM.
    order, ctx = golden_case("legit")
    emailed = order.model_copy(update={"provenance": "invoice_pdf_email"})
    result = RulesRisk().score(emailed, ctx)
    assert result.rules_fired == ["R-PV-01"] and result.score == 30
    assert result.floor_tier == Tier.MEDIUM and result.tier == Tier.MEDIUM
