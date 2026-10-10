"""Canonical scenario data: the fictional cast, their accounts and the two demo orders.

Shared by the engine (to run the scenarios) and by Lane B (golden test cases).
Everything here is synthetic.
"""

import re
from datetime import date, datetime, time, timezone
from difflib import SequenceMatcher

from .models import (
    Account,
    Amount,
    Approver,
    Contact,
    Creditor,
    Party,
    Payee,
    PayerSession,
    PaymentOrder,
    RiskContext,
)

# The demo "now" used by fixtures and golden cases (deterministic).
DEMO_NOW = datetime(2026, 10, 11, 9, 0, 0, tzinfo=timezone.utc)
DEMO_DATE = DEMO_NOW.date()

CORRIDOR = "FR-GH"
SCENARIOS = ("legit", "diverted")
PAYMENT_IDS = {"legit": "PAY-2026-0001", "diverted": "PAY-2026-0002"}
UETRS = {
    "legit": "8c2f3a1e-6d4b-4f0a-9b7c-1e5d2a3f4b01",
    "diverted": "0d3f6c7e-5b1a-4e2c-9a40-7f6d2c8b1e02",
}

# Account details from these sources are trusted; anything else is "untrusted provenance".
TRUSTED_PROVENANCE = frozenset({"verified_registry", "payment_history", "psp_attestation"})

LEGAL_SUFFIXES = frozenset({"LTD", "LIMITED", "SAS", "SA", "SARL"})

# --------------------------------------------------------------------------- cast

PAYER = Party(
    id="payer_rhone",
    name="Rhône Cosmétiques SAS",
    short_name="Rhône Cosmétiques",
    institution_id="payer_rhone",
    bank_institution_id="bank_fr",
    country="FR",
    approvers=[
        Approver(name="Claire Martin", role="CFO"),
        Approver(name="Marc Durand", role="Second approver"),
    ],
)

NOMINATED_ACCOUNT = Account(
    id="acc-ssx-nominated",
    holder_name="Savanna Shea Exports Ltd",
    institution_id="bank_gh",
    account_masked="•••• •••• 2291",
    country="GH",
    nominated_for_exports=True,
    opened_at=date(2019, 6, 3),
    first_seen=date(2024, 3, 12),
    successful_payments=14,
    verification="OOB_KNOWN_CONTACT",
)

# The account named in the fraudulent email. It is NOT in the supplier's registry entry.
MULE_ACCOUNT = Account(
    id="acc-mensah-aflao",
    holder_name="K. MENSAH VENTURES",
    institution_id="mule_bank",
    account_masked="•••• •••• 7730",
    country="GH",
    nominated_for_exports=False,
    opened_at=date(2026, 10, 2),  # 9 days before the demo date
    first_seen=None,
    successful_payments=0,
    verification=None,
)

SUPPLIER = Payee(
    id="payee-ssx",
    legal_name="Savanna Shea Exports Ltd",
    short_name="Savanna Shea",
    country="GH",
    known_domain="savanna-shea.com",
    accounts=[NOMINATED_ACCOUNT],
    known_contacts=[
        Contact(name="Kwame Asante", msisdn_masked="+233 •• ••• 4471", registered_at=date(2024, 3, 12)),
    ],
)

SUPPLIER_INSTITUTION_ID = "supplier_ssx"

ACCOUNTS = {a.id: a for a in (NOMINATED_ACCOUNT, MULE_ACCOUNT)}
PAYEES = {SUPPLIER.id: SUPPLIER}

# --------------------------------------------------------------------------- orders


def _order(name: str, account: Account, provenance: str, sender_domain: str | None) -> PaymentOrder:
    return PaymentOrder(
        payment_id=PAYMENT_IDS[name],
        uetr=UETRS[name],
        corridor=CORRIDOR,
        payer=PAYER,
        creditor=Creditor(
            payee_id=SUPPLIER.id,
            payee_name=SUPPLIER.legal_name,
            account_id=account.id,
            account_holder=account.holder_name,
            account_masked=account.account_masked,
            institution_id=account.institution_id,
            country=account.country,
        ),
        amount=Amount(value="85000.00", currency="EUR"),
        purpose="GOODS",
        invoice_ref="SSE-2026-118",
        loc_ref="LOC-GH-2026-0457",
        provenance=provenance,
        sender_domain=sender_domain,
        payer_session=PayerSession(sim_swap_72h=False, new_device_24h=False, country="FR"),
    )


ORDERS = {
    "legit": _order("legit", NOMINATED_ACCOUNT, "verified_registry", None),
    "diverted": _order("diverted", MULE_ACCOUNT, "invoice_pdf_email", "savannashea-exports.com"),
}

# Norm signals raised by the norms engine for each golden case (R1 = export proceeds
# requested on an account that is not the exporter's nominated account).
GOLDEN_NORM_SIGNALS = {"legit": [], "diverted": ["R1"]}


def order(name: str) -> PaymentOrder:
    return ORDERS[name].model_copy(deep=True)


def account(account_id: str) -> Account:
    return ACCOUNTS[account_id]


def payee(payee_id: str) -> Payee:
    return PAYEES[payee_id]


# --------------------------------------------------------------------------- risk context


def normalise_name(name: str) -> str:
    """Uppercase, strip punctuation, drop the legal suffixes LTD, LIMITED, SAS, SA, SARL."""
    words = re.sub(r"[^\w\s]", " ", name.upper(), flags=re.UNICODE).split()
    return " ".join(w for w in words if w not in LEGAL_SUFFIXES)


def name_match(account_holder: str, payee_name: str) -> float:
    """Similarity in [0, 1] between the account holder and the expected supplier name."""
    return SequenceMatcher(None, normalise_name(account_holder), normalise_name(payee_name)).ratio()


def account_age_hours(acc: Account, now: datetime) -> float:
    opened = datetime.combine(acc.opened_at, time(0, 0), tzinfo=timezone.utc)
    return max(0.0, (now - opened).total_seconds() / 3600.0)


def build_risk_context(order_: PaymentOrder, norm_signals: list[str], now: datetime = DEMO_NOW) -> RiskContext:
    """The context every RiskPort implementation receives. Built the same way in the engine and in tests."""
    acc = ACCOUNTS[order_.creditor.account_id]
    supplier = PAYEES.get(order_.creditor.payee_id)
    return RiskContext(
        payee=supplier,
        account=acc,
        norm_signals=list(norm_signals),
        payer_session=order_.payer_session,
        name_match=name_match(acc.holder_name, order_.creditor.payee_name),
        account_age_hours=account_age_hours(acc, now),
        amount_eur=order_.amount.as_float(),
    )


def golden_case(name: str) -> tuple[PaymentOrder, RiskContext]:
    """(order, context) of a demo scenario: `legit` must be LOW, `diverted` at least MEDIUM."""
    order_ = order(name)
    return order_, build_risk_context(order_, GOLDEN_NORM_SIGNALS[name], DEMO_NOW)
