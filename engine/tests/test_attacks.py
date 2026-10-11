"""The three integrity attacks of Scene 2b fail visibly (roadmap A1.5, v1 done criterion 4)."""

import pytest

from sylo.orchestrator import AttackNotApplicable, UnknownAttack

from .conftest import ATTACK_SEQUENCE, SWAP_SEQUENCE, events_of, make_orchestrator, types, until

DIVERTED = "PAY-2026-0002"


async def denied():
    orchestrator = make_orchestrator()
    await orchestrator.run_to_end("diverted", auto=True, auto_answer="deny")
    return orchestrator


async def test_swap_beneficiary_is_refused_by_the_adapter_then_by_the_escrow(event_validator):
    orchestrator = await denied()
    result = await orchestrator.attack("swap_beneficiary", DIVERTED)
    assert result == {"ok": True, "reverted": True, "reason": "CommitmentMismatch", "legRejected": "INTENT_HASH_MISMATCH"}
    assert types(orchestrator)[-3:] == SWAP_SEQUENCE
    rejected = events_of(orchestrator, "leg.rejected")[-1]["data"]
    assert rejected["reason"] == "INTENT_HASH_MISMATCH" and rejected["rail"] == "R3"
    assert (rejected["hop"], rejected["from"], rejected["to"]) == (3, "vasp_gh", "mule_bank")
    reverted = orchestrator.bus.events[-1]["data"]
    assert (reverted["function"], reverted["reason"]) == ("deposit", "CommitmentMismatch")
    for event in orchestrator.bus.events:
        assert not list(event_validator.iter_errors(event)), event["type"]


async def test_replay_of_the_signed_intent_reverts(event_validator):
    orchestrator = await denied()
    result = await orchestrator.attack("replay", DIVERTED)
    assert result == {"ok": True, "reverted": True, "reason": "InvalidTransition"}
    assert types(orchestrator)[-2:] == ATTACK_SEQUENCE
    assert orchestrator.bus.events[-1]["data"]["function"] == "commit"
    assert orchestrator.bus.events[-2]["data"]["attack"] == "replay"
    for event in orchestrator.bus.events[-2:]:
        assert not list(event_validator.iter_errors(event)), event["type"]


async def test_the_three_attacks_fail_one_after_the_other():
    orchestrator = await denied()
    reasons = [(await orchestrator.attack(name, DIVERTED))["reason"] for name in ("release_revoked", "swap_beneficiary", "replay")]
    assert reasons == ["PaymentNotReleasable", "CommitmentMismatch", "InvalidTransition"]


async def test_attacks_also_fail_on_a_paid_and_on_a_held_payment():
    paid = make_orchestrator()
    await paid.run_to_end("legit")
    assert (await paid.attack("swap_beneficiary", "PAY-2026-0001"))["legRejected"] == "INTENT_HASH_MISMATCH"
    assert (await paid.attack("replay", "PAY-2026-0001"))["reason"] == "InvalidTransition"

    held = make_orchestrator()
    held.start("diverted", auto=False)
    await until(held, DIVERTED, "awaiting_supplier")
    assert (await held.attack("swap_beneficiary", DIVERTED))["reason"] == "CommitmentMismatch"
    assert held._runs[DIVERTED].status == "awaiting_supplier", "an attack does not change the payment's state"
    await held.reset()


async def test_attacks_need_a_committed_intent_and_a_known_name():
    orchestrator = make_orchestrator(human_steps="manual")
    orchestrator.start("diverted", auto=False)
    await until(orchestrator, DIVERTED, "awaiting_approval")
    for name in ("swap_beneficiary", "replay"):
        with pytest.raises(AttackNotApplicable):
            await orchestrator.attack(name, DIVERTED)
    with pytest.raises(UnknownAttack):
        await orchestrator.attack("drain_everything", DIVERTED)
    await orchestrator.reset()
