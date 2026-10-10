"""Conformance suite for `ChainPort` implementations.

    from sylo_spec.conformance import run_chain_conformance
    run_chain_conformance(lambda: MockChain())

`make_chain` must return a FRESH chain for every call (a new mock, or a new
deployment on Anvil). The seven steps mirror the contract rules: MockChain passes
them in v0, FujiChain must pass the same steps in v1.

On a persistent chain, pass `id_prefix` and `nonce_start` values that were never
used before, and the role keys that the deployed contracts know (`keys`).
"""

import itertools
import time
from dataclasses import dataclass
from typing import Callable, Optional

from .. import eip712
from ..canonical import corridor_id_bytes, payment_id_bytes, record_hash
from ..devkeys import dev_keys
from ..models import (
    PaymentIntent,
    Revocation,
    RevocationReason,
    Status,
    Tier,
    TxRef,
    VerificationAttestation,
    VerificationMethod,
    VerificationResult,
)
from ..ports import ChainPort, ChainReverted

DEFAULT_TOKEN = "0x0000000000000000000000000000000000000E0C"
AMOUNT = 85_000 * 10**6  # EUR 85,000 with 6 decimals


@dataclass
class RoleKeys:
    router_pk: str
    verifier_pk: str
    analyst_pk: str
    outsider_pk: str  # a key that holds no role
    payer: str  # address that funds the escrow (EU CASP treasury)
    beneficiary: str  # address fixed in the intent (GH VASP)

    @classmethod
    def dev(cls) -> "RoleKeys":
        k = dev_keys()
        return cls(
            router_pk=k["router_signer"].private_key,
            verifier_pk=k["verifier_signer"].private_key,
            analyst_pk=k["analyst_signer"].private_key,
            outsider_pk=k["attacker"].private_key,
            payer=k["eu_casp"].address,
            beneficiary=k["gh_vasp"].address,
        )


class _Env:
    def __init__(self, chain: ChainPort, keys: RoleKeys, token: str, id_prefix: str, nonces: "itertools.count"):
        self.chain = chain
        self.keys = keys
        self.token = token
        self.id_prefix = id_prefix
        self.nonces = nonces
        self.domain = chain.domain()

    def intent(self, label: str, tier: Tier, nonce: Optional[int] = None, amount: int = AMOUNT) -> PaymentIntent:
        return PaymentIntent(
            payment_id=payment_id_bytes(f"{self.id_prefix}-{label}"),
            corridor_id=corridor_id_bytes("FR-GH"),
            beneficiary=self.keys.beneficiary,
            token=self.token,
            amount=amount,
            offchain_hash=record_hash({"label": label}),
            decision_hash=record_hash({"decision": label, "tier": tier.name}),
            approval_hash=record_hash({"approval": label}),
            tier=tier,
            valid_until=int(time.time()) + 600,
            nonce=next(self.nonces) if nonce is None else nonce,
        )

    def commit(self, intent: PaymentIntent, pk: Optional[str] = None) -> TxRef:
        return self.chain.commit(intent, eip712.sign(self.domain, intent, pk or self.keys.router_pk))

    def verify(self, intent: PaymentIntent, result: VerificationResult) -> TxRef:
        att = VerificationAttestation(
            payment_id=intent.payment_id,
            intent_hash=eip712.digest(self.domain, intent),
            method=VerificationMethod.OOB_KNOWN_CONTACT,
            result=result,
            sim_swap_checked=True,
            evidence_hash=record_hash({"result": result.name}),
            verified_at=int(time.time()),
            nonce=next(self.nonces),
        )
        return self.chain.record_verification(att, eip712.sign(self.domain, att, self.keys.verifier_pk))

    def revoke(self, intent: PaymentIntent) -> TxRef:
        rev = Revocation(
            payment_id=intent.payment_id,
            reason_code=RevocationReason.SUPPLIER_DENIED,
            case_hash=record_hash({"case": "conformance"}),
            nonce=next(self.nonces),
        )
        return self.chain.revoke(rev, eip712.sign(self.domain, rev, self.keys.analyst_pk))


def _expect_revert(reason: str, call: Callable[[], object]) -> None:
    try:
        call()
    except ChainReverted as err:
        assert err.reason == reason, f"expected revert {reason}, got {err.reason}"
        return
    raise AssertionError(f"expected revert {reason}, but the call succeeded")


def _assert_tx(tx: TxRef) -> None:
    assert isinstance(tx, TxRef), f"chain calls must return a TxRef, got {type(tx).__name__}"
    assert tx.tx_hash.startswith("0x") and len(tx.tx_hash) == 66, f"bad transaction hash: {tx.tx_hash}"


def _status(env: _Env, intent: PaymentIntent, expected: Status) -> None:
    actual = env.chain.status(intent.payment_id)
    assert actual == expected, f"expected status {expected.name}, got {Status(actual).name}"


# --------------------------------------------------------------------------- the seven steps


def step_1_commit(env: _Env) -> None:
    """Commit signed by the router key → COMMITTED. Committing the same payment again → InvalidTransition."""
    intent = env.intent("s1", Tier.MEDIUM)
    _status(env, intent, Status.NONE)
    _assert_tx(env.commit(intent))
    _status(env, intent, Status.COMMITTED)
    assert env.chain.intent_hash(intent.payment_id) == eip712.digest(env.domain, intent), (
        "intent_hash() must return the EIP-712 digest of the committed intent"
    )
    _expect_revert("InvalidTransition", lambda: env.commit(intent))


def step_2_unauthorized_signer(env: _Env) -> None:
    """Commit signed by a non-router key → UnauthorizedSigner."""
    intent = env.intent("s2", Tier.LOW)
    _expect_revert("UnauthorizedSigner", lambda: env.commit(intent, pk=env.keys.outsider_pk))
    _status(env, intent, Status.NONE)


def step_3_nonce_reuse(env: _Env) -> None:
    """Reusing a nonce for the same signer → NonceUsed."""
    first = env.intent("s3a", Tier.LOW)
    env.commit(first)
    second = env.intent("s3b", Tier.LOW, nonce=first.nonce)
    _expect_revert("NonceUsed", lambda: env.commit(second))
    _status(env, second, Status.NONE)


def step_4_deposit_guards(env: _Env) -> None:
    """Deposit with a different amount → CommitmentMismatch. Deposit of a LOW intent → TierNotEscrowable."""
    medium = env.intent("s4a", Tier.MEDIUM)
    env.commit(medium)
    tampered = medium.model_copy(update={"amount": medium.amount + 1})
    _expect_revert("CommitmentMismatch", lambda: env.chain.deposit(tampered, env.keys.payer))
    low = env.intent("s4b", Tier.LOW)
    env.commit(low)
    _expect_revert("TierNotEscrowable", lambda: env.chain.deposit(low, env.keys.payer))


def step_5_deny_revoke_refund(env: _Env) -> None:
    """MEDIUM: commit, deposit, DENIED, revoke → release reverts, refund works once."""
    intent = env.intent("s5", Tier.MEDIUM)
    env.commit(intent)
    _assert_tx(env.chain.deposit(intent, env.keys.payer))
    _assert_tx(env.verify(intent, VerificationResult.DENIED))
    _status(env, intent, Status.DENIED)
    _assert_tx(env.revoke(intent))
    _status(env, intent, Status.REVOKED)
    _expect_revert("PaymentNotReleasable", lambda: env.chain.release(intent.payment_id))
    _assert_tx(env.chain.refund(intent.payment_id))
    _expect_revert("AlreadySettled", lambda: env.chain.refund(intent.payment_id))
    _status(env, intent, Status.REVOKED)


def step_6_confirm_release(env: _Env) -> None:
    """MEDIUM: commit, deposit, CONFIRMED → release succeeds → EXECUTED."""
    intent = env.intent("s6", Tier.MEDIUM)
    env.commit(intent)
    env.chain.deposit(intent, env.keys.payer)
    env.verify(intent, VerificationResult.CONFIRMED)
    _status(env, intent, Status.CONFIRMED)
    _assert_tx(env.chain.release(intent.payment_id))
    _status(env, intent, Status.EXECUTED)


def step_7_low_executed(env: _Env) -> None:
    """LOW: commit → mark_executed → EXECUTED."""
    intent = env.intent("s7", Tier.LOW)
    env.commit(intent)
    _assert_tx(env.chain.mark_executed(intent.payment_id, record_hash({"execution": "s7"})))
    _status(env, intent, Status.EXECUTED)


STEPS = (
    step_1_commit,
    step_2_unauthorized_signer,
    step_3_nonce_reuse,
    step_4_deposit_guards,
    step_5_deny_revoke_refund,
    step_6_confirm_release,
    step_7_low_executed,
)


def run_chain_conformance(
    make_chain: Callable[[], ChainPort],
    *,
    keys: Optional[RoleKeys] = None,
    token: Optional[str] = None,
    id_prefix: str = "CONF",
    nonce_start: int = 1,
) -> list[str]:
    """Run every step on a fresh chain. Returns the names of the steps that passed."""
    keys = keys or RoleKeys.dev()
    nonces = itertools.count(nonce_start)
    passed = []
    for step in STEPS:
        chain = make_chain()
        assert isinstance(getattr(chain, "mode", None), str), "ChainPort.mode must be a string"
        env = _Env(chain, keys, token or getattr(chain, "token_address", DEFAULT_TOKEN), id_prefix, nonces)
        try:
            step(env)
        except AssertionError as err:
            raise AssertionError(f"{step.__name__}: {err}") from err
        passed.append(step.__name__)
    return passed
