import asyncio
from datetime import datetime

import pytest

from sylo.orchestrator import AttackNotApplicable, NotWaiting, UnknownPayment

from .conftest import ATTACK_SEQUENCE, CONFIRM_SEQUENCE, DENY_SEQUENCE, DIVERTED_PREFIX, LEGIT_SEQUENCE


def types(orchestrator):
    return [e["type"] for e in orchestrator.bus.events]


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
    assert offset_ms(by_type["intent.committed"], start) == 5000
    assert offset_ms(by_type["payment.credited"], start) == 15000
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
    for _ in range(10_000):
        await asyncio.sleep(0)
        if orchestrator._runs[payment_id].status == "awaiting_supplier":
            break
    orchestrator.supplier_response(payment_id, "deny")
    await orchestrator._task
    assert types(orchestrator)[-4:] == DENY_SEQUENCE
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
