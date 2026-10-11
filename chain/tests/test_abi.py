from __future__ import annotations

import json
import subprocess

import pytest
from conftest import CONTRACTS, _tool
from eth_utils import keccak
from sylo_chain.abi import CONTRACTS as ABI_CONTRACTS
from sylo_chain.abi import decode_revert, load_abi


def _encoded(signature: str, payload: bytes = b"") -> bytes:
    return keccak(text=signature)[:4] + payload


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (_encoded("CommitmentMismatch()"), "CommitmentMismatch"),
        ("0x" + _encoded("PaymentNotReleasable()").hex(), "PaymentNotReleasable"),
        (_encoded("AccessControlUnauthorizedAccount(address,bytes32)", bytes(64)), "AccessControlUnauthorizedAccount"),
        (_encoded("ERC20InsufficientAllowance(address,uint256,uint256)", bytes(96)), "ERC20InsufficientAllowance"),
        (_encoded("Error(string)", bytes(64)), "Error"),
        (_encoded("Panic(uint256)", bytes(32)), "Panic"),
        (_encoded("SomethingElse()"), "Reverted"),
        (b"", "Reverted"),
        (None, "Reverted"),
    ],
)
def test_decode_revert(data: bytes | str | None, reason: str) -> None:
    assert decode_revert(data) == reason


@pytest.mark.parametrize("contract", ABI_CONTRACTS)
def test_vendored_abi_matches_the_contracts(contract: str) -> None:
    forge = _tool("forge")
    if not forge:
        pytest.skip("Foundry is not installed")
    out = subprocess.run(
        [forge, "inspect", contract, "abi", "--json"], cwd=CONTRACTS, capture_output=True, text=True, check=True
    ).stdout
    assert load_abi(contract) == json.loads(out), "ABI changed: run chain/scripts/export-abi.sh"
