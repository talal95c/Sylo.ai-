"""Chain conformance suite (v0 spec §4.7).

``run_chain_conformance(make_chain, token=..., payer=...)`` runs seven steps, each on a fresh
chain from ``make_chain()``. Payment ids and nonces are random, so the suite can also run
against a persistent chain (Anvil or Fuji) where earlier runs left state behind.
"""

from __future__ import annotations

import secrets
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..canonical import hash_record, keccak_text, to_bytes32, to_hex
from ..devkeys import dev_address, dev_key
from ..eip712 import digest, sign
from ..models import (
    PaymentIntent,
    Revocation,
    RevocationReason,
    Status,
    Tier,
    VerificationAttestation,
    VerificationMethod,
    VerificationResult,
)
from ..ports import ChainPort, ChainReverted

AMOUNT = 85_000 * 10**6


@dataclass(frozen=True)
class ConformanceKeys:
    router: str = field(default_factory=lambda: dev_key("router_signer"))
    verifier: str = field(default_factory=lambda: dev_key("verifier_signer"))
    analyst: str = field(default_factory=lambda: dev_key("analyst_signer"))
    outsider: str = field(default_factory=lambda: dev_key("attacker"))
    beneficiary: str = field(default_factory=lambda: dev_address("gh_vasp"))


def _expect_revert(reason: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    try:
        fn(*args, **kwargs)
    except ChainReverted as err:
        assert err.reason == reason, f"expected revert {reason}, got {err.reason}"
        return
    raise AssertionError(f"expected revert {reason}, but the call succeeded")


def _nonce() -> int:
    return secrets.randbits(63)


class _Run:
    def __init__(self, chain: ChainPort, token: str, payer: str, keys: ConformanceKeys, now: Callable[[], float]):
        self.chain = chain
        self.token = token
        self.payer = payer
        self.keys = keys
        self.now = now

    def intent(self, tier: Tier, *, amount: int = AMOUNT, nonce: int | None = None) -> PaymentIntent:
        label = f"CONFORMANCE-{uuid.uuid4()}"
        return PaymentIntent(
            payment_id=to_hex(keccak_text(label)),
            corridor_id=to_hex(keccak_text("FR-GH")),
            beneficiary=self.keys.beneficiary,
            token=self.token,
            amount=amount,
            offchain_hash=hash_record({"label": label, "part": "offchain"}),
            decision_hash=hash_record({"label": label, "part": "decision"}),
            approval_hash=hash_record({"label": label, "part": "approval"}),
            tier=int(tier),
            valid_until=int(self.now()) + 600,
            nonce=_nonce() if nonce is None else nonce,
        )

    def commit(self, intent: PaymentIntent, key: str | None = None) -> None:
        self.chain.commit(intent, sign(intent, self.chain.domain(), key or self.keys.router))

    def attest(self, intent: PaymentIntent, result: VerificationResult) -> None:
        att = VerificationAttestation(
            payment_id=intent.payment_id,
            intent_hash=to_hex(digest(intent, self.chain.domain())),
            method=int(VerificationMethod.OOB_KNOWN_CONTACT),
            result=int(result),
            sim_swap_checked=True,
            evidence_hash=hash_record({"paymentId": intent.payment_id, "result": int(result)}),
            verified_at=int(self.now()),
            nonce=_nonce(),
        )
        self.chain.record_verification(att, sign(att, self.chain.domain(), self.keys.verifier))

    def revoke(self, intent: PaymentIntent) -> None:
        rev = Revocation(
            payment_id=intent.payment_id,
            reason_code=int(RevocationReason.SUPPLIER_DENIED),
            case_hash=hash_record({"paymentId": intent.payment_id, "case": "conformance"}),
            nonce=_nonce(),
        )
        self.chain.revoke(rev, sign(rev, self.chain.domain(), self.keys.analyst))

    def status(self, intent: PaymentIntent) -> Status:
        return Status(int(self.chain.status(to_bytes32(intent.payment_id))))

    def pid(self, intent: PaymentIntent) -> bytes:
        return to_bytes32(intent.payment_id)


def _step1_commit_once(run: _Run) -> None:
    intent = run.intent(Tier.LOW)
    run.commit(intent)
    assert run.status(intent) == Status.COMMITTED, "commit must set status COMMITTED"
    assert run.chain.intent_hash(run.pid(intent)) == digest(intent, run.chain.domain()), "stored intent hash differs"
    again = intent.model_copy(update={"nonce": _nonce()})
    _expect_revert("InvalidTransition", run.commit, again)


def _step2_router_only(run: _Run) -> None:
    _expect_revert("UnauthorizedSigner", run.commit, run.intent(Tier.LOW), run.keys.outsider)


def _step3_nonce_reuse(run: _Run) -> None:
    nonce = _nonce()
    run.commit(run.intent(Tier.LOW, nonce=nonce))
    _expect_revert("NonceUsed", run.commit, run.intent(Tier.LOW, nonce=nonce))


def _step4_deposit_checks(run: _Run) -> None:
    medium = run.intent(Tier.MEDIUM)
    run.commit(medium)
    tampered = medium.model_copy(update={"amount": medium.amount + 1})
    _expect_revert("CommitmentMismatch", run.chain.deposit, tampered, run.payer)
    low = run.intent(Tier.LOW)
    run.commit(low)
    _expect_revert("TierNotEscrowable", run.chain.deposit, low, run.payer)


def _step5_deny_revoke_refund(run: _Run) -> None:
    intent = run.intent(Tier.MEDIUM)
    run.commit(intent)
    run.chain.deposit(intent, run.payer)
    run.attest(intent, VerificationResult.DENIED)
    assert run.status(intent) == Status.DENIED, "a DENIED attestation must set status DENIED"
    run.revoke(intent)
    assert run.status(intent) == Status.REVOKED, "revoke must set status REVOKED"
    _expect_revert("PaymentNotReleasable", run.chain.release, run.pid(intent), "attacker")
    run.chain.refund(run.pid(intent))
    _expect_revert("AlreadySettled", run.chain.refund, run.pid(intent))


def _step6_confirm_release(run: _Run) -> None:
    intent = run.intent(Tier.MEDIUM)
    run.commit(intent)
    run.chain.deposit(intent, run.payer)
    run.attest(intent, VerificationResult.CONFIRMED)
    assert run.status(intent) == Status.CONFIRMED, "a CONFIRMED attestation must set status CONFIRMED"
    run.chain.release(run.pid(intent))
    assert run.status(intent) == Status.EXECUTED, "release must set status EXECUTED"


def _step7_low_executed(run: _Run) -> None:
    intent = run.intent(Tier.LOW)
    run.commit(intent)
    run.chain.mark_executed(run.pid(intent), keccak_text("conformance-execution"))
    assert run.status(intent) == Status.EXECUTED, "mark_executed must set status EXECUTED"


STEPS: tuple[Callable[[_Run], None], ...] = (
    _step1_commit_once,
    _step2_router_only,
    _step3_nonce_reuse,
    _step4_deposit_checks,
    _step5_deny_revoke_refund,
    _step6_confirm_release,
    _step7_low_executed,
)


def run_chain_conformance(
    make_chain: Callable[[], ChainPort],
    *,
    token: str,
    payer: str,
    keys: ConformanceKeys | None = None,
    now: Callable[[], float] = time.time,
) -> None:
    """Run every step on a fresh chain. ``payer`` must hold and have approved ``token`` for the escrow."""
    keys = keys or ConformanceKeys()
    for step in STEPS:
        try:
            step(_Run(make_chain(), token, payer, keys, now))
        except AssertionError as err:
            raise AssertionError(f"{step.__name__}: {err}") from err
