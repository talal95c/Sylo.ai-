"""Guardian (roadmap C2.1): watches the registry and the escrow through every RPC endpoint and stops what
the engine did not sign.

Rules:
- ``CONFIRMED_WITHOUT_OOB_RECORD``: a CONFIRMED verification whose exact signed attestation the engine
  never produced (a stolen verifier key). Freeze the hold, then pause its corridor.
- ``RELEASED_BEFORE_FREEZE``: a payment flagged by the rule above was released before the freeze landed.
- ``RELEASE_WITHOUT_INTENT``: the escrow released a payment the registry holds no intent for.
- ``UNKNOWN_CALLER_ON_PRIVILEGED_FUNCTION``: a role-gated function sent by an address that is not a known
  role holder. If the call succeeded, pause the watched corridors.
- ``ROLE_GRANTED_TO_UNKNOWN_ACCOUNT``: a role granted to an address that is not a known role holder.

The guardian only makes things stricter: it freezes and pauses, never releases or unpauses. If the engine
cannot be asked, a confirmation counts as unmatched. A log seen by any endpoint counts, so one lagging or
failing RPC does not hide it.

Limit: ``release`` is open to anyone once a payment is CONFIRMED, so a thief who confirms and releases in
the same block beats a poller. The challenge window of the roadmap closes that race.

    uv run python -m sylo_chain.guardian watch      # reads ../.env; posts incidents to the engine
    uv run python -m sylo_chain.guardian unpause    # admin key: reopen the corridor after a key rotation
"""

from __future__ import annotations

import argparse
import logging
import os
import threading
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

import requests
from eth_utils import keccak
from sylo_spec.canonical import corridor_id_of, keccak_text, to_hex
from sylo_spec.eip712 import digest
from sylo_spec.models import VerificationAttestation, VerificationResult
from sylo_spec.ports import ChainReverted
from sylo_spec.scenarios import CORRIDOR, ORDERS
from web3 import Web3
from web3.exceptions import BlockNotFound

from .abi import load_abi
from .envfile import load_env_file
from .fuji import FujiChain

log = logging.getLogger("sylo_chain.guardian")

POLL_SECONDS = 2.0
MAX_BLOCKS_PER_POLL = 200
MAX_RUNS_PER_ORDER = 50
MAX_PENDING_POSTS = 50
ZERO32 = "0x" + "00" * 32
ABI_NAMES = {"registry": "PaymentRegistry", "escrow": "PaymentEscrow"}
PRIVILEGED = {
    "registry": {"markExecuted", "grantRole", "revokeRole"},
    "escrow": {"deposit", "freeze", "pauseCorridor", "unpauseCorridor", "setHoldSeconds", "grantRole", "revokeRole"},
}
KNOWN_CALLER_VARS = (
    "DEPLOYER_ADDRESS",
    "RELAYER_ADDRESS",
    "ROUTER_SIGNER_ADDRESS",
    "VERIFIER_SIGNER_ADDRESS",
    "ANALYST_SIGNER_ADDRESS",
    "GUARDIAN_ADDRESS",
)
ATTESTATION_FIELDS = (
    "paymentId",
    "intentHash",
    "method",
    "result",
    "simSwapChecked",
    "evidenceHash",
    "verifiedAt",
    "nonce",
)


class EngineUnavailable(Exception):
    """The engine could not be asked what it signed."""


class Records(Protocol):
    def order_id(self, chain_pid: str) -> str | None: ...

    def attestation_digests(self, chain_pid: str) -> set[str]: ...

    def post_incident(self, body: Mapping[str, Any]) -> None: ...


class EngineRecords:
    """What the engine signed for a payment, read from ``GET /v1/payments/{id}/proof``.

    The engine signs an attestation before it sends it, so a genuine confirmation is already in the
    proof when its log appears on chain. On-chain ids are ``keccak(order id)``, or ``keccak("id#n")``
    for the n-th run of the same order.
    """

    def __init__(self, base_url: str, order_ids: Iterable[str] | None = None, timeout: float = 3.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        ids = list(order_ids) if order_ids is not None else [order.id for order in ORDERS.values()]
        self._labels: dict[str, str] = {}
        self._last_payment_refresh: float | None = None
        for order_id in ids:
            for run in range(1, MAX_RUNS_PER_ORDER + 1):
                label = order_id if run == 1 else f"{order_id}#{run}"
                self._labels[to_hex(keccak_text(label)).lower()] = order_id

    def order_id(self, chain_pid: str) -> str | None:
        normalized = chain_pid.lower()
        if normalized not in self._labels:
            self._refresh_payment_labels()
        return self._labels.get(normalized)

    def _refresh_payment_labels(self) -> None:
        now = time.monotonic()
        if self._last_payment_refresh is not None and now - self._last_payment_refresh < 5.0:
            return
        self._last_payment_refresh = now
        try:
            response = requests.get(f"{self.base_url}/v1/payments", timeout=self.timeout)
            if not response.ok:
                return
            payload = response.json()
            if not isinstance(payload, Mapping):
                return
            payments = payload.get("payments", [])
            if not isinstance(payments, list):
                return
        except (requests.RequestException, ValueError, TypeError, AttributeError):
            return
        for payment in payments:
            if not isinstance(payment, Mapping):
                continue
            payment_id = payment.get("paymentId")
            chain_payment_id = payment.get("chainPaymentId")
            if isinstance(payment_id, str) and isinstance(chain_payment_id, str):
                self._labels[chain_payment_id.lower()] = payment_id

    def attestation_digests(self, chain_pid: str) -> set[str]:
        order_id = self.order_id(chain_pid)
        if order_id is None:
            return set()
        try:
            response = requests.get(f"{self.base_url}/v1/payments/{order_id}/proof", timeout=self.timeout)
        except requests.RequestException as err:
            raise EngineUnavailable(type(err).__name__) from err
        if response.status_code == 404:
            return set()
        if not response.ok:
            raise EngineUnavailable(f"HTTP {response.status_code}")
        proof = response.json()
        if str(proof.get("chainPaymentId", "")).lower() != chain_pid.lower():
            return set()  # the engine's current run of this order is another payment
        return {
            str(item["digest"]).lower()
            for item in proof.get("signed", [])
            if item.get("type") == "VerificationAttestation" and item.get("digest")
        }

    def post_incident(self, body: Mapping[str, Any]) -> None:
        kwargs: dict[str, Any] = {"json": dict(body), "timeout": self.timeout}
        if token := os.environ.get("OPERATOR_TOKEN"):
            kwargs["headers"] = {"X-Sylo-Operator": token}
        response = requests.post(f"{self.base_url}/v1/guardian/incidents", **kwargs)
        response.raise_for_status()


@dataclass
class Incident:
    rule: str
    tx_hash: str
    action: str = "NONE"
    payment_id: str | None = None
    order_id: str | None = None
    detail: str = ""
    action_txs: list[str] = field(default_factory=list)
    seen_at: float | None = None
    acted_at: float = field(default_factory=time.time)


def _hex(value: Any) -> str:
    if isinstance(value, str):
        return value.lower() if value.startswith("0x") else "0x" + value.lower()
    return "0x" + bytes(value).hex()


def _attestation(raw: Any) -> VerificationAttestation:
    values = [raw[name] for name in ATTESTATION_FIELDS] if isinstance(raw, Mapping) else list(raw)
    payment_id, intent_hash, method, result, sim_swap, evidence, verified_at, nonce = values
    return VerificationAttestation(
        payment_id=_hex(payment_id),
        intent_hash=_hex(intent_hash),
        method=int(method),
        result=int(result),
        sim_swap_checked=bool(sim_swap),
        evidence_hash=_hex(evidence),
        verified_at=int(verified_at),
        nonce=int(nonce),
    )


class Guardian:
    def __init__(
        self,
        chain: FujiChain,
        records: Records,
        *,
        known_callers: Iterable[str] = (),
        corridors: Iterable[str] = (),
        pause: bool = True,
        from_block: int | None = None,
    ) -> None:
        self.chain = chain
        self.records = records
        self.pause = pause
        self.corridors = [c.lower() for c in corridors] or [corridor_id_of(CORRIDOR).lower()]
        roles = ("relayer", "analyst", "guardian", "admin")
        self.known = {a.lower() for a in known_callers if a}
        self.known |= {a.lower() for a in (chain.address(r) for r in roles) if a}
        self.known |= {chain.registry_address.lower(), chain.escrow_address.lower()}
        self.incidents: list[Incident] = []
        self._flagged: set[str] = set()
        self._pending: list[dict[str, Any]] = []
        self._topics = self._event_topics()
        self._addresses = {chain.registry_address.lower(): "registry", chain.escrow_address.lower(): "escrow"}
        self.cursor = from_block - 1 if from_block is not None else self._head()

    # --- loop ----------------------------------------------------------------------------------

    def run(self, interval: float = POLL_SECONDS, stop: threading.Event | None = None) -> None:
        stop = stop or threading.Event()
        log.info("guardian watching %s and %s from block %d", self.chain.registry_address, self.chain.escrow_address, self.cursor + 1)
        while not stop.is_set():
            try:
                self.poll_once()
            except Exception:
                log.exception("guardian poll failed; retrying")
            stop.wait(interval)

    def poll_once(self) -> list[Incident]:
        start = self.cursor + 1
        reached, entries = self._scan(start)
        found: list[Incident] = []
        for entry in entries:
            try:
                found.extend(self._on_log(entry))
            except Exception:
                log.exception("could not check log %s", _hex(entry["transactionHash"]))
        found.extend(self._check_calls(start, reached))
        self.cursor = max(self.cursor, reached)
        for incident in found:
            self._report(incident)
        self._flush()
        return found

    # --- reads on every endpoint ---------------------------------------------------------------

    def _head(self) -> int:
        heads = []
        for w3 in self.chain.endpoints:
            try:
                heads.append(int(w3.eth.block_number))
            except Exception as err:
                log.warning("RPC endpoint unreachable (%s)", type(err).__name__)
        if not heads:
            raise ConnectionError("no RPC endpoint answered")
        return max(heads)

    def _scan(self, start: int) -> tuple[int, list[Any]]:
        """Logs of both contracts from ``start``, merged across endpoints. Returns (last block covered, logs)."""
        reached = self.cursor
        merged: dict[tuple[str, int], Any] = {}
        for w3 in self.chain.endpoints:
            try:
                end = min(int(w3.eth.block_number), start + MAX_BLOCKS_PER_POLL - 1)
                if end < start:
                    continue
                logs = w3.eth.get_logs(
                    {
                        "address": [self.chain.registry_address, self.chain.escrow_address],
                        "fromBlock": start,
                        "toBlock": end,
                    }
                )
            except Exception as err:
                log.warning("RPC endpoint failed during the scan (%s); the others still count", type(err).__name__)
                continue
            reached = max(reached, end)
            for entry in logs:
                merged.setdefault((_hex(entry["transactionHash"]), int(entry["logIndex"])), entry)
        return reached, sorted(merged.values(), key=lambda e: (int(e["blockNumber"]), int(e["logIndex"])))

    def _on_any(self, call: Any) -> Any:
        last: Exception | None = None
        for w3 in self.chain.endpoints:
            try:
                return call(w3)
            except Exception as err:
                last = err
        raise ConnectionError(f"no RPC endpoint answered: {last}")

    def _block(self, number: int, full: bool = False) -> Any:
        def get(w3: Web3) -> Any:
            block = w3.eth.get_block(number, full_transactions=full)
            if block is None:
                raise BlockNotFound(number)
            return block

        return self._on_any(get)

    def _event_topics(self) -> dict[bytes, tuple[str, str]]:
        topics: dict[bytes, tuple[str, str]] = {}
        for contract, abi_name in ABI_NAMES.items():
            for item in load_abi(abi_name):
                if item.get("type") == "event":
                    signature = f"{item['name']}({','.join(i['type'] for i in item['inputs'])})"
                    topics[keccak(text=signature)] = (contract, item["name"])
        return topics

    # --- rules ---------------------------------------------------------------------------------

    def _on_log(self, entry: Any) -> list[Incident]:
        if not entry["topics"]:
            return []
        contract, event = self._topics.get(bytes(entry["topics"][0]), (None, None))
        if contract is None or event is None:
            return []
        w3 = self.chain.endpoints[0]
        args = getattr(self.chain.contract(w3, contract).events, event)().process_log(entry)["args"]
        tx_hash = _hex(entry["transactionHash"])
        if event == "VerificationRecorded" and int(args["result"]) == int(VerificationResult.CONFIRMED):
            return self._check_confirmation(_hex(args["paymentId"]), tx_hash, int(entry["blockNumber"]))
        if event == "Released":
            return self._check_release(_hex(args["paymentId"]), tx_hash)
        if event == "RoleGranted" and str(args["account"]).lower() not in self.known:
            return [
                Incident(
                    "ROLE_GRANTED_TO_UNKNOWN_ACCOUNT",
                    tx_hash,
                    detail=f"{contract} granted role {_hex(args['role'])} to {args['account']}",
                )
            ]
        return []

    def _check_confirmation(self, pid: str, tx_hash: str, block: int) -> list[Incident]:
        tx = self._on_any(lambda w3: w3.eth.get_transaction(tx_hash))
        _, params = self.chain.contract(self.chain.endpoints[0], "registry").decode_function_input(tx["input"])
        signed = to_hex(digest(_attestation(params["v"]), self.chain.domain())).lower()
        engine_down = None
        try:
            known = self.records.attestation_digests(pid)
        except EngineUnavailable as err:
            known, engine_down = set(), str(err)
        if signed in known:
            return []

        self._flagged.add(pid)
        incident = Incident(
            "CONFIRMED_WITHOUT_OOB_RECORD",
            tx_hash,
            payment_id=pid,
            order_id=self.records.order_id(pid),
            seen_at=float(self._block(block)["timestamp"]),
            detail=(
                f"engine unreachable ({engine_down}): treated as unmatched"
                if engine_down
                else "the engine never signed this attestation"
            ),
        )
        actions: list[str] = []
        hold = self.chain.hold(pid)
        if hold["expiresAt"] == 0:
            incident.detail += "; no escrow hold to freeze"
        elif hold["settled"]:
            incident.rule = "RELEASED_BEFORE_FREEZE"
            incident.detail += "; the hold was already settled"
        elif not hold["frozen"]:
            try:
                incident.action_txs.append(self.chain.freeze(pid, caller="guardian").tx_hash)
                actions.append("FREEZE")
            except ChainReverted as err:
                incident.detail += f"; freeze refused ({err.reason})"
        if self.pause and hold["expiresAt"] != 0 and hold["corridorId"] != ZERO32:
            if self._pause(hold["corridorId"], incident):
                actions.append("PAUSE")
        incident.action = "_AND_".join(actions) or "NONE"
        incident.acted_at = time.time()
        return [incident]

    def _check_release(self, pid: str, tx_hash: str) -> list[Incident]:
        if pid in self._flagged:
            return [Incident("RELEASED_BEFORE_FREEZE", tx_hash, payment_id=pid, order_id=self.records.order_id(pid))]
        if _hex(self.chain.intent_hash(pid)) == ZERO32:
            return [Incident("RELEASE_WITHOUT_INTENT", tx_hash, payment_id=pid, order_id=self.records.order_id(pid))]
        return []

    def _check_calls(self, start: int, end: int) -> list[Incident]:
        found: list[Incident] = []
        for number in range(start, end + 1):
            for tx in self._block(number, full=True)["transactions"]:
                contract = self._addresses.get(str(tx.get("to") or "").lower())
                sender = str(tx["from"]).lower()
                if contract is None or sender in self.known:
                    continue
                try:
                    function, _ = self.chain.contract(self.chain.endpoints[0], contract).decode_function_input(tx["input"])
                except ValueError:
                    continue
                if function.fn_name not in PRIVILEGED[contract]:
                    continue
                tx_hash = _hex(tx["hash"])
                receipt = self._on_any(lambda w3, h=tx_hash: w3.eth.get_transaction_receipt(h))
                succeeded = int(receipt["status"]) == 1
                incident = Incident(
                    "UNKNOWN_CALLER_ON_PRIVILEGED_FUNCTION",
                    tx_hash,
                    detail=f"{contract}.{function.fn_name} from {tx['from']}: "
                    + ("succeeded" if succeeded else "refused by the contract"),
                )
                if succeeded and self.pause:
                    paused = [c for c in self.corridors if self._pause(c, incident)]
                    incident.action = "PAUSE" if paused else "NONE"
                found.append(incident)
        return found

    def _pause(self, corridor_id: str, incident: Incident) -> bool:
        if self.chain.corridor_paused(corridor_id):
            return False
        try:
            incident.action_txs.append(self.chain.pause_corridor(corridor_id, caller="guardian").tx_hash)
            return True
        except ChainReverted as err:
            incident.detail += f"; pause refused ({err.reason})"
            return False

    # --- reporting -----------------------------------------------------------------------------

    def _report(self, incident: Incident) -> None:
        self.incidents.append(incident)
        log.warning(
            "INCIDENT %s on %s: action %s %s %s",
            incident.rule,
            incident.order_id or incident.payment_id or "-",
            incident.action,
            incident.action_txs,
            incident.detail,
        )
        duration = (incident.acted_at - incident.seen_at) / 60 if incident.seen_at else None
        body = {
            "rule": incident.rule,
            "action": incident.action,
            "txHash": incident.tx_hash,
            "explorerUrl": self.chain.explorer_tx_url(incident.tx_hash),
            "paymentId": incident.order_id,
            "simulated": self.chain.mode != "fuji",
            "durationMinutes": round(max(duration, 0.0), 2) if duration is not None else None,
        }
        self._pending.append({k: v for k, v in body.items() if v is not None})
        del self._pending[:-MAX_PENDING_POSTS]

    def _flush(self) -> None:
        while self._pending:
            try:
                self.records.post_incident(self._pending[0])
            except Exception as err:
                log.warning("engine did not take the incident (%s); retrying at the next poll", type(err).__name__)
                return
            self._pending.pop(0)


# --- command line --------------------------------------------------------------------------------


def _engine_url(env: Mapping[str, str]) -> str:
    return env.get("ENGINE_URL") or f"http://localhost:{env.get('ENGINE_PORT') or 8000}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sylo_chain.guardian", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    watch = sub.add_parser("watch", help="watch the contracts and act on incidents")
    watch.add_argument("--engine-url", help="default: ENGINE_URL or http://localhost:$ENGINE_PORT")
    watch.add_argument("--interval", type=float, default=POLL_SECONDS)
    watch.add_argument("--from-block", type=int, help="default: the current block")
    watch.add_argument("--no-pause", action="store_true", help="freeze only, never pause a corridor")
    unpause = sub.add_parser("unpause", help="reopen a corridor (admin key, after rotating the stolen key)")
    unpause.add_argument("--corridor", default=CORRIDOR)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_env_file()
    chain = FujiChain.from_env()
    if args.command == "unpause":
        corridor = corridor_id_of(args.corridor)
        if not chain.corridor_paused(corridor):
            print(f"corridor {args.corridor} is not paused")
            return 0
        ref = chain.unpause_corridor(corridor)
        print(f"corridor {args.corridor} reopened: {ref.explorer_url or ref.tx_hash}")
        return 0

    if not chain.address("guardian"):
        parser.error("GUARDIAN_PK is not set")
    guardian = Guardian(
        chain,
        EngineRecords(args.engine_url or _engine_url(os.environ)),
        known_callers=[os.environ.get(name, "") for name in KNOWN_CALLER_VARS],
        pause=not args.no_pause,
        from_block=args.from_block,
    )
    try:
        guardian.run(args.interval)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
