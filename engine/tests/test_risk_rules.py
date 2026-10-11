from sylo_spec.models import RiskReason, RiskResult, Tier
from sylo_spec.scenarios import build_risk_context, golden_case

from sylo.risk_rules import CombinedRisk, RulesRisk

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
    assert RulesRisk(strict=True).score(*golden_case("legit")).score == 10


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
