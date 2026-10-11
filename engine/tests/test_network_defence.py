"""v2: mule wave and regional circuit breaker, rail outage, kill switch, degraded mode, guardian incidents."""

import json
import sys
from datetime import datetime, timedelta, timezone

import pytest

from sylo_spec.models import Cluster, RiskResult, Status, Tier, WindowPayment
from sylo_spec.ports import ClusterPort

from sylo import texts
from sylo.breakers import BreakerError, Breakers, apply_breaker, apply_degraded
from sylo.clusters import SampleClusterPort, cluster_sample
from sylo.orchestrator import ActionNotAllowed, NotWaiting, UnknownBreaker, UnknownRoute

from .conftest import LEGIT_SEQUENCE, events_of, make_orchestrator, types, until

DIVERTED = "PAY-2026-0002"
NOW = datetime(2026, 10, 11, 9, 0, 0, tzinfo=timezone.utc)
WAVE_SEQUENCE = ["scenario.started", "traffic.sample", "traffic.sample", "traffic.sample", "cluster.detected", "breaker.on"]


def risk(score, tier, **kw):
    return RiskResult(score=score, tier=tier, floor_tier=Tier.LOW, rules_fired=[], reasons=[], model="rules-v0", **kw)


def cluster():
    return Cluster.model_validate(cluster_sample())


def valid(orchestrator, validator):
    for event in orchestrator.bus.events:
        errors = list(validator.iter_errors(event))
        assert not errors, f"{event['type']}: {errors[0].message}"


# --- circuit breaker ---------------------------------------------------------------------------


def test_a_breaker_is_proposed_confirmed_for_24_hours_and_only_lifted_by_a_person():
    breakers = Breakers()
    breaker = breakers.propose(cluster(), "FR-GH")
    assert breaker.status == "proposed" and breakers.propose(cluster(), "FR-GH") is breaker
    assert breakers.active_for("mule_bank", "FR-GH") is None, "a proposal changes nothing"
    breakers.confirm(breaker.id, "Julien", NOW)
    assert breaker.expires_at == NOW + timedelta(hours=24)
    assert breakers.active_for("mule_bank", "FR-GH") is breaker
    assert breakers.active_for("bank_gh", "FR-GH") is None and breakers.active_for("mule_bank", "NG-GH") is None
    with pytest.raises(BreakerError):
        breakers.confirm(breaker.id, "Julien", NOW)
    assert breakers.expire(NOW + timedelta(hours=23)) == []
    assert breakers.expire(NOW + timedelta(hours=25)) == [breaker] and breaker.status == "off"
    with pytest.raises(BreakerError):
        breakers.lift(breaker.id)
    with pytest.raises(KeyError):
        breakers.confirm("CB-unknown", "Julien", NOW)


def test_the_breaker_makes_a_payment_at_least_medium_and_reads_the_bands_20_points_lower():
    breakers = Breakers()
    breaker = breakers.confirm(breakers.propose(cluster(), "FR-GH").id, "Julien", NOW)
    low = apply_breaker(risk(10, Tier.LOW), breaker)
    assert (low.tier, low.score, low.floor_tier, low.rules_fired) == (Tier.MEDIUM, 10, Tier.MEDIUM, ["R-CB-01"])
    assert low.reasons[-1].rule_id == "R-CB-01" and "Volta Region" in low.reasons[-1].text
    assert apply_breaker(risk(55, Tier.MEDIUM), breaker).tier == Tier.HIGH
    assert apply_breaker(risk(75, Tier.HIGH), breaker).tier == Tier.CRITICAL
    assert apply_breaker(risk(95, Tier.CRITICAL), breaker).tier == Tier.CRITICAL, "never less strict"


def test_degraded_mode_only_tightens_payments_to_accounts_that_are_not_on_file():
    assert apply_degraded(risk(10, Tier.LOW), [], known_account=False).tier == Tier.LOW
    assert apply_degraded(risk(10, Tier.LOW), ["chain"], known_account=True).tier == Tier.LOW
    tightened = apply_degraded(risk(10, Tier.LOW), ["chain", "llm"], known_account=False)
    assert tightened.tier == Tier.MEDIUM and tightened.rules_fired == ["R-DG-01"] and "chain, llm" in tightened.reasons[-1].text
    assert apply_degraded(risk(80, Tier.HIGH), ["chain"], known_account=False).rules_fired == []


def test_the_stub_detector_is_a_cluster_port_and_needs_three_linked_payments():
    port = SampleClusterPort()
    assert isinstance(port, ClusterPort)

    def window(*accounts):
        return [
            WindowPayment(payment_id=f"P{i}", account_id=a, institution_id="mule_bank", amount_eur=1000, at="2026-10-11T09:00:00.000Z")
            for i, a in enumerate(accounts)
        ]

    assert port.detect(window("acc-aflao-02", "acc-aflao-04")) == []
    assert port.detect(window("acc-aflao-02", "acc-aflao-04", "acc-ssx-nominated")) == []
    found = port.detect(window("acc-aflao-02", "acc-ssx-nominated", "acc-aflao-04", "acc-mensah-aflao"))
    assert [c.cluster_id for c in found] == ["CL-AFLAO-01"] and found[0].linked_payments == ["P0", "P2", "P3"]


async def test_scene_3_three_linked_payments_propose_a_breaker_and_the_next_payment_is_held(event_validator):
    orchestrator = make_orchestrator()
    await orchestrator.run_wave()
    assert types(orchestrator) == WAVE_SEQUENCE
    detected = events_of(orchestrator, "cluster.detected")[0]["data"]
    assert (detected["accounts"], detected["agents"], detected["region"]) == (6, 3, "GH-TV")
    assert detected["linkedPayments"] == ["PAY-2026-0101", "PAY-2026-0102", "PAY-2026-0103"]
    assert detected["proposedBreaker"]["breakerId"] == "CB-CL-AFLAO-01" and detected["detector"] == "cluster-sample"
    on = events_of(orchestrator, "breaker.on")[0]["data"]
    assert on["thresholdsDelta"] == -20 and on["scope"] == detected["proposedBreaker"]["scope"]
    assert on["scope"]["institutions"] == ["mule_bank"] and on["expiresAt"].startswith("2026-10-12T09:00")
    seen = events_of(orchestrator, "traffic.sample")
    assert [e["paymentId"] for e in seen] == detected["linkedPayments"] and all(e["data"]["wave"] for e in seen)
    assert seen[0]["data"]["arcs"] == [{"from": "bank_fr", "to": "mule_bank", "kind": "bank"}]
    assert not events_of(orchestrator, "payment.created"), "the wave is traffic the engine sees, not payments it routes"

    run = await orchestrator.run_to_end("diverted", auto_answer="deny")
    scored = events_of(orchestrator, "risk.scored")[0]["data"]
    assert scored["tier"] == "HIGH" and scored["score"] == 64 and scored["rulesFired"][-1] == "R-CB-01"
    assert run.intent.tier == Tier.MEDIUM and events_of(orchestrator, "payment.held")[0]["data"]["reasons"][-1]["ruleId"] == "R-CB-01"
    assert run.status == "stopped" and "escrow.refunded" in types(orchestrator)
    valid(orchestrator, event_validator)


async def test_the_breaker_does_not_touch_a_payment_to_another_region():
    orchestrator = make_orchestrator()
    await orchestrator.run_wave()
    run = await orchestrator.run_to_end("legit")
    assert run.tier == Tier.LOW and run.decision.route.id == "R3" and run.risk.rules_fired == []


async def test_without_auto_the_breaker_waits_for_the_analyst_and_can_be_lifted():
    orchestrator = make_orchestrator(human_steps="manual")
    await orchestrator.run_wave(auto=False)
    assert types(orchestrator) == WAVE_SEQUENCE[:-1], "proposed, not switched on"
    assert (await orchestrator.run_to_end("diverted", auto_answer="deny")).tier == Tier.MEDIUM

    result = orchestrator.confirm_breaker("CB-CL-AFLAO-01")
    assert result["ok"] and events_of(orchestrator, "breaker.on")[0]["data"]["confirmedBy"] == "Julien (fraud analyst)"
    with pytest.raises(ActionNotAllowed):
        orchestrator.confirm_breaker("CB-CL-AFLAO-01")
    with pytest.raises(UnknownBreaker):
        orchestrator.confirm_breaker("CB-nope")
    assert (await orchestrator.run_to_end("diverted", auto_answer="deny")).tier == Tier.HIGH

    assert orchestrator.lift_breaker("CB-CL-AFLAO-01")["ok"]
    assert events_of(orchestrator, "breaker.off")[0]["data"] == {
        "breakerId": "CB-CL-AFLAO-01",
        "reason": "LIFTED",
        "by": "Julien (fraud analyst)",
    }
    assert (await orchestrator.run_to_end("diverted", auto_answer="deny")).tier == Tier.MEDIUM
    with pytest.raises(ActionNotAllowed):
        orchestrator.lift_breaker("CB-CL-AFLAO-01")


async def test_the_breaker_expires_after_24_hours():
    orchestrator = make_orchestrator()
    await orchestrator.run_wave()
    orchestrator.breakers.get("CB-CL-AFLAO-01").expires_at = NOW - timedelta(seconds=1)
    run = await orchestrator.run_to_end("diverted", auto_answer="deny")
    assert run.tier == Tier.MEDIUM
    assert events_of(orchestrator, "breaker.off")[0]["data"] == {"breakerId": "CB-CL-AFLAO-01", "reason": "EXPIRED"}


async def test_the_diverted_payment_and_two_others_within_the_hour_make_the_cluster():
    orchestrator = make_orchestrator()
    await orchestrator.run_to_end("diverted", auto_answer="deny")
    await orchestrator.run_to_end("diverted", auto_answer="deny")  # the same payment again counts once
    await orchestrator.run_wave()
    detected = events_of(orchestrator, "cluster.detected")
    assert len(detected) == 1 and detected[0]["data"]["linkedPayments"] == [DIVERTED, "PAY-2026-0101", "PAY-2026-0102"]
    third = [e["seq"] for e in events_of(orchestrator, "traffic.sample") if e["paymentId"] == "PAY-2026-0103"]
    assert detected[0]["seq"] < third[0], "found after the second of the other payments"


# --- rail outage -------------------------------------------------------------------------------


async def test_scene_5_the_rail_goes_down_the_payment_is_rerouted_and_the_rail_comes_back(event_validator):
    orchestrator = make_orchestrator()
    run = await orchestrator.run_to_end("outage")
    sequence = types(orchestrator)
    assert sequence[:2] == ["scenario.started", "rail.down"] and sequence[-2:] == ["payment.credited", "rail.up"]
    assert [t for t in sequence if not t.startswith("rail.")] == LEGIT_SEQUENCE[:-12] + ["leg.sent", "leg.settled"] * 4 + ["intent.executed", "payment.credited"]
    selected = events_of(orchestrator, "route.selected")[0]["data"]
    assert (selected["routeId"], selected["tier"], selected["settlement"]) == ("R1", "LOW", "DIRECT")
    assert {"routeId": "R3", "s": 855.81, "excludedBy": "RAIL_DOWN"}.items() <= next(
        score for score in selected["scores"] if score["routeId"] == "R3"
    ).items()
    assert run.tier == Tier.LOW and run.status == "credited"
    assert orchestrator.rails.adapter("R3").available
    assert (await orchestrator.run_to_end("legit")).decision.route.id == "R3"
    valid(orchestrator, event_validator)


async def test_rails_can_be_taken_down_and_up_by_hand():
    orchestrator = make_orchestrator()
    assert orchestrator.rail_down("R3", "maintenance") == {"ok": True, "routeId": "R3", "available": False}
    assert events_of(orchestrator, "rail.down")[0]["data"] == {
        "routeId": "R3",
        "name": "Euro stablecoin on Avalanche",
        "reason": "maintenance",
    }
    assert (await orchestrator.run_to_end("legit")).decision.route.id == "R1"
    assert orchestrator.rail_up("R3")["available"] is True
    assert (await orchestrator.run_to_end("legit")).decision.route.id == "R3"
    with pytest.raises(UnknownRoute):
        orchestrator.rail_down("R9")
    orchestrator.rail_down("R1")
    await orchestrator.reset()
    assert all(adapter.available for adapter in orchestrator.rails), "a reset starts a clean session"


async def test_with_every_conditional_rail_down_a_medium_payment_is_not_sent():
    orchestrator = make_orchestrator()
    orchestrator.rail_down("R3")
    orchestrator.rail_down("R1")
    run = await orchestrator.run_to_end("diverted")
    assert run.status == "stopped" and run.intent is None
    stopped = events_of(orchestrator, "payment.stopped")[0]["data"]
    assert "R1, R3 unavailable" in stopped["detail"]


# --- kill switch -------------------------------------------------------------------------------


async def test_two_changed_legs_cut_the_adapter_and_later_payments_avoid_it(event_validator):
    orchestrator = make_orchestrator()
    await orchestrator.run_to_end("diverted", auto_answer="deny")
    first = await orchestrator.attack("swap_beneficiary", DIVERTED)
    assert first["legRejected"] == "INTENT_HASH_MISMATCH" and not events_of(orchestrator, "killswitch.on")
    await orchestrator.attack("swap_beneficiary", DIVERTED)
    cut = events_of(orchestrator, "killswitch.on")
    assert len(cut) == 1 and cut[0]["data"]["adapter"] == "R3" and cut[0]["data"]["refusals"] == 2
    assert cut[0]["data"]["revoked"] == [] and not orchestrator.rails.adapter("R3").available
    third = await orchestrator.attack("swap_beneficiary", DIVERTED)
    assert third["legRejected"] == "KILL_SWITCH" and len(events_of(orchestrator, "killswitch.on")) == 1

    run = await orchestrator.run_to_end("legit")
    selected = events_of(orchestrator, "route.selected")[-1]["data"]
    assert run.decision.route.id == "R1" and {"routeId": "R3", "s": 855.81, "excludedBy": "KILL_SWITCH"}.items() <= next(
        score for score in selected["scores"] if score["routeId"] == "R3"
    ).items()
    assert "its adapter was cut by the kill switch" in selected["reason"]
    orchestrator.rail_up("R3")
    assert (await orchestrator.run_to_end("legit")).decision.route.id == "R3"
    valid(orchestrator, event_validator)


async def test_the_kill_switch_revokes_the_payment_held_on_that_route(event_validator):
    orchestrator = make_orchestrator()
    orchestrator.start("diverted", auto=False)
    run = await until(orchestrator, DIVERTED, "awaiting_supplier")
    await orchestrator.attack("swap_beneficiary", DIVERTED)
    await orchestrator.attack("swap_beneficiary", DIVERTED)
    await orchestrator._task
    assert events_of(orchestrator, "killswitch.on")[0]["data"]["revoked"] == [DIVERTED]
    revoked = events_of(orchestrator, "intent.revoked")[0]["data"]
    assert (revoked["reasonCode"], revoked["by"]) == ("KILL_SWITCH", "Kill switch (automatic)")
    assert not events_of(orchestrator, "case.action") and events_of(orchestrator, "escrow.refunded")
    assert run.status == "stopped" and orchestrator.chain.status(run.chain_pid) == Status.REVOKED
    assert events_of(orchestrator, "payment.stopped")[0]["data"]["detail"] == texts.STOPPED_DETAIL_KILL
    valid(orchestrator, event_validator)


async def test_a_single_refusal_or_refusals_ten_minutes_apart_do_not_cut_the_adapter():
    orchestrator = make_orchestrator()
    run = await orchestrator.run_to_end("diverted", auto_answer="deny")
    await orchestrator.attack("swap_beneficiary", DIVERTED)
    await run.pacer.wait(601_000)
    await orchestrator.attack("swap_beneficiary", DIVERTED)
    assert not events_of(orchestrator, "killswitch.on") and orchestrator.rails.adapter("R3").available


# --- degraded mode and guardian incidents ------------------------------------------------------


async def test_a_missing_dependency_shows_in_the_mode_and_leaves_known_payees_alone(monkeypatch):
    monkeypatch.setitem(sys.modules, "sylo_risk", None)
    monkeypatch.setitem(sys.modules, "sylo_risk.case", None)
    orchestrator = make_orchestrator(llm_mode="cached")
    assert orchestrator.mode()["degraded"] == ["llm"]
    run = await orchestrator.run_to_end("legit")
    assert run.tier == Tier.LOW and types(orchestrator) == LEGIT_SEQUENCE


async def test_a_guardian_incident_is_shown_drafted_for_dora_and_freezes_the_payment(tmp_path, event_validator):
    orchestrator = make_orchestrator(journal_path=str(tmp_path / "log.jsonl"))
    orchestrator.start("diverted", auto=False)
    run = await until(orchestrator, DIVERTED, "awaiting_supplier")
    orchestrator.chain.freeze(run.chain_pid)  # what the guardian does on-chain before it reports
    result = orchestrator.guardian_incident(
        {"rule": "CONFIRMED_WITHOUT_OOB_RECORD", "action": "FREEZE_AND_PAUSE", "txHash": "0x" + "ab" * 32, "paymentId": DIVERTED}
    )
    incident = events_of(orchestrator, "guardian.incident")[0]
    assert incident["paymentId"] == DIVERTED and incident["data"]["incidentId"] == result["incidentId"] == "INC-20261011-001"
    assert incident["data"]["dora"] == {
        "clientsAffected": 1,
        "amountEur": 85000.0,
        "durationMinutes": 0.0,
        "geographicSpread": ["FR", "GH"],
        "criticality": "Payment execution (critical function)",
        "thirdParties": ["Avalanche RPC providers"],
        "major": False,
        "draft": True,
    }
    draft = json.loads((tmp_path / "incidents" / "INC-20261011-001.json").read_text(encoding="utf-8"))
    assert draft["status"] == "DRAFT, not filed" and draft["paymentId"] == DIVERTED and draft["dora"]["draft"] is True

    assert run.frozen and run.incident_id == "INC-20261011-001"
    # The corridor is paused, so its escrow route is closed until a person reopens it.
    assert events_of(orchestrator, "rail.down")[0]["data"]["routeId"] == "R3" and not orchestrator.rails.adapter("R3").available
    await orchestrator._task  # the supplier is no longer waited for: the analyst (played by the engine here) revokes
    assert run.status == "stopped" and not events_of(orchestrator, "escrow.released")
    assert events_of(orchestrator, "intent.revoked")[0]["data"]["reasonCode"] == "ANALYST_DECISION"
    assert events_of(orchestrator, "escrow.refunded") and orchestrator.chain.status(run.chain_pid) == Status.REVOKED
    with pytest.raises(NotWaiting):
        orchestrator.supplier_response(DIVERTED, "confirm")
    valid(orchestrator, event_validator)


def test_a_guardian_incident_without_a_known_payment_is_still_recorded():
    orchestrator = make_orchestrator()
    result = orchestrator.guardian_incident({"rule": "UNKNOWN_CALLER", "action": "PAUSE_CORRIDOR", "incidentId": "INC-7", "amountEur": 12.5})
    assert result == {"ok": True, "incidentId": "INC-7"}
    event = events_of(orchestrator, "guardian.incident")[0]
    assert event["paymentId"] is None and event["data"]["txHash"] is None and event["data"]["dora"]["clientsAffected"] == 0
    assert event["data"]["dora"]["amountEur"] == 12.5 and orchestrator.incidents[0]["incidentId"] == "INC-7"
