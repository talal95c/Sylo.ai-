"""Router: the cheapest and fastest of the routes that norms and the risk tier still allow.

    S(r) = fees + λ·A·T + μ·A·pFail + ν·A·pUnusable + σ·routeRisk

`routeRisk` is the operational risk of the rail (outage, unreliable intermediary); it is 0 in v0.
FRAUD RISK IS NEVER AN INPUT OF S: the tier only restricts which routes are eligible.
"""

from dataclasses import dataclass
from typing import Any, Optional

from sylo_spec.models import Tier

from . import texts
from .norms import NormsResult, Pack, RouteEval

CONDITIONAL_SETTLEMENTS = ("ONCHAIN_ESCROW", "FIAT_HOLD")
TIER_MEDIUM_EXCLUSION = "TIER_MEDIUM_REQUIRES_CONDITIONAL_SETTLEMENT"
TIER_BLOCKED_EXCLUSION = "TIER_{tier}_NO_ROUTE"
SWIFT_ROUTE_ID = "R1"


def route_score(evaluation: RouteEval, amount_eur: float, weights: dict[str, float], route_risk: float = 0.0) -> float:
    r = evaluation.route
    return (
        r.fees_eur(amount_eur)
        + weights["lambda"] * amount_eur * r.time_days
        + weights["mu"] * amount_eur * r.p_fail
        + weights["nu"] * amount_eur * r.p_unusable
        + weights["sigma"] * route_risk
    )


@dataclass
class RouteDecision:
    tier: Tier
    selected: Optional[RouteEval]
    scores: list[dict[str, Any]]
    reason: str
    cost_eur: Optional[float]  # S of the selected route
    swift_cost_eur: Optional[float]  # S of the SWIFT route, the usual way to pay
    price_of_safety_eur: float

    def to_event(self, amount_eur: float) -> dict[str, Any]:
        route = self.selected.route
        return {
            "routeId": route.id,
            "name": route.name,
            "settlement": route.settlement,
            "tier": self.tier.name,
            "scores": self.scores,
            "reason": self.reason,
            "feesEur": round(route.fees_eur(amount_eur), 2),
            "etaLabel": route.eta_label,
            "priceOfSafetyEur": self.price_of_safety_eur,
        }


def _eligible_at(tier: Tier, evaluation: RouteEval) -> Optional[str]:
    """None when the route is allowed at this tier, else the exclusion code."""
    if tier == Tier.LOW:
        return None
    if tier == Tier.MEDIUM:
        return None if evaluation.route.settlement in CONDITIONAL_SETTLEMENTS else TIER_MEDIUM_EXCLUSION
    return TIER_BLOCKED_EXCLUSION.format(tier=tier.name)


def select_route(norms: NormsResult, tier: Tier, amount_eur: float, pack: Pack) -> RouteDecision:
    legal = [e for e in norms.routes if e.passed]
    s = {e.route.id: route_score(e, amount_eur, pack.weights) for e in legal}

    scores: list[dict[str, Any]] = []
    eligible: list[RouteEval] = []
    for evaluation in norms.routes:
        rid = evaluation.route.id
        if not evaluation.passed:
            scores.append({"routeId": rid, "s": None, "excludedBy": evaluation.excluded_by})
            continue
        exclusion = _eligible_at(tier, evaluation)
        scores.append({"routeId": rid, "s": round(s[rid], 2), "excludedBy": exclusion})
        if exclusion is None:
            eligible.append(evaluation)

    swift = round(s[SWIFT_ROUTE_ID], 2) if SWIFT_ROUTE_ID in s else None
    if not eligible:
        return RouteDecision(tier, None, scores, texts.ROUTE_REASON_NONE.format(tier=tier.name), None, swift, 0.0)

    best = min(eligible, key=lambda e: s[e.route.id])
    best_if_low = min(legal, key=lambda e: s[e.route.id])
    cost = round(s[best.route.id], 2)
    price_of_safety = round(s[best.route.id] - s[best_if_low.route.id], 2)

    if tier == Tier.LOW:
        wallet_excluded = any(e.excluded_by == "GH_FX_EXPORT_PROCEEDS_NOMINATED_BANK" for e in norms.routes)
        reason = texts.route_reason_low(best.route.id, cost, swift if swift is not None else cost, wallet_excluded)
    else:
        others = sorted(s[e.route.id] for e in eligible if e is not best)
        reason = texts.route_reason_medium(best.route.id, cost, others[0] if others else cost, price_of_safety)

    return RouteDecision(tier, best, scores, reason, cost, swift, price_of_safety)
