"""Pacers: every wait of the orchestrator goes through one, so tests run in milliseconds.

`RealPacer` sleeps and reads the wall clock. `VirtualPacer` never sleeps: it advances a
virtual clock, which makes scenario runs and recorded fixtures deterministic.
"""

import asyncio
from datetime import datetime, timedelta, timezone


def iso_millis(moment: datetime) -> str:
    """2026-10-11T09:00:12.300Z"""
    moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


class RealPacer:
    def __init__(self, speed: float = 1.0):
        self.speed = max(float(speed), 0.01)

    async def wait(self, ms: float) -> None:
        await asyncio.sleep(ms / self.speed / 1000.0)

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class VirtualPacer:
    def __init__(self, start: datetime, speed: float = 1.0):
        self.speed = max(float(speed), 0.01)
        self._now = start.astimezone(timezone.utc)

    async def wait(self, ms: float) -> None:
        self._now += timedelta(milliseconds=ms / self.speed)
        await asyncio.sleep(0)  # let the other tasks run, without waiting

    def now(self) -> datetime:
        return self._now
