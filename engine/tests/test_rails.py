"""Rail adapters: the checks made before a leg is sent (roadmap A1.5, PRD §13.5)."""

import dataclasses

import pytest

from sylo_spec.models import Status

from sylo.rails import EXPIRED, INTENT_HASH_MISMATCH, NONCE_USED, NOT_CONFIRMED, REVOKED, LegRejected

from .conftest import events_of, make_orchestrator, until

DIVERTED = "PAY-2026-0002"


async def finished(scenario="diverted", **kw):
    """A finished scenario, its run and the adapter of its route."""
    orchestrator = make_orchestrator()
    run = await orchestrator.run_to_end(scenario, **kw)
    return orchestrator, run, orchestrator.rails.adapter(run.decision.route.id)


async def held():
    """The diverted payment, in escrow, waiting for the supplier (every human step is manual)."""
    orchestrator = make_orchestrator(human_steps="manual")
    orchestrator.start("diverted", auto=False)
    await until(orchestrator, DIVERTED, "awaiting_approval")
    orchestrator.approve(DIVERTED, "claire")
    orchestrator.approve(DIVERTED, "marc")
    run = await until(orchestrator, DIVERTED, "awaiting_supplier")
    return orchestrator, run, orchestrator.rails.adapter("R3")


def leg(orchestrator, run, hop):
    return orchestrator._leg_message(run, hop, run.hops[hop])


def refused(adapter, message):
    with pytest.raises(LegRejected) as info:
        adapter.initiate(message)
    return info.value.reason


async def test_every_leg_of_a_run_went_through_its_adapter():
    orchestrator, run, adapter = await finished("legit")
    sent = events_of(orchestrator, "leg.sent")
    assert len(sent) == 5 and all(e["data"]["intentHash"] == run.intent_hash for e in sent)
    assert all(e["data"]["uetr"] == run.order.uetr for e in sent)
    keys = [e["data"]["idempotencyKey"] for e in sent]
    assert len(set(keys)) == 5 and all(adapter.status(key) == "SETTLED" for key in keys)


async def test_a_changed_leg_is_refused_before_it_is_sent():
    orchestrator, run, adapter = await finished("diverted", auto_answer="confirm")
    genuine = leg(orchestrator, run, 3)
    for change in (
        {"creditor_account": "GH•• •••• 6660"},
        {"creditor_name": "SOMEONE ELSE LTD"},
        {"creditor_bank": "momo_gh"},
        {"salt": "0x" + "11" * 32},
        {"intent": genuine.intent.model_copy(update={"amount": genuine.intent.amount + 1})},
        {"intent": genuine.intent.model_copy(update={"beneficiary": "0x" + "ab" * 20})},
    ):
        assert refused(adapter, dataclasses.replace(genuine, **change)) == INTENT_HASH_MISMATCH, change


async def test_a_settled_leg_cannot_be_replayed():
    orchestrator, run, adapter = await finished("diverted", auto_answer="confirm")
    assert refused(adapter, leg(orchestrator, run, 3)) == NONCE_USED

    orchestrator, run, adapter = await finished("legit")
    assert orchestrator.chain.status(run.chain_pid) == Status.EXECUTED
    assert refused(adapter, leg(orchestrator, run, 0)) == NONCE_USED


async def test_a_retry_of_a_pending_leg_is_not_sent_twice():
    orchestrator, run, adapter = await held()
    chain_leg = leg(orchestrator, run, 2)
    assert adapter.status(chain_leg.idempotency_key) == "PENDING"
    assert adapter.initiate(chain_leg) == {"idempotencyKey": chain_leg.idempotency_key, "status": "PENDING", "retry": True}
    await orchestrator.reset()


async def test_no_pay_out_leg_before_the_supplier_confirms_nor_after_a_revocation():
    orchestrator, run, adapter = await held()
    assert adapter.is_payout(3, run.intent.tier) and not adapter.is_payout(2, run.intent.tier)
    assert refused(adapter, leg(orchestrator, run, 3)) == NOT_CONFIRMED

    orchestrator.supplier_response(DIVERTED, "deny")
    await until(orchestrator, DIVERTED, "awaiting_analyst")
    assert refused(adapter, leg(orchestrator, run, 3)) == NOT_CONFIRMED
    await orchestrator.case_action(DIVERTED, "CONFIRM_REVOCATION")
    await orchestrator._task
    assert orchestrator.chain.status(run.chain_pid) == Status.REVOKED
    assert refused(adapter, leg(orchestrator, run, 3)) == REVOKED


async def test_an_expired_intent_cannot_start_a_funding_leg():
    orchestrator, run, adapter = await held()
    await run.pacer.wait(601_000)
    assert refused(adapter, leg(orchestrator, run, 1)) == EXPIRED
    await orchestrator.reset()


async def test_refusals_are_counted_per_adapter():
    orchestrator, run, adapter = await finished("diverted", auto_answer="confirm")
    assert adapter.integrity_refusals(600) == 0
    refused(adapter, dataclasses.replace(leg(orchestrator, run, 3), creditor_account="GH•• •••• 6660"))
    refused(adapter, leg(orchestrator, run, 3))
    assert adapter.integrity_refusals(600) == 2
    assert orchestrator.rails.adapter("R1").integrity_refusals(600) == 0


async def test_quotes_and_hold_hops_come_from_the_pack():
    orchestrator = make_orchestrator()
    quotes = {q["routeId"]: q for q in orchestrator.rails.quotes(85_000)}
    assert quotes["R1"]["feesEur"] == 80 and quotes["R3"]["feesEur"] == 170 and quotes["R4"]["feesEur"] == 1275
    assert all(q["simulated"] and q["available"] for q in quotes.values())
    assert orchestrator.rails.adapter("R3").hold_hop() == 2
    assert orchestrator.rails.adapter("R1").hold_hop() == 0
    assert orchestrator.rails.adapter("R2").hold_hop() is None
