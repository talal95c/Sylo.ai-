from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Protocol

from web3 import HTTPProvider, Web3

from api.chain.signer import CHAIN_ID, EIP712_TYPES, keccak, signer

REPO_ROOT = Path(__file__).resolve().parents[2]
FUJI_RPC_DEFAULTS = (
    "https://api.avax-test.network/ext/bc/C/rpc",
    "https://avalanche-fuji-c-chain-rpc.publicnode.com",
)
STATUS_NAMES = {
    0: "NONE",
    1: "COMMITTED",
    2: "CONFIRMED",
    3: "DENIED",
    4: "REVOKED",
    5: "EXECUTED",
}


class ChainRevert(RuntimeError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class ChainClient(Protocol):
    def commit(self, intent: dict[str, Any], signature: str | None = None) -> dict[str, Any]: ...
    def confirm(self, payment_id: str, verification: dict[str, Any] | None = None) -> dict[str, Any]: ...
    def deny(self, payment_id: str, verification: dict[str, Any] | None = None) -> dict[str, Any]: ...
    def revoke(self, payment_id: str, revocation: dict[str, Any] | None = None) -> dict[str, Any]: ...
    def markExecuted(self, payment_id: str, execution_ref: str) -> dict[str, Any]: ...
    def status(self, payment_id: str) -> dict[str, Any]: ...
    def escrowDeposit(self, payment_id: str, **kwargs: Any) -> dict[str, Any]: ...
    def escrowRelease(self, payment_id: str) -> dict[str, Any]: ...
    def escrowRefund(self, payment_id: str, caller: str = "analyst") -> dict[str, Any]: ...


class FakeChain:
    def __init__(self) -> None:
        self.payments: dict[str, dict[str, Any]] = {}
        self.escrows: dict[str, dict[str, Any]] = {}
        self.used_nonces: set[int] = set()
        self._tx_counter = 0

    def _tx(self, status: str) -> dict[str, Any]:
        self._tx_counter += 1
        digest = hashlib.sha256(
            f"fake-chain:{self._tx_counter}:{status}".encode()
        ).hexdigest()
        return {"txHash": f"0x{digest}", "status": status, "explorerUrl": None}

    @staticmethod
    def _same_bytes32(left: Any, right: Any) -> bool:
        return str(left).lower() == str(right).lower()

    def commit(
        self, intent: dict[str, Any], signature: str | None = None
    ) -> dict[str, Any]:
        del signature
        payment_id = str(intent["paymentId"])
        nonce = int(intent["nonce"])
        if payment_id in self.payments:
            raise ChainRevert("PaymentAlreadyCommitted")
        if nonce in self.used_nonces:
            raise ChainRevert("NonceUsed")
        intent_hash_value = intent.get("intentHash") or signer.intent_hash(intent)
        self.used_nonces.add(nonce)
        self.payments[payment_id] = {
            "intent": dict(intent),
            "intentHash": intent_hash_value,
            "status": "COMMITTED",
            "lastTxHash": None,
            "verification": None,
        }
        tx = self._tx("COMMITTED")
        self.payments[payment_id]["lastTxHash"] = tx["txHash"]
        return tx | {"intentHash": intent_hash_value}

    def _payment(self, payment_id: str) -> dict[str, Any]:
        if payment_id not in self.payments:
            raise ChainRevert("PaymentNotFound")
        return self.payments[payment_id]

    def confirm(
        self,
        payment_id: str,
        verification: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payment = self._payment(payment_id)
        if payment["status"] != "COMMITTED":
            raise ChainRevert("InvalidStatusTransition")
        payment["status"] = "CONFIRMED"
        payment["verification"] = verification or {"result": "CONFIRMED"}
        tx = self._tx("CONFIRMED")
        payment["lastTxHash"] = tx["txHash"]
        return tx

    def deny(
        self,
        payment_id: str,
        verification: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payment = self._payment(payment_id)
        if payment["status"] != "COMMITTED":
            raise ChainRevert("InvalidStatusTransition")
        payment["status"] = "DENIED"
        payment["verification"] = verification or {"result": "DENIED"}
        tx = self._tx("DENIED")
        payment["lastTxHash"] = tx["txHash"]
        return tx

    def revoke(
        self,
        payment_id: str,
        revocation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del revocation
        payment = self._payment(payment_id)
        if payment["status"] not in {"COMMITTED", "CONFIRMED", "DENIED"}:
            raise ChainRevert("InvalidStatusTransition")
        payment["status"] = "REVOKED"
        tx = self._tx("REVOKED")
        payment["lastTxHash"] = tx["txHash"]
        return tx

    def markExecuted(self, payment_id: str, execution_ref: str) -> dict[str, Any]:
        del execution_ref
        payment = self._payment(payment_id)
        if payment["status"] not in {"COMMITTED", "CONFIRMED"}:
            raise ChainRevert("PaymentNotExecutable")
        payment["status"] = "EXECUTED"
        tx = self._tx("EXECUTED")
        payment["lastTxHash"] = tx["txHash"]
        return tx

    def status(self, payment_id: str) -> dict[str, Any]:
        payment = self._payment(payment_id)
        return {
            "txHash": payment["lastTxHash"],
            "status": payment["status"],
            "explorerUrl": None,
        }

    def escrowDeposit(self, payment_id: str, **kwargs: Any) -> dict[str, Any]:
        payment = self._payment(payment_id)
        if payment["status"] != "COMMITTED":
            raise ChainRevert("PaymentNotDepositable")
        if payment_id in self.escrows:
            raise ChainRevert("AlreadyDeposited")
        intent = kwargs.get("intent", payment["intent"])
        if kwargs.get("intentHash") and not self._same_bytes32(
            kwargs["intentHash"], payment["intentHash"]
        ):
            raise ChainRevert("CommitmentMismatch")
        committed = payment["intent"]
        for field in ("beneficiary", "amount", "token"):
            if field in kwargs and not self._same_bytes32(
                kwargs[field], committed.get(field)
            ):
                raise ChainRevert("CommitmentMismatch")
        if self._same_bytes32(
            signer.intent_hash(intent), payment["intentHash"]
        ) is False:
            raise ChainRevert("CommitmentMismatch")
        self.escrows[payment_id] = {
            "status": "DEPOSITED",
            "payer": kwargs.get("payer"),
            "beneficiary": committed.get("beneficiary"),
            "amount": committed.get("amount"),
            "expiresAt": int(time.time()) + 24 * 60 * 60,
            "frozen": False,
        }
        return self._tx("DEPOSITED")

    def escrowRelease(self, payment_id: str) -> dict[str, Any]:
        payment = self._payment(payment_id)
        escrow = self.escrows.get(payment_id)
        if (
            escrow is None
            or escrow["status"] != "DEPOSITED"
            or payment["status"] != "CONFIRMED"
            or escrow["frozen"]
            or escrow["expiresAt"] <= int(time.time())
        ):
            raise ChainRevert("PaymentNotReleasable")
        escrow["status"] = "RELEASED"
        return self._tx("RELEASED")

    def escrowRefund(
        self, payment_id: str, caller: str = "analyst"
    ) -> dict[str, Any]:
        payment = self._payment(payment_id)
        escrow = self.escrows.get(payment_id)
        if escrow is None or escrow["status"] not in {"DEPOSITED", "FROZEN"}:
            raise ChainRevert("EscrowNotRefundable")
        expired_or_revoked = (
            payment["status"] == "REVOKED"
            or escrow["expiresAt"] <= int(time.time())
        )
        if caller != "analyst" and not expired_or_revoked:
            raise ChainRevert("Unauthorized")
        escrow["status"] = "REFUNDED"
        return self._tx("REFUNDED")

    def reset(self) -> None:
        self.payments.clear()
        self.escrows.clear()
        self.used_nonces.clear()
        self._tx_counter = 0


class Web3Chain:
    def __init__(self, rpc_urls: list[str] | None = None) -> None:
        configured = rpc_urls or [
            os.getenv("FUJI_RPC_URL_1", FUJI_RPC_DEFAULTS[0]),
            os.getenv("FUJI_RPC_URL_2", FUJI_RPC_DEFAULTS[1]),
        ]
        self.web3s: list[Web3] = []
        for url in configured:
            web3 = Web3(HTTPProvider(url, request_kwargs={"timeout": 10}))
            if not web3.is_connected():
                continue
            chain_id = int(web3.eth.chain_id)
            if chain_id != CHAIN_ID:
                raise RuntimeError(
                    f"Refusing Fuji RPC with chainId {chain_id}; expected {CHAIN_ID}"
                )
            self.web3s.append(web3)
        if not self.web3s:
            raise ConnectionError("No configured Fuji RPC endpoint is reachable")
        self.deployment = self._load_deployment()
        self.registry = self._contract("PaymentRegistry")
        self.escrow = self._contract("PaymentEscrow")

    def _load_deployment(self) -> dict[str, Any]:
        path = REPO_ROOT / "contracts" / "deployments" / "fuji.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if int(data.get("chainId", 0)) != CHAIN_ID:
                raise RuntimeError("Fuji deployment file has a wrong chainId")
            contracts = data.get("contracts", {})
            abis = data.setdefault("abis", {})
            for name, key in (
                ("PaymentRegistry", "registry"),
                ("PaymentEscrow", "escrow"),
            ):
                entry = contracts.get(name, data.get(name, {}))
                if isinstance(entry, dict):
                    data.setdefault(key, entry.get("address"))
                    if entry.get("abi"):
                        abis.setdefault(name, entry["abi"])
            return data
        return {
            "chainId": CHAIN_ID,
            "registry": os.getenv("REGISTRY_ADDRESS"),
            "escrow": os.getenv("ESCROW_ADDRESS"),
            "token": os.getenv("TOKEN_ADDRESS"),
        }

    def _abi(self, contract_name: str) -> list[dict[str, Any]]:
        deployment_abis = self.deployment.get("abis", {})
        if contract_name in deployment_abis:
            return deployment_abis[contract_name]
        out_dir = REPO_ROOT / "contracts" / "out"
        matches = list(out_dir.rglob(f"{contract_name}.json")) if out_dir.exists() else []
        if not matches:
            raise FileNotFoundError(f"No ABI found for {contract_name} in contracts/out")
        artifact = json.loads(matches[0].read_text(encoding="utf-8"))
        return artifact["abi"]

    def _contract(self, name: str):
        address = self.deployment.get(
            "registry" if name == "PaymentRegistry" else "escrow"
        )
        if not address:
            raise RuntimeError(f"Missing {name} deployment address")
        return self.web3s[0].eth.contract(
            address=Web3.to_checksum_address(address),
            abi=self._abi(name),
        )

    def _web3_contract(self, name: str):
        address = self.deployment.get(
            "registry" if name == "PaymentRegistry" else "escrow"
        )
        abi = self._abi(name)
        return [
            web3.eth.contract(address=Web3.to_checksum_address(address), abi=abi)
            for web3 in self.web3s
        ]

    def _submit(self, contract_name: str, method: str, *args: Any) -> dict[str, Any]:
        last_error: Exception | None = None
        for web3, contract in zip(self.web3s, self._web3_contract(contract_name)):
            account = signer._accounts["relayer"]
            try:
                function = getattr(contract.functions, method)(*args)
                transaction = function.build_transaction(
                    {
                        "from": account.address,
                        "nonce": web3.eth.get_transaction_count(account.address),
                        "chainId": CHAIN_ID,
                        "gas": 500_000,
                        "gasPrice": web3.eth.gas_price,
                    }
                )
                signed = account.sign_transaction(transaction)
                tx_hash = web3.eth.send_raw_transaction(signed.raw_transaction)
                receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
                return {
                    "txHash": tx_hash.hex(),
                    "status": "CONFIRMED" if receipt["status"] else "REVERTED",
                    "explorerUrl": (
                        "https://testnet.snowtrace.io/tx/" + tx_hash.hex()
                    ),
                }
            except Exception as error:
                last_error = error
        if last_error:
            message = str(last_error)
            for reason in (
                "PaymentNotReleasable",
                "CommitmentMismatch",
                "NonceUsed",
            ):
                if reason in message:
                    raise ChainRevert(reason) from last_error
            raise last_error
        raise ConnectionError("No Fuji RPC provider accepted the transaction")

    @staticmethod
    def _typed_tuple(type_name: str, message: dict[str, Any]) -> tuple[Any, ...]:
        normalized = signer.build_typed_data(type_name, message)["message"]
        return tuple(
            normalized[field["name"]]
            for field in EIP712_TYPES[type_name]
        )

    @staticmethod
    def _bytes32_arg(value: str) -> bytes:
        if value.startswith("0x") and len(value) == 66:
            return bytes.fromhex(value[2:])
        return keccak(text=value)

    def commit(self, intent: dict[str, Any], signature: str | None = None) -> dict[str, Any]:
        return self._submit(
            "PaymentRegistry",
            "commit",
            self._typed_tuple("PaymentIntent", intent),
            signature or signer.sign("router", "PaymentIntent", intent).signature,
        )

    def confirm(
        self, payment_id: str, verification: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if verification is None:
            raise ValueError("verification attestation is required")
        return self._submit(
            "PaymentRegistry",
            "recordVerification",
            self._typed_tuple("VerificationAttestation", verification),
            signer.sign("verifier", "VerificationAttestation", verification).signature,
        )

    def deny(
        self, payment_id: str, verification: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return self.confirm(payment_id, verification | {"result": "DENIED"} if verification else None)

    def revoke(
        self, payment_id: str, revocation: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        payload = revocation or {
            "paymentId": payment_id,
            "reasonCode": 1,
            "caseHash": "0x" + "00" * 32,
            "nonce": 0,
        }
        return self._submit(
            "PaymentRegistry",
            "revoke",
            self._typed_tuple("Revocation", payload),
            signer.sign("analyst", "Revocation", payload).signature,
        )

    def markExecuted(self, payment_id: str, execution_ref: str) -> dict[str, Any]:
        return self._submit(
            "PaymentRegistry",
            "markExecuted",
            self._bytes32_arg(payment_id),
            self._bytes32_arg(execution_ref),
        )

    def status(self, payment_id: str) -> dict[str, Any]:
        last_error: Exception | None = None
        for contract in self._web3_contract("PaymentRegistry"):
            try:
                value = contract.functions.statusOf(
                    self._bytes32_arg(payment_id)
                ).call()
                return {
                    "txHash": None,
                    "status": STATUS_NAMES.get(int(value), str(value)),
                    "explorerUrl": None,
                }
            except Exception as error:
                last_error = error
        if last_error:
            raise last_error
        raise ConnectionError("No Fuji RPC provider is available")

    def escrowDeposit(self, payment_id: str, **kwargs: Any) -> dict[str, Any]:
        intent = kwargs["intent"]
        return self._submit(
            "PaymentEscrow",
            "deposit",
            self._typed_tuple("PaymentIntent", intent),
            kwargs["payer"],
        )

    def escrowRelease(self, payment_id: str) -> dict[str, Any]:
        return self._submit(
            "PaymentEscrow", "release", self._bytes32_arg(payment_id)
        )

    def escrowRefund(self, payment_id: str, caller: str = "analyst") -> dict[str, Any]:
        del caller
        return self._submit(
            "PaymentEscrow", "refund", self._bytes32_arg(payment_id)
        )


def create_chain_client(mode: str | None = None) -> ChainClient:
    selected = (mode or os.getenv("CHAIN_MODE", "fake")).lower()
    if selected == "fake":
        return FakeChain()
    if selected == "fuji":
        return Web3Chain()
    raise ValueError("CHAIN_MODE must be 'fake' or 'fuji'")
