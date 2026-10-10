import asyncio
from collections import deque
from datetime import datetime, timezone
from threading import RLock
from typing import Any, AsyncIterator


class EventBus:
    def __init__(self, history_size: int = 1000) -> None:
        self._events: deque[dict[str, Any]] = deque(maxlen=history_size)
        self._subscribers: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = set()
        self._next_id = 1
        self._lock = RLock()

    def publish(
        self,
        type: str,
        paymentId: str,
        uetr: str,
        scene: str,
        data: dict[str, Any],
        explorerUrl: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            envelope = {
                "id": self._next_id,
                "type": type,
                "ts": datetime.now(timezone.utc)
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z"),
                "paymentId": paymentId,
                "uetr": uetr,
                "scene": scene,
                "data": data,
                "explorerUrl": explorerUrl,
            }
            self._next_id += 1
            self._events.append(envelope)
            subscribers = tuple(self._subscribers)
        for loop, queue in subscribers:
            loop.call_soon_threadsafe(queue.put_nowait, envelope)
        return envelope

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [event.copy() for event in self._events]

    def clear(self, *, reset_ids: bool = False) -> None:
        with self._lock:
            self._events.clear()
            if reset_ids:
                self._next_id = 1

    async def stream(self, last_event_id: int | None = None) -> AsyncIterator[dict[str, Any] | None]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        subscriber = (loop, queue)
        with self._lock:
            replay = [
                event.copy()
                for event in self._events
                if last_event_id is not None and event["id"] > last_event_id
            ]
            self._subscribers.add(subscriber)
        try:
            for event in replay:
                yield event
            while True:
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield None
        finally:
            with self._lock:
                self._subscribers.discard(subscriber)


event_bus = EventBus()
