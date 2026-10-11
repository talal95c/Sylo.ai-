"""FujiChain: ChainPort over the deployed PaymentRegistry and PaymentEscrow on Avalanche Fuji (or Anvil).

Every write is first simulated with ``eth_call``: a revert raises ``ChainReverted(<custom error name>)``
without spending gas. Attack calls (``caller="attacker"``, or inside ``visible_failures()``) are sent
anyway with a fixed gas limit, so the failed transaction is mined and visible on the explorer.
Calls are synchronous and serialised by a lock (the engine runs them in a worker thread).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TypeVar

import requests
from eth_account import Account
from eth_account.signers.local import LocalAccount
from eth_utils import to_checksum_address
from sylo_spec.canonical import to_bytes32
from sylo_spec.models import (
    Eip712Domain,
    PaymentIntent,
    Revocation,
    Status,
    TxRef,
    VerificationAttestation,
)
from sylo_spec.ports import ChainReverted, CorridorIdLike, PaymentIdLike
from web3 import HTTPProvider, Web3
from web3.contract import Contract
from web3.exceptions import (
    BlockNotFound,
    ContractLogicError,
    ProviderConnectionError,
    TimeExhausted,
    Web3RPCError,
)
from web3.types import BlockIdentifier

from .abi import decode_revert, load_abi

log = logging.getLogger(__name__)

FUJI_CHAIN_ID = 43113
DEFAULT_EXPLORER = "https://testnet.snowtrace.io"
DOMAIN_NAME = "SyloPaymentRegistry"
DOMAIN_VERSION = "1"
FAILED_TX_GAS = 300_000
GAS_MARGIN = 1.25
NONCE_RETRIES = 5
DEPLOYMENTS = Path(__file__).resolve().parents[2] / "contracts" / "deployments"

_NETWORK_ERRORS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    ProviderConnectionError,
    ConnectionError,
    TimeoutError,
)
_NONCE_ERRORS = ("nonce too low", "already known", "replacement transaction underpriced", "invalid nonce")

T = TypeVar("T")


def _hex(data: bytes) -> str:
    return "0x" + bytes(data).hex()


def _revert_data(err: ContractLogicError) -> Any:
    data = err.data
    if isinstance(data, dict):
        data = data.get("data")
    return data


class FujiChain:
    """``ChainPort`` on a deployed registry and escrow. ``keys`` maps a role to its private key:
    ``relayer`` (required) sends the engine's transactions; ``attacker``, ``analyst`` and ``guardian``
    are optional and only needed for attacks, ``freeze`` and ``pause_corridor``."""

    def __init__(
        self,
        *,
        rpc_urls: Sequence[str],
        registry: str,
        escrow: str,
        keys: Mapping[str, str],
        chain_id: int = FUJI_CHAIN_ID,
        explorer_base_url: str | None = DEFAULT_EXPLORER,
        receipt_timeout: float = 60.0,
        poll_latency: float = 0.5,
        rpc_timeout: float = 10.0,
    ) -> None:
        if "relayer" not in keys:
            raise ValueError("FujiChain needs the relayer key")
        self.mode = "fuji" if chain_id == FUJI_CHAIN_ID else "anvil"
        self._chain_id = chain_id
        self._explorer = explorer_base_url.rstrip("/") if explorer_base_url else None
        self._receipt_timeout = receipt_timeout
        self._poll_latency = poll_latency
        self._accounts: dict[str, LocalAccount] = {role: Account.from_key(key) for role, key in keys.items() if key}
        self._registry_address = to_checksum_address(registry)
        self._escrow_address = to_checksum_address(escrow)
        self._lock = threading.RLock()
        self._local = threading.local()
        self._nonces: dict[str, int] = {}
        self._seen_block = 0
        self._providers = self._connect(rpc_urls, rpc_timeout)
        self._current = 0
        self._domain = self._read_domain()

    # --- construction --------------------------------------------------------------------------

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> FujiChain:
        """Reads ``.env`` values (docs/setup.md section 8). Refuses any network other than Fuji."""
        env = os.environ if env is None else env
        chain_id = int(env.get("CHAIN_ID") or FUJI_CHAIN_ID)
        if chain_id != FUJI_CHAIN_ID:
            raise ValueError(f"FujiChain.from_env runs on Fuji only: CHAIN_ID is {chain_id}, expected {FUJI_CHAIN_ID}")
        urls = [u for u in (env.get("FUJI_RPC_URL"), env.get("FUJI_RPC_URL_2")) if u]
        if not urls:
            raise ValueError("FUJI_RPC_URL is not set")
        registry, escrow = env.get("REGISTRY_ADDRESS"), env.get("ESCROW_ADDRESS")
        if not (registry and escrow):
            deployment = DEPLOYMENTS / f"{FUJI_CHAIN_ID}.json"
            if not deployment.exists():
                raise ValueError("REGISTRY_ADDRESS / ESCROW_ADDRESS are not set and no deployments/43113.json")
            addresses = json.loads(deployment.read_text())
            registry, escrow = registry or addresses["registry"], escrow or addresses["escrow"]
        if not env.get("RELAYER_PK"):
            raise ValueError("RELAYER_PK is not set")
        keys = {
            "relayer": env["RELAYER_PK"],
            "attacker": env.get("ATTACKER_PK", ""),
            "analyst": env.get("ANALYST_SIGNER_PK", ""),
            "guardian": env.get("GUARDIAN_PK", ""),
        }
        return cls(
            rpc_urls=urls,
            registry=registry,
            escrow=escrow,
            keys=keys,
            chain_id=chain_id,
            explorer_base_url=env.get("EXPLORER_BASE_URL") or DEFAULT_EXPLORER,
        )

    def _connect(self, urls: Sequence[str], timeout: float) -> list[Web3]:
        providers: list[Web3] = []
        for url in urls:
            w3 = Web3(HTTPProvider(url, request_kwargs={"timeout": timeout}))
            try:
                remote = w3.eth.chain_id
            except _NETWORK_ERRORS as err:
                log.warning("RPC %s unreachable, skipped: %s", url, err)
                continue
            if remote != self._chain_id:
                raise ValueError(f"refusing to start: {url} is chain {remote}, expected {self._chain_id}")
            providers.append(w3)
        if not providers:
            raise ConnectionError(f"no reachable RPC endpoint for chain {self._chain_id}")
        return providers

    def _read_domain(self) -> Eip712Domain:
        _, name, version, chain_id, contract, _, _ = self._read(
            lambda w3, block: self._registry(w3).functions.eip712Domain().call(block_identifier=block)
        )
        if (name, version, chain_id) != (
            DOMAIN_NAME,
            DOMAIN_VERSION,
            self._chain_id,
        ) or contract != self._registry_address:
            raise ValueError(
                f"unexpected EIP-712 domain at {self._registry_address}: {name} {version} {chain_id} {contract}"
            )
        return Eip712Domain(chain_id=chain_id, verifying_contract=contract)

    # --- plumbing ------------------------------------------------------------------------------

    def _rpc(self, call: Callable[[Web3], T]) -> T:
        """Runs ``call`` on the current endpoint, moving to the next one on a network error."""
        last: Exception | None = None
        for attempt in range(len(self._providers)):
            index = (self._current + attempt) % len(self._providers)
            try:
                result = call(self._providers[index])
            except _NETWORK_ERRORS as err:
                log.warning("RPC endpoint %d failed (%s), trying the next one", index, err)
                last = err
                continue
            self._current = index
            return result
        raise ConnectionError(f"every RPC endpoint failed: {last}")

    def _read(self, call: Callable[[Web3, BlockIdentifier], T]) -> T:
        """Runs a read at or after the block of our last mined transaction. Public Fuji RPCs are load
        balanced: a plain "latest" read can reach a node that has not seen that block and return stale
        state (a stale simulation would wrongly refuse a release). A lagging node errors on the pinned
        block, so we retry until it catches up."""
        deadline = time.monotonic() + self._receipt_timeout
        while True:
            try:
                return self._rpc(lambda w3: call(w3, self._read_block(w3)))
            except (Web3RPCError, BlockNotFound):
                if not self._seen_block or time.monotonic() > deadline:
                    raise
                time.sleep(self._poll_latency)

    def _read_block(self, w3: Web3) -> BlockIdentifier:
        return max(self._seen_block, w3.eth.block_number) if self._seen_block else "latest"

    def _registry(self, w3: Web3) -> Contract:
        return w3.eth.contract(address=self._registry_address, abi=load_abi("PaymentRegistry"))

    def _escrow(self, w3: Web3) -> Contract:
        return w3.eth.contract(address=self._escrow_address, abi=load_abi("PaymentEscrow"))

    def _account(self, role: str) -> LocalAccount:
        try:
            return self._accounts[role]
        except KeyError:
            raise ValueError(f"no key configured for role {role!r}") from None

    def _txref(self, tx_hash: str, block_number: int | None) -> TxRef:
        url = f"{self._explorer}/tx/{tx_hash}" if self._explorer and self.mode == "fuji" else None
        return TxRef(tx_hash=tx_hash, explorer_url=url, simulated=False, block_number=block_number)

    def _next_nonce(self, w3: Web3, address: str, *, refresh: bool = False) -> int:
        if refresh or address not in self._nonces:
            self._nonces[address] = w3.eth.get_transaction_count(address, "pending")
        nonce = self._nonces[address]
        self._nonces[address] = nonce + 1
        return nonce

    @contextmanager
    def visible_failures(self) -> Iterator[None]:
        """Inside this block, a call that would revert is still sent (fixed gas) and mined, so the
        failure shows on the explorer. Used for the scene 2b attacks."""
        previous = getattr(self._local, "visible", False)
        self._local.visible = True
        try:
            yield
        finally:
            self._local.visible = previous

    def _transact(self, role: str, contract: str, function: str, *args: Any) -> TxRef:
        account = self._account(role)
        visible = role == "attacker" or getattr(self._local, "visible", False)

        def bound(w3: Web3) -> Any:
            target = self._registry(w3) if contract == "registry" else self._escrow(w3)
            return getattr(target.functions, function)(*args)

        with self._lock:
            reason = self._simulate(bound, account.address)
            if reason is not None and not visible:
                raise ChainReverted(reason, tx=None, function=function)
            gas = FAILED_TX_GAS if reason is not None else None
            tx_hash, receipt = self._send(bound, account, gas)
            ref = self._txref(tx_hash, receipt["blockNumber"])
            if receipt["status"] != 1:
                raise ChainReverted(reason or self._replay(bound, account.address, receipt), tx=ref, function=function)
            if reason is not None:
                raise ChainReverted(reason, tx=ref, function=function)
            return ref

    def _simulate(self, bound: Callable[[Web3], Any], sender: str) -> str | None:
        try:
            self._read(lambda w3, block: bound(w3).call({"from": sender}, block_identifier=block))
        except ContractLogicError as err:
            return decode_revert(_revert_data(err))
        return None

    def _replay(self, bound: Callable[[Web3], Any], sender: str, receipt: Mapping[str, Any]) -> str:
        block = max(int(receipt["blockNumber"]) - 1, 0)
        try:
            self._rpc(lambda w3: bound(w3).call({"from": sender}, block_identifier=block))
        except ContractLogicError as err:
            return decode_revert(_revert_data(err))
        return "Reverted"

    def _send(self, bound: Callable[[Web3], Any], account: LocalAccount, gas: int | None) -> tuple[str, Any]:
        if gas is None:
            estimate = self._read(lambda w3, block: bound(w3).estimate_gas({"from": account.address}, block))
            gas = int(estimate * GAS_MARGIN)

        def build_and_send(w3: Web3, refresh: bool) -> str:
            fn = bound(w3)
            tx = fn.build_transaction(
                {
                    "from": account.address,
                    "nonce": self._next_nonce(w3, account.address, refresh=refresh),
                    "gas": gas,
                    "chainId": self._chain_id,
                }
            )
            signed = account.sign_transaction(tx)
            return _hex(w3.eth.send_raw_transaction(signed.raw_transaction))

        for attempt in range(NONCE_RETRIES):
            try:
                tx_hash = self._rpc(lambda w3, refresh=attempt > 0: build_and_send(w3, refresh))
                break
            except (Web3RPCError, ValueError) as err:
                if attempt == NONCE_RETRIES - 1 or not any(m in str(err).lower() for m in _NONCE_ERRORS):
                    raise
                log.warning("nonce out of sync for %s (%s); resyncing", account.address, err)
                time.sleep(self._poll_latency)

        try:
            receipt = self._rpc(
                lambda w3: w3.eth.wait_for_transaction_receipt(
                    tx_hash, timeout=self._receipt_timeout, poll_latency=self._poll_latency
                )
            )
        except TimeExhausted:
            self._nonces.pop(account.address, None)
            raise ChainReverted("ReceiptTimeout", tx=self._txref(tx_hash, None), function=None) from None
        self._seen_block = max(self._seen_block, int(receipt["blockNumber"]))
        return tx_hash, receipt

    @staticmethod
    def _pid(payment_id: PaymentIdLike) -> bytes:
        return to_bytes32(payment_id)

    @staticmethod
    def _intent(i: PaymentIntent) -> tuple[Any, ...]:
        return (
            to_bytes32(i.payment_id),
            to_bytes32(i.corridor_id),
            to_checksum_address(i.beneficiary),
            to_checksum_address(i.token),
            int(i.amount),
            to_bytes32(i.offchain_hash),
            to_bytes32(i.decision_hash),
            to_bytes32(i.approval_hash),
            int(i.tier),
            int(i.valid_until),
            int(i.nonce),
        )

    @staticmethod
    def _attestation(v: VerificationAttestation) -> tuple[Any, ...]:
        return (
            to_bytes32(v.payment_id),
            to_bytes32(v.intent_hash),
            int(v.method),
            int(v.result),
            bool(v.sim_swap_checked),
            to_bytes32(v.evidence_hash),
            int(v.verified_at),
            int(v.nonce),
        )

    @staticmethod
    def _revocation(r: Revocation) -> tuple[Any, ...]:
        return (to_bytes32(r.payment_id), int(r.reason_code), to_bytes32(r.case_hash), int(r.nonce))

    # --- ChainPort -----------------------------------------------------------------------------

    def domain(self) -> Eip712Domain:
        return self._domain

    def commit(self, intent: PaymentIntent, router_sig: bytes) -> TxRef:
        return self._transact("relayer", "registry", "commit", self._intent(intent), bytes(router_sig))

    def deposit(self, intent: PaymentIntent, payer: str) -> TxRef:
        return self._transact("relayer", "escrow", "deposit", self._intent(intent), to_checksum_address(payer))

    def record_verification(self, att: VerificationAttestation, verifier_sig: bytes) -> TxRef:
        return self._transact("relayer", "registry", "recordVerification", self._attestation(att), bytes(verifier_sig))

    def revoke(self, rev: Revocation, analyst_sig: bytes) -> TxRef:
        return self._transact("relayer", "registry", "revoke", self._revocation(rev), bytes(analyst_sig))

    def release(self, payment_id: PaymentIdLike, caller: str = "relayer") -> TxRef:
        return self._transact(caller, "escrow", "release", self._pid(payment_id))

    def refund(self, payment_id: PaymentIdLike) -> TxRef:
        return self._transact("relayer", "escrow", "refund", self._pid(payment_id))

    def mark_executed(self, payment_id: PaymentIdLike, execution_ref: bytes) -> TxRef:
        return self._transact("relayer", "registry", "markExecuted", self._pid(payment_id), to_bytes32(execution_ref))

    def status(self, payment_id: PaymentIdLike) -> Status:
        pid = self._pid(payment_id)
        return Status(
            self._read(lambda w3, block: self._registry(w3).functions.statusOf(pid).call(block_identifier=block))
        )

    def intent_hash(self, payment_id: PaymentIdLike) -> bytes:
        pid = self._pid(payment_id)
        return bytes(
            self._read(lambda w3, block: self._registry(w3).functions.intentOf(pid).call(block_identifier=block))
        )

    # --- guardian and analyst controls ---------------------------------------------------------

    def freeze(self, payment_id: PaymentIdLike, caller: str = "analyst") -> TxRef:
        return self._transact(caller, "escrow", "freeze", self._pid(payment_id))

    def pause_corridor(self, corridor_id: CorridorIdLike, caller: str = "guardian") -> TxRef:
        return self._transact(caller, "escrow", "pauseCorridor", to_bytes32(corridor_id))
