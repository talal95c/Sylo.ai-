"""Port interfaces between the engine and the lanes (v0 spec §4.7).

Lane B implements ``RiskPort`` (``sylo_risk.ModelRisk``) and ``CasePort``
(``sylo_risk.CaseWriter``); Lane C implements ``ChainPort``
(``sylo_chain.FujiChain``). Both must pass the suites in ``sylo_spec.conformance``.
"""

from __future__ import annotations

from typing import Protocol, Union, runtime_checkable

from .models import (
    CaseFile,
    Cluster,
    Eip712Domain,
    Event,
    PaymentIntent,
    PaymentOrder,
    Revocation,
    RiskContext,
    RiskResult,
    Status,
    TxRef,
    VerificationAttestation,
    WindowPayment,
)

PaymentIdLike = Union[bytes, str]
"""A bytes32 payment id, as 32 raw bytes or a 0x-prefixed hex string."""


@runtime_checkable
class RiskPort(Protocol):
    name: str

    def score(self, order: PaymentOrder, ctx: RiskContext) -> RiskResult: ...


@runtime_checkable
class CasePort(Protocol):
    """System 2: writes the analyst case file of a held payment from its events.

    Advisory only: the result is shown to humans and never read by a decision. Every sentence must
    cite a ref, rule id or event id present in ``events``; on any failure, fall back to a template.
    """

    name: str

    def write(self, payment_id: str, events: list[Event]) -> CaseFile: ...


@runtime_checkable
class ClusterPort(Protocol):
    """v2: finds mule clusters among recent payments (Lane B, ``sylo_risk.clusters``).

    ``detect`` returns the clusters that at least three payments of ``window`` point to, with the
    ids of those payments in ``linked_payments``. An empty list means nothing to report.
    """

    name: str

    def detect(self, window: list[WindowPayment]) -> list[Cluster]: ...


class ChainReverted(Exception):
    """A chain call was rejected. ``reason`` is the Solidity custom error name."""

    def __init__(self, reason: str, tx: TxRef | None = None, function: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.tx = tx
        self.function = function


@runtime_checkable
class ChainPort(Protocol):
    mode: str  # "mock", "anvil", "fuji"

    def domain(self) -> Eip712Domain: ...

    def commit(self, intent: PaymentIntent, router_sig: bytes) -> TxRef: ...

    def deposit(self, intent: PaymentIntent, payer: str) -> TxRef: ...

    def record_verification(self, att: VerificationAttestation, verifier_sig: bytes) -> TxRef: ...

    def revoke(self, rev: Revocation, analyst_sig: bytes) -> TxRef: ...

    def release(self, payment_id: PaymentIdLike, caller: str = "relayer") -> TxRef: ...

    def refund(self, payment_id: PaymentIdLike) -> TxRef: ...

    def mark_executed(self, payment_id: PaymentIdLike, execution_ref: bytes) -> TxRef: ...

    def status(self, payment_id: PaymentIdLike) -> Status: ...

    def intent_hash(self, payment_id: PaymentIdLike) -> bytes: ...
