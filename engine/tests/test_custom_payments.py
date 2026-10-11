import json

import pytest
from fastapi.testclient import TestClient
from sylo_spec.models import Tier
from sylo_spec.scenarios import ACCOUNTS

from sylo.main import create_app

from .conftest import events_of, make_orchestrator, until


ACCOUNT_NUMBER = "GH739201004859321"


def custom_payload(**updates):
    return {
        "amount": "48500",
        "invoiceRef": "SSE-NEW-485",
        "account": "new",
        "accountNumber": ACCOUNT_NUMBER,
        "holderName": "Savanna Shea Export Account",
        **updates,
    }


async def test_new_beneficiary_quote_holds_and_requests_supplier_sms():
    orchestrator = make_orchestrator(live_invoice=True, llm_mode="off")
    quote = orchestrator.quote_custom(
        custom_payload(invoiceText="Updated invoice with new bank details.")
    )
    payment_id = orchestrator.submit(quote_id=quote["quoteId"], speed=100)["paymentId"]
    run = await until(orchestrator, payment_id, "awaiting_supplier")

    diverted_tier = Tier[make_orchestrator().quote("diverted")["risk"]["tier"]]
    assert run.hold == "escrow"
    assert run.risk is not None and run.risk.tier >= diverted_tier
    assert run.invoice_text == "Updated invoice with new bank details."
    assert run.case is not None and run.case.llm == "off"
    assert events_of(orchestrator, "payment.held")
    assert events_of(orchestrator, "case.ready")
    requested = events_of(orchestrator, "verification.requested")[0]["data"]
    assert requested["channel"] == "SMS"
    assert requested["contactName"] == "Kwame Asante"

    account = ACCOUNTS[run.order.creditor_account_id]
    assert account.account_masked.endswith(ACCOUNT_NUMBER[-4:])
    assert ACCOUNT_NUMBER not in json.dumps(orchestrator.bus.events, ensure_ascii=False)
    await orchestrator.reset()


async def test_custom_verified_account_completes():
    orchestrator = make_orchestrator()
    quote = orchestrator.quote_custom(
        {"amount": "12000", "invoiceRef": "SSE-VER-120", "account": "verified"}
    )
    payment_id = orchestrator.submit(
        quote_id=quote["quoteId"], speed=100, auto=True
    )["paymentId"]

    run = await until(orchestrator, payment_id, "credited")
    await orchestrator._task
    assert run.hold is None
    assert run.order.creditor_account_id == "acc-ssx-nominated"
    assert run.order.documents.invoice_ref == "SSE-VER-120"
    await orchestrator.reset()


async def test_swap_beneficiary_attack_is_refused_for_custom_payment():
    orchestrator = make_orchestrator()
    quote = orchestrator.quote_custom(custom_payload())
    payment_id = orchestrator.submit(quote_id=quote["quoteId"], speed=100)["paymentId"]
    await until(orchestrator, payment_id, "awaiting_supplier")

    result = await orchestrator.attack("swap_beneficiary", payment_id)

    assert result["reverted"] is True
    assert events_of(orchestrator, "tx.reverted")
    await orchestrator.reset()


def test_reset_removes_custom_accounts_and_public_payment_list_is_private():
    orchestrator = make_orchestrator()
    with TestClient(create_app(orchestrator.settings, orchestrator)) as client:
        quote = client.post("/v1/quotes", json={"custom": custom_payload()})
        assert quote.status_code == 200 and quote.json()["executable"] is True
        account_id = next(iter(orchestrator._custom_accounts))
        assert account_id in ACCOUNTS

        submitted = client.post(
            "/v1/payments",
            json={"quoteId": quote.json()["quoteId"], "speed": 100},
        )
        assert submitted.status_code == 200
        listed = client.get("/v1/payments")
        assert listed.status_code == 200
        payment = listed.json()["payments"][0]
        assert payment["paymentId"] == submitted.json()["paymentId"]
        assert payment["chainPaymentId"].startswith("0x")
        assert set(payment) == {"paymentId", "chainPaymentId"}

        reset = client.post("/v1/reset")
        assert reset.status_code == 200
        assert account_id not in ACCOUNTS


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"order": "legit", "custom": custom_payload()},
        {"custom": custom_payload(amount="99.99")},
        {"custom": custom_payload(amount="1000000.01")},
        {"custom": custom_payload(amount="1e3")},
        {"custom": custom_payload(invoiceRef="bad/ref")},
        {"custom": custom_payload(account="new", accountNumber=None)},
        {"custom": custom_payload(account="new", holderName=None)},
        {"custom": custom_payload(accountNumber="invalid/number")},
        {"custom": custom_payload(senderDomain="https://invalid.example")},
        {"custom": custom_payload(invoiceText="x" * 2001)},
    ],
)
def test_custom_quote_rejects_invalid_payloads_with_422(payload):
    orchestrator = make_orchestrator()
    with TestClient(create_app(orchestrator.settings, orchestrator)) as client:
        response = client.post("/v1/quotes", json=payload)
    assert response.status_code == 422


def test_operator_token_opens_operator_routes_on_public_demo():
    orchestrator = make_orchestrator(demo_public=True, operator_token="not-a-real-secret")
    with TestClient(create_app(orchestrator.settings, orchestrator)) as client:
        denied = client.post("/v1/sim/clock", json={"advanceHours": 1})
        wrong = client.post(
            "/v1/sim/clock",
            json={"advanceHours": 1},
            headers={"X-Sylo-Operator": "wrong"},
        )
        allowed = client.post(
            "/v1/sim/clock",
            json={"advanceHours": 1},
            headers={"X-Sylo-Operator": "not-a-real-secret"},
        )

    assert denied.status_code == wrong.status_code == 403
    assert allowed.status_code == 200
