"""HIGH risk that an out-of-band confirmation can lift is held in escrow, never paid directly (Lane B spec)."""

from sylo_spec.models import RiskReason, RiskResult, Status, Tier

from sylo.orchestrator import action_tier
from sylo.risk_rules import CombinedRisk, RulesRisk

from .conftest import events_of, make_orchestrator, types


class _Model:
    name = "fake-gbm"

    def __init__(self, score, oob_resolvable):
        self._score, self._oob = score, oob_resolvable

    def score(self, order, ctx):
        return RiskResult(
            score=self._score,
            tier=Tier.LOW,
            floor_tier=Tier.LOW,
            rules_fired=[],
            reasons=[RiskReason(ref="M", text="The model finds this beneficiary change unusual.")],
            oob_resolvable=self._oob,
            model="fake-gbm-1",
        )


def with_model(score, oob_resolvable):
    orchestrator = make_orchestrator()
    orchestrator.risk = CombinedRisk(RulesRisk(), _Model(score, oob_resolvable))
    return orchestrator


def test_only_high_and_resolvable_is_handled_like_medium():
    def result(tier, oob):
        return RiskResult(score=50, tier=tier, floor_tier=Tier.LOW, rules_fired=[], reasons=[], oob_resolvable=oob, model="m")

    assert action_tier(result(Tier.HIGH, True)) == Tier.MEDIUM
    assert action_tier(result(Tier.HIGH, False)) == Tier.HIGH
    assert action_tier(result(Tier.CRITICAL, True)) == Tier.CRITICAL
    assert action_tier(result(Tier.LOW, True)) == Tier.LOW


async def test_high_but_resolvable_goes_through_escrow_and_the_supplier_check(event_validator):
    orchestrator = with_model(80, True)
    run = await orchestrator.run_to_end("diverted", auto_answer="deny")
    risk = events_of(orchestrator, "risk.scored")[0]["data"]
    assert risk["tier"] == "HIGH" and risk["oobResolvable"] is True and risk["model"] == "fake-gbm-1"
    assert run.intent.tier == Tier.MEDIUM and events_of(orchestrator, "intent.committed")[0]["data"]["tier"] == "MEDIUM"
    assert events_of(orchestrator, "approval.granted")[0]["data"]["conditional"] is True
    held = events_of(orchestrator, "payment.held")[0]["data"]
    assert held["tier"] == "HIGH" and held["nextStep"].endswith(
        "High risk on the beneficiary's identity only: held in escrow until out-of-band confirmation"
    )
    assert "escrow.deposited" in types(orchestrator) and "escrow.refunded" in types(orchestrator)
    assert run.status == "stopped" and orchestrator.chain.status(run.chain_pid) == Status.REVOKED
    for event in orchestrator.bus.events:
        assert not list(event_validator.iter_errors(event)), event["type"]


async def test_high_and_not_resolvable_gets_no_route_and_a_case():
    orchestrator = with_model(80, False)
    run = await orchestrator.run_to_end("diverted")
    assert run.status == "stopped" and run.intent is None
    assert types(orchestrator)[-2:] == ["payment.stopped", "case.ready"]
    assert not events_of(orchestrator, "approval.required") and not events_of(orchestrator, "leg.sent")
    assert events_of(orchestrator, "case.ready")[0]["data"]["recommendedAction"] == "ESCALATE_AML"


async def test_the_rules_alone_mark_the_two_scenarios_as_resolvable():
    orchestrator = make_orchestrator()
    await orchestrator.run_to_end("diverted")
    assert events_of(orchestrator, "risk.scored")[0]["data"]["oobResolvable"] is True
