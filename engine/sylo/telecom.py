"""Telecom mock: SIM-swap check on a known contact (roadmap A1.4, PRD §12.1 and rule R-OOB-01).

Shaped like the CAMARA SIM Swap API: ``check(phoneNumber, maxAge)`` answers whether the SIM behind a
number changed within the last ``maxAge`` hours, and ``retrieve_date`` gives the latest change.
Simulated: there is no operator behind it, only what a scenario declares.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone


class SimSwapMock:
    simulated = True

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._changes: dict[str, datetime] = {}

    def declare_swap(self, msisdn: str, *, hours_ago: float) -> None:
        """Scenario set-up: the SIM behind ``msisdn`` changed ``hours_ago`` hours before now."""
        self._changes[msisdn] = self._clock() - timedelta(hours=hours_ago)

    def clear(self) -> None:
        self._changes.clear()

    def retrieve_date(self, msisdn: str) -> datetime | None:
        """CAMARA ``retrieve-date``: the latest SIM change, or None when none is known."""
        return self._changes.get(msisdn)

    def check(self, msisdn: str, max_age_hours: int = 240) -> bool:
        """CAMARA ``check``: True when the SIM changed within the last ``max_age_hours`` hours."""
        changed = self._changes.get(msisdn)
        if changed is None:
            return False
        return self._clock() - changed <= timedelta(hours=max_age_hours)
