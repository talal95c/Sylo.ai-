from __future__ import annotations

import hashlib
import json
from typing import Any

from api.events import EventBus, event_bus

GENESIS_HASH = "0x" + "0" * 64


class HashChainJournal:
    def __init__(
        self,
        *,
        bus: EventBus = event_bus,
        payment_id: str = "unknown",
        uetr: str = "unknown",
        scene: str = "",
    ) -> None:
        self.entries: list[dict[str, Any]] = []
        self.bus = bus
        self.payment_id = payment_id
        self.uetr = uetr
        self.scene = scene

    @staticmethod
    def _hash(seq: int, previous: str, kind: str, payload: Any) -> str:
        encoded = json.dumps(
            {
                "seq": seq,
                "prevHash": previous,
                "type": kind,
                "payload": payload,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return "0x" + hashlib.sha256(encoded).hexdigest()

    def append(self, kind: str, payload: Any) -> dict[str, Any]:
        seq = len(self.entries) + 1
        previous = self.entries[-1]["hash"] if self.entries else GENESIS_HASH
        entry = {
            "seq": seq,
            "prevHash": previous,
            "type": kind,
            "payload": payload,
            "hash": self._hash(seq, previous, kind, payload),
            "anchoredRoot": None,
        }
        self.entries.append(entry)
        return entry

    def verify(self) -> bool:
        previous = GENESIS_HASH
        for index, entry in enumerate(self.entries, start=1):
            expected = self._hash(
                index,
                entry.get("prevHash", ""),
                entry.get("type", ""),
                entry.get("payload"),
            )
            if (
                entry.get("seq") != index
                or entry.get("prevHash") != previous
                or entry.get("hash") != expected
            ):
                self.bus.publish(
                    "log.tampered",
                    self.payment_id,
                    self.uetr,
                    self.scene,
                    {
                        "seq": entry.get("seq", index),
                        "expectedHash": expected,
                        "actualHash": entry.get("hash", ""),
                        "reason": "journal hash chain mismatch",
                    },
                )
                return False
            previous = entry["hash"]
        return True
