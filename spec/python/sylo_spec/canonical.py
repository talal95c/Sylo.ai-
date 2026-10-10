"""Canonical JSON and keccak helpers (hashing conventions of the build spec, section 4.4)."""

import json
from typing import Any

from eth_utils import keccak


def canonical_json(value: Any) -> bytes:
    """Deterministic JSON bytes: sorted keys, no spaces, UTF-8, non-ASCII kept as is."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def keccak_text(text: str) -> bytes:
    return keccak(text=text)


def payment_id_bytes(payment_id: str) -> bytes:
    """bytes32 id used on-chain: keccak256(utf8("PAY-2026-0001"))."""
    return keccak(text=payment_id)


def corridor_id_bytes(corridor: str) -> bytes:
    """bytes32 corridor id: keccak256(utf8("FR-GH"))."""
    return keccak(text=corridor)


def record_hash(record: Any) -> bytes:
    """decisionHash, approvalHash, evidenceHash, caseHash = keccak256(canonical_json(record))."""
    return keccak(canonical_json(record))


def offchain_hash(salt: bytes, fields: dict[str, Any]) -> bytes:
    """keccak256(salt32 ‖ canonical_json(fields)): nothing personal is readable or guessable on-chain."""
    if len(salt) != 32:
        raise ValueError("salt must be 32 bytes")
    return keccak(salt + canonical_json(fields))


def hex0x(value: bytes) -> str:
    return "0x" + value.hex()
