"""Risk conformance suite (v0 spec §4.7).

``run_risk_conformance(risk)`` raises ``AssertionError`` with a readable message on failure.
"""

from __future__ import annotations

import time

from ..models import RiskResult, Tier, band
from ..ports import RiskPort
from ..scenarios import golden_case


def _validated(result: object, label: str) -> RiskResult:
    if not isinstance(result, RiskResult):
        result = RiskResult.model_validate(result)
    assert 0 <= result.score <= 100, f"{label}: score {result.score} outside 0–100"
    expected = max(result.floor_tier, band(result.score))
    assert result.tier == expected, (
        f"{label}: tier {result.tier.name} must equal max(floorTier, band(score)) = {Tier(expected).name}"
    )
    assert result.model, f"{label}: model name is empty"
    return result


def run_risk_conformance(risk: RiskPort, *, calls: int = 200, max_p95_seconds: float = 0.050) -> None:
    legit_order, legit_ctx = golden_case("legit")
    diverted_order, diverted_ctx = golden_case("diverted")

    legit = _validated(risk.score(legit_order, legit_ctx), "legit")
    assert legit.tier == Tier.LOW, f"legit golden case must be LOW, got {legit.tier.name} (score {legit.score})"

    diverted = _validated(risk.score(diverted_order, diverted_ctx), "diverted")
    assert diverted.tier >= Tier.MEDIUM, f"diverted golden case must be at least MEDIUM, got {diverted.tier.name}"
    assert len(diverted.reasons) >= 3, f"diverted golden case needs at least 3 reasons, got {len(diverted.reasons)}"

    again = risk.score(diverted_order, diverted_ctx)
    assert RiskResult.model_validate(again).model_dump() == diverted.model_dump(), "same input gave a different output"

    durations = []
    for _ in range(calls):
        start = time.perf_counter()
        risk.score(diverted_order, diverted_ctx)
        durations.append(time.perf_counter() - start)
    durations.sort()
    p95 = durations[max(0, int(0.95 * len(durations)) - 1)]
    assert p95 < max_p95_seconds, f"p95 latency {p95 * 1000:.1f} ms is above {max_p95_seconds * 1000:.0f} ms"
