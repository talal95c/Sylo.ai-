"""EIP-712 typed data for Sylo.ai (PRD §13.4, v0 spec §4.4).

Struct hashes and digests are computed by hand (so Solidity can mirror them line by line) and
signing goes through eth-account; the tests check that both paths agree.

Regenerate the shared test vector with ``python -m sylo_spec.eip712 --write``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Union

from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import keccak, to_checksum_address

from . import SPEC_DIR
from .canonical import hash_record, keccak_text, to_bytes32, to_hex
from .models import (
    Eip712Domain,
    PaymentIntent,
    Revocation,
    RevocationReason,
    Status,
    Tier,
    VerificationAttestation,
    VerificationMethod,
    VerificationResult,
)

DOMAIN_NAME = "SyloPaymentRegistry"
DOMAIN_VERSION = "1"

EIP712_DOMAIN_FIELDS = [
    {"name": "name", "type": "string"},
    {"name": "version", "type": "string"},
    {"name": "chainId", "type": "uint256"},
    {"name": "verifyingContract", "type": "address"},
]

TYPES: dict[str, list[dict[str, str]]] = {
    "PaymentIntent": [
        {"name": "paymentId", "type": "bytes32"},
        {"name": "corridorId", "type": "bytes32"},
        {"name": "beneficiary", "type": "address"},
        {"name": "token", "type": "address"},
        {"name": "amount", "type": "uint256"},
        {"name": "offchainHash", "type": "bytes32"},
        {"name": "decisionHash", "type": "bytes32"},
        {"name": "approvalHash", "type": "bytes32"},
        {"name": "tier", "type": "uint8"},
        {"name": "validUntil", "type": "uint64"},
        {"name": "nonce", "type": "uint256"},
    ],
    "VerificationAttestation": [
        {"name": "paymentId", "type": "bytes32"},
        {"name": "intentHash", "type": "bytes32"},
        {"name": "method", "type": "uint8"},
        {"name": "result", "type": "uint8"},
        {"name": "simSwapChecked", "type": "bool"},
        {"name": "evidenceHash", "type": "bytes32"},
        {"name": "verifiedAt", "type": "uint64"},
        {"name": "nonce", "type": "uint256"},
    ],
    "Revocation": [
        {"name": "paymentId", "type": "bytes32"},
        {"name": "reasonCode", "type": "uint8"},
        {"name": "caseHash", "type": "bytes32"},
        {"name": "nonce", "type": "uint256"},
    ],
}

Message = Union[PaymentIntent, VerificationAttestation, Revocation]

_PRIMARY: dict[type, str] = {
    PaymentIntent: "PaymentIntent",
    VerificationAttestation: "VerificationAttestation",
    Revocation: "Revocation",
}

DOMAIN_TYPE_STRING = "EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
DOMAIN_TYPEHASH = keccak(text=DOMAIN_TYPE_STRING)


def type_string(primary: str) -> str:
    fields = ",".join(f"{f['type']} {f['name']}" for f in TYPES[primary])
    return f"{primary}({fields})"


def typehash(primary: str) -> bytes:
    return keccak(text=type_string(primary))


def primary_type(msg: Message) -> str:
    return _PRIMARY[type(msg)]


def _encode_value(kind: str, value: Any) -> bytes:
    if kind == "bytes32":
        return to_bytes32(value)
    if kind == "address":
        return bytes(12) + bytes.fromhex(to_checksum_address(value)[2:])
    if kind == "bool":
        return int(bool(value)).to_bytes(32, "big")
    if kind.startswith("uint"):
        bits = int(kind[4:])
        number = int(value)
        if not 0 <= number < 2**bits:
            raise ValueError(f"{number} does not fit in {kind}")
        return number.to_bytes(32, "big")
    raise ValueError(f"unsupported EIP-712 type {kind}")


def message_values(msg: Message) -> dict[str, Any]:
    """The message as EIP-712 field name -> Python value (the form eth-account expects)."""
    raw = msg.model_dump(by_alias=True)
    values: dict[str, Any] = {}
    for field in TYPES[primary_type(msg)]:
        kind, value = field["type"], raw[field["name"]]
        if kind == "bytes32":
            values[field["name"]] = to_bytes32(value)
        elif kind == "address":
            values[field["name"]] = to_checksum_address(value)
        elif kind == "bool":
            values[field["name"]] = bool(value)
        else:
            values[field["name"]] = int(value)
    return values


def struct_hash(msg: Message) -> bytes:
    primary = primary_type(msg)
    raw = msg.model_dump(by_alias=True)
    encoded = b"".join(_encode_value(f["type"], raw[f["name"]]) for f in TYPES[primary])
    return keccak(typehash(primary) + encoded)


def domain_separator(domain: Eip712Domain) -> bytes:
    return keccak(
        DOMAIN_TYPEHASH
        + keccak(text=domain.name)
        + keccak(text=domain.version)
        + _encode_value("uint256", domain.chain_id)
        + _encode_value("address", domain.verifying_contract)
    )


def digest(msg: Message, domain: Eip712Domain) -> bytes:
    """The EIP-712 digest. For a PaymentIntent this is the ``intentHash`` stored by the registry."""
    return keccak(b"\x19\x01" + domain_separator(domain) + struct_hash(msg))


def typed_data(msg: Message, domain: Eip712Domain) -> dict[str, Any]:
    primary = primary_type(msg)
    return {
        "types": {"EIP712Domain": EIP712_DOMAIN_FIELDS, primary: TYPES[primary]},
        "primaryType": primary,
        "domain": {
            "name": domain.name,
            "version": domain.version,
            "chainId": domain.chain_id,
            "verifyingContract": to_checksum_address(domain.verifying_contract),
        },
        "message": message_values(msg),
    }


def eth_account_digest(msg: Message, domain: Eip712Domain) -> bytes:
    """Digest computed by eth-account (used to cross-check :func:`digest`)."""
    signable = encode_typed_data(full_message=typed_data(msg, domain))
    return keccak(b"\x19" + signable.version + signable.header + signable.body)


def sign(msg: Message, domain: Eip712Domain, private_key: str) -> bytes:
    """65-byte signature r || s || v (v = 27 or 28)."""
    signable = encode_typed_data(full_message=typed_data(msg, domain))
    return bytes(Account.sign_message(signable, private_key).signature)


def recover(msg: Message, domain: Eip712Domain, signature: bytes) -> str:
    signable = encode_typed_data(full_message=typed_data(msg, domain))
    return Account.recover_message(signable, signature=signature)


# --- Shared test vector (spec/eip712.json) ---------------------------------------------------

VECTOR_DOMAIN = Eip712Domain(chain_id=43113, verifying_contract="0x0000000000000000000000000000000000000001")
VECTOR_TOKEN = to_checksum_address("0x" + "0" * 37 + "e0c")
VECTOR_PATH = SPEC_DIR / "eip712.json"


def vector_messages() -> dict[str, Message]:
    from .devkeys import dev_address

    intent = PaymentIntent(
        payment_id=to_hex(keccak_text("PAY-2026-0002")),
        corridor_id=to_hex(keccak_text("FR-GH")),
        beneficiary=dev_address("gh_vasp"),
        token=VECTOR_TOKEN,
        amount=85_000 * 10**6,
        offchain_hash=hash_record({"vector": "offchain"}),
        decision_hash=hash_record({"vector": "decision"}),
        approval_hash=hash_record({"vector": "approval"}),
        tier=int(Tier.MEDIUM),
        valid_until=1791709800,
        nonce=1,
    )
    attestation = VerificationAttestation(
        payment_id=intent.payment_id,
        intent_hash=to_hex(digest(intent, VECTOR_DOMAIN)),
        method=int(VerificationMethod.OOB_KNOWN_CONTACT),
        result=int(VerificationResult.DENIED),
        sim_swap_checked=True,
        evidence_hash=hash_record({"vector": "evidence"}),
        verified_at=1791709260,
        nonce=1,
    )
    revocation = Revocation(
        payment_id=intent.payment_id,
        reason_code=int(RevocationReason.SUPPLIER_DENIED),
        case_hash=hash_record({"vector": "case"}),
        nonce=1,
    )
    return {"PaymentIntent": intent, "VerificationAttestation": attestation, "Revocation": revocation}


def _json_message(msg: Message) -> dict[str, Any]:
    raw = msg.model_dump(by_alias=True)
    out: dict[str, Any] = {}
    for field in TYPES[primary_type(msg)]:
        kind, value = field["type"], raw[field["name"]]
        if kind.startswith("uint"):
            out[field["name"]] = str(int(value))
        elif kind == "address":
            out[field["name"]] = to_checksum_address(value)
        elif kind == "bool":
            out[field["name"]] = bool(value)
        else:
            out[field["name"]] = to_hex(to_bytes32(value))
    return out


def build_vector() -> dict[str, Any]:
    messages = vector_messages()
    return {
        "$comment": "Generated by `python -m sylo_spec.eip712 --write`. Never edit by hand.",
        "domain": {
            "name": VECTOR_DOMAIN.name,
            "version": VECTOR_DOMAIN.version,
            "chainId": str(VECTOR_DOMAIN.chain_id),
            "verifyingContract": to_checksum_address(VECTOR_DOMAIN.verifying_contract),
            "separator": to_hex(domain_separator(VECTOR_DOMAIN)),
        },
        "domainType": DOMAIN_TYPE_STRING,
        "types": {name: type_string(name) for name in TYPES},
        "typehashes": {name: to_hex(typehash(name)) for name in TYPES},
        "enums": {
            enum.__name__: {member.name: member.value for member in enum}
            for enum in (Tier, Status, VerificationMethod, VerificationResult, RevocationReason)
        },
        "vectors": {
            name: {
                "message": _json_message(msg),
                "structHash": to_hex(struct_hash(msg)),
                "digest": to_hex(digest(msg, VECTOR_DOMAIN)),
            }
            for name, msg in messages.items()
        },
    }


def render_vector() -> str:
    return json.dumps(build_vector(), indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate or check spec/eip712.json")
    parser.add_argument("--write", action="store_true", help="write the vector file")
    parser.add_argument("--check", action="store_true", help="fail if the file differs from the code")
    parser.add_argument("--path", type=Path, default=VECTOR_PATH)
    args = parser.parse_args(argv)
    rendered = render_vector()
    if args.write:
        args.path.write_text(rendered, encoding="utf-8")
        print(f"wrote {args.path}")
        return 0
    if args.check:
        current = args.path.read_text(encoding="utf-8") if args.path.exists() else ""
        if current != rendered:
            print(f"{args.path} is out of date: run python -m sylo_spec.eip712 --write", file=sys.stderr)
            return 1
        print(f"{args.path} is up to date")
        return 0
    sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
