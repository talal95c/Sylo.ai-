from datetime import datetime

import pytest

from sylo.config import Settings
from sylo.orchestrator import AttackNotApplicable, NotWaiting, UnknownPayment, build_orchestrator
from sylo.pacer import VirtualPacer
from sylo.risk_rules import CombinedRisk, RulesRisk

from .conftest import ATTACK_SEQUENCE, CONFIRM_SEQUENCE, DENY_SEQUENCE, DIVERTED_PREFIX, LEGIT_SEQUENCE, START, types, until


def assert_valid(orchestrator, validator):
    for event in orchestrator.bus.events:
        errors = list(validator.iter_errors(event))
        assert not errors, f"{event['type']} (seq {event['seq']}): {errors[0].message}"


def offset_ms(event, start):
    return round((datetime.fromisoformat(event["ts"].replace("Z", "+00:00")) - start).total_seconds() * 1000)


async def test_legit_sequence_and_timeline(orchestrator, event_validator):
    run = await orchestrator.run_to_end("legit")
    assert types(orchestrator) == LEGIT_SEQUENCE
    assert run.status == "credited"
    assert_valid(orchestrator, event_validator)
    events = orchestrator.bus.events
    start = datetime.fromisoformat(events[0]["ts"].replace("Z", "+00:00"))
    by_type = {e["type"]: e for e in events}
    assert offset_ms(by_type["payment.created"], start) == 400
    assert offset_ms(by_type["approval.granted"], start) == 5300
    assert offset_ms(by_type["intent.committed"], start) == 6200
    assert offset_ms(by_type["payment.credited"], start) == 16200
    assert by_type["payment.credited"]["data"]["at"] == "supplier_ssx"


async def test_diverted_then_deny_then_attack(orchestrator, event_validator):
    run = await orchestrator.run_to_end("diverted", auto=True, auto_answer="deny")
    assert types(orchestrator) == DIVERTED_PREFIX + DENY_SEQUENCE
    assert run.status == "stopped"
    result = await orchestrator.attack("release_revoked", "PAY-2026-0002")
    assert result == {"ok": True, "reverted": True, "reason": "PaymentNotReleasable"}
    assert types(orchestrator)[-2:] == ATTACK_SEQUENCE
    assert orchestrator.bus.events[-1]["data"]["reason"] == "PaymentNotReleasable"
    assert_valid(orchestrator, event_validator)


async def test_diverted_then_confirm(orchestrator, event_validator):
    run = await orchestrator.run_to_end("diverted", auto=True, auto_answer="confirm")
    assert types(orchestrator) == DIVERTED_PREFIX + CONFIRM_SEQUENCE
    assert run.status == "credited"
    assert orchestrator.bus.events[-1]["data"]["at"] == "mule_bank"
    assert_valid(orchestrator, event_validator)


async def test_held_event_carries_the_alert_content(orchestrator):
    await orchestrator.run_to_end("diverted", auto=True)
    held = next(e for e in orchestrator.bus.events if e["type"] == "payment.held")["data"]
    assert held["hop"] == 2 and held["at"] == "escrow" and held["tier"] == "MEDIUM"
    assert held["headline"] == "Payment held: possible supplier impersonation"
    assert len(held["reasons"]) == 4


async def test_supplier_answer_through_the_api_path(orchestrator):
    payment_id = orchestrator.start("diverted", auto=False)
    with pytest.raises(NotWaiting):
        orchestrator.supplier_response(payment_id, "deny")
    await until(orchestrator, payment_id, "awaiting_supplier")
    orchestrator.supplier_response(payment_id, "deny")
    await orchestrator._task
    assert types(orchestrator)[-len(DENY_SEQUENCE) :] == DENY_SEQUENCE
    with pytest.raises(UnknownPayment):
        orchestrator.supplier_response("PAY-0000", "deny")


async def test_attack_needs_a_revoked_payment(orchestrator):
    await orchestrator.run_to_end("legit")
    with pytest.raises(AttackNotApplicable):
        await orchestrator.attack("release_revoked", "PAY-2026-0001")


async def test_a_scenario_can_run_twice(orchestrator):
    await orchestrator.run_to_end("diverted", auto=True, auto_answer="deny")
    run = await orchestrator.run_to_end("diverted", auto=True, auto_answer="confirm")
    assert run.status == "credited"


async def test_reset_clears_the_session_but_seq_keeps_increasing(orchestrator):
    await orchestrator.run_to_end("legit")
    last = orchestrator.bus.last_seq
    await orchestrator.reset()
    assert [e["type"] for e in orchestrator.bus.events] == ["session.reset"]
    assert orchestrator.bus.events[0]["seq"] == last + 1


def model_orchestrator():
    return build_orchestrator(
        Settings(risk_mode="model"),
        env={},
        pacer_factory=lambda speed: VirtualPacer(START, speed),
    )


async def test_model_mode_routes_legit_direct_and_diverted_through_escrow():
    legit_orchestrator = model_orchestrator()
    assert legit_orchestrator.mode()["risk"] == "model"
    legit = await legit_orchestrator.run_to_end("legit")
    legit_risk = next(
        event["data"] for event in legit_orchestrator.bus.events if event["type"] == "risk.scored"
    )
    legit_route = next(
        event["data"] for event in legit_orchestrator.bus.events if event["type"] == "route.selected"
    )
    assert legit_risk["tier"] == "LOW"
    assert legit_route["settlement"] == "DIRECT"
    assert not any(event["type"] == "escrow.deposited" for event in legit_orchestrator.bus.events)
    assert legit.status == "credited"

    diverted_orchestrator = model_orchestrator()
    diverted = await diverted_orchestrator.run_to_end("diverted", auto=True, auto_answer="deny")
    events = diverted_orchestrator.bus.events
    risk = next(event["data"] for event in events if event["type"] == "risk.scored")
    held = next(event["data"] for event in events if event["type"] == "payment.held")
    assert risk["tier"] == "HIGH" and risk["oobResolvable"] is True
    assert diverted.intent.tier == 1
    committed = next(event["data"] for event in events if event["type"] == "intent.committed")
    assert committed["tier"] == "MEDIUM"
    assert any(event["type"] == "escrow.deposited" for event in events)
    assert any(event["type"] == "verification.requested" for event in events)
    assert any(event["type"] == "escrow.refunded" for event in events)
    assert held["nextStep"].endswith(
        "High risk on the beneficiary's identity only: held in escrow until out-of-band confirmation"
    )
    assert diverted.status == "stopped"


async def test_model_mode_blocks_diverted_payment_when_session_has_sim_swap():
    from sylo_risk import ModelRisk

    class SimSwapModel:
        def __init__(self):
            self.model = ModelRisk()
            self.name = self.model.name

        def score(self, order, ctx):
            session = ctx.payer_session.model_copy(update={"sim_swap_72h": True})
            return self.model.score(order, ctx.model_copy(update={"payer_session": session}))

    orchestrator = model_orchestrator()
    orchestrator.risk = CombinedRisk(RulesRisk(), SimSwapModel())
    run = await orchestrator.run_to_end("diverted", auto=True, auto_answer="deny")
    risk = next(
        event["data"] for event in orchestrator.bus.events if event["type"] == "risk.scored"
    )

    assert risk["oobResolvable"] is False
    assert risk["tier"] == "HIGH"
    assert run.status == "stopped"
    assert run.intent is None
    assert any(event["type"] == "payment.stopped" for event in orchestrator.bus.events)
    assert not any(event["type"] == "escrow.deposited" for event in orchestrator.bus.events)
