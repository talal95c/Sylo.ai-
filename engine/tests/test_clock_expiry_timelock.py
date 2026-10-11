"""Demo clock (PRD P1-9), hold expiry with automatic refund, time-lock on a first payment to a new account,
and the payer's limits on a reroute (PRD §11.3, §12.3)."""

import pytest

from sylo_spec.models import Status, Tier
from sylo_spec.scenarios import LEGIT_ORDER

from sylo import texts
from sylo.norms import NormsEngine
from sylo.orchestrator import NotWaiting
from sylo.router import PAYER_LIMIT, RerouteLimits, choose_route

from .conftest import events_of, make_orchestrator, types, until

DIVERTED = "PAY-2026-0002"
LEGIT = "PAY-2026-0001"


def valid(orchestrator, validator):
    for event in orchestrator.bus.events:
        errors = list(validator.iter_errors(event))
        assert not errors, f"{event['type']}: {errors[0].message}"


async def held(orchestrator):
    orchestrator.start("diverted", auto=False)
    if orchestrator.settings.human_steps == "manual":
        await until(orchestrator, DIVERTED, "awaiting_approval")
        for approver in ("claire", "marc"):
            orchestrator.approve(DIVERTED, approver)
    return await until(orchestrator, DIVERTED, "awaiting_supplier")


# --- hold expiry -----------------------------------------------------------------------------


async def test_a_hold_nobody_answers_expires_and_refunds_the_payer(event_validator):
    orchestrator = make_orchestrator()
    run = await orchestrator.run_to_end("diverted_expiry")
    sequence = types(orchestrator)
    assert sequence[sequence.index("clock.advanced") :] == [
        "clock.advanced",
        "intent.revoked",
        "escrow.refunded",
        "alert.raised",
        "payment.stopped",
    ]
    revoked = events_of(orchestrator, "intent.revoked")[0]["data"]
    assert revoked["reasonCode"] == "EXPIRED" and revoked["by"] == texts.EXPIRY_BY
    assert run.status == "stopped" and run.hold is None and orchestrator.chain.status(run.chain_pid) == Status.REVOKED
    assert events_of(orchestrator, "payment.stopped")[0]["data"]["detail"] == texts.STOPPED_DETAIL_EXPIRED
    # Silence is not proof of fraud: no analyst action is claimed and the other bank is not asked to freeze.
    assert not events_of(orchestrator, "case.action")
    assert [e["data"]["audience"] for e in events_of(orchestrator, "alert.raised")] == ["payer", "payer"]
    assert events_of(orchestrator, "clock.advanced")[0]["data"]["hours"] == 24
    valid(orchestrator, event_validator)


async def test_the_demo_clock_expires_a_waiting_hold_only_once_its_time_has_passed():
    orchestrator = make_orchestrator()
    run = await held(orchestrator)
    orchestrator.advance_clock(23)
    assert run.status == "awaiting_supplier" and not run.expiry.done()
    answer = orchestrator.advance_clock(2)
    assert answer["ok"] and answer["now"].startswith("2026-10-12T10:")
    await orchestrator._task
    assert run.status == "stopped" and events_of(orchestrator, "intent.revoked")[0]["data"]["reasonCode"] == "EXPIRED"
    with pytest.raises(NotWaiting):
        orchestrator.supplier_response(DIVERTED, "confirm")


async def test_an_answer_that_arrives_after_the_expiry_cannot_release_the_hold():
    orchestrator = make_orchestrator()
    run = await held(orchestrator)
    orchestrator.advance_clock(25)
    orchestrator.supplier_response(DIVERTED, "confirm")  # accepted by the API a moment before the script wakes up
    await orchestrator._task
    assert run.status == "stopped" and not events_of(orchestrator, "escrow.released")
    assert not events_of(orchestrator, "verification.recorded") and len(events_of(orchestrator, "escrow.refunded")) == 1


async def test_a_denied_payment_the_analyst_never_handles_is_refunded_at_expiry():
    orchestrator = make_orchestrator(human_steps="manual")
    run = await held(orchestrator)
    orchestrator.supplier_response(DIVERTED, "deny")
    await until(orchestrator, DIVERTED, "awaiting_analyst")
    orchestrator.advance_clock(25)
    await orchestrator._task
    assert run.status == "stopped" and orchestrator.chain.status(run.chain_pid) == Status.REVOKED
    assert events_of(orchestrator, "intent.revoked")[0]["data"]["reasonCode"] == "EXPIRED"


async def test_the_demo_clock_also_ends_a_circuit_breaker():
    orchestrator = make_orchestrator()
    await orchestrator.run_wave()
    assert events_of(orchestrator, "breaker.on")
    orchestrator.advance_clock(25)
    off = events_of(orchestrator, "breaker.off")[0]["data"]
    assert off["reason"] == "EXPIRED"
    run = await orchestrator.run_to_end("diverted")
    assert "R-CB-01" not in run.risk.rules_fired


async def test_a_new_session_starts_from_the_real_time_again():
    orchestrator = make_orchestrator()
    orchestrator.advance_clock(48)
    await orchestrator.reset()
    assert orchestrator._clock_offset.total_seconds() == 0


# --- time-lock -------------------------------------------------------------------------------


async def test_a_confirmed_first_payment_to_a_new_account_waits_for_its_time_lock_at_the_bank(event_validator):
    orchestrator = make_orchestrator()
    run = await orchestrator.run_to_end("diverted_timelock", auto_answer="confirm")
    assert run.decision.route.id == "R1" and run.status == "credited"
    lock = events_of(orchestrator, "timelock.on")[0]["data"]
    assert lock["hours"] == 24 and lock["until"].startswith("2026-10-12T09:00") and "24 h" in lock["text"]
    sequence = types(orchestrator)
    after = sequence[sequence.index("verification.recorded") :]
    assert after[:4] == ["verification.recorded", "timelock.on", "clock.advanced", "timelock.off"]
    assert sequence.index("timelock.off") < sequence.index("payment.credited")
    valid(orchestrator, event_validator)


async def test_the_lock_holds_until_the_clock_reaches_it():
    orchestrator = make_orchestrator()
    orchestrator.rail_down("R3")
    run = await held(orchestrator)
    orchestrator.supplier_response(DIVERTED, "confirm")
    await until(orchestrator, DIVERTED, "time_locked")
    info = await orchestrator.payment_info(DIVERTED)
    assert info["lockedUntil"] == events_of(orchestrator, "timelock.on")[0]["data"]["until"] and info["hold"] == "bank"
    orchestrator.advance_clock(10)
    assert run.status == "time_locked" and not events_of(orchestrator, "timelock.off")
    orchestrator.advance_clock(15)
    await orchestrator._task
    assert run.status == "credited" and events_of(orchestrator, "timelock.off")[0]["data"] == {"reason": "ELAPSED"}


async def test_the_analyst_can_still_stop_a_payment_during_its_time_lock():
    orchestrator = make_orchestrator(human_steps="manual")
    orchestrator.rail_down("R3")
    run = await held(orchestrator)
    orchestrator.supplier_response(DIVERTED, "confirm")
    await until(orchestrator, DIVERTED, "time_locked")
    await orchestrator.case_action(DIVERTED, "CONFIRM_REVOCATION")
    await orchestrator._task
    assert run.status == "stopped" and not events_of(orchestrator, "payment.credited")
    assert events_of(orchestrator, "intent.revoked")[0]["data"]["reasonCode"] == "ANALYST_DECISION"


async def test_the_lock_follows_the_amount_bands_and_the_escrow_stands_in_for_it():
    four_hours = make_orchestrator(time_lock_long_from_eur=100_000)
    await four_hours.run_to_end("diverted_timelock", auto_answer="confirm")
    assert events_of(four_hours, "timelock.on")[0]["data"]["hours"] == 4

    none = make_orchestrator(time_lock_from_eur=100_000, time_lock_long_from_eur=200_000)
    run = await none.run_to_end("diverted_timelock", auto_answer="confirm")
    assert run.status == "credited" and not events_of(none, "timelock.on")

    escrow = make_orchestrator()
    run = await escrow.run_to_end("diverted", auto_answer="confirm")
    assert run.decision.route.id == "R3" and run.status == "credited" and not events_of(escrow, "timelock.on")


# --- payer limits on a reroute ---------------------------------------------------------------

NORMS = NormsEngine()
MODEL = NORMS.pack.route_model
LIMITS = RerouteLimits(max_fees_eur=500, max_days=3)


def route(unavailable=None, limits=LIMITS, tier=Tier.LOW):
    return choose_route(NORMS.evaluate(LEGIT_ORDER), tier, 85_000.0, MODEL, unavailable=unavailable, limits=limits)


def excluded(decision):
    return {score["routeId"]: score["excludedBy"] for score in decision.scores}


def test_limits_do_not_apply_while_the_usual_route_is_available():
    decision = route(limits=RerouteLimits(max_fees_eur=100, max_days=0.01))
    assert decision.route.id == "R3" and excluded(decision)["R2"] is None


def test_a_reroute_keeps_to_the_fees_and_delay_the_payer_accepts():
    decision = route({"R3": "RAIL_DOWN"})
    assert decision.route.id == "R1" and excluded(decision) == {
        "R1": None,
        "R2": PAYER_LIMIT,  # EUR 935 of fees is above the limit
        "R3": "RAIL_DOWN",
        "R4": "GH_FX_EXPORT_PROCEEDS_NOMINATED_BANK",
    }
    slow = route({"R3": "RAIL_DOWN"}, RerouteLimits(max_fees_eur=1_000, max_days=1))
    assert slow.route.id == "R2" and excluded(slow)["R1"] == PAYER_LIMIT  # SWIFT takes two days


def test_without_a_replacement_within_the_limits_the_payment_waits():
    decision = route({"R3": "RAIL_DOWN", "R1": "KILL_SWITCH"})
    assert decision.route is None and decision.blocked_by == PAYER_LIMIT
    assert "R2" in decision.reason and "€500" in decision.reason
    assert route({"R3": "RAIL_DOWN", "R1": "KILL_SWITCH"}, limits=None).route.id == "R2"
    assert route({"R1": "RAIL_DOWN", "R2": "RAIL_DOWN", "R3": "RAIL_DOWN"}).blocked_by == "RAILS"
    assert route(tier=Tier.HIGH).blocked_by == "TIER"


async def test_a_payment_with_no_replacement_within_the_limits_is_not_sent_and_is_not_a_fraud_case(event_validator):
    orchestrator = make_orchestrator()
    orchestrator.rail_down("R3")
    orchestrator.rail_down("R1")
    run = await orchestrator.run_to_end("legit")
    stopped = events_of(orchestrator, "payment.stopped")[0]["data"]
    assert stopped["headline"] == texts.NO_ROUTE_LIMITS_HEADLINE and stopped["blockedBy"] == PAYER_LIMIT
    assert run.status == "stopped" and run.tier == Tier.LOW
    assert not events_of(orchestrator, "case.ready") and not events_of(orchestrator, "intent.committed")
    alert = events_of(orchestrator, "alert.raised")[0]["data"]
    assert (alert["audience"], alert["channel"]) == ("payer", "IN_APP")
    valid(orchestrator, event_validator)

    generous = make_orchestrator(reroute_max_fees_eur=1_000)
    generous.rail_down("R3")
    generous.rail_down("R1")
    paid = await generous.run_to_end("legit")
    assert paid.decision.route.id == "R2" and paid.status == "credited"
