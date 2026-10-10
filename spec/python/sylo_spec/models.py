"""Pydantic models shared by every lane.

JSON uses camelCase aliases (`alias_generator=to_camel`, `populate_by_name=True`).
Unknown fields are ignored, so producers can add optional fields without breaking consumers.
"""

from datetime import date
from decimal import Decimal
from enum import IntEnum
from typing import Annotated, Any, Optional

from eth_utils import to_checksum_address
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, PlainSerializer
from pydantic.alias_generators import to_camel

# --------------------------------------------------------------------------- enums
# The numbers are binding: the same values are used in Solidity and TypeScript.


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


# --------------------------------------------------------------------------- field types


def _parse_tier(value: Any) -> Tier:
    if isinstance(value, Tier):
        return value
    if isinstance(value, str):
        return Tier[value.upper()]
    return Tier(int(value))


def _parse_bytes32(value: Any) -> bytes:
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
    elif isinstance(value, str):
        raw = bytes.fromhex(value[2:] if value.startswith(("0x", "0X")) else value)
    else:
        raise TypeError("bytes32 must be bytes or a hex string")
    if len(raw) != 32:
        raise ValueError(f"expected 32 bytes, got {len(raw)}")
    return raw


def _parse_address(value: Any) -> str:
    return to_checksum_address(value)


# A tier that serialises as its name ("MEDIUM") in JSON and stays a Tier in Python.
TierName = Annotated[
    Tier,
    BeforeValidator(_parse_tier),
    PlainSerializer(lambda t: t.name, return_type=str, when_used="json"),
]

# 32 bytes in Python, "0x…" hex in JSON.
Bytes32 = Annotated[
    bytes,
    BeforeValidator(_parse_bytes32),
    PlainSerializer(lambda b: "0x" + b.hex(), return_type=str, when_used="json"),
]

# EIP-55 checksummed address.
Address = Annotated[str, BeforeValidator(_parse_address)]


class SpecModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")

    def to_json(self) -> dict[str, Any]:
        """JSON-ready dict with camelCase keys."""
        return self.model_dump(mode="json", by_alias=True)


# --------------------------------------------------------------------------- business objects


class Amount(SpecModel):
    value: str  # decimal string, e.g. "85000.00"
    currency: str = "EUR"

    def as_decimal(self) -> Decimal:
        return Decimal(self.value)

    def as_float(self) -> float:
        return float(self.value)

    def units(self, decimals: int = 6) -> int:
        """Token units for an ERC-20 with `decimals` decimals."""
        return int(self.as_decimal() * (Decimal(10) ** decimals))


class Institution(SpecModel):
    id: str
    name: str
    kind: str
    city: str
    country: str
    lat: float
    lng: float


class Hop(SpecModel):
    src: str = Field(alias="from")
    dst: str = Field(alias="to")
    kind: str  # "bank" | "chain" | "wallet"


class Contact(SpecModel):
    name: str
    msisdn_masked: str
    registered_at: date


class Account(SpecModel):
    id: str
    holder_name: str
    institution_id: str
    account_masked: str
    country: str
    nominated_for_exports: bool = False
    opened_at: date
    first_seen: Optional[date] = None
    successful_payments: int = 0
    verification: Optional[str] = None  # "OOB_KNOWN_CONTACT" | "PSP_ATTESTATION"


class Payee(SpecModel):
    id: str
    legal_name: str
    short_name: Optional[str] = None  # how the UI names the payee in a sentence
    country: str
    known_domain: str
    accounts: list[Account]
    known_contacts: list[Contact]

    def account(self, account_id: str) -> Optional[Account]:
        return next((a for a in self.accounts if a.id == account_id), None)

    def nominated_account(self) -> Optional[Account]:
        return next((a for a in self.accounts if a.nominated_for_exports), None)


class Approver(SpecModel):
    name: str
    role: str


class Party(SpecModel):
    id: str
    name: str
    short_name: Optional[str] = None
    institution_id: str  # the party's own node on the globe
    bank_institution_id: str
    country: str
    approvers: list[Approver] = []


class Creditor(SpecModel):
    payee_id: str
    payee_name: str
    account_id: str
    account_holder: str
    account_masked: str
    institution_id: str
    country: str


class PayerSession(SpecModel):
    sim_swap_72h: bool = Field(default=False, alias="simSwap72h")
    new_device_24h: bool = Field(default=False, alias="newDevice24h")
    country: str = "FR"


class PaymentOrder(SpecModel):
    payment_id: str  # "PAY-2026-0001"
    uetr: str
    corridor: str = "FR-GH"
    payer: Party
    creditor: Creditor
    amount: Amount
    purpose: str  # "GOODS" | "SERVICES_TECHNICAL" | "SERVICES_OTHER"
    invoice_ref: str
    loc_ref: Optional[str] = None
    provenance: str  # where the creditor account details come from
    sender_domain: Optional[str] = None
    payer_session: PayerSession = PayerSession()


# --------------------------------------------------------------------------- risk port


class RiskContext(SpecModel):
    payee: Optional[Payee] = None
    account: Account
    norm_signals: list[str] = []
    payer_session: PayerSession = PayerSession()
    name_match: float
    account_age_hours: float
    amount_eur: float


class RiskReason(SpecModel):
    ref: str  # signal family: B, V, P, G, H, N, S, R
    text: str
    rule_id: Optional[str] = None


class RiskResult(SpecModel):
    score: int = Field(ge=0, le=100)
    tier: TierName
    floor_tier: TierName
    rules_fired: list[str] = []
    reasons: list[RiskReason] = []
    model: str


# --------------------------------------------------------------------------- chain port


class TxRef(SpecModel):
    tx_hash: str
    explorer_url: Optional[str] = None
    simulated: bool = True
    block_number: Optional[int] = None


class Eip712Domain(SpecModel):
    name: str = "SyloPaymentRegistry"
    version: str = "1"
    chain_id: int
    verifying_contract: Address


class PaymentIntent(SpecModel):
    payment_id: Bytes32
    corridor_id: Bytes32
    beneficiary: Address
    token: Address
    amount: int
    offchain_hash: Bytes32
    decision_hash: Bytes32
    approval_hash: Bytes32
    tier: Tier
    valid_until: int
    nonce: int


class VerificationAttestation(SpecModel):
    payment_id: Bytes32
    intent_hash: Bytes32
    method: VerificationMethod
    result: VerificationResult
    sim_swap_checked: bool
    evidence_hash: Bytes32
    verified_at: int
    nonce: int


class Revocation(SpecModel):
    payment_id: Bytes32
    reason_code: RevocationReason
    case_hash: Bytes32
    nonce: int
