"""MockChain: a simulated chain that mirrors the rules of PaymentRegistry and PaymentEscrow.

Same statuses, same custom error names, real EIP-712 signature recovery, role checks, nonce
tracking, escrow holds with expiry. Transaction hashes are fake and labelled `simulated`.
It passes `sylo_spec.conformance.run_chain_conformance`; FujiChain must pass the same suite.
"""

import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from eth_utils import keccak, to_checksum_address

from sylo_spec import eip712
from sylo_spec.devkeys import dev_keys
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
from sylo_spec.ports import ChainReverted

from .config import MOCK_REGISTRY_ADDRESS, MOCK_TOKEN_ADDRESS

ZERO32 = b"\x00" * 32
TREASURY_MINT = 10_000_000 * 10**6  # the deploy script mints 10,000,000 tEURC to the EU CASP


@dataclass
class _Payment:
    digest: bytes
    status: Status
    beneficiary: str
    token: str
    amount: int
    tier: Tier
    corridor_id: bytes


@dataclass
class _Hold:
    payer: str
    beneficiary: str
    token: str
    amount: int
    expires_at: float
    settled: bool = False
    frozen: bool = False


class MockChain:
    mode = "mock"

    def __init__(
        self,
        *,
        chain_id: int = 43113,
        registry_address: str = MOCK_REGISTRY_ADDRESS,
        token_address: str = MOCK_TOKEN_ADDRESS,
        hold_seconds: int = 86_400,
        clock: Optional[Callable[[], float]] = None,
        router_signer: Optional[str] = None,
        verifier_signer: Optional[str] = None,
        analyst_signer: Optional[str] = None,
        payer_treasury: Optional[str] = None,
    ):
        dev = dev_keys()
        self._domain = Eip712Domain(chain_id=chain_id, verifying_contract=registry_address)
        self.token_address = to_checksum_address(token_address)
        self.hold_seconds = hold_seconds
        self._clock = clock or time.time
        self._router = to_checksum_address(router_signer or dev["router_signer"].address)
        self._verifier = to_checksum_address(verifier_signer or dev["verifier_signer"].address)
        self._analyst = to_checksum_address(analyst_signer or dev["analyst_signer"].address)
        self._treasury = to_checksum_address(payer_treasury or dev["eu_casp"].address)
        self._lock = threading.Lock()
        self._tx_counter = 0
        self._payments: dict[bytes, _Payment] = {}
        self._holds: dict[bytes, _Hold] = {}
        self._nonces: set[tuple[str, int]] = set()
        self._paused: set[bytes] = set()
        self._balances: dict[tuple[str, str], int] = {(self.token_address, self._treasury): TREASURY_MINT}

    # ------------------------------------------------------------------ helpers

    def _tx(self) -> TxRef:
        self._tx_counter += 1
        digest = keccak(text=f"sylo-mock-{self._tx_counter}")
        return TxRef(tx_hash="0x" + digest.hex(), explorer_url=None, simulated=True, block_number=None)

    def _now(self) -> float:
        return float(self._clock())

    def _signer(self, message, signature: bytes, expected: str) -> str:
        """Recover the signer; like the contract, any invalid signature is `UnauthorizedSigner`."""
        try:
            signer = eip712.recover(self._domain, message, signature)
        except Exception as err:  # malformed signature
            raise ChainReverted("UnauthorizedSigner") from err
        if signer != expected:
            raise ChainReverted("UnauthorizedSigner")
        return signer

    def _use_nonce(self, signer: str, nonce: int) -> None:
        if (signer, nonce) in self._nonces:
            raise ChainReverted("NonceUsed")
        self._nonces.add((signer, nonce))

    def _status(self, payment_id: bytes) -> Status:
        payment = self._payments.get(bytes(payment_id))
        return payment.status if payment else Status.NONE

    def balance_of(self, address: str, token: Optional[str] = None) -> int:
        return self._balances.get((to_checksum_address(token or self.token_address), to_checksum_address(address)), 0)

    def _move(self, token: str, src: str, dst: str, amount: int) -> None:
        if self._balances.get((token, src), 0) < amount:
            raise ChainReverted("ERC20InsufficientBalance")
        self._balances[(token, src)] -= amount
        self._balances[(token, dst)] = self._balances.get((token, dst), 0) + amount

    # Placeholder address of the escrow contract in the mock ledger.
    ESCROW = to_checksum_address("0x000000000000000000000000000000000000e5c0")

    # ------------------------------------------------------------------ ChainPort

    def domain(self) -> Eip712Domain:
        return self._domain

    def commit(self, intent: PaymentIntent, router_sig: bytes) -> TxRef:
        with self._lock:
            if self._status(intent.payment_id) != Status.NONE:
                raise ChainReverted("InvalidTransition")
            if self._now() > intent.valid_until:
                raise ChainReverted("IntentExpired")
            signer = self._signer(intent, router_sig, self._router)
            self._use_nonce(signer, intent.nonce)
            self._payments[intent.payment_id] = _Payment(
                digest=eip712.digest(self._domain, intent),
                status=Status.COMMITTED,
                beneficiary=intent.beneficiary,
                token=intent.token,
                amount=intent.amount,
                tier=intent.tier,
                corridor_id=intent.corridor_id,
            )
            return self._tx()

    def deposit(self, intent: PaymentIntent, payer: str) -> TxRef:
        with self._lock:
            payment = self._payments.get(intent.payment_id)
            if payment is None or payment.status != Status.COMMITTED:
                raise ChainReverted("InvalidTransition")
            if eip712.digest(self._domain, intent) != payment.digest:
                raise ChainReverted("CommitmentMismatch")
            if payment.tier != Tier.MEDIUM:
                raise ChainReverted("TierNotEscrowable")
            if intent.payment_id in self._holds:
                raise ChainReverted("AlreadyDeposited")
            payer = to_checksum_address(payer)
            self._move(payment.token, payer, self.ESCROW, payment.amount)
            self._holds[intent.payment_id] = _Hold(
                payer=payer,
                beneficiary=payment.beneficiary,
                token=payment.token,
                amount=payment.amount,
                expires_at=self._now() + self.hold_seconds,
            )
            return self._tx()

    def record_verification(self, att: VerificationAttestation, verifier_sig: bytes) -> TxRef:
        with self._lock:
            payment = self._payments.get(att.payment_id)
            if payment is None or payment.status != Status.COMMITTED:
                raise ChainReverted("InvalidTransition")
            if att.intent_hash != payment.digest:
                raise ChainReverted("CommitmentMismatch")
            signer = self._signer(att, verifier_sig, self._verifier)
            self._use_nonce(signer, att.nonce)
            payment.status = Status.CONFIRMED if att.result == VerificationResult.CONFIRMED else Status.DENIED
            return self._tx()

    def revoke(self, rev: Revocation, analyst_sig: bytes) -> TxRef:
        with self._lock:
            payment = self._payments.get(rev.payment_id)
            if payment is None or payment.status not in (Status.COMMITTED, Status.CONFIRMED, Status.DENIED):
                raise ChainReverted("InvalidTransition")
            signer = self._signer(rev, analyst_sig, self._analyst)
            self._use_nonce(signer, rev.nonce)
            payment.status = Status.REVOKED
            return self._tx()

    def release(self, payment_id: bytes, caller: str = "relayer") -> TxRef:
        """Anyone may call release; it only succeeds for a CONFIRMED, open, unfrozen, unexpired hold."""
        with self._lock:
            payment_id = bytes(payment_id)
            payment = self._payments.get(payment_id)
            hold = self._holds.get(payment_id)
            releasable = (
                payment is not None
                and hold is not None
                and not hold.settled
                and not hold.frozen
                and self._now() <= hold.expires_at
                and payment.corridor_id not in self._paused
                and payment.status == Status.CONFIRMED
            )
            if not releasable:
                # An attacker's transaction is sent anyway, so the failure is visible (as on Fuji in v1).
                raise ChainReverted("PaymentNotReleasable", tx=self._tx() if caller == "attacker" else None)
            hold.settled = True
            self._move(hold.token, self.ESCROW, hold.beneficiary, hold.amount)
            payment.status = Status.EXECUTED
            return self._tx()

    def refund(self, payment_id: bytes) -> TxRef:
        with self._lock:
            payment_id = bytes(payment_id)
            payment = self._payments.get(payment_id)
            hold = self._holds.get(payment_id)
            if payment is None or hold is None:
                raise ChainReverted("UnknownPayment")
            if hold.settled:
                raise ChainReverted("AlreadySettled")
            expired = self._now() > hold.expires_at
            if payment.status != Status.REVOKED and not expired:
                raise ChainReverted("NotRefundable")  # the relayer is not an analyst
            hold.settled = True
            self._move(hold.token, self.ESCROW, hold.payer, hold.amount)
            return self._tx()

    def mark_executed(self, payment_id: bytes, execution_ref: bytes) -> TxRef:
        with self._lock:
            payment = self._payments.get(bytes(payment_id))
            allowed = payment is not None and (
                (payment.status == Status.COMMITTED and payment.tier == Tier.LOW) or payment.status == Status.CONFIRMED
            )
            if not allowed:
                raise ChainReverted("InvalidTransition")
            payment.status = Status.EXECUTED
            return self._tx()

    def status(self, payment_id: bytes) -> Status:
        with self._lock:
            return self._status(payment_id)

    def intent_hash(self, payment_id: bytes) -> bytes:
        with self._lock:
            payment = self._payments.get(bytes(payment_id))
            return payment.digest if payment else ZERO32

    # ------------------------------------------------------------------ mock-only helpers

    def hold_expires_at(self, payment_id: bytes) -> Optional[float]:
        hold = self._holds.get(bytes(payment_id))
        return hold.expires_at if hold else None

    def forget(self, payment_id: bytes) -> None:
        """Drop one payment so a demo scenario can be run again with the same id (mock only)."""
        with self._lock:
            payment_id = bytes(payment_id)
            hold = self._holds.pop(payment_id, None)
            if hold and not hold.settled:
                self._move(hold.token, self.ESCROW, hold.payer, hold.amount)
            self._payments.pop(payment_id, None)
