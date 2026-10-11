from __future__ import annotations

import importlib
import sys
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st
from sylo_spec.models import Money, PairHistory, PayerSession, Tier
from sylo_spec.scenarios import golden_case

from sylo_risk.fallback_risk import FALLBACK_REASON, FallbackRisk

ENGINE_DIR = Path(__file__).resolve().parents[2] / "engine"
sys.path.insert(0, str(ENGINE_DIR))

from sylo.risk_rules import CombinedRisk, RulesRisk  # noqa: E402


def test_fallback_risk_loads_when_lightgbm_import_is_blocked(monkeypatch):
    monkeypatch.setitem(sys.modules, "lightgbm", None)

    importlib.reload(importlib.import_module("sylo_risk.model_risk"))
    importlib.reload(importlib.import_module("sylo_risk.fallback_risk"))
    package = importlib.reload(importlib.import_module("sylo_risk"))
    risk = package.FallbackRisk()
    order, context = golden_case("legit")

    assert risk.score(order, context).score in range(101)


def test_fallback_risk_is_floored_by_strict_rules():
    risk = CombinedRisk(RulesRisk(strict=True), FallbackRisk())
    order, context = golden_case("legit")
    context = context.model_copy(
        update={
            "payer_session": context.payer_session.model_copy(
                update={"sim_swap_72h": True}
            )
        }
    )

    strict_floor = RulesRisk(strict=True).score(order, context).floor_tier
    result = risk.score(order, context)

    assert result.tier >= strict_floor
    assert FALLBACK_REASON in {reason.text for reason in result.reasons}


@settings(max_examples=75, deadline=None)
@given(
    amount=st.floats(min_value=0.01, max_value=1_000_000, allow_nan=False, allow_infinity=False),
    account_age=st.floats(min_value=0, max_value=100_000, allow_nan=False, allow_infinity=False),
    name_match=st.floats(min_value=0, max_value=1, allow_nan=False, allow_infinity=False),
    successful_count=st.integers(min_value=0, max_value=10_000),
    median=st.one_of(
        st.none(),
        st.floats(min_value=0.01, max_value=1_000_000, allow_nan=False, allow_infinity=False),
    ),
    payments_24h=st.integers(min_value=0, max_value=100),
    sim_swap=st.booleans(),
    new_device=st.booleans(),
    session_country=st.sampled_from(["FR", "GH", "GB", "DE"]),
    provenance=st.sampled_from(
        ["verified_registry", "payment_history", "invoice_pdf_email", "user_input"]
    ),
    purpose=st.sampled_from(["GOODS", "DECLARED_SPLIT"]),
)
def test_fallback_tier_never_below_strict_floor_and_score_is_bounded(
    amount,
    account_age,
    name_match,
    successful_count,
    median,
    payments_24h,
    sim_swap,
    new_device,
    session_country,
    provenance,
    purpose,
):
    order, context = golden_case("legit")
    order = order.model_copy(
        update={
            "amount": Money(value=f"{amount:.8f}", currency="EUR"),
            "purpose": purpose,
            "provenance": {"creditorAccount": provenance},
        }
    )
    context = context.model_copy(
        update={
            "amount_eur": amount,
            "account_age_hours": account_age,
            "name_match": name_match,
            "history": PairHistory(
                successful_count=successful_count,
                median_amount_eur=median,
                payments_24h=payments_24h,
                last_account_id=context.account.id if context.account else None,
            ),
            "payer_session": PayerSession(
                sim_swap_72h=sim_swap,
                new_device_24h=new_device,
                country=session_country,
            ),
        }
    )
    strict = RulesRisk(strict=True).score(order, context)
    fallback = CombinedRisk(RulesRisk(strict=True), FallbackRisk()).score(order, context)

    assert fallback.tier >= strict.floor_tier
    assert 0 <= fallback.score <= 100
    assert FALLBACK_REASON in {reason.text for reason in fallback.reasons}
