from sylo_spec.models import RiskContext, Status, Tier, band
from sylo_spec.scenarios import DIVERTED_ORDER, LEGIT_ORDER, golden_case, name_match, normalize_name


def test_enum_numbers_match_the_spec():
    assert [t.value for t in Tier] == [0, 1, 2, 3]
    assert Status.NONE == 0 and Status.REVOKED == 4 and Status.EXECUTED == 5


def test_bands():
    assert band(10) == Tier.LOW and band(39) == Tier.LOW
    assert band(40) == Tier.MEDIUM and band(64) == Tier.MEDIUM
    assert band(70) == Tier.HIGH and band(90) == Tier.CRITICAL


def test_name_normalisation_drops_punctuation_and_legal_suffixes():
    assert normalize_name("Savanna Shea Exports Ltd") == "SAVANNA SHEA EXPORTS"
    assert normalize_name("K. MENSAH VENTURES") == "K MENSAH VENTURES"
    assert name_match("SAVANNA SHEA EXPORTS LTD", "Savanna Shea Exports Ltd") == 1.0
    assert name_match("K. MENSAH VENTURES", "Savanna Shea Exports Ltd") < 0.85


def test_golden_cases():
    legit_order, legit_ctx = golden_case("legit")
    diverted_order, diverted_ctx = golden_case("diverted")
    assert legit_order is LEGIT_ORDER and diverted_order is DIVERTED_ORDER
    assert legit_ctx.account.successful_payments == 14 and legit_ctx.norm_signals == []
    assert diverted_ctx.account.successful_payments == 0 and diverted_ctx.norm_signals == ["R1"]
    assert diverted_ctx.account_age_hours == 225.0
    assert diverted_ctx.amount_eur == 85000.0


def test_camel_case_aliases_round_trip():
    _, ctx = golden_case("diverted")
    payload = ctx.to_json_dict()
    assert "normSignals" in payload and "simSwap72h" in payload["payerSession"]
    assert RiskContext.model_validate(payload) == ctx
