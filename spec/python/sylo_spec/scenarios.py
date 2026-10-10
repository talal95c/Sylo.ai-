"""Canonical scenario data (v0 spec §4.6).

Shared by the engine (to run the scenarios) and by Lane B (golden test cases). All names are
fictional and all data is synthetic.
"""

from __future__ import annotations

import difflib
import re
from datetime import datetime, timezone

from .models import (
    Account,
    AccountVerification,
    Approver,
    Channel,
    Contact,
    Documents,
    Money,
    Party,
    Payee,
    Payer,
    PayerSession,
    PaymentOrder,
    RiskContext,
)

DEMO_NOW = datetime(2026, 10, 11, 9, 0, 0, tzinfo=timezone.utc)
"""Scenario clock used for account ages, so results do not depend on the day the demo runs."""

CORRIDOR = "FR-GH"

PAYER = Payer(
    id="payer_rhone",
    name="Rhône Cosmétiques SAS",
    country="FR",
    institution_id="payer_rhone",
    bank_institution_id="bank_fr",
    approvers=[
        Approver(id="claire", name="Claire Martin", role="CFO"),
        Approver(id="marc", name="Marc Durand", role="Second approver"),
    ],
)

SUPPLIER_ACCOUNT = Account(
    id="acc-ssx-nominated",
    holder_name="SAVANNA SHEA EXPORTS LTD",
    institution_id="bank_gh",
    account_masked="GH•• •••• 2207",
    first_seen="2024-03-12",
    successful_payments=14,
    nominated_for_exports=True,
    verification=AccountVerification(method="OOB_KNOWN_CONTACT", at="2024-03-12", by="Banque Hexagone payee desk"),
)

MULE_ACCOUNT = Account(
    id="acc-mensah-aflao",
    holder_name="K. MENSAH VENTURES",
    institution_id="mule_bank",
    account_masked="GH•• •••• 9083",
    first_seen="2026-10-02",
    successful_payments=0,
    nominated_for_exports=False,
)

KWAME = Contact(name="Kwame Asante", msisdn_masked="+233 •• ••• 4471", since="2024-03-12")

SUPPLIER = Payee(
    id="payee-ssx",
    legal_name="Savanna Shea Exports Ltd",
    country="GH",
    institution_id="supplier_ssx",
    known_domain="savanna-shea.com",
    accounts=[SUPPLIER_ACCOUNT],
    known_contacts=[KWAME],
)

PAYEES: dict[str, Payee] = {SUPPLIER.id: SUPPLIER}
ACCOUNTS: dict[str, Account] = {a.id: a for a in (SUPPLIER_ACCOUNT, MULE_ACCOUNT)}

_DEBTOR = Party(id=PAYER.id, name=PAYER.name, country=PAYER.country, institution_id=PAYER.bank_institution_id)
_CHANNEL = Channel(device_id="dev-claire-laptop", msisdn="+33 6 •• •• 21 08", session_country="FR")

LEGIT_ORDER = PaymentOrder(
    id="PAY-2026-0001",
    uetr="9f1c2a7e-3b5d-4c8e-a1f0-6d2b7e4c9a01",
    corridor=CORRIDOR,
    debtor=_DEBTOR,
    creditor=Party(id=SUPPLIER.id, name=SUPPLIER.legal_name, country="GH", institution_id="bank_gh"),
    payee_id=SUPPLIER.id,
    creditor_account_id=SUPPLIER_ACCOUNT.id,
    amount=Money(value="85000.00", currency="EUR"),
    purpose="GOODS",
    documents=Documents(invoice_ref="SSE-2026-118", loc_ref="LOC-GH-2026-0457"),
    provenance={"creditorAccount": "verified_registry"},
    channel=_CHANNEL,
)

DIVERTED_ORDER = PaymentOrder(
    id="PAY-2026-0002",
    uetr="4b8e6d21-7c3a-4f59-9e12-a5d0c3b7f802",
    corridor=CORRIDOR,
    debtor=_DEBTOR,
    creditor=Party(id=SUPPLIER.id, name=SUPPLIER.legal_name, country="GH", institution_id="mule_bank"),
    payee_id=SUPPLIER.id,
    creditor_account_id=MULE_ACCOUNT.id,
    amount=Money(value="85000.00", currency="EUR"),
    purpose="GOODS",
    documents=Documents(
        invoice_ref="SSE-2026-118",
        loc_ref="LOC-GH-2026-0457",
        sender_domain="savannashea-exports.com",
    ),
    provenance={"creditorAccount": "invoice_pdf_email"},
    channel=_CHANNEL,
)

ORDERS: dict[str, PaymentOrder] = {"legit": LEGIT_ORDER, "diverted": DIVERTED_ORDER}

PAYER_SESSION = PayerSession()
"""Normal session for both scenarios: no SIM swap, known device, in France."""

_LEGAL_SUFFIXES = frozenset({"LTD", "LIMITED", "SAS", "SA", "SARL"})


def normalize_name(name: str) -> str:
    """Uppercase, strip punctuation and legal suffixes (LTD, LIMITED, SAS, SA, SARL)."""
    cleaned = re.sub(r"[^A-Z0-9 ]+", " ", name.upper())
    return " ".join(word for word in cleaned.split() if word not in _LEGAL_SUFFIXES)


def name_match(holder: str, payee: str) -> float:
    """Similarity of the account holder's name to the payee's legal name, 0.0–1.0."""
    return difflib.SequenceMatcher(None, normalize_name(holder), normalize_name(payee)).ratio()


def account_age_hours(account: Account, now: datetime = DEMO_NOW) -> float:
    first_seen = datetime.fromisoformat(account.first_seen).replace(tzinfo=timezone.utc)
    return (now - first_seen).total_seconds() / 3600


def build_risk_context(
    order: PaymentOrder,
    norm_signals: list[str],
    *,
    now: datetime = DEMO_NOW,
    session: PayerSession = PAYER_SESSION,
    sanctions_hit: bool = False,
) -> RiskContext:
    payee = PAYEES.get(order.payee_id)
    account = ACCOUNTS.get(order.creditor_account_id)
    holder = account.holder_name if account else order.creditor.name
    claimed = payee.legal_name if payee else order.creditor.name
    return RiskContext(
        payee=payee,
        account=account,
        norm_signals=list(norm_signals),
        payer_session=session,
        name_match=round(name_match(holder, claimed), 4),
        account_age_hours=account_age_hours(account, now) if account else 0.0,
        amount_eur=order.amount.as_float,
        sanctions_hit=sanctions_hit,
    )


GOLDEN_NORM_SIGNALS: dict[str, list[str]] = {"legit": [], "diverted": ["R1"]}


def golden_case(name: str) -> tuple[PaymentOrder, RiskContext]:
    """The order and risk context the engine builds for a canonical scenario."""
    order = ORDERS[name]
    return order, build_risk_context(order, GOLDEN_NORM_SIGNALS[name])
