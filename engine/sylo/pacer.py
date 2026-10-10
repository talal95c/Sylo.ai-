"""Pacers: every wait in the orchestrator goes through one (v0 spec §5.4)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Protocol


class Pacer(Protocol):
    speed: float

    def now(self) -> datetime: ...

    async def wait(self, ms: float) -> None: ...


class RealPacer:
    """Wall clock; sleeps for ``ms / speed``."""

    def __init__(self, speed: float = 1.0) -> None:
        self.speed = speed

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    async def wait(self, ms: float) -> None:
        await asyncio.sleep(ms / self.speed / 1000)


class VirtualPacer:
    """Virtual clock for tests and the fixture recorder: never sleeps, only advances time."""

    def __init__(self, start: datetime, speed: float = 1.0) -> None:
        self._now = start
        self.speed = speed

    def now(self) -> datetime:
        return self._now

    async def wait(self, ms: float) -> None:
        self._now += timedelta(milliseconds=ms / self.speed)
        await asyncio.sleep(0)


def iso_ms(moment: datetime) -> str:
    """UTC timestamp with milliseconds, e.g. 2026-10-11T09:00:12.300Z."""
    moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"
