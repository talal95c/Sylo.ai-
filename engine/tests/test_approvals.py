"""Payer approval and dual control (roadmap A1.3)."""

from datetime import datetime, timezone

import pytest

from sylo_spec.scenarios import PAYER

from sylo.approvals import ApprovalError, ApprovalSession, required_approvers
from sylo.orchestrator import NotWaiting

from .conftest import DIVERTED_PREFIX, events_of, make_orchestrator, types, until

NOW = datetime(2026, 10, 11, 9, 0, 0, tzinfo=timezone.utc)
RULES = {"dual_control_eur": 20_000, "new_payee_eur": 5_000}


def session(approvers=None, method="DUAL_CONTROL"):
    return ApprovalSession(required=approvers or list(PAYER.approvers), method=method, conditional=True)


def test_dual_control_from_20k_or_from_5k_for_a_new_account():
    both = [a.id for a in PAYER.approvers]
    assert [a.id for a in required_approvers(PAYER, 85_000, known_account=True, **RULES)[0]] == both
    assert required_approvers(PAYER, 20_000, known_account=True, **RULES)[1] == "DUAL_CONTROL"
    assert required_approvers(PAYER, 19_999, known_account=True, **RULES) == ([PAYER.approvers[0]], "SCA")
    assert required_approvers(PAYER, 5_000, known_account=False, **RULES)[1] == "DUAL_CONTROL"
    assert required_approvers(PAYER, 4_999, known_account=False, **RULES)[1] == "SCA"


def test_the_author_approves_first_and_cannot_be_the_second_approver():
    s = session()
    with pytest.raises(ApprovalError) as too_early:
        s.approve("marc", NOW)
    assert too_early.value.code == "AUTHOR_FIRST"
    s.approve("claire", NOW)
    with pytest.raises(ApprovalError) as twice:
        s.approve("claire", NOW)
    assert twice.value.code == "AUTHOR_CANNOT_CO_APPROVE"
    assert not s.complete and [a.id for a in s.pending] == ["marc"]
    s.approve("marc", NOW)
    assert s.complete
    with pytest.raises(ApprovalError) as again:
        s.approve("marc", NOW)
    assert again.value.code == "ALREADY_APPROVED"
    with pytest.raises(ApprovalError) as stranger:
        s.approve("mallory", NOW)
    assert stranger.value.code == "NOT_AN_APPROVER"


def test_the_approval_hash_covers_every_approval_record():
    one, two = session(), session()
    for s in (one, two):
        s.approve("claire", NOW)
    one.approve("marc", NOW)
    two.approve("marc", NOW.replace(second=1))
    args = {"payment_id": "PAY-1", "route_id": "R3", "amount": "85000.00"}
    assert one.approval_hash(**args) != two.approval_hash(**args)
    assert one.approval_hash(**args) != one.approval_hash(**{**args, "route_id": "R1"})


async def test_without_auto_the_scenario_waits_for_both_approvals():
    orchestrator = make_orchestrator(human_steps="manual")
    payment_id = orchestrator.start("diverted", auto=False)
    run = await until(orchestrator, payment_id, "awaiting_approval")
    assert types(orchestrator)[-1] == "approval.required" and run.intent is None
    asked = events_of(orchestrator, "approval.required")[0]["data"]
    assert asked["pending"] == ["claire", "marc"] and asked["conditional"] is True
    assert asked["note"] == "Funds are released only after the supplier confirms on a known contact"
    assert [a["name"] for a in asked["required"]] == ["Claire Martin", "Marc Durand"]

    with pytest.raises(ApprovalError):
        orchestrator.approve(payment_id, "marc")
    assert orchestrator.approve(payment_id, "claire") == {"ok": True, "pending": ["marc"]}
    assert events_of(orchestrator, "approval.required")[-1]["data"]["received"][0]["id"] == "claire"
    assert not events_of(orchestrator, "approval.granted"), "one approval is not enough above EUR 20,000"
    assert orchestrator.approve(payment_id, "marc") == {"ok": True, "pending": []}

    await until(orchestrator, payment_id, "awaiting_supplier")
    assert types(orchestrator) == DIVERTED_PREFIX
    granted = events_of(orchestrator, "approval.granted")[0]["data"]
    assert [b["id"] for b in granted["by"]] == ["claire", "marc"] and granted["method"] == "DUAL_CONTROL"
    assert run.intent is not None and run.intent.approval_hash == granted["approvalHash"]
    with pytest.raises(NotWaiting):
        orchestrator.approve(payment_id, "claire")
    await orchestrator.reset()


async def test_with_auto_the_scenario_approves_by_itself_even_in_manual_mode():
    orchestrator = make_orchestrator(human_steps="manual")
    run = await orchestrator.run_to_end("legit", auto=True)
    assert run.status == "credited"
    assert events_of(orchestrator, "approval.granted")[0]["data"]["conditional"] is False


async def test_the_intent_is_committed_only_after_the_approval():
    orchestrator = make_orchestrator()
    await orchestrator.run_to_end("diverted")
    order = types(orchestrator)
    assert order.index("approval.granted") < order.index("intent.committed") < order.index("leg.sent")
