import pytest

from sylo.chain_mock import MockChain
from sylo_spec import eip712
from sylo_spec.canonical import corridor_id_bytes, payment_id_bytes, record_hash
from sylo_spec.conformance import run_chain_conformance
from sylo_spec.devkeys import dev_address, dev_key
from sylo_spec.models import PaymentIntent, Status, Tier
from sylo_spec.ports import ChainPort, ChainReverted


def test_mockchain_passes_the_chain_conformance_suite():
    passed = run_chain_conformance(lambda: MockChain())
    assert len(passed) == 7


def test_mockchain_is_a_chainport_and_labels_its_transactions_simulated():
    chain = MockChain()
    assert isinstance(chain, ChainPort) and chain.mode == "mock"
    assert chain.domain().chain_id == 43113


def _intent(clock_now: float, tier=Tier.MEDIUM, nonce=1) -> PaymentIntent:
    return PaymentIntent(
        payment_id=payment_id_bytes("T-1"), corridor_id=corridor_id_bytes("FR-GH"),
        beneficiary=dev_address("gh_vasp"), token="0x0000000000000000000000000000000000000E0C",
        amount=85_000 * 10**6, offchain_hash=record_hash(1), decision_hash=record_hash(2), approval_hash=record_hash(3),
        tier=tier, valid_until=int(clock_now) + 600, nonce=nonce,
    )


def test_expiry_and_money_conservation():
    now = [1_000_000.0]
    chain = MockChain(clock=lambda: now[0], hold_seconds=3600)
    intent = _intent(now[0])
    sign = lambda i: eip712.sign(chain.domain(), i, dev_key("router_signer").private_key)

    # an expired intent cannot be committed
    now[0] += 601
    with pytest.raises(ChainReverted, match="IntentExpired"):
        chain.commit(intent, sign(intent))
    now[0] -= 601

    tx = chain.commit(intent, sign(intent))
    assert tx.simulated and tx.explorer_url is None and tx.tx_hash.startswith("0x")
    treasury, escrow = dev_address("eu_casp"), MockChain.ESCROW
    before = chain.balance_of(treasury)
    chain.deposit(intent, treasury)
    assert chain.balance_of(treasury) == before - intent.amount and chain.balance_of(escrow) == intent.amount

    # not revoked and not expired: nobody but an analyst can refund; not confirmed: nobody can release
    with pytest.raises(ChainReverted, match="NotRefundable"):
        chain.refund(intent.payment_id)
    with pytest.raises(ChainReverted, match="PaymentNotReleasable"):
        chain.release(intent.payment_id)

    # after expiry the refund is permissionless and the money goes back to the payer
    now[0] += 3601
    chain.refund(intent.payment_id)
    assert chain.balance_of(treasury) == before and chain.balance_of(escrow) == 0
    assert chain.balance_of(dev_address("gh_vasp")) == 0 and chain.balance_of(dev_address("attacker")) == 0
    assert chain.status(intent.payment_id) == Status.COMMITTED


def test_an_attacker_release_reverts_with_a_visible_failed_transaction():
    chain = MockChain()
    with pytest.raises(ChainReverted) as info:
        chain.release(payment_id_bytes("nothing"), caller="attacker")
    assert info.value.reason == "PaymentNotReleasable" and info.value.tx is not None and info.value.tx.simulated
