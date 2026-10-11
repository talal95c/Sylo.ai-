"""Regional circuit breaker and degraded mode: overlays that can only make a decision stricter (roadmap A2.1, A2.3).

A breaker is proposed when a mule cluster is detected and switched on by the analyst. For 24 hours,
payments towards its region are at least MEDIUM and every threshold is 20 points lower (rule
R-CB-01). Only a person lifts it early. Fraud risk still never enters the route score: the overlay
changes the tier, and the tier only filters which settlements are allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sylo_spec.models import Cluster, RiskReason, RiskResult, Tier, band

from . import texts
from .pacer import iso_ms

BREAKER_RULE = "R-CB-01"
DEGRADED_RULE = "R-DG-01"
THRESHOLDS_DELTA = -20
BREAKER_HOURS = 24


@dataclass
class Breaker:
    id: str
    cluster_id: str
    region: str
    region_name: str
    corridor: str
    institutions: tuple[str, ...]
    thresholds_delta: int = THRESHOLDS_DELTA
    hours: int = BREAKER_HOURS
    status: str = "proposed"
    expires_at: datetime | None = None
    confirmed_by: str | None = None

    def scope(self) -> dict[str, Any]:
        return {
            "region": self.region,
            "regionName": self.region_name,
            "corridor": self.corridor,
            "institutions": list(self.institutions),
        }

    def proposal(self) -> dict[str, Any]:
        return {
            "breakerId": self.id,
            "scope": self.scope(),
            "thresholdsDelta": self.thresholds_delta,
            "hours": self.hours,
            "text": texts.BREAKER_PROPOSED.format(region=self.region_name, hours=self.hours),
        }

    def on_event(self) -> dict[str, Any]:
        assert self.expires_at is not None and self.confirmed_by is not None
        return {
            "breakerId": self.id,
            "clusterId": self.cluster_id,
            "scope": self.scope(),
            "thresholdsDelta": self.thresholds_delta,
            "expiresAt": iso_ms(self.expires_at),
            "confirmedBy": self.confirmed_by,
            "text": texts.BREAKER_ON.format(region=self.region_name, points=-self.thresholds_delta, hours=self.hours),
        }


class BreakerError(Exception):
    pass


class Breakers:
    def __init__(self) -> None:
        self._breakers: dict[str, Breaker] = {}

    def reset(self) -> None:
        self._breakers.clear()

    def get(self, breaker_id: str) -> Breaker | None:
        return self._breakers.get(breaker_id)

    def propose(self, cluster: Cluster, corridor: str) -> Breaker:
        """One breaker per cluster: detecting the same cluster again returns the existing one."""
        breaker_id = f"CB-{cluster.cluster_id}"
        existing = self._breakers.get(breaker_id)
        if existing is not None and existing.status != "off":
            return existing
        breaker = Breaker(
            id=breaker_id,
            cluster_id=cluster.cluster_id,
            region=cluster.region,
            region_name=cluster.region_name or cluster.region,
            corridor=corridor,
            institutions=tuple(cluster.institutions),
        )
        self._breakers[breaker_id] = breaker
        return breaker

    def confirm(self, breaker_id: str, by: str, now: datetime) -> Breaker:
        breaker = self._breakers.get(breaker_id)
        if breaker is None:
            raise KeyError(breaker_id)
        if breaker.status != "proposed":
            raise BreakerError(f"breaker {breaker_id} is {breaker.status}, not waiting for a confirmation")
        breaker.status = "on"
        breaker.confirmed_by = by
        breaker.expires_at = now + timedelta(hours=breaker.hours)
        return breaker

    def lift(self, breaker_id: str) -> Breaker:
        breaker = self._breakers.get(breaker_id)
        if breaker is None:
            raise KeyError(breaker_id)
        if breaker.status != "on":
            raise BreakerError(f"breaker {breaker_id} is {breaker.status}, not on")
        breaker.status = "off"
        return breaker

    def expire(self, now: datetime) -> list[Breaker]:
        """Switch off the breakers whose 24 hours have passed and return them."""
        expired = [b for b in self._breakers.values() if b.status == "on" and b.expires_at and now > b.expires_at]
        for breaker in expired:
            breaker.status = "off"
        return expired

    def active_for(self, institution_id: str, corridor: str) -> Breaker | None:
        return next(
            (
                b
                for b in self._breakers.values()
                if b.status == "on" and b.corridor == corridor and institution_id in b.institutions
            ),
            None,
        )


def _stricter(risk: RiskResult, tier: Tier, reason: RiskReason) -> RiskResult:
    return risk.model_copy(
        update={
            "tier": Tier(max(risk.tier, tier)),
            "floor_tier": Tier(max(risk.floor_tier, Tier.MEDIUM)),
            "rules_fired": [*risk.rules_fired, reason.rule_id],
            "reasons": [*risk.reasons, reason],
        }
    )


def apply_breaker(risk: RiskResult, breaker: Breaker) -> RiskResult:
    """Rule R-CB-01: at least MEDIUM, and the bands are read 20 points lower. The score itself is unchanged."""
    shifted = band(min(100, risk.score - breaker.thresholds_delta))
    reason = RiskReason(
        ref="N",
        text=texts.REASON_BREAKER.format(region=breaker.region_name, points=-breaker.thresholds_delta),
        rule_id=BREAKER_RULE,
    )
    return _stricter(risk, Tier(max(Tier.MEDIUM, shifted)), reason)


def apply_degraded(risk: RiskResult, degraded: list[str], known_account: bool) -> RiskResult:
    """Rule R-DG-01: while a dependency is down, a payment to an account that is not on file is at least MEDIUM."""
    if not degraded or known_account or risk.tier >= Tier.MEDIUM:
        return risk
    reason = RiskReason(ref="S", text=texts.REASON_DEGRADED.format(what=", ".join(degraded)), rule_id=DEGRADED_RULE)
    return _stricter(risk, Tier.MEDIUM, reason)
