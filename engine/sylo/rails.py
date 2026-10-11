"""Rail adapters R1–R4 (roadmap A1.5, PRD §13.5). The four adapters are simulated.

Every rail is reached through the same interface: ``quote``, ``initiate``, ``status``. A leg is a
pacs.008-shaped message that carries the payment's UETR, the signed intent and the salt of its
off-chain fields. Before a leg is initiated the adapter

1. recomputes the intent digest from the leg's own fields and salt and compares it with the registry;
2. checks the validity window and that the leg was not already executed;
3. reads the registry: not revoked, ``COMMITTED`` (LOW, or the funding legs of a MEDIUM payment) or
   confirmed (the pay-out legs of a MEDIUM payment).

Any failure is refused (``LegRejected``): a substituted beneficiary is prevented, not just detected.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from sylo_spec.canonical import keccak_text, offchain_hash, to_bytes32, to_hex
from sylo_spec.eip712 import digest
from sylo_spec.models import Money, PaymentIntent, Status, Tier
from sylo_spec.ports import ChainPort

from .norms import Pack, RouteDef

INTENT_HASH_MISMATCH = "INTENT_HASH_MISMATCH"
NONCE_USED = "NONCE_USED"
REVOKED = "REVOKED"
EXPIRED = "EXPIRED"
NOT_CONFIRMED = "NOT_CONFIRMED"
RAIL_DOWN = "RAIL_DOWN"
KILL_SWITCH = "KILL_SWITCH"

INTEGRITY_REASONS = frozenset({INTENT_HASH_MISMATCH, NONCE_USED})
"""Refusals that count towards the kill switch: someone tried to change or replay a leg."""


@dataclass(frozen=True)
class LegMessage:
    """One leg of a payment, shaped like a pacs.008 credit transfer (JSON, not ISO 20022 XML)."""

    order_id: str
    uetr: str
    hop: int
    rail: str
    sender: str
    receiver: str
    kind: str
    amount: Money
    creditor_name: str
    creditor_account: str
    creditor_bank: str
    invoice_ref: str | None
    salt: str
    intent: PaymentIntent

    @property
    def idempotency_key(self) -> str:
        return to_hex(keccak_text(f"{self.order_id}:{self.hop}:{self.intent.nonce}"))

    def offchain_fields(self) -> dict[str, Any]:
        """The fields hidden behind ``intent.offchainHash`` (same keys as the orchestrator uses)."""
        return {
            "creditorName": self.creditor_name,
            "account": self.creditor_account,
            "bank": self.creditor_bank,
            "invoiceRef": self.invoice_ref,
            "uetr": self.uetr,
        }

    def recomputed_intent(self) -> PaymentIntent:
        """The intent as this leg describes it: the off-chain hash is rebuilt from the leg's own fields."""
        salt = bytes.fromhex(self.salt[2:] if self.salt.startswith("0x") else self.salt)
        return self.intent.model_copy(update={"offchain_hash": offchain_hash(salt, self.offchain_fields())})

    def to_pacs008(self, intent_hash: str) -> dict[str, Any]:
        return {
            "format": "pacs.008-shaped JSON (simulated)",
            "uetr": self.uetr,
            "instructingAgent": self.sender,
            "instructedAgent": self.receiver,
            "interbankSettlementAmount": {"value": self.amount.value, "currency": self.amount.currency},
            "creditor": {"name": self.creditor_name, "account": self.creditor_account, "agent": self.creditor_bank},
            "remittanceInformation": self.invoice_ref,
            "supplementaryData": {
                "intentHash": intent_hash,
                "nonce": self.intent.nonce,
                "validUntil": self.intent.valid_until,
                "idempotencyKey": self.idempotency_key,
            },
        }


LEG_STATUSES = ("PENDING", "SETTLED", "FAILED", "RETURNED")
WEBHOOK_STATUSES = ("SETTLED", "FAILED", "RETURNED")


class LegRejected(Exception):
    def __init__(self, reason: str, leg: LegMessage, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.leg = leg
        self.detail = detail


class RailAdapter:
    """One simulated rail. Thread-safe: ``initiate`` runs in a worker thread because it reads the chain."""

    simulated = True

    def __init__(self, route: RouteDef, chain: ChainPort, clock: Callable[[], float]) -> None:
        self.route = route
        self.id = route.id
        self.name = route.name
        self._chain = chain
        self._clock = clock
        self._legs: dict[str, str] = {}
        self._refusals: list[tuple[float, str]] = []
        self._lock = threading.RLock()
        self.down_reason: str | None = None
        self.killed_reason: str | None = None

    # --- interface ---------------------------------------------------------------------------

    def quote(self, amount_eur: float) -> dict[str, Any]:
        return {
            "routeId": self.id,
            "rail": self.name,
            "settlement": self.route.settlement,
            "feesEur": round(self.route.fees(amount_eur), 2),
            "etaLabel": self.route.eta_label,
            "available": self.available,
            "simulated": True,
        }

    def initiate(self, leg: LegMessage) -> dict[str, Any]:
        """Send one leg, or raise ``LegRejected``. A retry of a leg that is still pending is not sent twice."""
        with self._lock:
            if self.killed_reason is not None:
                self._refuse(KILL_SWITCH, leg, f"the {self.name} adapter is cut: {self.killed_reason}")
            if self.down_reason is not None:
                self._refuse(RAIL_DOWN, leg, f"the {self.name} rail is down: {self.down_reason}")

            payment_id = leg.intent.payment_id
            domain = self._chain.domain()
            expected = bytes(self._chain.intent_hash(to_bytes32(payment_id)))
            if digest(leg.recomputed_intent(), domain) != expected:
                self._refuse(INTENT_HASH_MISMATCH, leg, "the leg does not match the intent sealed in the registry")

            key = leg.idempotency_key
            previous = self._legs.get(key)
            if previous == "PENDING":
                return {"idempotencyKey": key, "status": previous, "retry": True}

            status = Status(int(self._chain.status(to_bytes32(payment_id))))
            payout = self.is_payout(leg.hop, leg.intent.tier)
            # A pay-out leg follows a hold that may last hours: the on-chain release already checked its expiry.
            if not payout and self._clock() > leg.intent.valid_until:
                self._refuse(EXPIRED, leg, "the intent's validity window has passed")
            if previous is not None:
                self._refuse(NONCE_USED, leg, "this leg was already executed")
            if status == Status.EXECUTED and not payout:
                self._refuse(NONCE_USED, leg, "the intent was already executed")
            if status == Status.REVOKED:
                self._refuse(REVOKED, leg, "the payment was revoked")
            allowed = (Status.CONFIRMED, Status.EXECUTED) if payout else (Status.COMMITTED, Status.CONFIRMED)
            if leg.intent.tier == Tier.LOW:
                allowed = (Status.COMMITTED,)
            if leg.intent.tier > Tier.MEDIUM or status not in allowed:
                self._refuse(NOT_CONFIRMED, leg, f"the registry status is {status.name}")

            self._legs[key] = "PENDING"
            return {"idempotencyKey": key, "status": "PENDING", "retry": False}

    def settle(self, idempotency_key: str) -> None:
        with self._lock:
            if idempotency_key in self._legs:
                self._legs[idempotency_key] = "SETTLED"

    def status(self, idempotency_key: str) -> str:
        return self._legs.get(idempotency_key, "UNKNOWN")

    def on_webhook(self, notification: Mapping[str, Any]) -> dict[str, Any]:
        """An asynchronous status sent by the rail. It can only move a leg this adapter sent, and only
        forward: a webhook never creates a leg, and a final status is not reopened (a settled leg can
        still come back as returned)."""
        key = str(notification.get("idempotencyKey") or "")
        status = str(notification.get("status") or "").upper()
        with self._lock:
            current = self._legs.get(key)
            if current is None:
                return {"accepted": False, "reason": "UNKNOWN_LEG"}
            if status not in WEBHOOK_STATUSES:
                return {"accepted": False, "reason": "UNKNOWN_STATUS", "status": current}
            if current != "PENDING" and not (current == "SETTLED" and status == "RETURNED"):
                return {"accepted": False, "reason": "FINAL_STATUS", "status": current}
            self._legs[key] = status
            return {"accepted": True, "status": status}

    def reconcile(self) -> dict[str, Any]:
        """What the adapter holds about its legs, to compare with the rail's own statement."""
        with self._lock:
            counts = {status: 0 for status in LEG_STATUSES}
            for status in self._legs.values():
                counts[status] = counts.get(status, 0) + 1
            return {
                "routeId": self.id,
                "rail": self.name,
                "legs": len(self._legs),
                "byStatus": counts,
                "open": sorted(key for key, status in self._legs.items() if status == "PENDING"),
                "toInvestigate": sorted(key for key, status in self._legs.items() if status in ("FAILED", "RETURNED")),
                "refusals": len(self._refusals),
                "simulated": True,
            }

    # --- routing facts -----------------------------------------------------------------------

    @property
    def available(self) -> bool:
        return self.down_reason is None and self.killed_reason is None

    def hold_hop(self) -> int | None:
        """Index of the hop where a MEDIUM payment waits: the chain hop (escrow) or the sender's bank (fiat hold)."""
        if self.route.settlement == "ONCHAIN_ESCROW":
            return next((i for i, hop in enumerate(self.route.hops) if hop[2] == "chain"), None)
        if self.route.settlement == "FIAT_HOLD":
            return 0
        return None

    def is_payout(self, hop: int, tier: int) -> bool:
        """Pay-out legs move money towards the beneficiary after the hold; they need a confirmed payment."""
        if tier == Tier.LOW:
            return False
        hold = self.hold_hop()
        return hold is None or hop > hold

    # --- refusals and kill switch ------------------------------------------------------------

    def _refuse(self, reason: str, leg: LegMessage, detail: str) -> None:
        self._refusals.append((self._clock(), reason))
        raise LegRejected(reason, leg, detail)

    def integrity_refusals(self, within_seconds: float) -> int:
        cutoff = self._clock() - within_seconds
        return sum(1 for at, reason in self._refusals if at >= cutoff and reason in INTEGRITY_REASONS)

    def restore(self) -> None:
        """The rail is back and the adapter is trusted again (after an outage, or after the keys were rotated)."""
        self.down_reason = None
        self.killed_reason = None
        self._refusals.clear()


class Rails:
    """The adapters of one corridor pack."""

    def __init__(self, pack: Pack, chain: ChainPort, clock: Callable[[], float]) -> None:
        self._adapters = {route.id: RailAdapter(route, chain, clock) for route in pack.routes}

    def adapter(self, route_id: str) -> RailAdapter:
        return self._adapters[route_id]

    def get(self, route_id: str) -> RailAdapter | None:
        return self._adapters.get(route_id)

    def reset(self) -> None:
        """A new demo session: every rail is up and every adapter trusted. Executed legs stay executed."""
        for adapter in self:
            adapter.restore()

    def __iter__(self):
        return iter(self._adapters.values())

    def unavailable(self) -> dict[str, str]:
        """Route id -> why it cannot be used right now (rail down or adapter cut by the kill switch)."""
        return {
            adapter.id: (KILL_SWITCH if adapter.killed_reason is not None else RAIL_DOWN)
            for adapter in self
            if not adapter.available
        }

    def quotes(self, amount_eur: float) -> list[dict[str, Any]]:
        return [adapter.quote(amount_eur) for adapter in self]
