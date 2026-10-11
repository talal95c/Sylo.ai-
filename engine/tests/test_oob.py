"""Out-of-band check, SIM-swap mock and analyst actions (roadmap A1.4 and A1.8)."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from sylo_spec.models import Status

from sylo.orchestrator import ActionNotAllowed, UnknownAction
from sylo.telecom import SimSwapMock

from .conftest import CONFIRM_SEQUENCE, DIVERTED_PREFIX, REVOKE_SEQUENCE, events_of, make_orchestrator, types, until

DIVERTED = "PAY-2026-0002"
NOW = datetime(2026, 10, 11, 9, 0, 0, tzinfo=timezone.utc)


def test_sim_swap_mock_follows_the_camara_shape():
    clock = {"now": NOW}
    telecom = SimSwapMock(clock=lambda: clock["now"])
    assert telecom.check("+233 •• ••• 4471") is False and telecom.retrieve_date("+233 •• ••• 4471") is None
    telecom.declare_swap("+233 •• ••• 4471", hours_ago=5)
    assert telecom.check("+233 •• ••• 4471", max_age_hours=168) is True
    assert telecom.check("+233 •• ••• 4471", max_age_hours=4) is False
    assert telecom.check("+233 •• ••• 0000", max_age_hours=168) is False
    clock["now"] = NOW + timedelta(days=8)
    assert telecom.check("+233 •• ••• 4471", max_age_hours=168) is False
    telecom.clear()
    assert telecom.retrieve_date("+233 •• ••• 4471") is None


async def test_sim_swap_on_the_known_number_sends_no_sms_and_goes_to_the_analyst(event_validator):
    orchestrator = make_orchestrator()
    run = await orchestrator.run_to_end("diverted_simswap")
    assert types(orchestrator) == DIVERTED_PREFIX + REVOKE_SEQUENCE
    assert run.status == "stopped" and orchestrator.chain.status(run.chain_pid) == Status.REVOKED
    requested = events_of(orchestrator, "verification.requested")[0]["data"]
    assert requested["channel"] == "ANALYST" and requested["simSwapRecent"] is True and requested["simSwapChecked"] is True
    held = events_of(orchestrator, "payment.held")[0]["data"]
    assert held["reasons"][-1]["ruleId"] == "R-OOB-01" and "5 hours ago" in held["nextStep"]
    assert not events_of(orchestrator, "verification.recorded"), "nobody was asked, so nothing is attested"
    assert events_of(orchestrator, "intent.revoked")[0]["data"]["reasonCode"] == "ANALYST_DECISION"
    for event in orchestrator.bus.events:
        assert not list(event_validator.iter_errors(event)), event["type"]


async def test_the_normal_scenario_checks_the_sim_and_texts_the_known_contact():
    orchestrator = make_orchestrator()
    await orchestrator.run_to_end("diverted_simswap")
    await orchestrator.run_to_end("diverted")
    requested = events_of(orchestrator, "verification.requested")[-1]["data"]
    assert requested["channel"] == "SMS" and requested["simSwapRecent"] is False
    assert requested["contactName"] == "Kwame Asante" and requested["contactSince"] == "2024-03-12"


async def test_without_auto_the_revocation_waits_for_the_analyst():
    orchestrator = make_orchestrator(human_steps="manual")
    orchestrator.start("diverted", auto=False)
    await until(orchestrator, DIVERTED, "awaiting_approval")
    orchestrator.approve(DIVERTED, "claire")
    orchestrator.approve(DIVERTED, "marc")
    run = await until(orchestrator, DIVERTED, "awaiting_supplier")
    with pytest.raises(ActionNotAllowed):
        await orchestrator.case_action(DIVERTED, "RELEASE")
    orchestrator.supplier_response(DIVERTED, "deny")
    await until(orchestrator, DIVERTED, "awaiting_analyst")
    assert types(orchestrator)[-1] == "verification.recorded"
    assert orchestrator.chain.status(run.chain_pid) == Status.DENIED, "denied, but not revoked until a human confirms"

    assert await orchestrator.case_action(DIVERTED, "CONFIRM_REVOCATION") == {"ok": True}
    await orchestrator._task
    assert types(orchestrator)[-len(REVOKE_SEQUENCE) :] == REVOKE_SEQUENCE
    action = events_of(orchestrator, "case.action")[0]["data"]
    assert action == {"action": "CONFIRM_REVOCATION", "by": "Julien (fraud analyst)"}
    assert events_of(orchestrator, "intent.revoked")[0]["data"]["by"] == "Julien (fraud analyst)"
    with pytest.raises(ActionNotAllowed):
        await orchestrator.case_action(DIVERTED, "CONFIRM_REVOCATION")
    with pytest.raises(UnknownAction):
        await orchestrator.case_action(DIVERTED, "PAY_ANYWAY")


async def test_the_analyst_can_revoke_before_the_supplier_answers():
    orchestrator = make_orchestrator()
    orchestrator.start("diverted", auto=False)
    run = await until(orchestrator, DIVERTED, "awaiting_supplier")
    await orchestrator.case_action(DIVERTED, "CONFIRM_REVOCATION")
    await orchestrator._task
    assert run.status == "stopped" and orchestrator.chain.status(run.chain_pid) == Status.REVOKED
    assert events_of(orchestrator, "intent.revoked")[0]["data"]["reasonCode"] == "ANALYST_DECISION"
    assert not events_of(orchestrator, "verification.recorded")


async def test_a_frozen_payment_is_not_released_even_if_the_supplier_confirms(event_validator):
    orchestrator = make_orchestrator(human_steps="manual")
    orchestrator.start("diverted", auto=False)
    await until(orchestrator, DIVERTED, "awaiting_approval")
    orchestrator.approve(DIVERTED, "claire")
    orchestrator.approve(DIVERTED, "marc")
    run = await until(orchestrator, DIVERTED, "awaiting_supplier")
    assert await orchestrator.case_action(DIVERTED, "FREEZE") == {"ok": True}
    frozen = events_of(orchestrator, "case.action")[0]["data"]
    assert frozen["action"] == "FREEZE" and frozen["txHash"].startswith("0x")
    with pytest.raises(ActionNotAllowed):
        await orchestrator.case_action(DIVERTED, "FREEZE")

    orchestrator.supplier_response(DIVERTED, "confirm")
    await until(orchestrator, DIVERTED, "awaiting_analyst")
    reverted = events_of(orchestrator, "tx.reverted")[0]["data"]
    assert (reverted["function"], reverted["reason"]) == ("release", "PaymentNotReleasable")
    assert run.hold == "escrow" and not events_of(orchestrator, "escrow.released")

    await orchestrator.case_action(DIVERTED, "CONFIRM_REVOCATION")
    await orchestrator._task
    assert run.status == "stopped" and events_of(orchestrator, "escrow.refunded")
    for event in orchestrator.bus.events:
        assert not list(event_validator.iter_errors(event)), event["type"]


async def test_release_by_the_analyst_is_only_possible_once_confirmed():
    orchestrator = make_orchestrator()
    orchestrator.start("diverted", auto=False)
    run = await until(orchestrator, DIVERTED, "awaiting_supplier")

    # With a virtual clock the "confirmed" second lasts no time at all: hold the script there.
    gate, advance = asyncio.Event(), run.pacer.wait

    async def wait(ms):
        if run.status == "confirmed":
            await gate.wait()
        await advance(ms)

    run.pacer.wait = wait
    orchestrator.supplier_response(DIVERTED, "confirm")
    await until(orchestrator, DIVERTED, "confirmed")
    assert await orchestrator.case_action(DIVERTED, "RELEASE") == {"ok": True}
    gate.set()
    await orchestrator._task
    assert types(orchestrator)[-len(CONFIRM_SEQUENCE) - 1 :] == ["verification.recorded", "case.action"] + CONFIRM_SEQUENCE[1:]
    with pytest.raises(ActionNotAllowed):
        await orchestrator.case_action(DIVERTED, "RELEASE")
