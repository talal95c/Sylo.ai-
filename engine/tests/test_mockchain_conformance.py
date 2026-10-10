import time

import pytest

from sylo_spec.canonical import hash_record, keccak_text, to_bytes32, to_hex
from sylo_spec.conformance import run_chain_conformance
from sylo_spec.devkeys import dev_address, dev_key
from sylo_spec.eip712 import digest, sign
from sylo_spec.models import PaymentIntent, Status, Tier, VerificationAttestation
from sylo_spec.ports import ChainPort, ChainReverted

from sylo.chain_mock import MockChain
from sylo.orchestrator import DEFAULT_TOKEN


def test_mock_chain_passes_the_chain_conformance_suite():
    run_chain_conformance(MockChain, token=DEFAULT_TOKEN, payer=dev_address("eu_casp"))


def test_mock_chain_implements_the_port():
    assert isinstance(MockChain(), ChainPort)


class Clock:
    def __init__(self) -> None:
        self.t = time.time()

    def __call__(self) -> float:
        return self.t


def _medium_intent(clock: Clock, label: str) -> PaymentIntent:
    return PaymentIntent(
        payment_id=to_hex(keccak_text(label)),
        corridor_id=to_hex(keccak_text("FR-GH")),
        beneficiary=dev_address("gh_vasp"),
        token=DEFAULT_TOKEN,
        amount=85_000_000_000,
        offchain_hash=hash_record({"l": label}),
        decision_hash=hash_record({"d": label}),
        approval_hash=hash_record({"a": label}),
        tier=int(Tier.MEDIUM),
        valid_until=int(clock()) + 600,
        nonce=abs(hash(label)) % 10**9,
    )


def _committed_and_deposited(label: str):
    clock = Clock()
    chain = MockChain(clock=clock, hold_seconds=3600)
    intent = _medium_intent(clock, label)
    chain.commit(intent, sign(intent, chain.domain(), dev_key("router_signer")))
    chain.deposit(intent, dev_address("eu_casp"))
    return chain, clock, intent


def test_expired_intent_cannot_be_committed():
    clock = Clock()
    chain = MockChain(clock=clock)
    intent = _medium_intent(clock, "expired")
    clock.t += 601
    with pytest.raises(ChainReverted, match="IntentExpired"):
        chain.commit(intent, sign(intent, chain.domain(), dev_key("router_signer")))


def test_anyone_can_refund_after_expiry_and_release_is_refused():
    chain, clock, intent = _committed_and_deposited("expiry")
    pid = to_bytes32(intent.payment_id)
    with pytest.raises(ChainReverted, match="RefundNotAllowed"):
        chain.refund(pid)
    clock.t += 3601
    with pytest.raises(ChainReverted, match="PaymentNotReleasable"):
        chain.release(pid)
    chain.refund(pid)
    assert chain.status(pid) == Status.COMMITTED


def test_frozen_hold_cannot_be_released():
    chain, clock, intent = _committed_and_deposited("frozen")
    att = VerificationAttestation(
        payment_id=intent.payment_id,
        intent_hash=to_hex(digest(intent, chain.domain())),
        method=1,
        result=1,
        sim_swap_checked=True,
        evidence_hash=hash_record({"e": 1}),
        verified_at=int(clock()),
        nonce=1,
    )
    chain.record_verification(att, sign(att, chain.domain(), dev_key("verifier_signer")))
    chain.freeze(to_bytes32(intent.payment_id))
    with pytest.raises(ChainReverted, match="PaymentNotReleasable"):
        chain.release(to_bytes32(intent.payment_id))


def test_attestation_must_bind_the_committed_intent():
    chain, clock, intent = _committed_and_deposited("binding")
    att = VerificationAttestation(
        payment_id=intent.payment_id,
        intent_hash=hash_record({"some": "other intent"}),
        method=1,
        result=1,
        sim_swap_checked=True,
        evidence_hash=hash_record({"e": 1}),
        verified_at=int(clock()),
        nonce=1,
    )
    with pytest.raises(ChainReverted, match="CommitmentMismatch"):
        chain.record_verification(att, sign(att, chain.domain(), dev_key("verifier_signer")))


SECP256K1_ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141


def test_malleable_or_badly_encoded_signature_is_refused_like_the_contract():
    clock = Clock()
    chain = MockChain(clock=clock)
    intent = _medium_intent(clock, "malleable")
    sig = sign(intent, chain.domain(), dev_key("router_signer"))
    high_s = (SECP256K1_ORDER - int.from_bytes(sig[32:64], "big")).to_bytes(32, "big")
    twin = sig[:32] + high_s + bytes([55 - sig[64]])
    for bad in (twin, sig[:64] + bytes([sig[64] - 27]), sig[:64]):
        with pytest.raises(ChainReverted) as err:
            chain.commit(intent, bad)
        assert err.value.reason == "UnauthorizedSigner"
    chain.commit(intent, sig)
