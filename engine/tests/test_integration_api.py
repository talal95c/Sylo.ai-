"""Integration surface of PRD §16.2: quote, payment, status leg by leg, cases, payee verification,
the attack console, and the rail adapters' webhook and reconciliation (§13.5)."""

from datetime import datetime

import pytest

from sylo_spec.models import Tier

from sylo.orchestrator import ActionNotAllowed, UnknownAction, UnknownPayee, UnknownQuote, UnknownScenario

from .conftest import events_of, make_orchestrator, types, until

LEGIT = "PAY-2026-0001"
DIVERTED = "PAY-2026-0002"
SUPPLIER = "payee-ssx"
MULE_ACCOUNT = "acc-mensah-aflao"


def parse(stamp):
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


# --- quotes and payments -----------------------------------------------------------------------


def test_a_quote_gives_the_decision_and_what_it_needs_without_committing_anything():
    orchestrator = make_orchestrator()
    quote = orchestrator.quote("legit")
    assert quote["quoteId"] == "Q-0001" and quote["executable"] and quote["paymentId"] == LEGIT
    assert 590 <= (parse(quote["validUntil"]) - orchestrator.now()).total_seconds() <= 600
    assert quote["route"]["chosen"] == "R3" and quote["route"]["settlement"] == "DIRECT" and quote["route"]["feesEur"] == 170.0
    assert quote["route"]["quoteValidUntil"] == quote["validUntil"]
    assert {c["routeId"]: c["excludedBy"] for c in quote["route"]["candidates"]}["R4"] == "GH_FX_EXPORT_PROCEEDS_NOMINATED_BANK"
    assert quote["risk"]["tier"] == "LOW" and quote["verifications"] == []
    assert quote["approval"]["method"] == "DUAL_CONTROL" and [a["id"] for a in quote["approval"]["required"]] == ["claire", "marc"]
    excluded = next(c for c in quote["normChecks"] if c["routeId"] == "R4" and c["result"] == "FAIL")
    assert "Act 723" in excluded["legalRef"] or "wallet" in excluded["legalRef"]
    assert [c["ruleId"] for c in quote["controls"]] == ["EU_VOP_SCOPE"] and len(quote["rails"]) == 4
    assert orchestrator.bus.events == [] and not orchestrator.running


def test_a_quote_for_the_diverted_order_asks_for_a_conditional_approval_and_the_out_of_band_check():
    quote = make_orchestrator().quote("diverted")
    assert quote["risk"]["tier"] == "MEDIUM" and "R-PV-01" in quote["risk"]["rulesFired"]
    assert quote["route"]["chosen"] == "R3" and quote["route"]["settlement"] == "ONCHAIN_ESCROW"
    assert quote["approval"]["conditional"] and quote["verifications"] == ["SIM_SWAP_CHECK", "OOB_KNOWN_CONTACT"]
    assert quote["route"]["priceOfSafetyEur"] == 0.0 and [s["code"] for s in quote["signals"]] == ["R1"]


def test_a_quote_can_price_another_amount_but_only_the_recorded_orders_run():
    orchestrator = make_orchestrator()
    small = orchestrator.quote("legit", "4000.00")
    assert not small["executable"] and small["approval"]["method"] == "SCA" and len(small["approval"]["required"]) == 1
    assert small["route"]["chosen"] == "R1"  # fixed fees weigh more on a small amount: SWIFT at 80 beats 170
    with pytest.raises(ActionNotAllowed):
        orchestrator.submit(quote_id=small["quoteId"])
    with pytest.raises(UnknownQuote):
        orchestrator.submit(quote_id="Q-9999")
    with pytest.raises(UnknownScenario):
        orchestrator.quote("nope")


async def test_executing_a_quote_runs_the_payment_and_an_idempotency_key_never_starts_two():
    orchestrator = make_orchestrator()
    quote = orchestrator.quote("legit")
    answer = orchestrator.submit(quote_id=quote["quoteId"], auto=True, idempotency_key="key-1")
    assert answer["paymentId"] == LEGIT and not answer["replayed"] and answer["decision"]["route"]["chosen"] == "R3"
    again = orchestrator.submit(quote_id=quote["quoteId"], auto=True, idempotency_key="key-1")
    assert again["replayed"] and again["paymentId"] == LEGIT
    await orchestrator._task
    assert types(orchestrator).count("payment.created") == 1 and types(orchestrator)[-1] == "payment.credited"


async def test_an_expired_quote_is_refused():
    orchestrator = make_orchestrator()
    quote = orchestrator.quote("legit")
    orchestrator.advance_clock(1)
    with pytest.raises(ActionNotAllowed, match="expired"):
        orchestrator.submit(quote_id=quote["quoteId"])
    assert not orchestrator.running


# --- status leg by leg, cases ------------------------------------------------------------------


async def test_the_status_is_given_leg_by_leg_and_a_payment_is_found_by_its_uetr():
    orchestrator = make_orchestrator()
    run = await orchestrator.run_to_end("legit")
    info = await orchestrator.payment_info(run.order.uetr)
    assert info["paymentId"] == LEGIT and info["uetr"] == run.order.uetr
    assert [leg["status"] for leg in info["legs"]] == ["settled"] * 5
    assert [leg["to"] for leg in info["legs"]] == ["bank_fr", "casp_eu", "vasp_gh", "bank_gh", "supplier_ssx"]
    assert all(leg["rail"] == "R3" and leg["idempotencyKey"] for leg in info["legs"])

    await orchestrator.run_to_end("diverted")
    await orchestrator.attack("swap_beneficiary", DIVERTED)
    legs = (await orchestrator.payment_info(DIVERTED))["legs"]
    assert [leg["status"] for leg in legs] == ["settled", "settled", "pending", "rejected"]
    assert legs[-1]["reason"] == "INTENT_HASH_MISMATCH"


async def test_the_case_queue_lists_what_the_analyst_can_do():
    orchestrator = make_orchestrator()
    await orchestrator.run_to_end("legit")
    assert orchestrator.cases() == []
    orchestrator.start("diverted", auto=False)
    await until(orchestrator, DIVERTED, "awaiting_supplier")
    (case,) = orchestrator.cases()
    assert case["paymentId"] == DIVERTED and case["tier"] == "MEDIUM" and case["hold"] == "escrow" and case["caseReady"]
    assert case["allowedActions"] == ["CONFIRM_REVOCATION", "FREEZE"] and case["holdExpiresAt"]
    await orchestrator.case_action(DIVERTED, "FREEZE")
    assert orchestrator.cases()[0]["allowedActions"] == ["CONFIRM_REVOCATION"] and orchestrator.cases()[0]["frozen"]
    await orchestrator.case_action(DIVERTED, "CONFIRM_REVOCATION")
    await orchestrator._task
    assert orchestrator.cases()[0]["allowedActions"] == [] and orchestrator.cases()[0]["status"] == "stopped"


# --- payee verification before any payment -----------------------------------------------------


async def test_an_account_the_supplier_denied_is_blocked_before_any_approval(event_validator):
    orchestrator = make_orchestrator()
    asked = orchestrator.start_payee_verification(SUPPLIER, MULE_ACCOUNT)
    assert asked["channel"] == "SMS" and asked["step"] == "REQUESTED" and asked["simSwapChecked"] and "2024-03-12" in asked["text"]
    recorded = orchestrator.record_payee_verification(SUPPLIER, MULE_ACCOUNT, "DENIED")
    assert recorded["result"] == "DENIED" and [e["data"]["step"] for e in events_of(orchestrator, "payee.verification")] == ["REQUESTED", "RECORDED"]

    run = await orchestrator.run_to_end("diverted")
    stopped = events_of(orchestrator, "payment.stopped")[0]["data"]
    assert run.status == "stopped" and stopped["blockedBy"] == "PAYEE_VERIFICATION_DENIED" and "not theirs" in stopped["detail"]
    kinds = types(orchestrator)
    assert "approval.required" not in kinds and "intent.committed" not in kinds and "leg.sent" not in kinds
    alert = events_of(orchestrator, "alert.raised")[0]["data"]
    assert (alert["audience"], alert["channel"]) == ("payer", "IN_APP")
    legit = await orchestrator.run_to_end("legit")
    assert legit.status == "credited"  # the nominated account is untouched
    for event in orchestrator.bus.events:
        errors = list(event_validator.iter_errors(event))
        assert not errors, f"{event['type']}: {errors[0].message}"


async def test_a_confirmed_account_is_no_longer_an_untrusted_source_but_stays_a_new_account():
    orchestrator = make_orchestrator()
    orchestrator.start_payee_verification(SUPPLIER, MULE_ACCOUNT)
    orchestrator.record_payee_verification(SUPPLIER, MULE_ACCOUNT, "CONFIRMED")
    assert "R-PV-01" not in orchestrator.quote("diverted")["risk"]["rulesFired"]
    run = await orchestrator.run_to_end("diverted", auto_answer="confirm")
    assert events_of(orchestrator, "payment.created")[0]["data"]["provenance"] == "verified_registry"
    assert "R-PV-01" not in run.risk.rules_fired and run.tier >= Tier.MEDIUM, "a new account is never LOW"
    assert events_of(orchestrator, "payment.held") and run.status == "credited"


def test_the_check_needs_a_trusted_contact_and_an_open_request():
    orchestrator = make_orchestrator()
    with pytest.raises(ActionNotAllowed, match="start one first"):
        orchestrator.record_payee_verification(SUPPLIER, MULE_ACCOUNT, "CONFIRMED")
    with pytest.raises(UnknownPayee):
        orchestrator.start_payee_verification("payee-nope", MULE_ACCOUNT)
    with pytest.raises(UnknownPayee):
        orchestrator.start_payee_verification(SUPPLIER, "acc-nope")
    orchestrator.telecom.declare_swap("+233 •• ••• 4471", hours_ago=5)
    asked = orchestrator.start_payee_verification(SUPPLIER, MULE_ACCOUNT)
    assert asked["channel"] == "ANALYST" and asked["simSwapRecent"] and "SIM" in asked["text"]
    with pytest.raises(ActionNotAllowed, match="analyst"):
        orchestrator.record_payee_verification(SUPPLIER, MULE_ACCOUNT, "CONFIRMED")


# --- attack console ----------------------------------------------------------------------------


async def test_the_attack_console_injects_outage_clock_and_a_sim_swap_for_the_next_check():
    orchestrator = make_orchestrator()
    assert (await orchestrator.sim_event("rail_down", {"routeId": "R3"}))["available"] is False
    assert (await orchestrator.sim_event("rail_up", {"routeId": "R3"}))["available"] is True
    assert (await orchestrator.sim_event("clock", {"advanceHours": 2}))["ok"]
    assert (await orchestrator.sim_event("sim_swap", {"hoursAgo": 3}))["appliesTo"] == "the next out-of-band check"
    await orchestrator.run_to_end("diverted")
    requested = events_of(orchestrator, "verification.requested")[0]["data"]
    assert requested["simSwapRecent"] and requested["channel"] == "ANALYST"
    await orchestrator.run_to_end("diverted")
    assert events_of(orchestrator, "verification.requested")[1]["data"]["channel"] == "SMS"  # injected once
    with pytest.raises(UnknownAction):
        await orchestrator.sim_event("meteor", {})


async def test_a_compromised_connector_is_cut_by_the_kill_switch():
    orchestrator = make_orchestrator()
    await orchestrator.run_to_end("diverted")
    answer = await orchestrator.sim_event("compromised_connector", {"paymentId": DIVERTED})
    assert answer["killSwitch"] and [a["legRejected"] for a in answer["attempts"]] == ["INTENT_HASH_MISMATCH"] * 2
    assert events_of(orchestrator, "killswitch.on")[0]["data"]["adapter"] == "R3"


# --- rail adapters: webhook and reconciliation -------------------------------------------------


async def test_a_webhook_only_moves_a_leg_the_adapter_sent_and_only_forward():
    orchestrator = make_orchestrator()
    orchestrator.start("diverted", auto=False)
    await until(orchestrator, DIVERTED, "awaiting_supplier")
    legs = (await orchestrator.payment_info(DIVERTED))["legs"]
    settled, pending = legs[0]["idempotencyKey"], legs[2]["idempotencyKey"]

    assert orchestrator.rail_webhook("R3", {"idempotencyKey": "made-up", "status": "SETTLED"}) == {
        "routeId": "R3", "accepted": False, "reason": "UNKNOWN_LEG",
    }
    assert orchestrator.rail_webhook("R3", {"idempotencyKey": pending, "status": "PAID"})["reason"] == "UNKNOWN_STATUS"
    assert orchestrator.rail_webhook("R3", {"idempotencyKey": settled, "status": "FAILED"})["reason"] == "FINAL_STATUS"
    assert orchestrator.rail_webhook("R3", {"idempotencyKey": settled, "status": "returned"}) == {
        "routeId": "R3", "accepted": True, "status": "RETURNED",
    }
    report = orchestrator.rail_reconcile("R3")
    assert report["legs"] == 3 and report["byStatus"] == {"PENDING": 1, "SETTLED": 1, "FAILED": 0, "RETURNED": 1}
    assert report["open"] == [pending] and report["toInvestigate"] == [settled] and report["simulated"]
    assert orchestrator.rail_reconcile("R1")["legs"] == 0
