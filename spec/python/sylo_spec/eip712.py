"""EIP-712 for Sylo.ai: type strings, struct hashes, digests, signing and the shared test vector.

The field order of the three types is binding (PRD section 13.4). Python, Solidity and
TypeScript must all produce the hashes stored in `spec/eip712.json`.

    python -m sylo_spec.eip712            # (re)write spec/eip712.json from this code
    python -m sylo_spec.eip712 --check    # fail if the file differs from what this code computes
"""

import json
import sys
from pathlib import Path
from typing import Any, Union

from eth_abi import encode as abi_encode
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import keccak

from .canonical import corridor_id_bytes, hex0x, offchain_hash, payment_id_bytes, record_hash
from .models import (
    Eip712Domain,
    PaymentIntent,
    Revocation,
    RevocationReason,
    Tier,
    VerificationAttestation,
    VerificationMethod,
    VerificationResult,
)

Message = Union[PaymentIntent, VerificationAttestation, Revocation]

DOMAIN_NAME = "SyloPaymentRegistry"
DOMAIN_VERSION = "1"
EIP712_DOMAIN_FIELDS = [
    ("name", "string"),
    ("version", "string"),
    ("chainId", "uint256"),
    ("verifyingContract", "address"),
]

# (field name, solidity type) in binding order.
FIELDS: dict[str, list[tuple[str, str]]] = {
    "PaymentIntent": [
        ("paymentId", "bytes32"),
        ("corridorId", "bytes32"),
        ("beneficiary", "address"),
        ("token", "address"),
        ("amount", "uint256"),
        ("offchainHash", "bytes32"),
        ("decisionHash", "bytes32"),
        ("approvalHash", "bytes32"),
        ("tier", "uint8"),
        ("validUntil", "uint64"),
        ("nonce", "uint256"),
    ],
    "VerificationAttestation": [
        ("paymentId", "bytes32"),
        ("intentHash", "bytes32"),
        ("method", "uint8"),
        ("result", "uint8"),
        ("simSwapChecked", "bool"),
        ("evidenceHash", "bytes32"),
        ("verifiedAt", "uint64"),
        ("nonce", "uint256"),
    ],
    "Revocation": [
        ("paymentId", "bytes32"),
        ("reasonCode", "uint8"),
        ("caseHash", "bytes32"),
        ("nonce", "uint256"),
    ],
}


def _encode_type(name: str, fields: list[tuple[str, str]]) -> str:
    return f"{name}(" + ",".join(f"{sol_type} {field}" for field, sol_type in fields) + ")"


def type_string(name: str) -> str:
    return _encode_type(name, FIELDS[name])


def type_hash(name: str) -> bytes:
    return keccak(text=type_string(name))


def _name_of(message: Message) -> str:
    return type(message).__name__


def message_values(message: Message) -> dict[str, Any]:
    """Field values keyed by their EIP-712 (camelCase) names: bytes, int, bool and address strings."""
    raw = message.model_dump(by_alias=True)
    return {field: (int(raw[field]) if sol.startswith("uint") else raw[field]) for field, sol in FIELDS[_name_of(message)]}


def struct_hash(message: Message) -> bytes:
    name = _name_of(message)
    values = message_values(message)
    types = ["bytes32"] + [sol for _, sol in FIELDS[name]]
    args = [type_hash(name)] + [values[field] for field, _ in FIELDS[name]]
    return keccak(abi_encode(types, args))


def domain_separator(domain: Eip712Domain) -> bytes:
    return keccak(
        abi_encode(
            ["bytes32", "bytes32", "bytes32", "uint256", "address"],
            [
                keccak(text=_encode_type("EIP712Domain", EIP712_DOMAIN_FIELDS)),
                keccak(text=domain.name),
                keccak(text=domain.version),
                domain.chain_id,
                domain.verifying_contract,
            ],
        )
    )


def digest(domain: Eip712Domain, message: Message) -> bytes:
    """The EIP-712 digest: keccak256(0x1901 ‖ domainSeparator ‖ structHash). This is the `intentHash`."""
    return keccak(b"\x19\x01" + domain_separator(domain) + struct_hash(message))


def typed_data(domain: Eip712Domain, message: Message) -> dict[str, Any]:
    """Full EIP-712 typed data (the JSON a wallet signs with eth_signTypedData_v4)."""
    name = _name_of(message)
    return {
        "types": {
            "EIP712Domain": [{"name": f, "type": t} for f, t in EIP712_DOMAIN_FIELDS],
            name: [{"name": f, "type": t} for f, t in FIELDS[name]],
        },
        "primaryType": name,
        "domain": {
            "name": domain.name,
            "version": domain.version,
            "chainId": domain.chain_id,
            "verifyingContract": domain.verifying_contract,
        },
        "message": message_values(message),
    }


def sign(domain: Eip712Domain, message: Message, private_key: str) -> bytes:
    """65-byte signature r ‖ s ‖ v (v = 27 or 28), as OpenZeppelin's ECDSA.recover expects."""
    signed = Account.sign_typed_data(private_key, full_message=typed_data(domain, message))
    return bytes(signed.signature)


def recover(domain: Eip712Domain, message: Message, signature: bytes) -> str:
    """Address that signed `message` under `domain`."""
    signable = encode_typed_data(full_message=typed_data(domain, message))
    return Account.recover_message(signable, signature=signature)


# --------------------------------------------------------------------------- shared test vector

SPEC_DIR = Path(__file__).resolve().parents[2]
VECTOR_PATH = SPEC_DIR / "eip712.json"

VECTOR_DOMAIN = Eip712Domain(chain_id=43113, verifying_contract="0x0000000000000000000000000000000000000001")
VECTOR_TOKEN = "0x0000000000000000000000000000000000000E0C"
VECTOR_BENEFICIARY = "0x14dC79964da2C08b23698B3D3cc7Ca32193d9955"  # dev key index 7 (GH VASP), public
VECTOR_VALID_UNTIL = 1791709800  # fixed example timestamp
VECTOR_VERIFIED_AT = 1791709300


def vector_messages() -> dict[str, Message]:
    payment_id = payment_id_bytes("PAY-2026-0002")
    intent = PaymentIntent(
        payment_id=payment_id,
        corridor_id=corridor_id_bytes("FR-GH"),
        beneficiary=VECTOR_BENEFICIARY,
        token=VECTOR_TOKEN,
        amount=85_000 * 10**6,
        offchain_hash=offchain_hash(
            keccak(text="sylo-vector-salt"),
            {
                "account": "acc-mensah-aflao",
                "bank": "mule_bank",
                "creditorName": "K. MENSAH VENTURES",
                "invoiceRef": "SSE-2026-118",
                "uetr": "0d3f6c7e-5b1a-4e2c-9a40-7f6d2c8b1e02",
            },
        ),
        decision_hash=record_hash({"routeId": "R3", "score": 64, "tier": "MEDIUM"}),
        approval_hash=record_hash({"by": ["Claire Martin", "Marc Durand"], "conditional": True}),
        tier=Tier.MEDIUM,
        valid_until=VECTOR_VALID_UNTIL,
        nonce=1,
    )
    verification = VerificationAttestation(
        payment_id=payment_id,
        intent_hash=digest(VECTOR_DOMAIN, intent),
        method=VerificationMethod.OOB_KNOWN_CONTACT,
        result=VerificationResult.DENIED,
        sim_swap_checked=True,
        evidence_hash=record_hash({"answer": "deny", "contact": "Kwame Asante", "simSwapRecent": False}),
        verified_at=VECTOR_VERIFIED_AT,
        nonce=1,
    )
    revocation = Revocation(
        payment_id=payment_id,
        reason_code=RevocationReason.SUPPLIER_DENIED,
        case_hash=record_hash({"case": "CASE-PAY-2026-0002", "reason": "SUPPLIER_DENIED"}),
        nonce=1,
    )
    return {"PaymentIntent": intent, "VerificationAttestation": verification, "Revocation": revocation}


def _vector_message_json(message: Message) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for field, sol in FIELDS[_name_of(message)]:
        value = message_values(message)[field]
        if sol.startswith("uint"):
            out[field] = str(int(value))  # uint values as decimal strings
        elif sol == "bytes32":
            out[field] = hex0x(value)
        else:
            out[field] = value  # address string or bool
    return out


def build_vector() -> dict[str, Any]:
    messages = vector_messages()
    return {
        "description": "Shared EIP-712 test vector. Generated by `python -m sylo_spec.eip712`; never edit by hand.",
        "domain": {
            "name": VECTOR_DOMAIN.name,
            "version": VECTOR_DOMAIN.version,
            "chainId": VECTOR_DOMAIN.chain_id,
            "verifyingContract": VECTOR_DOMAIN.verifying_contract,
        },
        "domainSeparator": hex0x(domain_separator(VECTOR_DOMAIN)),
        "types": {name: type_string(name) for name in FIELDS},
        "typeHashes": {name: hex0x(type_hash(name)) for name in FIELDS},
        "enums": {
            "Tier": {e.name: e.value for e in Tier},
            "Status": {"NONE": 0, "COMMITTED": 1, "CONFIRMED": 2, "DENIED": 3, "REVOKED": 4, "EXECUTED": 5},
            "VerificationMethod": {e.name: e.value for e in VerificationMethod},
            "VerificationResult": {e.name: e.value for e in VerificationResult},
            "RevocationReason": {e.name: e.value for e in RevocationReason},
        },
        "vectors": {
            name: {
                "message": _vector_message_json(message),
                "structHash": hex0x(struct_hash(message)),
                "digest": hex0x(digest(VECTOR_DOMAIN, message)),
            }
            for name, message in messages.items()
        },
    }


def render_vector() -> str:
    return json.dumps(build_vector(), indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    rendered = render_vector()
    if "--check" in argv:
        current = VECTOR_PATH.read_text(encoding="utf-8") if VECTOR_PATH.exists() else ""
        if current != rendered:
            print(f"{VECTOR_PATH} is out of date: run `python -m sylo_spec.eip712`", file=sys.stderr)
            return 1
        print(f"{VECTOR_PATH} is up to date")
        return 0
    VECTOR_PATH.write_text(rendered, encoding="utf-8")
    print(f"wrote {VECTOR_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
