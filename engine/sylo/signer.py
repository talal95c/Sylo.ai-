"""Role keys and EIP-712 records.

Three services of the sending bank sign, each with its own key (separation of duties):
the router signs the `PaymentIntent`, the verifier signs the `VerificationAttestation`,
the analyst signs the `Revocation`. Keys come from the environment; in mock mode, if they
are not set, the public dev keys of `sylo_spec.devkeys` are used (never on a real network).
"""

import itertools
import random
from dataclasses import dataclass
from typing import Any, Optional

from eth_account import Account

from sylo_spec import eip712
from sylo_spec.canonical import corridor_id_bytes, hex0x, offchain_hash, payment_id_bytes, record_hash
from sylo_spec.devkeys import dev_keys
from sylo_spec.models import (
    Eip712Domain,
    PaymentIntent,
    PaymentOrder,
    Revocation,
    RevocationReason,
    Tier,
    VerificationAttestation,
    VerificationMethod,
    VerificationResult,
)

from .config import Settings

INTENT_VALIDITY_SECONDS = 600  # the quote is valid for 600 s
TOKEN_DECIMALS = 6


@dataclass(frozen=True)
class RoleAddresses:
    router_signer: str
    verifier_signer: str
    analyst_signer: str
    relayer: str
    payer_treasury: str  # EU CASP: holds the token and funds the escrow
    beneficiary: str  # GH VASP: receives released funds


class Signer:
    def __init__(self, settings: Settings, allow_dev: Optional[bool] = None):
        dev = dev_keys()
        if allow_dev is None:
            allow_dev = settings.chain_mode == "mock"

        def key(env_name: str, role: str) -> str:
            value = settings.get(env_name)
            if value:
                return value
            if not allow_dev:
                raise RuntimeError(f"{env_name} is not set (dev keys are only allowed with CHAIN_MODE=mock)")
            return dev[role].private_key

        def address(env_name: str, role: str) -> str:
            return settings.get(env_name) or dev[role].address

        self._router_pk = key("ROUTER_SIGNER_PK", "router_signer")
        self._verifier_pk = key("VERIFIER_SIGNER_PK", "verifier_signer")
        self._analyst_pk = key("ANALYST_SIGNER_PK", "analyst_signer")
        self.addresses = RoleAddresses(
            router_signer=Account.from_key(self._router_pk).address,
            verifier_signer=Account.from_key(self._verifier_pk).address,
            analyst_signer=Account.from_key(self._analyst_pk).address,
            relayer=address("RELAYER_ADDRESS", "relayer"),
            payer_treasury=address("EU_CASP_ADDRESS", "eu_casp"),
            beneficiary=address("GH_VASP_ADDRESS", "gh_vasp"),
        )
        self.token = settings.token_address
        self.seed = settings.seed
        self._nonces = {role: itertools.count(1) for role in ("router", "verifier", "analyst")}

    # ------------------------------------------------------------------ helpers

    def salt_for(self, payment_id: str) -> bytes:
        """32 random bytes per payment, seeded so that runs and fixtures are reproducible."""
        return random.Random(f"sylo-salt:{self.seed}:{payment_id}").randbytes(32)

    @staticmethod
    def offchain_fields(order: PaymentOrder) -> dict[str, Any]:
        return {
            "account": order.creditor.account_id,
            "bank": order.creditor.institution_id,
            "creditorName": order.creditor.account_holder,
            "invoiceRef": order.invoice_ref,
            "uetr": order.uetr,
        }

    # ------------------------------------------------------------------ records

    def build_intent(self, order: PaymentOrder, tier: Tier, decision: dict[str, Any], approval: dict[str, Any], now_ts: int) -> PaymentIntent:
        return PaymentIntent(
            payment_id=payment_id_bytes(order.payment_id),
            corridor_id=corridor_id_bytes(order.corridor),
            beneficiary=self.addresses.beneficiary,
            token=self.token,
            amount=order.amount.units(TOKEN_DECIMALS),
            offchain_hash=offchain_hash(self.salt_for(order.payment_id), self.offchain_fields(order)),
            decision_hash=record_hash(decision),
            approval_hash=record_hash(approval),
            tier=tier,
            valid_until=now_ts + INTENT_VALIDITY_SECONDS,
            nonce=next(self._nonces["router"]),
        )

    def sign_intent(self, domain: Eip712Domain, intent: PaymentIntent) -> bytes:
        return eip712.sign(domain, intent, self._router_pk)

    def build_attestation(self, intent: PaymentIntent, intent_digest: bytes, result: VerificationResult, evidence: dict[str, Any], now_ts: int) -> VerificationAttestation:
        return VerificationAttestation(
            payment_id=intent.payment_id,
            intent_hash=intent_digest,
            method=VerificationMethod.OOB_KNOWN_CONTACT,
            result=result,
            sim_swap_checked=True,
            evidence_hash=record_hash(evidence),
            verified_at=now_ts,
            nonce=next(self._nonces["verifier"]),
        )

    def sign_attestation(self, domain: Eip712Domain, attestation: VerificationAttestation) -> bytes:
        return eip712.sign(domain, attestation, self._verifier_pk)

    def build_revocation(self, intent: PaymentIntent, reason: RevocationReason, case: dict[str, Any]) -> Revocation:
        return Revocation(
            payment_id=intent.payment_id,
            reason_code=reason,
            case_hash=record_hash(case),
            nonce=next(self._nonces["analyst"]),
        )

    def sign_revocation(self, domain: Eip712Domain, revocation: Revocation) -> bytes:
        return eip712.sign(domain, revocation, self._analyst_pk)


def approval_hash_hex(approval: dict[str, Any]) -> str:
    return hex0x(record_hash(approval))
