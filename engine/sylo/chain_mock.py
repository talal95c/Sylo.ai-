"""MockChain: an in-memory ChainPort that mirrors PaymentRegistry + PaymentEscrow (v0 spec §5.9).

Same statuses, same checks in the same order, same custom error names as the Solidity contracts.
Transactions are simulated: hashes are keccak256("sylo-mock-<n>") and there is no explorer link.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from sylo_spec.canonical import keccak_text, to_bytes32, to_hex
from sylo_spec.devkeys import dev_address
from sylo_spec.eip712 import Message, digest, recover
from sylo_spec.models import (
    Eip712Domain,
    PaymentIntent,
    Revocation,
    Status,
    Tier,
    TxRef,
    VerificationAttestation,
    VerificationResult,
)
from sylo_spec.ports import ChainReverted, PaymentIdLike

SECP256K1_HALF_ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141 // 2

DEFAULT_REGISTRY = "0x0000000000000000000000000000000000000001"


@dataclass
class _Payment:
    intent_hash: bytes
    status: Status
    tier: int
    beneficiary: str
    token: str
    amount: int
    corridor_id: str


@dataclass
class _Hold:
    payer: str
    beneficiary: str
    token: str
    amount: int
    expires_at: float
    corridor_id: str
    frozen: bool = False
    settled: bool = False


def _address_set(addresses: Iterable[str] | None, dev_role: str) -> frozenset[str]:
    return frozenset(a.lower() for a in (addresses if addresses is not None else [dev_address(dev_role)]))


class MockChain:
    mode = "mock"

    def __init__(
        self,
        *,
        chain_id: int = 43113,
        registry_address: str | None = None,
        router_signers: Iterable[str] | None = None,
        verifier_signers: Iterable[str] | None = None,
        analyst_signers: Iterable[str] | None = None,
        hold_seconds: int = 86_400,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._domain = Eip712Domain(chain_id=chain_id, verifying_contract=registry_address or DEFAULT_REGISTRY)
        self._routers = _address_set(router_signers, "router_signer")
        self._verifiers = _address_set(verifier_signers, "verifier_signer")
        self._analysts = _address_set(analyst_signers, "analyst_signer")
        self._hold_seconds = hold_seconds
        self._clock = clock
        self._payments: dict[bytes, _Payment] = {}
        self._holds: dict[bytes, _Hold] = {}
        self._nonces: set[tuple[str, int]] = set()
        self._paused_corridors: set[str] = set()
        self._tx_counter = 0
        self._lock = threading.RLock()

    # --- helpers -----------------------------------------------------------------------------

    def domain(self) -> Eip712Domain:
        return self._domain

    def _tx(self) -> TxRef:
        self._tx_counter += 1
        return TxRef(tx_hash=to_hex(keccak_text(f"sylo-mock-{self._tx_counter}")), explorer_url=None, simulated=True)

    @staticmethod
    def _revert(reason: str, function: str) -> None:
        raise ChainReverted(reason, tx=None, function=function)

    def _signer(self, message: Message, signature: bytes, allowed: frozenset[str], function: str) -> str:
        """Same strictness as OpenZeppelin's ECDSA: 65 bytes, v is 27 or 28, s in the lower half."""
        well_formed = (
            len(signature) == 65
            and signature[64] in (27, 28)
            and int.from_bytes(signature[32:64], "big") <= SECP256K1_HALF_ORDER
        )
        if not well_formed:
            self._revert("UnauthorizedSigner", function)
        try:
            signer = recover(message, self._domain, signature)
        except Exception:
            self._revert("UnauthorizedSigner", function)
        if signer.lower() not in allowed:
            self._revert("UnauthorizedSigner", function)
        return signer

    def _use_nonce(self, signer: str, nonce: int, function: str) -> None:
        key = (signer.lower(), int(nonce))
        if key in self._nonces:
            self._revert("NonceUsed", function)
        self._nonces.add(key)

    # --- registry ----------------------------------------------------------------------------

    def commit(self, intent: PaymentIntent, router_sig: bytes) -> TxRef:
        with self._lock:
            pid = to_bytes32(intent.payment_id)
            current = self._payments.get(pid)
            if current is not None and current.status != Status.NONE:
                self._revert("InvalidTransition", "commit")
            if self._clock() > intent.valid_until:
                self._revert("IntentExpired", "commit")
            signer = self._signer(intent, router_sig, self._routers, "commit")
            self._use_nonce(signer, intent.nonce, "commit")
            self._payments[pid] = _Payment(
                intent_hash=digest(intent, self._domain),
                status=Status.COMMITTED,
                tier=intent.tier,
                beneficiary=intent.beneficiary,
                token=intent.token,
                amount=intent.amount,
                corridor_id=intent.corridor_id,
            )
            return self._tx()

    def record_verification(self, att: VerificationAttestation, verifier_sig: bytes) -> TxRef:
        with self._lock:
            payment = self._payments.get(to_bytes32(att.payment_id))
            if payment is None or payment.status != Status.COMMITTED:
                self._revert("InvalidTransition", "recordVerification")
            if to_bytes32(att.intent_hash) != payment.intent_hash:
                self._revert("CommitmentMismatch", "recordVerification")
            if att.result not in (VerificationResult.CONFIRMED, VerificationResult.DENIED):
                self._revert("InvalidResult", "recordVerification")
            signer = self._signer(att, verifier_sig, self._verifiers, "recordVerification")
            self._use_nonce(signer, att.nonce, "recordVerification")
            payment.status = Status.CONFIRMED if att.result == VerificationResult.CONFIRMED else Status.DENIED
            return self._tx()

    def revoke(self, rev: Revocation, analyst_sig: bytes) -> TxRef:
        with self._lock:
            payment = self._payments.get(to_bytes32(rev.payment_id))
            if payment is None or payment.status not in (Status.COMMITTED, Status.CONFIRMED, Status.DENIED):
                self._revert("InvalidTransition", "revoke")
            signer = self._signer(rev, analyst_sig, self._analysts, "revoke")
            self._use_nonce(signer, rev.nonce, "revoke")
            payment.status = Status.REVOKED
            return self._tx()

    def mark_executed(self, payment_id: PaymentIdLike, execution_ref: bytes) -> TxRef:
        with self._lock:
            payment = self._payments.get(to_bytes32(payment_id))
            allowed = payment is not None and (
                (payment.status == Status.COMMITTED and payment.tier == Tier.LOW) or payment.status == Status.CONFIRMED
            )
            if not allowed:
                self._revert("InvalidTransition", "markExecuted")
            payment.status = Status.EXECUTED
            return self._tx()

    def status(self, payment_id: PaymentIdLike) -> Status:
        payment = self._payments.get(to_bytes32(payment_id))
        return payment.status if payment else Status.NONE

    def intent_hash(self, payment_id: PaymentIdLike) -> bytes:
        payment = self._payments.get(to_bytes32(payment_id))
        return payment.intent_hash if payment else bytes(32)

    # --- escrow ------------------------------------------------------------------------------

    def deposit(self, intent: PaymentIntent, payer: str) -> TxRef:
        with self._lock:
            pid = to_bytes32(intent.payment_id)
            payment = self._payments.get(pid)
            if payment is None or payment.intent_hash != digest(intent, self._domain):
                self._revert("CommitmentMismatch", "deposit")
            if payment.status != Status.COMMITTED:
                self._revert("InvalidTransition", "deposit")
            if intent.tier != Tier.MEDIUM:
                self._revert("TierNotEscrowable", "deposit")
            if pid in self._holds:
                self._revert("AlreadyDeposited", "deposit")
            self._holds[pid] = _Hold(
                payer=payer,
                beneficiary=intent.beneficiary,
                token=intent.token,
                amount=intent.amount,
                expires_at=self._clock() + self._hold_seconds,
                corridor_id=intent.corridor_id,
            )
            return self._tx()

    def release(self, payment_id: PaymentIdLike, caller: str = "relayer") -> TxRef:
        with self._lock:
            pid = to_bytes32(payment_id)
            hold, payment = self._holds.get(pid), self._payments.get(pid)
            releasable = (
                hold is not None
                and payment is not None
                and not hold.settled
                and not hold.frozen
                and self._clock() <= hold.expires_at
                and hold.corridor_id not in self._paused_corridors
                and payment.status == Status.CONFIRMED
            )
            if not releasable:
                self._revert("PaymentNotReleasable", "release")
            hold.settled = True
            payment.status = Status.EXECUTED
            return self._tx()

    def refund(self, payment_id: PaymentIdLike) -> TxRef:
        with self._lock:
            pid = to_bytes32(payment_id)
            hold = self._holds.get(pid)
            if hold is None:
                self._revert("NoHold", "refund")
            if hold.settled:
                self._revert("AlreadySettled", "refund")
            expired = self._clock() > hold.expires_at
            if not expired and self._payments[pid].status != Status.REVOKED:
                self._revert("RefundNotAllowed", "refund")
            hold.settled = True
            return self._tx()

    def freeze(self, payment_id: PaymentIdLike) -> TxRef:
        with self._lock:
            hold = self._holds.get(to_bytes32(payment_id))
            if hold is None:
                self._revert("NoHold", "freeze")
            hold.frozen = True
            return self._tx()

    def pause_corridor(self, corridor_id: str) -> TxRef:
        with self._lock:
            self._paused_corridors.add(to_hex(to_bytes32(corridor_id)))
            return self._tx()

    def unpause_corridor(self, corridor_id: str) -> TxRef:
        """The admin's unpause. Not part of ``ChainPort``: on Fuji only the deployer key can do it."""
        with self._lock:
            self._paused_corridors.discard(to_hex(to_bytes32(corridor_id)))
            return self._tx()
