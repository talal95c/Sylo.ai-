"""A payment typed by a user (POST /v1/quotes with ``payment``): the engine decides it and runs it."""

import asyncio
import json

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from sylo_spec.scenarios import ACCOUNTS

from sylo.payees import InvalidPayment, PaymentIn, ghana_banks, saved_payees

from .conftest import REPO_DIR, make_orchestrator

LOC = "LOC-GH-2026-0457"
SCHEMA = json.loads((REPO_DIR / "spec" / "events.schema.json").read_text(encoding="utf-8"))


def typed(**beneficiary):
    return {"name": "Tamale Grain Co", "accountHolder": "TAMALE GRAIN CO LTD", "accountNumber": "0099887766554",
            "bankId": "bank_gh_tamale", **beneficiary}


def payment(beneficiary, amount="42000", **fields):
    return PaymentIn.model_validate({"beneficiary": beneficiary, "amount": amount, "invoiceRef": "INV-2026-131", "locRef": LOC, **fields})


def run(orchestrator, quote, **kw):
    async def go():
        answer = orchestrator.submit(quote_id=quote["quoteId"], auto=True, speed=100, **kw)
        await orchestrator._task
        return answer

    answer = asyncio.run(go())
    return answer, orchestrator._runs[answer["paymentId"]]


def test_the_three_synthetic_banks_are_listed_with_the_two_recorded_ones():
    cities = {b["city"] for b in ghana_banks()}
    assert {"Accra", "Tamale", "Takoradi", "Kumasi", "Aflao"} <= cities
    accounts = [a for p in saved_payees() for a in p["accounts"]]
    assert {a["accountId"] for a in accounts} >= {"acc-ssx-nominated"}
    assert all("•" in a["accountMasked"] for a in accounts)


def test_a_saved_account_at_any_amount_is_priced_executed_and_credited():
    orchestrator = make_orchestrator()
    quote = orchestrator.quote_payment(payment({"accountId": "acc-ssx-nominated"}, detailsSource="saved"))
    assert quote["executable"] and quote["paymentId"] == "PAY-2026-1001" and quote["risk"]["tier"] == "LOW"
    assert quote["route"]["chosen"] == "R3" and quote["route"]["settlement"] == "DIRECT"
    answer, payment_run = run(orchestrator, quote, idempotency_key="k1")
    assert payment_run.status == "credited" and payment_run.order.amount.value == "42000.00"
    again = orchestrator.submit(quote_id=quote["quoteId"], idempotency_key="k1")
    assert again["paymentId"] == answer["paymentId"] and again["replayed"]
    validator = Draft202012Validator(SCHEMA)
    for event in orchestrator.bus.events:
        validator.validate(event)
    assert orchestrator.bus.events[0]["data"]["scenario"] == "custom"


def test_a_new_account_for_a_known_payee_is_held_and_never_credited_without_the_supplier():
    orchestrator = make_orchestrator()
    quote = orchestrator.quote_payment(
        payment(typed(name="Savanna Shea Exports Ltd", bankId="bank_gh_accra"), detailsSource="invoice_email",
                senderDomain="savannashea-exports.com")
    )
    assert quote["risk"]["tier"] in {"MEDIUM", "HIGH"} and quote["route"]["settlement"] == "ONCHAIN_ESCROW"
    _, payment_run = run(orchestrator, quote)
    assert payment_run.status == "stopped"
    asked = next(e for e in orchestrator.bus.events if e["type"] == "verification.requested")
    assert asked["data"]["channel"] == "SMS"  # the known contact on file, not one given with the payment


def test_an_unknown_payee_has_nobody_to_confirm_out_of_band_so_the_analyst_decides():
    orchestrator = make_orchestrator()
    quote = orchestrator.quote_payment(payment(typed(), amount="12000", purpose="SERVICES"))
    assert quote["route"]["settlement"] == "ONCHAIN_ESCROW"
    _, payment_run = run(orchestrator, quote)
    asked = next(e for e in orchestrator.bus.events if e["type"] == "verification.requested")
    assert asked["data"]["channel"] == "ANALYST" and payment_run.status == "stopped"
    events = json.dumps(orchestrator.bus.events)
    assert "0099887766554" not in events and "6554" in events  # only the masked number leaves the engine


def test_a_sanctioned_name_is_stopped_before_any_money_moves():
    orchestrator = make_orchestrator()
    quote = orchestrator.quote_payment(
        payment(typed(name="Northwind Mule Trading Ltd", accountHolder="NORTHWIND MULE TRADING LTD", bankId="bank_gh_takoradi"))
    )
    assert quote["route"]["chosen"] is None
    _, payment_run = run(orchestrator, quote)
    assert payment_run.status == "stopped"
    assert not [e for e in orchestrator.bus.events if e["type"] == "leg.sent"]


@pytest.mark.parametrize(
    "beneficiary, amount, message",
    [
        (typed(bankId="bank_fr"), "100", "unknown Ghanaian bank"),
        (typed(bankId="no_such_bank"), "100", "unknown Ghanaian bank"),
        ({"accountId": "acc-nope"}, "100", "unknown saved account"),
        ({"name": "Tamale Grain Co"}, "100", "missing beneficiary fields"),
        (typed(), "0", "between 1 and"),
        (typed(), "2000000", "between 1 and"),
    ],
)
def test_a_payment_the_engine_cannot_price_is_refused(beneficiary, amount, message):
    with pytest.raises(InvalidPayment, match=message):
        make_orchestrator().quote_payment(payment(beneficiary, amount=amount))


@pytest.mark.parametrize("field, value", [("accountNumber", "12AB"), ("name", "<script>"), ("bankId", "Bank GH")])
def test_malformed_fields_are_refused_by_the_schema(field, value):
    with pytest.raises(ValidationError):
        payment(typed(**{field: value}))


def test_reset_forgets_the_accounts_typed_in_the_session_and_keeps_the_recorded_ones():
    orchestrator = make_orchestrator()
    orchestrator.quote_payment(payment(typed()))
    assert any(a.startswith("acc-s-") for a in ACCOUNTS)
    asyncio.run(orchestrator.reset())
    assert not any(a.startswith("acc-s-") for a in ACCOUNTS) and "acc-mensah-aflao" in ACCOUNTS
    assert orchestrator.quote("legit")["paymentId"] == "PAY-2026-0001"


def test_an_expired_typed_quote_cannot_be_executed():
    orchestrator = make_orchestrator()
    quote = orchestrator.quote_payment(payment({"accountId": "acc-ssx-nominated"}))
    orchestrator.advance_clock(1)
    with pytest.raises(Exception, match="expired"):
        orchestrator.submit(quote_id=quote["quoteId"])


def test_the_invoice_text_of_a_typed_payment_reaches_the_run_as_data():
    orchestrator = make_orchestrator(live_invoice=True, llm_mode="off")
    quote = orchestrator.quote_payment(payment(typed(), invoiceText="Please pay\x07 our new account.\x00"))
    _, payment_run = run(orchestrator, quote)
    assert payment_run.invoice_text == "Please pay our new account."


def test_the_short_custom_form_and_a_typed_payment_are_published_as_one_custom_scenario():
    orchestrator = make_orchestrator()
    validator = Draft202012Validator(SCHEMA)
    for ask in (
        lambda: orchestrator.quote_custom({"amount": "12000", "invoiceRef": "SSE-VER-120", "account": "verified"}),
        lambda: orchestrator.quote_payment(payment({"accountId": "acc-ssx-nominated"}, detailsSource="saved")),
    ):
        run(orchestrator, ask())
        started = [e for e in orchestrator.bus.events if e["type"] == "scenario.started"][-1]
        assert started["data"]["scenario"] == "custom"
        validator.validate(started)
