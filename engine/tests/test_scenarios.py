"""The scenario timelines of the build spec (section 5.10), on a virtual clock."""

import asyncio
from datetime import datetime

import pytest

from sylo import record_fixtures
from sylo.orchestrator import Conflict, NotFound
from sylo_spec import validate_event
from sylo_spec.canonical import payment_id_bytes
from sylo_spec.models import Status

DECISION = ["scenario.started", "payment.created", "norms.checked", "risk.scored", "route.selected", "approval.granted", "intent.committed"]
LEG = ["leg.sent", "leg.settled"]
LEGIT = DECISION + LEG * 5 + ["intent.executed", "payment.credited"]
DIVERTED = DECISION + LEG * 2 + ["leg.sent", "escrow.deposited", "payment.held", "verification.requested"]
DENY = ["verification.recorded", "intent.revoked", "escrow.refunded", "payment.stopped"]
CONFIRM = ["verification.recorded", "escrow.released", "intent.executed", "leg.settled", "leg.sent", "leg.settled", "payment.credited"]
ATTACK = ["attack.attempted", "tx.reverted"]


def _types(core):
    return [e["type"] for e in core.bus.events()]


def _ms(event):
    return datetime.fromisoformat(event["ts"].replace("Z", "+00:00")).timestamp() * 1000


def _check(core):
    events = core.bus.events()
    for event in events:
        validate_event(event)
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert [e["id"] for e in events] == [f"evt-{i:06d}" for i in range(1, len(events) + 1)]
    return events


async def _until(predicate, timeout=5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        assert asyncio.get_running_loop().time() < deadline, "timed out"
        await asyncio.sleep(0.001)


async def test_legit_timeline(core):
    payment_id = core.orchestrator.start("legit", auto=True)
    await core.orchestrator.wait_idle()
    events = _check(core)
    assert payment_id == "PAY-2026-0001" and _types(core) == LEGIT
    by_type = {e["type"]: e for e in events}
    assert by_type["risk.scored"]["data"]["score"] == 10 and by_type["risk.scored"]["data"]["tier"] == "LOW"
    assert by_type["route.selected"]["data"]["routeId"] == "R3"
    approval = by_type["approval.granted"]["data"]
    assert [a["name"] for a in approval["by"]] == ["Claire Martin", "Marc Durand"]
    assert approval["method"] == "DUAL_CONTROL" and approval["conditional"] is False
    credited = by_type["payment.credited"]["data"]
    assert credited == {"at": "supplier_ssx", "feesEur": 170.0, "routeCostEur": 179.21, "swiftRouteCostEur": 216.0, "elapsedLabel": "≈ 2 h (simulated)"}
    legs = [e["data"] for e in events if e["type"] == "leg.sent"]
    assert [(l["hop"], l["kind"], l["durationMs"]) for l in legs] == [(0, "bank", 1400), (1, "bank", 1400), (2, "chain", 2200), (3, "bank", 1400), (4, "bank", 1400)]
    # decisions are real computations; rails and mock-chain transactions are simulated
    assert not by_type["risk.scored"]["simulated"] and by_type["leg.sent"]["simulated"] and by_type["intent.committed"]["simulated"]
    assert by_type["intent.committed"]["data"]["explorerUrl"] is None
    # delays of the spec: created +400, norms +900, risk +900, route +900, approval +1000, commit +900, first leg +300
    gaps = [round(_ms(b) - _ms(a)) for a, b in zip(events, events[1:])]
    assert gaps[:7] == [400, 900, 900, 900, 1000, 900, 300] and gaps[-2:] == [400, 300]
    view = core.orchestrator.payment_view(payment_id)
    assert (view["status"], view["tier"], view["routeId"], view["chainStatus"], view["lastSeq"]) == ("credited", "LOW", "R3", "EXECUTED", 19)


async def test_diverted_then_deny_then_attack(core):
    payment_id = core.orchestrator.start("diverted", auto=True, auto_answer="deny")
    await core.orchestrator.wait_idle()
    events = _check(core)
    assert _types(core) == DIVERTED + DENY
    by_type = {e["type"]: e for e in events}
    assert by_type["payment.created"]["data"]["beneficiary"]["knownAccount"] is False
    assert by_type["payment.created"]["data"]["senderDomain"] == "savannashea-exports.com"
    assert by_type["risk.scored"]["data"]["score"] == 64 and by_type["risk.scored"]["data"]["rulesFired"] == ["R-PV-01", "R-FL-01", "R-FL-03", "R-NM-01"]
    assert by_type["approval.granted"]["data"]["conditional"] is True
    held = by_type["payment.held"]["data"]
    assert (held["hop"], held["at"], held["tier"], len(held["reasons"])) == (2, "escrow", "MEDIUM", 4)
    assert held["headline"] == "Payment held: possible supplier impersonation"
    assert held["expiresAt"] == "2026-10-12T09:00:09.800Z"  # deposit time + 24 h
    assert by_type["verification.requested"]["data"]["contactName"] == "Kwame Asante"
    assert by_type["verification.recorded"]["data"]["result"] == "DENIED"
    assert by_type["intent.revoked"]["data"]["by"] == "Analyst (auto-confirmed in v0)"
    assert by_type["escrow.refunded"]["data"]["to"] == "payer_rhone"
    assert by_type["payment.stopped"]["data"]["headline"] == "Payment stopped. EUR 85,000 returned to Rhône Cosmétiques."
    assert core.orchestrator.payment_view(payment_id)["chainStatus"] == "REVOKED"
    # the escrowed money went back to the payer treasury, not to the beneficiary
    chain, signer = core.ports.chain, core.signer
    assert chain.balance_of(signer.addresses.beneficiary) == 0 and chain.balance_of(chain.ESCROW) == 0

    result = await core.orchestrator.attack("release_revoked", payment_id)
    assert result == {"ok": True, "reverted": True, "reason": "PaymentNotReleasable"}
    events = _check(core)
    assert _types(core) == DIVERTED + DENY + ATTACK
    reverted = events[-1]["data"]
    assert (reverted["function"], reverted["reason"]) == ("release", "PaymentNotReleasable")
    assert reverted["text"] == "Rejected by the smart contract: PaymentNotReleasable."
    assert chain.balance_of(signer.addresses.beneficiary) == 0  # the attack moved nothing


async def test_diverted_then_confirm(core):
    payment_id = core.orchestrator.start("diverted", auto=True, auto_answer="confirm")
    await core.orchestrator.wait_idle()
    events = _check(core)
    assert _types(core) == DIVERTED + CONFIRM
    by_type = {e["type"]: e for e in events}
    assert by_type["escrow.released"]["data"]["to"] == "vasp_gh"
    assert by_type["payment.credited"]["data"]["at"] == "mule_bank"
    assert events[-4]["data"] == {"hop": 2, "at": "vasp_gh"}  # the chain hop settles after the release
    view = core.orchestrator.payment_view(payment_id)
    assert (view["status"], view["chainStatus"]) == ("credited", "EXECUTED")
    assert core.ports.chain.balance_of(core.signer.addresses.beneficiary) == 85_000 * 10**6
    with pytest.raises(Conflict):  # the attack only makes sense on a revoked payment
        await core.orchestrator.attack("release_revoked", payment_id)


async def test_manual_supplier_answer_and_conflicts(core):
    orchestrator = core.orchestrator
    with pytest.raises(NotFound):
        orchestrator.start("nope")
    payment_id = orchestrator.start("diverted")  # auto is off: the scenario waits for the supplier
    with pytest.raises(Conflict):
        orchestrator.start("legit")  # a scenario is running
    with pytest.raises(Conflict):
        orchestrator.supplier_response(payment_id, "deny")  # not waiting for an answer yet
    with pytest.raises(NotFound):
        orchestrator.supplier_response("PAY-0000", "deny")
    await _until(lambda: orchestrator.payments[payment_id].status == "awaiting_supplier")
    assert _types(core) == DIVERTED and orchestrator.running
    # nothing is released while nobody answers: the registry is COMMITTED and the money sits in escrow
    assert core.ports.chain.status(payment_id_bytes(payment_id)) == Status.COMMITTED
    assert core.ports.chain.balance_of(core.ports.chain.ESCROW) == 85_000 * 10**6
    orchestrator.supplier_response(payment_id, "deny")
    with pytest.raises(Conflict):
        orchestrator.supplier_response(payment_id, "confirm")  # only one answer counts
    await orchestrator.wait_idle()
    assert _types(core) == DIVERTED + DENY
    with pytest.raises(NotFound):
        await orchestrator.attack("no_such_attack", payment_id)


async def test_reset_and_rerun(core):
    orchestrator = core.orchestrator
    orchestrator.start("diverted")
    await _until(lambda: len(core.bus.events()) >= 3)
    await orchestrator.reset()
    events = core.bus.events()
    assert [e["type"] for e in events] == ["session.reset"] and events[0]["paymentId"] is None
    assert events[0]["seq"] == core.bus.last_seq > 1  # seq never restarts
    assert not orchestrator.running and orchestrator.payments == {}
    # the same demo payment can be run again, to the end
    orchestrator.start("diverted", auto=True, auto_answer="confirm")
    await orchestrator.wait_idle()
    assert [e["type"] for e in core.bus.events()] == ["session.reset"] + DIVERTED + CONFIRM
    orchestrator.start("diverted", auto=True)
    await orchestrator.wait_idle()
    assert [e["type"] for e in core.bus.events()][-4:] == DENY


async def test_mode_event_is_seq_zero_and_not_stored(core):
    mode = core.bus.mode_event()
    validate_event(mode)
    assert (mode["seq"], mode["id"], mode["type"]) == (0, "evt-000000", "system.mode")
    assert mode["data"] == {"risk": "rules", "chain": "mock", "llm": "off", "rails": "simulated", "degraded": []}
    assert core.bus.events() == []


def test_recorded_fixtures_are_up_to_date():
    assert record_fixtures.main(["--check"]) == 0
