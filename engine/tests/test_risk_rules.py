import sys
from types import ModuleType

from sylo_spec.models import PairHistory, RiskReason, RiskResult, Tier
from sylo_spec.scenarios import build_risk_context, golden_case

from sylo.config import Settings
from sylo.ports_loader import load_ports
from sylo.risk_rules import CombinedRisk, RulesRisk
from sylo.signer import Signer

RISK = RulesRisk()


def test_legit_is_low_10_with_two_positive_reasons():
    result = RISK.score(*golden_case("legit"))
    assert (result.score, result.tier, result.rules_fired) == (10, Tier.LOW, [])
    assert result.oob_resolvable
    assert [r.text for r in result.reasons] == [
        "Known supplier: 14 successful payments to this nominated account since 2024.",
        "Bank details come from the verified supplier registry.",
    ]
    assert [r.ref for r in result.reasons] == ["B", "V"]


def test_diverted_is_medium_64_with_four_rules_sorted_by_weight():
    result = RISK.score(*golden_case("diverted"))
    assert (result.score, result.tier, result.floor_tier) == (64, Tier.MEDIUM, Tier.MEDIUM)
    assert result.rules_fired == ["R-PV-01", "R-FL-01", "R-FL-03", "R-NM-01"]
    assert result.oob_resolvable
    assert [(r.ref, r.text) for r in result.reasons] == [
        ("V", "The new bank details came from an emailed invoice, not from Savanna Shea's verified records."),
        ("B", "This is the first payment ever to this account, and it is for EUR 85,000."),
        (
            "B",
            "The account holder 'K. MENSAH VENTURES' does not match the supplier 'Savanna Shea Exports Ltd' "
            "(name match 0.38).",
        ),
        ("R", "Ghanaian rules require export payments to reach the exporter's nominated bank. This account is not it."),
    ]


def test_established_owned_account_name_mismatch_does_not_fire_r_fl_03():
    order, ctx = golden_case("legit")
    assert ctx.account is not None and ctx.payee is not None
    assert ctx.account.successful_payments >= 1 and ctx.payee.owns(ctx.account.id)

    result = RISK.score(order, ctx.model_copy(update={"name_match": 0.80}))

    assert "R-FL-03" not in result.rules_fired


def test_new_account_name_mismatch_fires_r_fl_03():
    order, ctx = golden_case("diverted")
    assert ctx.account is not None and ctx.account.successful_payments == 0

    result = RISK.score(order, ctx.model_copy(update={"name_match": 0.80}))

    assert "R-FL-03" in result.rules_fired


def test_sanctions_hit_is_critical():
    order, _ = golden_case("legit")
    result = RISK.score(order, build_risk_context(order, [], sanctions_hit=True))
    assert (result.score, result.tier, result.rules_fired) == (95, Tier.CRITICAL, ["R-HB-01"])
    assert not result.oob_resolvable


def test_young_account_fires_r_fl_02():
    order, ctx = golden_case("diverted")
    result = RISK.score(order, ctx.model_copy(update={"account_age_hours": 20.0}))
    assert "R-FL-02" in result.rules_fired and result.score == 74 and result.tier == Tier.HIGH


def test_strict_mode_is_stricter():
    assert RulesRisk(strict=True).score(*golden_case("diverted")).score == 74


def test_strict_mode_holds_legit_golden_when_history_is_missing():
    order, ctx = golden_case("legit")
    assert ctx.history is None

    result = RulesRisk(strict=True).score(order, ctx)

    assert result.tier == Tier.MEDIUM
    assert result.floor_tier == Tier.MEDIUM
    assert result.score == 20
    assert "R-DG-01" in result.rules_fired


def test_strict_mode_allows_established_trusted_history_known_legit():
    order, ctx = golden_case("legit")
    assert ctx.account is not None and ctx.payee is not None
    established_context = ctx.model_copy(
        update={
            "history": PairHistory(
                successful_count=ctx.account.successful_payments,
                median_amount_eur=85_000.0,
                payments_24h=0,
                last_account_id=ctx.account.id,
            )
        }
    )

    result = RulesRisk(strict=True).score(order, established_context)

    assert result.tier == Tier.LOW
    assert "R-DG-01" not in result.rules_fired


def test_strict_mode_session_and_velocity_causes_force_high_non_oob():
    order, ctx = golden_case("legit")
    session = ctx.payer_session.model_copy(update={"sim_swap_72h": True})
    session_result = RulesRisk(strict=True).score(
        order, ctx.model_copy(update={"payer_session": session})
    )
    velocity_result = RulesRisk(strict=True).score(
        order,
        ctx.model_copy(
            update={
                "history": PairHistory(
                    successful_count=14,
                    median_amount_eur=85_000.0,
                    payments_24h=3,
                )
            }
        ),
    )

    assert session_result.tier >= Tier.HIGH
    assert session_result.floor_tier == Tier.HIGH
    assert not session_result.oob_resolvable
    assert velocity_result.tier >= Tier.HIGH
    assert velocity_result.floor_tier == Tier.HIGH
    assert not velocity_result.oob_resolvable


def test_strict_mode_spike_cause_forces_high_non_oob():
    order, ctx = golden_case("legit")
    context = ctx.model_copy(
        update={
            "amount_eur": 260_000.0,
            "history": PairHistory(successful_count=14, median_amount_eur=85_000.0),
        }
    )

    result = RulesRisk(strict=True).score(order, context)

    assert result.tier >= Tier.HIGH
    assert result.floor_tier == Tier.HIGH
    assert not result.oob_resolvable


def test_strict_mode_adds_nonresolvable_degraded_rule_for_session_causes():
    order, ctx = golden_case("legit")
    for updates in (
        {"sim_swap_72h": True},
        {"new_device_24h": True},
        {"country": "GH"},
    ):
        session = ctx.payer_session.model_copy(update=updates)
        result = RulesRisk(strict=True).score(
            order, ctx.model_copy(update={"payer_session": session})
        )
        reason = next(reason for reason in result.reasons if reason.rule_id == "R-DG-01")

        assert result.score == 20 and result.tier == Tier.HIGH
        assert result.floor_tier == Tier.HIGH
        assert reason.ref == "P"
        assert reason.text == "Risk model unavailable: held for verification as a precaution."
        assert not result.oob_resolvable


def test_strict_mode_degraded_account_causes_remain_resolvable_but_structuring_does_not():
    order, ctx = golden_case("legit")
    for updates in (
        {"account": None},
        {"account_age_hours": 24.0},
    ):
        result = RulesRisk(strict=True).score(order, ctx.model_copy(update=updates))
        assert "R-DG-01" in result.rules_fired
        reason = next(reason for reason in result.reasons if reason.rule_id == "R-DG-01")
        assert reason.ref == "B"
        assert result.oob_resolvable

    history = PairHistory(successful_count=14, median_amount_eur=85_000.0)
    result = RulesRisk(strict=True).score(
        order,
        ctx.model_copy(
            update={"amount_eur": 9_500.0, "history": history}
        ),
    )
    reason = next(reason for reason in result.reasons if reason.rule_id == "R-DG-01")
    assert reason.ref == "B"
    assert result.floor_tier == Tier.HIGH
    assert not result.oob_resolvable

    declared_split = order.model_copy(update={"purpose": "DECLARED_SPLIT"})
    result = RulesRisk(strict=True).score(
        declared_split,
        ctx.model_copy(
            update={"amount_eur": 9_500.0, "history": history}
        ),
    )
    assert "R-DG-01" not in result.rules_fired


def test_model_load_failure_holds_sim_swap_payment_at_medium(monkeypatch):
    class CaseWriter:
        def __init__(self, **kwargs):
            pass

    risk_package = ModuleType("sylo_risk")
    risk_package.CaseWriter = CaseWriter
    monkeypatch.setitem(sys.modules, "sylo_risk", risk_package)

    risk, _, _, degraded = load_ports(
        Settings(risk_mode="model"),
        signer=Signer(env={}),
        clock=lambda: 0.0,
        env={},
    )
    order, ctx = golden_case("legit")
    assert ctx.account is not None and ctx.payee is not None
    assert ctx.account.successful_payments >= 1 and ctx.payee.owns(ctx.account.id)
    session = ctx.payer_session.model_copy(update={"sim_swap_72h": True})
    result = risk.score(order, ctx.model_copy(update={"payer_session": session}))

    assert "risk" in degraded
    assert result.tier >= Tier.MEDIUM
    assert "R-DG-01" in result.rules_fired


class _FakeModel:
    name = "fake"
    oob_resolvable = True

    def __init__(self, score: int) -> None:
        self._score = score

    def score(self, order, ctx):
        return RiskResult(
            score=self._score,
            tier=Tier.LOW,
            floor_tier=Tier.LOW,
            rules_fired=[],
            reasons=[RiskReason(ref="M", text="Model reason.")],
            oob_resolvable=self.oob_resolvable,
            model="fake-model",
        )


def test_a_model_can_only_make_the_decision_stricter():
    lenient = CombinedRisk(RulesRisk(), _FakeModel(5)).score(*golden_case("diverted"))
    assert lenient.tier == Tier.MEDIUM and lenient.floor_tier == Tier.MEDIUM
    strict = CombinedRisk(RulesRisk(), _FakeModel(80)).score(*golden_case("diverted"))
    assert strict.tier == Tier.HIGH
    assert strict.reasons[-1].text == "Model reason."


def test_a_failing_model_falls_back_to_the_rules():
    class Broken:
        name = "broken"

        def score(self, order, ctx):
            raise RuntimeError("model down")

    result = CombinedRisk(RulesRisk(), Broken()).score(*golden_case("diverted"))
    assert result.score == 64 and result.model == "rules-v0"
    assert result.oob_resolvable


def test_combined_risk_requires_oob_from_both_rules_and_model():
    class NonResolvableModel(_FakeModel):
        oob_resolvable = False

    result = CombinedRisk(RulesRisk(), NonResolvableModel(80)).score(*golden_case("diverted"))
    assert result.tier == Tier.HIGH
    assert not result.oob_resolvable

    order, context = golden_case("legit")
    sanctioned = context.model_copy(update={"sanctions_hit": True})
    critical = CombinedRisk(RulesRisk(), _FakeModel(5)).score(order, sanctioned)
    assert critical.tier == Tier.CRITICAL
    assert not critical.oob_resolvable
