"""Ports: the interfaces between lanes.

Lane B implements `RiskPort` (`sylo_risk.ModelRisk`), Lane C implements `ChainPort`
(`sylo_chain.FujiChain`). The engine ships a rules-based risk and a mock chain.
Every implementation must pass the suites in `sylo_spec.conformance`.
"""

from typing import Optional, Protocol, runtime_checkable

from .models import (
    Eip712Domain,
    PaymentIntent,
    PaymentOrder,
    Revocation,
    RiskContext,
    RiskResult,
    Status,
    TxRef,
    VerificationAttestation,
)


@runtime_checkable
class RiskPort(Protocol):
    name: str  # "rules-v0", "model-v1", ...

    def score(self, order: PaymentOrder, ctx: RiskContext) -> RiskResult: ...


class ChainReverted(Exception):
    """A chain call reverted. `reason` is the Solidity custom error name, e.g. "PaymentNotReleasable"."""

    def __init__(self, reason: str, tx: Optional[TxRef] = None):
        super().__init__(reason)
        self.reason = reason
        self.tx = tx  # set when a failed transaction was mined


@runtime_checkable
class ChainPort(Protocol):
    mode: str  # "mock", "anvil", "fuji"

    def domain(self) -> Eip712Domain: ...

    def commit(self, intent: PaymentIntent, router_sig: bytes) -> TxRef: ...

    def deposit(self, intent: PaymentIntent, payer: str) -> TxRef: ...

    def record_verification(self, att: VerificationAttestation, verifier_sig: bytes) -> TxRef: ...

    def revoke(self, rev: Revocation, analyst_sig: bytes) -> TxRef: ...

    def release(self, payment_id: bytes, caller: str = "relayer") -> TxRef: ...

    def refund(self, payment_id: bytes) -> TxRef: ...

    def mark_executed(self, payment_id: bytes, execution_ref: bytes) -> TxRef: ...

    def status(self, payment_id: bytes) -> Status: ...

    def intent_hash(self, payment_id: bytes) -> bytes: ...
