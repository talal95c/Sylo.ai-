"""Pydantic v2 models shared by every lane (v0 spec §4.6–4.7, PRD §13.4).

Python attributes are snake_case; JSON uses camelCase aliases. Unknown fields are ignored so
that additive spec changes never break a consumer.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class SpecModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")

    def to_json_dict(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json")


# --- Enumerations (same numbers in Python, Solidity and TypeScript) -------------------------


class Tier(IntEnum):
    LOW = 0
    MEDIUM = 1
    HIGH = 2
    CRITICAL = 3


class Status(IntEnum):
    NONE = 0
    COMMITTED = 1
    CONFIRMED = 2
    DENIED = 3
    REVOKED = 4
    EXECUTED = 5


class VerificationMethod(IntEnum):
    OOB_KNOWN_CONTACT = 1
    PSP_ATTESTATION = 2


class VerificationResult(IntEnum):
    CONFIRMED = 1
    DENIED = 2


class RevocationReason(IntEnum):
    SUPPLIER_DENIED = 1
    ANALYST_DECISION = 2
    KILL_SWITCH = 3
    EXPIRED = 4


TRUSTED_PROVENANCE = frozenset({"verified_registry", "payment_history", "psp_attestation"})
"""Sources of bank details that the risk rules trust (anything else is untrusted)."""


def band(score: int) -> Tier:
    """Score bands: 0–39 LOW, 40–69 MEDIUM, 70–89 HIGH, 90–100 CRITICAL."""
    if score >= 90:
        return Tier.CRITICAL
    if score >= 70:
        return Tier.HIGH
    if score >= 40:
        return Tier.MEDIUM
    return Tier.LOW


# --- Parties, payees, accounts ----------------------------------------------------------------


class Party(SpecModel):
    id: str
    name: str
    country: str
    institution_id: str


class Approver(SpecModel):
    id: str
    name: str
    role: str


class Payer(SpecModel):
    id: str
    name: str
    country: str
    institution_id: str
    bank_institution_id: str
    approvers: list[Approver]


class Contact(SpecModel):
    name: str
    msisdn_masked: str
    since: str


class AccountVerification(SpecModel):
    method: str
    at: str
    by: str


class Account(SpecModel):
    id: str
    holder_name: str
    institution_id: str
    account_masked: str
    first_seen: str
    successful_payments: int
    nominated_for_exports: bool = False
    verification: AccountVerification | None = None


class Payee(SpecModel):
    id: str
    legal_name: str
    country: str
    institution_id: str
    known_domain: str | None = None
    accounts: list[Account] = Field(default_factory=list)
    known_contacts: list[Contact] = Field(default_factory=list)

    def owns(self, account_id: str) -> bool:
        return any(a.id == account_id for a in self.accounts)


# --- Payment order ---------------------------------------------------------------------------


class Money(SpecModel):
    value: str
    currency: str

    @property
    def as_float(self) -> float:
        return float(self.value)


class Documents(SpecModel):
    invoice_ref: str | None = None
    loc_ref: str | None = None
    sender_domain: str | None = None


class Channel(SpecModel):
    device_id: str
    msisdn: str
    session_country: str


class PaymentOrder(SpecModel):
    id: str
    uetr: str
    corridor: str
    debtor: Party
    creditor: Party
    payee_id: str
    creditor_account_id: str
    amount: Money
    purpose: str
    documents: Documents
    provenance: dict[str, str]
    channel: Channel


# --- Risk ------------------------------------------------------------------------------------


class PayerSession(SpecModel):
    sim_swap_72h: bool = Field(False, alias="simSwap72h")
    new_device_24h: bool = Field(False, alias="newDevice24h")
    country: str = "FR"


class PairHistory(SpecModel):
    successful_count: int = 0
    median_amount_eur: float | None = None
    payments_24h: int = 0


class RiskContext(SpecModel):
    payee: Payee | None
    account: Account | None
    norm_signals: list[str] = Field(default_factory=list)
    payer_session: PayerSession = Field(default_factory=PayerSession)
    name_match: float
    account_age_hours: float
    amount_eur: float
    sanctions_hit: bool = False
    history: PairHistory | None = None


class RiskReason(SpecModel):
    ref: str
    text: str
    rule_id: str | None = None


class RiskResult(SpecModel):
    score: int = Field(ge=0, le=100)
    tier: Tier
    floor_tier: Tier
    rules_fired: list[str]
    reasons: list[RiskReason]
    model: str
    oob_resolvable: bool = False
    """True when the risk is about the beneficiary's identity only (families B, V, R), so an
    out-of-band confirmation by the real supplier can lift it. False (the safe default) keeps the
    current action matrix: HIGH and above get no route."""


# --- Case file (System 2, written by Lane B's CasePort) ---------------------------------------

RecommendedAction = Literal["CONFIRM_REVOCATION", "RELEASE_AFTER_CONFIRMATION", "ESCALATE_AML", "NO_ACTION"]
LlmMode = Literal["off", "cached", "live"]


class Citation(SpecModel):
    ref: str
    """A reason ref, a rule id (e.g. ``R-PV-01``) or an event id (``evt-000012``)."""
    source: str
    """Where the cited fact comes from: ``rule``, ``model``, ``event`` or ``norms``."""


class CaseSentence(SpecModel):
    text: str
    refs: list[str] = Field(min_length=1)


class TimelineEntry(SpecModel):
    at: str
    event_id: str
    text: str


class CaseFile(SpecModel):
    """Analyst case file. Advisory only: no engine decision ever reads it."""

    payment_id: str
    summary: str
    sentences: list[CaseSentence]
    timeline: list[TimelineEntry]
    typology: str
    recommended_action: RecommendedAction
    explanation: str
    citations: list[Citation]
    report_draft: str | None = None
    llm: LlmMode
    prompt_version: str
    model: str


# --- EIP-712 structs (field order is binding, see eip712.py) --------------------------------


class Eip712Domain(SpecModel):
    name: str = "SyloPaymentRegistry"
    version: str = "1"
    chain_id: int
    verifying_contract: str


class PaymentIntent(SpecModel):
    payment_id: str
    corridor_id: str
    beneficiary: str
    token: str
    amount: int
    offchain_hash: str
    decision_hash: str
    approval_hash: str
    tier: int
    valid_until: int
    nonce: int


class VerificationAttestation(SpecModel):
    payment_id: str
    intent_hash: str
    method: int
    result: int
    sim_swap_checked: bool
    evidence_hash: str
    verified_at: int
    nonce: int


class Revocation(SpecModel):
    payment_id: str
    reason_code: int
    case_hash: str
    nonce: int


# --- Chain and events ------------------------------------------------------------------------


class TxRef(SpecModel):
    tx_hash: str
    explorer_url: str | None = None
    simulated: bool = True
    block_number: int | None = None


class Event(SpecModel):
    v: int = 1
    seq: int
    id: str
    ts: str
    type: str
    payment_id: str | None = None
    simulated: bool
    data: dict[str, Any] = Field(default_factory=dict)
