"""Canonical JSON and keccak helpers (v0 spec §4.4, hashing conventions)."""

from __future__ import annotations

import json
from typing import Any

from eth_utils import keccak


def canonical_json(obj: Any) -> bytes:
    """Deterministic JSON bytes: sorted keys, no spaces, UTF-8."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def keccak256(data: bytes) -> bytes:
    return keccak(data)


def keccak_text(text: str) -> bytes:
    return keccak(text.encode("utf-8"))


def to_hex(data: bytes) -> str:
    return "0x" + data.hex()


def to_bytes32(value: bytes | str) -> bytes:
    """Accept 32 raw bytes or a 0x-prefixed 64-hex-digit string."""
    if isinstance(value, str):
        raw = bytes.fromhex(value[2:] if value.startswith("0x") else value)
    else:
        raw = bytes(value)
    if len(raw) != 32:
        raise ValueError(f"expected 32 bytes, got {len(raw)}")
    return raw


def hash_record(obj: Any) -> str:
    """keccak256(canonical_json(obj)) as 0x-hex: decisionHash, approvalHash, evidenceHash, caseHash."""
    return to_hex(keccak(canonical_json(obj)))


def payment_id_of(order_id: str) -> str:
    """bytes32 paymentId = keccak256(utf8(order id)), e.g. "PAY-2026-0001"."""
    return to_hex(keccak_text(order_id))


def corridor_id_of(corridor: str) -> str:
    """bytes32 corridorId = keccak256(utf8(corridor)), e.g. "FR-GH"."""
    return to_hex(keccak_text(corridor))


def offchain_hash(salt: bytes, fields: dict[str, Any]) -> str:
    """keccak256(salt32 || canonical_json(off-chain fields)); the salt hides the fields from guessing."""
    if len(salt) != 32:
        raise ValueError("salt must be 32 bytes")
    return to_hex(keccak(salt + canonical_json(fields)))
