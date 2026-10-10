"""In-memory event bus: session buffer, seq numbering and fan-out to stream subscribers (v0 spec §5.3)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from .pacer import iso_ms


class EventBus:
    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []
        self._seq = 0
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    @property
    def events(self) -> list[dict[str, Any]]:
        return list(self._events)

    @property
    def last_seq(self) -> int:
        return self._seq

    def publish(
        self,
        type_: str,
        data: dict[str, Any],
        *,
        payment_id: str | None = None,
        simulated: bool = False,
        ts: datetime | None = None,
    ) -> dict[str, Any]:
        self._seq += 1
        event = {
            "v": 1,
            "seq": self._seq,
            "id": f"evt-{self._seq:06d}",
            "ts": iso_ms(ts or datetime.now(timezone.utc)),
            "type": type_,
            "paymentId": payment_id,
            "simulated": simulated,
            "data": data,
        }
        self._events.append(event)
        for queue in list(self._subscribers):
            queue.put_nowait(event)
        return event

    def clear(self) -> None:
        """Forget the session's events. ``seq`` keeps increasing so reconnecting clients stay consistent."""
        self._events.clear()

    def since(self, last_seq: int | None) -> list[dict[str, Any]]:
        if last_seq is None:
            return list(self._events)
        return [e for e in self._events if e["seq"] > last_seq]

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)
