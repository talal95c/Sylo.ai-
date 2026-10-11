"""Router: the cheapest route that is legal and allowed at the payment's tier (v0 spec §5.7).

S(r) = fees + lambda*A*T + mu*A*pFail + nu*A*pUnusable + sigma*routeRisk. Fraud risk is never an
input: the tier only filters which settlement modes are allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sylo_spec.models import Tier

from . import texts
from .norms import PASS, NormsResult, RouteDef, RouteEval, RouteModel

CONDITIONAL_SETTLEMENTS = frozenset({"ONCHAIN_ESCROW", "FIAT_HOLD"})


def route_cost(route: RouteDef, amount: float, model: RouteModel, route_risk: float = 0.0) -> float:
    return (
        route.fees(amount)
        + model.lam * amount * route.days
        + model.mu * amount * route.p_fail
        + model.nu * amount * route.p_unusable
        + model.sigma * route_risk
    )


def tier_exclusion(tier: Tier, route: RouteDef) -> str | None:
    if tier >= Tier.HIGH:
        return f"TIER_{tier.name}_NO_ROUTE"
    if tier == Tier.MEDIUM and route.settlement not in CONDITIONAL_SETTLEMENTS:
        return "TIER_MEDIUM_REQUIRES_CONDITIONAL_SETTLEMENT"
    return None


@dataclass
class RouteDecision:
    tier: Tier
    route_eval: RouteEval | None
    scores: list[dict[str, Any]]
    reason: str
    settlement: str | None
    fees_eur: float | None
    s_selected: float | None
    s_swift: float | None
    price_of_safety: float

    @property
    def route(self) -> RouteDef | None:
        return self.route_eval.route if self.route_eval else None

    def to_event_data(self) -> dict[str, Any]:
        assert self.route_eval is not None
        route = self.route_eval.route
        return {
            "routeId": route.id,
            "name": route.name,
            "settlement": self.settlement,
            "tier": self.tier.name,
            "scores": self.scores,
            "reason": self.reason,
            "feesEur": self.fees_eur,
            "etaLabel": route.eta_label,
            "priceOfSafetyEur": self.price_of_safety,
            "hops": self.route_eval.hops,
        }


def choose_route(
    norms: NormsResult,
    tier: Tier,
    amount: float,
    model: RouteModel,
    oob_resolvable: bool = False,
) -> RouteDecision:
    action_tier = Tier.MEDIUM if tier == Tier.HIGH and oob_resolvable else tier
    scores: list[dict[str, Any]] = []
    allowed: list[tuple[float, str, RouteEval]] = []
    legal: list[tuple[float, str, RouteEval]] = []
    cost_by_id: dict[str, float] = {}

    for evaluation in norms.routes:
        route = evaluation.route
        if evaluation.status != PASS:
            scores.append({"routeId": route.id, "s": None, "excludedBy": evaluation.excluded_by})
            continue
        s = round(route_cost(route, amount, model), 2)
        cost_by_id[route.id] = s
        legal.append((s, route.id, evaluation))
        exclusion = tier_exclusion(action_tier, route)
        scores.append({"routeId": route.id, "s": s, "excludedBy": exclusion})
        if exclusion is None:
            allowed.append((s, route.id, evaluation))

    swift = cost_by_id.get("R1")
    if not allowed:
        return RouteDecision(
            tier=action_tier,
            route_eval=None,
            scores=scores,
            reason=texts.NO_ROUTE_DETAIL.format(tier=action_tier.name),
            settlement=None,
            fees_eur=None,
            s_selected=None,
            s_swift=swift,
            price_of_safety=0.0,
        )

    best_s, best_id, best = min(allowed, key=lambda c: (c[0], c[1]))
    cheapest_legal = min(legal, key=lambda c: (c[0], c[1]))[0]
    price_of_safety = round(best_s - cheapest_legal, 2)
    if action_tier == Tier.LOW:
        excluded = [(e.route.id, e.excluded_by or "") for e in norms.routes if e.status != PASS]
        reason = texts.route_reason_low(best_id, best_s, swift, excluded)
        settlement = "DIRECT"
    else:
        holding = [(c[2].route.id, c[2].route.settlement) for c in sorted(allowed, key=lambda c: c[1])]
        reason = texts.route_reason_medium(best_id, best_s, swift, holding, price_of_safety)
        settlement = best.route.settlement
    return RouteDecision(
        tier=action_tier,
        route_eval=best,
        scores=scores,
        reason=reason,
        settlement=settlement,
        fees_eur=round(best.route.fees(amount), 2),
        s_selected=best_s,
        s_swift=swift,
        price_of_safety=price_of_safety,
    )
