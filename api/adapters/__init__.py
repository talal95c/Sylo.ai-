from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel

from api.chain.client import ChainClient, ChainRevert
from api.chain.signer import intent_hash

EventPublisher = Callable[[str, dict[str, Any]], Any]


class RailAdapter:
    def __init__(
        self,
        rail: str,
        publish: EventPublisher,
        kill_switch: Callable[[str], Any] | None = None,
        *,
        failure_limit: int = 2,
    ) -> None:
        self.rail = rail
        self.publish = publish
        self.kill_switch = kill_switch
        self.failure_limit = failure_limit
        self.failure_count = 0
        self.killed = False
        self.used_nonces: set[int] = set()
        self.idempotency: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _plain(value: Any) -> Any:
        return value.model_dump() if isinstance(value, BaseModel) else value

    def _reject(
        self,
        reason: str,
        *,
        attack: str | None = None,
        expected_hash: str | None = None,
        received_hash: str | None = None,
        nonce: int | None = None,
    ) -> None:
        data: dict[str, Any] = {"rail": self.rail, "reason": reason}
        if attack:
            data["attack"] = attack
        if expected_hash:
            data["expectedIntentHash"] = expected_hash
        if received_hash:
            data["receivedIntentHash"] = received_hash
        if nonce is not None:
            data["nonce"] = nonce
        self.publish("leg.rejected", data)
        self.failure_count += 1
        if self.failure_count >= self.failure_limit and not self.killed:
            self.killed = True
            if self.kill_switch:
                self.kill_switch(reason)
        raise ChainRevert(reason)

    def integrity_failure(
        self,
        reason: str,
        *,
        attack: str | None = None,
        expected_hash: str | None = None,
        received_hash: str | None = None,
        nonce: int | None = None,
    ) -> None:
        try:
            self._reject(
                reason,
                attack=attack,
                expected_hash=expected_hash,
                received_hash=received_hash,
                nonce=nonce,
            )
        except ChainRevert:
            return

    def record_failure(self, reason: str) -> None:
        self.failure_count += 1
        if self.failure_count >= self.failure_limit and not self.killed:
            self.killed = True
            if self.kill_switch:
                self.kill_switch(reason)

    def initiate(
        self,
        leg: dict[str, Any],
        intent: dict[str, Any],
        chain: ChainClient,
        *,
        expected_intent_hash: str,
        tier: str,
        idempotency_key: str,
        attack: str | None = None,
        now: int | None = None,
    ) -> dict[str, Any]:
        if idempotency_key in self.idempotency:
            return self.idempotency[idempotency_key]
        if not idempotency_key:
            self._reject("IdempotencyKeyRequired", attack=attack)
        if self.killed:
            self._reject("AdapterKillSwitched", attack=attack)

        try:
            computed_hash = intent_hash(intent)
        except (KeyError, TypeError, ValueError):
            self._reject("IntentHashMismatch", attack=attack)
        received_hash = leg.get("intentHash")
        if (
            computed_hash.lower() != expected_intent_hash.lower()
            or received_hash is None
            or received_hash.lower() != expected_intent_hash.lower()
        ):
            self._reject(
                "IntentHashMismatch",
                attack=attack,
                expected_hash=expected_intent_hash,
                received_hash=str(received_hash),
            )

        timestamp = now if now is not None else __import__("time").time_ns() // 1_000_000_000
        if timestamp >= int(intent["validUntil"]):
            self._reject("IntentExpired", attack=attack)
        nonce = int(intent["nonce"])
        if int(leg.get("nonce", -1)) != nonce:
            self._reject("NonceMismatch", attack=attack, nonce=nonce)
        if nonce in self.used_nonces:
            self._reject("NonceUsed", attack=attack, nonce=nonce)
        state = chain.status(str(intent["paymentId"]))["status"]
        expected_state = "COMMITTED" if tier == "LOW" else "CONFIRMED"
        if state != expected_state:
            self._reject("PaymentNotExecutable", attack=attack)

        self.used_nonces.add(nonce)
        result = {"status": "pending", "rail": self.rail, "nonce": nonce}
        self.idempotency[idempotency_key] = result
        return result

    def settle(self, leg: dict[str, Any]) -> dict[str, Any]:
        result = dict(leg)
        result["status"] = "settled"
        return result