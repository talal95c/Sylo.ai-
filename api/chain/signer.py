from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import keccak, to_checksum_address

CHAIN_ID = 43113
DEFAULT_VERIFYING_CONTRACT = "0x0000000000000000000000000000000000000001"
DEV_MNEMONIC = "test test test test test test test test test test test junk"
ROLES = ("relayer", "router", "verifier", "analyst", "claire", "marc")
TIER_CODES = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
METHOD_CODES = {"OOB_KNOWN_CONTACT": 0, "PSP_ATTESTATION": 1}
APPROVAL_METHOD_CODES = {"SCA": 0, "DUAL_CONTROL": 1}
RESULT_CODES = {"CONFIRMED": 0, "DENIED": 1}
LOGGER = logging.getLogger(__name__)

EIP712_TYPES: dict[str, list[dict[str, str]]] = {
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
    "Approval": [
        {"name": "paymentId", "type": "bytes32"},
        {"name": "approverId", "type": "bytes32"},
        {"name": "method", "type": "uint8"},
        {"name": "approvedAt", "type": "uint64"},
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
    "Verification": [
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
VERIFICATION_TYPE = "VerificationAttestation"


def _bytes32(value: Any) -> bytes:
    if isinstance(value, bytes) and len(value) == 32:
        return value
    if isinstance(value, str) and value.startswith("0x") and len(value) == 66:
        try:
            return bytes.fromhex(value[2:])
        except ValueError:
            pass
    return keccak(text=str(value))


def _normalize_message(type_name: str, message: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(message)
    fields = EIP712_TYPES[type_name]
    for field in fields:
        name, field_type = field["name"], field["type"]
        if name not in normalized:
            raise ValueError(f"missing {name} in {type_name}")
        if field_type == "bytes32":
            normalized[name] = _bytes32(normalized[name])
        elif field_type == "address":
            normalized[name] = to_checksum_address(normalized[name])
        elif name == "tier" and isinstance(normalized[name], str):
            normalized[name] = TIER_CODES[normalized[name]]
        elif name == "method" and isinstance(normalized[name], str):
            codes = APPROVAL_METHOD_CODES if type_name == "Approval" else METHOD_CODES
            normalized[name] = codes[normalized[name]]
        elif name == "result" and isinstance(normalized[name], str):
            normalized[name] = RESULT_CODES[normalized[name]]
        elif field_type.startswith("uint"):
            normalized[name] = int(normalized[name])
        elif field_type == "bool":
            normalized[name] = bool(normalized[name])
    return normalized


@dataclass(frozen=True)
class SignedTypedData:
    primary_type: str
    struct_hash: str
    digest: str
    signature: str
    signer: str


class Signer:
    def __init__(self) -> None:
        self.chain_id = CHAIN_ID
        configured_contract = os.getenv("REGISTRY_ADDRESS", "").strip()
        self.verifying_contract = to_checksum_address(
            configured_contract or DEFAULT_VERIFYING_CONTRACT
        )
        self._accounts: dict[str, Any] = {}
        missing_roles: list[str] = []
        for index, role in enumerate(ROLES):
            env_name = f"{role.upper()}_PRIVATE_KEY"
            private_key = os.getenv(env_name)
            if private_key:
                self._accounts[role] = Account.from_key(private_key)
            else:
                missing_roles.append(role)
                Account.enable_unaudited_hdwallet_features()
                self._accounts[role] = Account.from_mnemonic(
                    DEV_MNEMONIC,
                    account_path=f"m/44'/60'/0'/0/{index}",
                )
        if missing_roles:
            LOGGER.warning(
                "Using deterministic Anvil development keys for roles: %s",
                ", ".join(missing_roles),
            )

    def address(self, role: str) -> str:
        return self._accounts[role].address

    def build_typed_data(
        self,
        primary_type: str,
        message: dict[str, Any],
        *,
        verifying_contract: str | None = None,
    ) -> dict[str, Any]:
        if primary_type not in EIP712_TYPES:
            raise ValueError(f"unsupported EIP-712 type: {primary_type}")
        return {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                primary_type: EIP712_TYPES[primary_type],
            },
            "primaryType": primary_type,
            "domain": {
                "name": "SyloPaymentRegistry",
                "version": "1",
                "chainId": self.chain_id,
                "verifyingContract": to_checksum_address(
                    verifying_contract or self.verifying_contract
                ),
            },
            "message": _normalize_message(primary_type, message),
        }

    def struct_hash(
        self,
        primary_type: str,
        message: dict[str, Any],
        *,
        verifying_contract: str | None = None,
    ) -> str:
        typed = self.build_typed_data(
            primary_type,
            message,
            verifying_contract=verifying_contract,
        )
        encoded = encode_typed_data(full_message=typed)
        return "0x" + encoded.body.hex()

    def sign(
        self,
        role: str,
        primary_type: str,
        message: dict[str, Any],
        *,
        verifying_contract: str | None = None,
    ) -> SignedTypedData:
        typed = self.build_typed_data(
            primary_type,
            message,
            verifying_contract=verifying_contract,
        )
        encoded = encode_typed_data(full_message=typed)
        digest = keccak(b"\x19" + encoded.version + encoded.header + encoded.body)
        signed = self._accounts[role].sign_message(encoded)
        return SignedTypedData(
            primary_type=primary_type,
            struct_hash="0x" + encoded.body.hex(),
            digest="0x" + digest.hex(),
            signature="0x" + signed.signature.hex(),
            signer=self._accounts[role].address,
        )

    def intent_hash(self, intent: dict[str, Any]) -> str:
        return self.struct_hash("PaymentIntent", intent)


signer = Signer()


def intent_hash(intent: dict[str, Any]) -> str:
    return signer.intent_hash(intent)
