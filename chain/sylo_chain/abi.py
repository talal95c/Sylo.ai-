"""Contract ABIs (copied from Foundry by scripts/export-abi.sh) and custom-error decoding."""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from typing import Any

from eth_utils import keccak

CONTRACTS = ("PaymentRegistry", "PaymentEscrow", "MockEURC")


@cache
def load_abi(contract: str) -> list[dict[str, Any]]:
    return json.loads(resources.files("sylo_chain").joinpath("abi", f"{contract}.json").read_text())


def _canonical_type(param: dict[str, Any]) -> str:
    kind = param["type"]
    if kind.startswith("tuple"):
        return "(" + ",".join(_canonical_type(c) for c in param["components"]) + ")" + kind[len("tuple") :]
    return kind


@cache
def error_names() -> dict[bytes, str]:
    """4-byte selector -> custom error name, across every contract the escrow can bubble errors from."""
    names: dict[bytes, str] = {}
    for contract in CONTRACTS:
        for item in load_abi(contract):
            if item.get("type") == "error":
                signature = f"{item['name']}({','.join(_canonical_type(p) for p in item['inputs'])})"
                names[keccak(text=signature)[:4]] = item["name"]
    return names


_ERROR_STRING = keccak(text="Error(string)")[:4]
_PANIC = keccak(text="Panic(uint256)")[:4]


def decode_revert(data: bytes | str | None) -> str:
    """Revert data -> the Solidity error name (``CommitmentMismatch``), ``Error`` or ``Panic``, else ``Reverted``."""
    if isinstance(data, str):
        data = bytes.fromhex(data.removeprefix("0x")) if data.startswith("0x") else b""
    if not data or len(data) < 4:
        return "Reverted"
    selector = data[:4]
    if selector == _ERROR_STRING:
        return "Error"
    if selector == _PANIC:
        return "Panic"
    return error_names().get(selector, "Reverted")
