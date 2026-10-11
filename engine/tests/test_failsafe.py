"""Fail-safe behaviour: alerts never use e-mail, a failing chain releases nothing, a bank hold replaces the escrow."""

from sylo_spec.models import Status

from sylo import texts

from .conftest import DECISION, APPROVAL, events_of, make_orchestrator, types


async def test_no_alert_is_ever_sent_by_email():
    orchestrator = make_orchestrator()
    await orchestrator.run_to_end("diverted", auto_answer="deny")
    alerts = [e["data"] for e in events_of(orchestrator, "alert.raised")]
    assert [(a["audience"], a["channel"]) for a in alerts] == [("payer", "IN_APP"), ("beneficiary_bank", "NETWORK"), ("payer", "SMS")]
    assert "EMAIL" not in texts.ALERT_CHANNELS and all(a["channel"] in texts.ALERT_CHANNELS for a in alerts)
    assert alerts[1]["to"] == "mule_bank" and alerts[1]["uetr"] == "4b8e6d21-7c3a-4f59-9e12-a5d0c3b7f802"
    assert alerts[2]["text"] == "Payment stopped: the supplier did not confirm the new account. Funds returned."


class _FailingAt:
    """Wraps a chain port and makes one method fail like a dead RPC endpoint (not a revert)."""

    def __init__(self, chain, method):
        self._chain, self._method = chain, method

    def __getattr__(self, name):
        if name == self._method:
            def dead(*args, **kwargs):
                raise ConnectionError("RPC endpoint unreachable")

            return dead
        return getattr(self._chain, name)


async def test_a_dead_chain_before_commit_stops_the_payment_and_turns_the_banner():
    orchestrator = make_orchestrator()
    orchestrator.chain = _FailingAt(orchestrator.chain, "commit")
    run = await orchestrator.run_to_end("legit")
    assert types(orchestrator) == DECISION + APPROVAL + ["system.mode", "alert.raised", "payment.stopped"]
    assert run.status == "stopped" and "chain" in orchestrator.mode()["degraded"]
    assert events_of(orchestrator, "system.mode")[0]["data"]["degraded"] == ["chain"]
    assert not events_of(orchestrator, "leg.sent"), "no money moves without a sealed intent"


async def test_a_dead_chain_during_the_hold_releases_nothing():
    orchestrator = make_orchestrator()
    real = orchestrator.chain
    orchestrator.chain = _FailingAt(real, "record_verification")
    run = await orchestrator.run_to_end("diverted", auto_answer="confirm")
    assert run.status == "held" and run.hold == "escrow"
    assert real.status(run.chain_pid) == Status.COMMITTED
    assert not events_of(orchestrator, "escrow.released") and not events_of(orchestrator, "payment.credited")
    alert = events_of(orchestrator, "alert.raised")[-1]["data"]
    assert alert["audience"] == "analyst" and alert["headline"] == texts.CHAIN_DOWN_HEADLINE


async def test_when_the_escrow_rail_is_down_a_medium_payment_is_held_at_the_bank(event_validator):
    orchestrator = make_orchestrator()
    orchestrator.rails.adapter("R3").down_reason = "maintenance"
    run = await orchestrator.run_to_end("diverted", auto_answer="deny")
    selected = events_of(orchestrator, "route.selected")[0]["data"]
    assert (selected["routeId"], selected["settlement"], selected["tier"]) == ("R1", "FIAT_HOLD", "MEDIUM")
    assert {"routeId": "R3", "s": 855.81, "excludedBy": "RAIL_DOWN"}.items() <= next(
        score for score in selected["scores"] if score["routeId"] == "R3"
    ).items()
    assert selected["reason"].endswith("R3 is not available: its rail is down.")
    held = events_of(orchestrator, "payment.held")[0]["data"]
    assert (held["at"], held["hop"]) == ("bank", 0) and "Banque Hexagone" in held["protection"]
    assert not events_of(orchestrator, "escrow.deposited") and not events_of(orchestrator, "escrow.refunded")
    assert run.status == "stopped" and orchestrator.chain.status(run.chain_pid) == Status.REVOKED
    assert [e["data"]["hop"] for e in events_of(orchestrator, "leg.sent")] == [0], "only the leg to the payer's own bank was sent"
    for event in orchestrator.bus.events:
        assert not list(event_validator.iter_errors(event)), event["type"]


async def test_a_bank_hold_continues_after_the_supplier_confirms():
    orchestrator = make_orchestrator()
    orchestrator.rails.adapter("R3").down_reason = "maintenance"
    run = await orchestrator.run_to_end("diverted", auto_answer="confirm")
    assert run.status == "credited" and orchestrator.chain.status(run.chain_pid) == Status.EXECUTED
    assert [e["data"]["hop"] for e in events_of(orchestrator, "leg.sent")] == [0, 1, 2]
    assert types(orchestrator)[-2:] == ["intent.executed", "payment.credited"]


async def test_a_rail_down_never_changes_the_tier_and_a_low_payment_is_rerouted():
    orchestrator = make_orchestrator()
    orchestrator.rails.adapter("R3").down_reason = "maintenance"
    run = await orchestrator.run_to_end("legit")
    assert run.tier.name == "LOW" and run.decision.route.id == "R1" and run.status == "credited"
