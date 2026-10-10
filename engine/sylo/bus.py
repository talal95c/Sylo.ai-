"""Event bus: stamps events, keeps the session buffer and fans out to stream subscribers.

`seq` increases by one for every stored event and never restarts while the engine runs.
`reset()` clears the session buffer; the next event (`session.reset`) opens the new session.
"""

import asyncio
from typing import Any, Callable, Optional

from .pacer import iso_millis

SCHEMA_VERSION = 1


class EventBus:
    def __init__(self, pacer, mode_data: Callable[[], dict[str, Any]]):
        self._pacer = pacer
        self._mode_data = mode_data
        self._events: list[dict[str, Any]] = []
        self._seq = 0
        self._subscribers: set[asyncio.Queue] = set()

    # ------------------------------------------------------------------ publishing

    def _envelope(self, seq: int, type_: str, payment_id: Optional[str], data: dict[str, Any], simulated: bool) -> dict[str, Any]:
        return {
            "v": SCHEMA_VERSION,
            "seq": seq,
            "id": f"evt-{seq:06d}",
            "ts": iso_millis(self._pacer.now()),
            "type": type_,
            "paymentId": payment_id,
            "simulated": bool(simulated),
            "data": data,
        }

    def publish(self, type_: str, payment_id: Optional[str], data: dict[str, Any], simulated: bool = False) -> dict[str, Any]:
        self._seq += 1
        event = self._envelope(self._seq, type_, payment_id, data, simulated)
        self._events.append(event)
        for queue in list(self._subscribers):
            queue.put_nowait(event)
        return event

    def mode_event(self) -> dict[str, Any]:
        """The `system.mode` message sent to each new stream connection: seq 0, not stored."""
        return self._envelope(0, "system.mode", None, self._mode_data(), False)

    def publish_mode(self) -> dict[str, Any]:
        """A stored `system.mode` event, for mode changes while the engine runs."""
        return self.publish("system.mode", None, self._mode_data(), False)

    # ------------------------------------------------------------------ session

    def reset(self) -> None:
        self._events.clear()

    @property
    def last_seq(self) -> int:
        return self._seq

    def events(self, after: Optional[int] = None) -> list[dict[str, Any]]:
        if after is None:
            return list(self._events)
        return [e for e in self._events if e["seq"] > after]

    # ------------------------------------------------------------------ subscribers

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)
