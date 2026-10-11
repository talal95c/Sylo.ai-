"""FujiChain against the real contracts on a local Anvil chain (needs Foundry; runs in CI)."""

from __future__ import annotations

import pytest
from conftest import AnvilDeployment, commit, confirm, make_intent
from sylo_chain import FujiChain
from sylo_spec.canonical import keccak_text
from sylo_spec.conformance import run_chain_conformance
from sylo_spec.devkeys import dev_address
from sylo_spec.models import Status, Tier
from sylo_spec.ports import ChainPort, ChainReverted
from web3 import Web3


def _receipt_status(anvil: AnvilDeployment, tx_hash: str) -> int:
    return Web3(Web3.HTTPProvider(anvil.rpc_url)).eth.get_transaction_receipt(tx_hash)["status"]


def test_passes_the_chain_conformance_suite(anvil: AnvilDeployment) -> None:
    run_chain_conformance(anvil.chain, token=anvil.token, payer=dev_address("eu_casp"))


def test_is_a_chain_port_with_real_tx_refs(anvil: AnvilDeployment) -> None:
    chain = anvil.chain()
    assert isinstance(chain, ChainPort)
    assert chain.mode == "anvil"
    assert chain.domain().chain_id == 31337
    assert chain.domain().verifying_contract == Web3.to_checksum_address(anvil.registry)
    ref = commit(chain, make_intent(chain, anvil.token, Tier.LOW))
    assert ref.simulated is False
    assert ref.explorer_url is None
    assert ref.block_number is not None and ref.tx_hash.startswith("0x") and len(ref.tx_hash) == 66


def test_engine_reverts_are_simulated_and_not_sent(anvil: AnvilDeployment) -> None:
    chain = anvil.chain()
    intent = make_intent(chain, anvil.token)
    commit(chain, intent)
    with pytest.raises(ChainReverted) as err:
        chain.deposit(intent.model_copy(update={"amount": intent.amount + 1}), dev_address("eu_casp"))
    assert (err.value.reason, err.value.tx, err.value.function) == ("CommitmentMismatch", None, "deposit")


def test_attacker_release_is_mined_as_a_failed_transaction(anvil: AnvilDeployment) -> None:
    chain = anvil.chain()
    intent = make_intent(chain, anvil.token)
    commit(chain, intent)
    chain.deposit(intent, dev_address("eu_casp"))
    with pytest.raises(ChainReverted) as err:
        chain.release(intent.payment_id, caller="attacker")
    assert err.value.reason == "PaymentNotReleasable"
    assert err.value.tx is not None and err.value.tx.simulated is False
    assert _receipt_status(anvil, err.value.tx.tx_hash) == 0
    assert chain.status(intent.payment_id) == Status.COMMITTED


def test_visible_failures_mines_a_tampered_deposit(anvil: AnvilDeployment) -> None:
    chain = anvil.chain()
    intent = make_intent(chain, anvil.token)
    commit(chain, intent)
    swapped = intent.model_copy(update={"beneficiary": dev_address("attacker")})
    with chain.visible_failures(), pytest.raises(ChainReverted) as err:
        chain.deposit(swapped, dev_address("eu_casp"))
    assert err.value.reason == "CommitmentMismatch"
    assert err.value.tx is not None and _receipt_status(anvil, err.value.tx.tx_hash) == 0
    chain.deposit(intent, dev_address("eu_casp"))


def test_freeze_blocks_release(anvil: AnvilDeployment) -> None:
    chain = anvil.chain()
    intent = make_intent(chain, anvil.token)
    commit(chain, intent)
    chain.deposit(intent, dev_address("eu_casp"))
    confirm(chain, intent)
    chain.freeze(intent.payment_id)
    with pytest.raises(ChainReverted, match="PaymentNotReleasable"):
        chain.release(intent.payment_id)


def test_pause_corridor_blocks_release(anvil: AnvilDeployment) -> None:
    chain = anvil.chain()
    intent = make_intent(chain, anvil.token)
    commit(chain, intent)
    chain.deposit(intent, dev_address("eu_casp"))
    confirm(chain, intent)
    chain.pause_corridor(intent.corridor_id)
    with pytest.raises(ChainReverted, match="PaymentNotReleasable"):
        chain.release(intent.payment_id)


def test_only_the_guardian_pauses_a_corridor(anvil: AnvilDeployment) -> None:
    chain = anvil.chain()
    with pytest.raises(ChainReverted, match="AccessControlUnauthorizedAccount"):
        chain.pause_corridor(keccak_text("FR-GH"), caller="relayer")


def test_refuses_a_node_on_another_chain(anvil: AnvilDeployment) -> None:
    with pytest.raises(ValueError, match="refusing to start"):
        anvil.chain(chain_id=43113)


def test_skips_a_dead_rpc_endpoint(anvil: AnvilDeployment) -> None:
    chain = anvil.chain(rpc_urls=["http://127.0.0.1:9", anvil.rpc_url], rpc_timeout=1.0)
    assert chain.status(keccak_text("nothing")) == Status.NONE


def test_fails_over_when_the_current_endpoint_dies(anvil: AnvilDeployment) -> None:
    chain = anvil.chain(rpc_urls=[anvil.rpc_url, anvil.rpc_url], rpc_timeout=1.0)
    chain._providers[0] = Web3(Web3.HTTPProvider("http://127.0.0.1:9", request_kwargs={"timeout": 1.0}))
    intent = make_intent(chain, anvil.token, Tier.LOW)
    commit(chain, intent)
    assert chain.status(intent.payment_id) == Status.COMMITTED


def test_refuses_without_a_relayer_key(anvil: AnvilDeployment) -> None:
    with pytest.raises(ValueError, match="relayer"):
        anvil.chain(keys={})


def test_from_env_runs_on_fuji_only() -> None:
    with pytest.raises(ValueError, match="Fuji only"):
        FujiChain.from_env({"CHAIN_ID": "31337", "FUJI_RPC_URL": "http://127.0.0.1:8545", "RELAYER_PK": "0x01"})
    with pytest.raises(ValueError, match="FUJI_RPC_URL"):
        FujiChain.from_env({"RELAYER_PK": "0x01"})
