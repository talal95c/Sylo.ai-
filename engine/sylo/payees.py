"""Payment orders typed by a user (the ``/test`` flow, PRD §16.2).

The fields are data, never instructions. An account is matched against the payer's registry by bank and
last four digits; an account the payer has never paid is added for this session only, as a new account
(no history, not nominated), and cleared by ``/v1/reset``. Only the masked number is kept."""

from __future__ import annotations

import hashlib
import json
import uuid
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from typing import Any, Literal

from pydantic import BaseModel, Field

from sylo_spec import SPEC_DIR
from sylo_spec.models import Account, Documents, Money, Party, PaymentOrder
from sylo_spec.scenarios import ACCOUNTS, CORRIDOR, DEMO_NOW, LEGIT_ORDER, PAYEES, name_match

MAX_AMOUNT_EUR = Decimal("1000000")
MAX_SESSION_ACCOUNTS = 200
NAME_MATCH_KNOWN_PAYEE = 0.9
SESSION_ACCOUNT_PREFIX = "acc-s-"
SESSION_PAYEE_PREFIX = "payee-s-"
PROVENANCE = {
    "saved": "verified_registry",
    "invoice_email": "invoice_pdf_email",
    "phone": "inbound_call",
    "typed": "user_input",
}
_NAME = r"^[\w][\w .,'&()/-]*$"

_session_accounts: set[str] = set()


class InvalidPayment(ValueError):
    """The typed payment cannot be priced: unknown bank or account, missing field, amount out of range."""


class BeneficiaryIn(BaseModel):
    accountId: str | None = Field(default=None, max_length=60)
    """A saved account of a known payee (``GET /v1/payees``). Otherwise the four fields below."""
    name: str | None = Field(default=None, min_length=2, max_length=120, pattern=_NAME)
    accountHolder: str | None = Field(default=None, min_length=2, max_length=120, pattern=_NAME)
    accountNumber: str | None = Field(default=None, pattern=r"^[0-9]{10,16}$")
    bankId: str | None = Field(default=None, max_length=40, pattern=r"^[a-z][a-z0-9_]*$")


class PaymentIn(BaseModel):
    beneficiary: BeneficiaryIn
    amount: str = Field(pattern=r"^[0-9]{1,7}(\.[0-9]{1,2})?$")
    purpose: Literal["GOODS", "SERVICES"] = "GOODS"
    invoiceRef: str | None = Field(default=None, min_length=1, max_length=40, pattern=r"^[A-Za-z0-9][A-Za-z0-9 ._/-]*$")
    locRef: str | None = Field(default=None, min_length=1, max_length=40, pattern=r"^[A-Za-z0-9][A-Za-z0-9 ._/-]*$")
    """Bank of Ghana export letter of credit: a payment for goods to Ghana needs it on every bank route."""
    detailsSource: Literal["saved", "invoice_email", "phone", "typed"] = "typed"
    senderDomain: str | None = Field(default=None, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,}$")


@lru_cache(maxsize=1)
def _institutions() -> dict[str, dict[str, Any]]:
    raw = json.loads((SPEC_DIR / "geo" / "institutions.json").read_text(encoding="utf-8"))
    return {item["id"]: item for item in raw["institutions"]}


def ghana_banks() -> list[dict[str, str]]:
    """Banks a Ghanaian beneficiary can hold an account with: the ones the globe can draw."""
    return [
        {"id": i["id"], "name": i["name"], "short": i.get("short", i["name"]), "city": i["city"]}
        for i in _institutions().values()
        if i["country"] == "GH" and i["kind"] == "bank"
    ]


def saved_payees() -> list[dict[str, Any]]:
    """The payer's known payees and the accounts they own (masked)."""
    banks = _institutions()
    return [
        {
            "payeeId": payee.id,
            "name": payee.legal_name,
            "country": payee.country,
            "accounts": [
                {
                    "accountId": account.id,
                    "accountHolder": account.holder_name,
                    "accountMasked": account.account_masked,
                    "bankId": account.institution_id,
                    "bankName": banks.get(account.institution_id, {}).get("short", account.institution_id),
                    "successfulPayments": account.successful_payments,
                }
                for account in payee.accounts
            ],
        }
        for payee in PAYEES.values()
        if not payee.id.startswith(SESSION_PAYEE_PREFIX)
    ]


def _masked(digits: str) -> str:
    return f"GH•• •••• {digits[-4:]}"


def _known_payee(name: str):
    best = max(PAYEES.values(), key=lambda payee: name_match(name, payee.legal_name), default=None)
    return best if best is not None and name_match(name, best.legal_name) >= NAME_MATCH_KNOWN_PAYEE else None


def _account_for(bank_id: str, number: str, holder: str) -> Account:
    masked = _masked(number)
    for account in ACCOUNTS.values():
        if account.institution_id == bank_id and account.account_masked == masked:
            return account
    if len(_session_accounts) >= MAX_SESSION_ACCOUNTS:
        raise InvalidPayment("too many new accounts in this session: POST /v1/reset")
    digest = hashlib.sha256(f"{bank_id}:{number}".encode()).hexdigest()[:10]
    account = Account(
        id=f"{SESSION_ACCOUNT_PREFIX}{digest}",
        holder_name=holder.strip().upper(),
        institution_id=bank_id,
        account_masked=masked,
        first_seen=DEMO_NOW.date().isoformat(),
        successful_payments=0,
        nominated_for_exports=False,
    )
    ACCOUNTS[account.id] = account
    _session_accounts.add(account.id)
    return account


def build_order(payment: PaymentIn, payment_id: str) -> PaymentOrder:
    """The order the engine decides on, from what the user typed."""
    try:
        amount = Decimal(payment.amount)
    except InvalidOperation:
        raise InvalidPayment("the amount is not a number") from None
    if not Decimal("1") <= amount <= MAX_AMOUNT_EUR:
        raise InvalidPayment(f"the amount must be between 1 and {MAX_AMOUNT_EUR:,} EUR")
    beneficiary = payment.beneficiary
    if beneficiary.accountId is not None:
        account = ACCOUNTS.get(beneficiary.accountId)
        payee = next((p for p in PAYEES.values() if account and p.owns(account.id)), None)
        if account is None or payee is None:
            raise InvalidPayment(f"unknown saved account {beneficiary.accountId!r}")
        name = payee.legal_name
    else:
        missing = [f for f in ("name", "accountHolder", "accountNumber", "bankId") if getattr(beneficiary, f) is None]
        if missing:
            raise InvalidPayment(f"missing beneficiary fields: {', '.join(missing)}")
        bank = _institutions().get(beneficiary.bankId or "")
        if bank is None or bank["country"] != "GH" or bank["kind"] != "bank":
            raise InvalidPayment(f"unknown Ghanaian bank {beneficiary.bankId!r}: see GET /v1/banks")
        name = beneficiary.name.strip()  # type: ignore[union-attr]
        account = _account_for(bank["id"], beneficiary.accountNumber, beneficiary.accountHolder)  # type: ignore[arg-type]
        payee = _known_payee(name)
    owned = bool(payee and payee.owns(account.id))
    provenance = PROVENANCE[payment.detailsSource]
    if provenance == "verified_registry" and not owned:
        provenance = "user_input"  # only an account the payee already owns counts as saved
    payee_id = payee.id if payee else f"{SESSION_PAYEE_PREFIX}{hashlib.sha256(name.lower().encode()).hexdigest()[:10]}"
    return PaymentOrder(
        id=payment_id,
        uetr=str(uuid.uuid4()),
        corridor=CORRIDOR,
        debtor=LEGIT_ORDER.debtor,
        creditor=Party(id=payee_id, name=payee.legal_name if payee else name, country="GH", institution_id=account.institution_id),
        payee_id=payee_id,
        creditor_account_id=account.id,
        amount=Money(value=f"{amount:.2f}", currency="EUR"),
        purpose=payment.purpose,
        documents=Documents(
            invoice_ref=payment.invoiceRef,
            loc_ref=payment.locRef,
            sender_domain=payment.senderDomain if payment.detailsSource == "invoice_email" else None,
        ),
        provenance={"creditorAccount": provenance},
        channel=LEGIT_ORDER.channel,
    )


def forget_session_accounts() -> None:
    for account_id in _session_accounts:
        ACCOUNTS.pop(account_id, None)
    _session_accounts.clear()
