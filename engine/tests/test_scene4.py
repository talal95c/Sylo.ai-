"""Scene 4: a stolen verifier key confirms a held payment. Whatever happens next, the payer is refunded."""

import pytest

from sylo_spec.canonical import hash_record, to_hex
from sylo_spec.eip712 import digest
from sylo_spec.models import Status, VerificationAttestation, VerificationMethod, VerificationResult
from sylo_spec.ports import ChainReverted

from sylo.orchestrator import ActionNotAllowed, AttackNotApplicable, NotWaiting

from .conftest import events_of, make_orchestrator, types, until

LEGIT = "PAY-2026-0001"
DIVERTED = "PAY-2026-0002"
SCENE = [
    "attack.attempted",
    "guardian.incident",
    "rail.down",
    "alert.raised",
    "tx.reverted",
    "case.action",
    "intent.revoked",
    "escrow.refunded",
    "alert.raised",
    "alert.raised",
    "payment.stopped",
]


async def held(orchestrator):
    """The diverted payment, in escrow, waiting for the supplier's answer."""
    orchestrator.start("diverted", auto=False)
    if orchestrator.settings.human_steps == "manual":
        await until(orchestrator, DIVERTED, "awaiting_approval")
        for approver in ("claire", "marc"):
            orchestrator.approve(DIVERTED, approver)
    return await until(orchestrator, DIVERTED, "awaiting_supplier")


def forge_confirmation(orchestrator, run):
    """What the thief does on-chain: a CONFIRMED attestation, signed with the verifier key, that the engine never recorded."""
    domain = orchestrator.chain.domain()
    forged = VerificationAttestation(
        payment_id=run.intent.payment_id,
        intent_hash=to_hex(digest(run.intent, domain)),
        method=int(VerificationMethod.OOB_KNOWN_CONTACT),
        result=int(VerificationResult.CONFIRMED),
        sim_swap_checked=True,
        evidence_hash=hash_record({"forged": True}),
        verified_at=int(orchestrator.now().timestamp()),
        nonce=orchestrator.signer.next_nonce("verifier_signer"),
    )
    orchestrator.chain.record_verification(forged, orchestrator.signer.sign("verifier_signer", forged, domain))


def refunded(orchestrator, run):
    return (
        run.status == "stopped"
        and run.hold is None
        and orchestrator.chain.status(run.chain_pid) == Status.REVOKED
        and len(events_of(orchestrator, "escrow.refunded")) == 1
        and not events_of(orchestrator, "escrow.released")
    )


async def test_the_stolen_key_scene_ends_revoked_and_refunded(event_validator):
    orchestrator = make_orchestrator()
    run = await held(orchestrator)
    result = await orchestrator.attack("stolen_verifier_key", DIVERTED)
    assert result == {"ok": True, "reverted": True, "reason": "PaymentNotReleasable", "incidentId": "INC-20261011-001"}
    await orchestrator._task

    sequence = types(orchestrator)
    assert sequence[sequence.index("attack.attempted") :] == SCENE
    assert refunded(orchestrator, run) and run.frozen and run.incident_id == "INC-20261011-001"
    incident = events_of(orchestrator, "guardian.incident")[0]["data"]
    assert incident["rule"] == "CONFIRMED_WITHOUT_OOB_RECORD" and incident["action"] == "FREEZE_AND_PAUSE"
    assert incident["dora"]["draft"] is True and incident["txHash"].startswith("0x")
    assert events_of(orchestrator, "tx.reverted")[0]["data"]["function"] == "release"
    assert "never signed" in events_of(orchestrator, "payment.stopped")[0]["data"]["detail"]
    # The supplier never answered, and the forged attestation is not among what the engine signed.
    assert not events_of(orchestrator, "verification.recorded")
    proof = await orchestrator.proof(DIVERTED)
    assert [item["type"] for item in proof["signed"]] == ["PaymentIntent", "Revocation"]
    for event in orchestrator.bus.events:
        errors = list(event_validator.iter_errors(event))
        assert not errors, f"{event['type']}: {errors[0].message}"


async def test_the_paused_corridor_closes_the_escrow_route_until_a_person_reopens_it():
    orchestrator = make_orchestrator()
    await held(orchestrator)
    await orchestrator.attack("stolen_verifier_key", DIVERTED)
    await orchestrator._task
    assert orchestrator.rails.unavailable() == {"R3": "RAIL_DOWN"}
    assert "guardian" in events_of(orchestrator, "rail.down")[0]["data"]["reason"]

    rerouted = await orchestrator.run_to_end("legit")
    assert rerouted.decision.route.id == "R1" and rerouted.status == "credited" and rerouted.tier.name == "LOW"

    orchestrator.rail_up("R3")
    confirmed = await orchestrator.run_to_end("diverted", auto_answer="confirm")
    assert confirmed.decision.route.id == "R3" and confirmed.status == "credited"
    assert len(events_of(orchestrator, "escrow.released")) == 1


async def test_a_new_session_reopens_the_corridor_on_the_simulated_chain():
    orchestrator = make_orchestrator()
    await held(orchestrator)
    await orchestrator.attack("stolen_verifier_key", DIVERTED)
    await orchestrator._task
    await orchestrator.reset()
    confirmed = await orchestrator.run_to_end("diverted", auto_answer="confirm")
    assert confirmed.decision.route.id == "R3" and confirmed.status == "credited"


async def test_with_manual_steps_only_the_analyst_can_close_the_frozen_case():
    orchestrator = make_orchestrator(human_steps="manual")
    run = await held(orchestrator)
    await orchestrator.attack("stolen_verifier_key", DIVERTED)
    await until(orchestrator, DIVERTED, "awaiting_analyst")
    assert (await orchestrator.payment_info(DIVERTED))["incidentId"] == "INC-20261011-001"
    with pytest.raises(NotWaiting):
        orchestrator.supplier_response(DIVERTED, "confirm")
    with pytest.raises(ActionNotAllowed):
        await orchestrator.case_action(DIVERTED, "RELEASE")
    assert orchestrator.chain.status(run.chain_pid) == Status.CONFIRMED and run.hold == "escrow"

    await orchestrator.case_action(DIVERTED, "CONFIRM_REVOCATION")
    await orchestrator._task
    assert refunded(orchestrator, run)


@pytest.mark.parametrize("answer", ["deny", "confirm"])
async def test_without_a_guardian_the_registry_refuses_the_answer_and_the_payer_is_refunded(answer):
    orchestrator = make_orchestrator()
    run = await held(orchestrator)
    forge_confirmation(orchestrator, run)
    orchestrator.supplier_response(DIVERTED, answer)
    await orchestrator._task

    reverted = events_of(orchestrator, "tx.reverted")[0]["data"]
    assert reverted["function"] == "recordVerification" and reverted["reason"] == "InvalidTransition"
    assert [e["data"]["audience"] for e in events_of(orchestrator, "alert.raised")][1] == "analyst"
    assert refunded(orchestrator, run) and not events_of(orchestrator, "verification.recorded")


async def test_a_revert_while_money_is_held_leaves_it_held_for_the_analyst(monkeypatch):
    orchestrator = make_orchestrator()
    run = await held(orchestrator)

    def refused(*args):
        raise ChainReverted("InvalidTransition", function="revoke")

    monkeypatch.setattr(orchestrator.chain, "revoke", refused)
    orchestrator.supplier_response(DIVERTED, "deny")
    await orchestrator._task
    assert run.status == "held" and run.hold == "escrow" and not events_of(orchestrator, "payment.stopped")
    alert = events_of(orchestrator, "alert.raised")[-1]["data"]
    assert alert["audience"] == "analyst" and "stays in the hold" in alert["text"]


async def test_the_scene_needs_a_payment_waiting_in_escrow():
    orchestrator = make_orchestrator()
    await orchestrator.run_to_end("legit")
    with pytest.raises(AttackNotApplicable):
        await orchestrator.attack("stolen_verifier_key", LEGIT)
    await orchestrator.run_to_end("diverted", auto_answer="deny")
    with pytest.raises(AttackNotApplicable):
        await orchestrator.attack("stolen_verifier_key", DIVERTED)
