"""Conformance suite for `RiskPort` implementations.

    from sylo_spec.conformance import run_risk_conformance
    run_risk_conformance(MyRisk())

Raises AssertionError with a readable message on the first failure.
"""

import time

from ..models import RiskResult, Tier
from ..ports import RiskPort
from ..scenarios import golden_case

LATENCY_CALLS = 200
LATENCY_P95_MS = 50.0


def _validate(result: RiskResult) -> None:
    assert isinstance(result, RiskResult), f"score() must return a RiskResult, got {type(result).__name__}"
    RiskResult.model_validate(result.to_json())  # round-trips through JSON
    assert 0 <= result.score <= 100, f"score out of range: {result.score}"
    assert result.tier >= result.floor_tier, "tier must never be below the rule floor"
    assert result.model, "model name must not be empty"
    for reason in result.reasons:
        assert reason.ref and reason.text, "every reason needs a ref and a text"


def run_risk_conformance(risk: RiskPort) -> None:
    assert isinstance(getattr(risk, "name", None), str) and risk.name, "RiskPort.name must be a non-empty string"

    legit_order, legit_ctx = golden_case("legit")
    legit = risk.score(legit_order, legit_ctx)
    _validate(legit)
    assert legit.tier == Tier.LOW, f"legit golden case must be LOW, got {legit.tier.name} (score {legit.score})"

    diverted_order, diverted_ctx = golden_case("diverted")
    diverted = risk.score(diverted_order, diverted_ctx)
    _validate(diverted)
    assert diverted.tier >= Tier.MEDIUM, f"diverted golden case must be at least MEDIUM, got {diverted.tier.name}"
    assert len(diverted.reasons) >= 3, f"diverted golden case needs at least 3 reasons, got {len(diverted.reasons)}"

    # Determinism: same input, same output.
    again = risk.score(*golden_case("diverted"))
    assert again.to_json() == diverted.to_json(), "same input must give the same output"

    # Latency: p95 under 50 ms over 200 calls.
    durations = []
    for i in range(LATENCY_CALLS):
        case = golden_case("diverted" if i % 2 else "legit")
        start = time.perf_counter()
        risk.score(*case)
        durations.append((time.perf_counter() - start) * 1000.0)
    durations.sort()
    p95 = durations[int(0.95 * len(durations)) - 1]
    assert p95 < LATENCY_P95_MS, f"p95 latency {p95:.1f} ms is over {LATENCY_P95_MS} ms"
