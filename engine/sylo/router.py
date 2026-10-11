"""Router: the cheapest route that is legal and allowed at the payment's tier (v0 spec §5.7).

S(r) = fees + fxMargin*A + lambda*A*T + mu*A*pFail + nu*A*pUnusable + sigma*routeRisk. Fraud risk
is never an input: the tier only filters which settlement modes are allowed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sylo_spec.models import Tier

from . import texts
from .norms import PASS, NormsResult, RouteDef, RouteEval, RouteModel

CONDITIONAL_SETTLEMENTS = frozenset({"ONCHAIN_ESCROW", "FIAT_HOLD"})
PAYER_LIMIT = "PAYER_LIMIT"


@dataclass(frozen=True)
class RerouteLimits:
    """What the payer accepts without being asked when its usual route cannot be used (PRD §11.3, §12.2)."""

    max_fees_eur: float
    max_days: float

    def exceeded_by(self, route: RouteDef, amount: float) -> bool:
        return route.fees(amount) > self.max_fees_eur or route.days > self.max_days


def route_cost(route: RouteDef, amount: float, model: RouteModel, route_risk: float = 0.0) -> float:
    return route_cost_breakdown(route, amount, model, route_risk)["totalCostEur"]


def route_cost_breakdown(
    route: RouteDef, amount: float, model: RouteModel, route_risk: float = 0.0
) -> dict[str, float]:
    fees = round(route.fees(amount), 2)
    fx_margin = round(route.fx_margin(amount), 2)
    cash_cost = round(fees + fx_margin, 2)
    time_cost = round(model.lam * amount * route.days, 2)
    failure_cost = round(
        model.mu * amount * route.p_fail + model.nu * amount * route.p_unusable + model.sigma * route_risk, 2
    )
    return {
        "feesEur": fees,
        "fxMarginEur": fx_margin,
        "timeCostEur": time_cost,
        "failureCostEur": failure_cost,
        "cashCostEur": cash_cost,
        "totalCostEur": round(cash_cost + time_cost + failure_cost, 2),
    }


def _route_comparison(
    route: RouteDef, amount: float, model: RouteModel, mid_rate: float | None
) -> dict[str, Any]:
    cost = route_cost_breakdown(route, amount, model)
    return {
        "name": route.name,
        "etaLabel": route.eta_label,
        "etaMinutes": route.minutes,
        "feesEur": cost["feesEur"],
        "fxMarginEur": cost["fxMarginEur"],
        "cashCostEur": cost["cashCostEur"],
        "recipientGetsGhs": (
            round(amount * (1 - route.fx_margin_pct) * mid_rate, 2) if mid_rate is not None else None
        ),
    }


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
    blocked_by: str | None = None
    """Why no route was chosen: ``TIER``, ``RAILS`` or ``PAYER_LIMIT``. None when a route was chosen."""
    cost: dict[str, float] | None = None
    eta_minutes: float | None = None
    mid_rate_eur_ghs: float | None = None
    recipient_gets_ghs: float | None = None

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
            "cost": self.cost,
            "etaMinutes": self.eta_minutes,
            "midRateEurGhs": self.mid_rate_eur_ghs,
            "recipientGetsGhs": self.recipient_gets_ghs,
        }


def choose_route(
    norms: NormsResult,
    tier: Tier,
    amount: float,
    model: RouteModel,
    oob_resolvable: bool = False,
    unavailable: Mapping[str, str] | None = None,
    limits: RerouteLimits | None = None,
    symbol: str = "€",
) -> RouteDecision:
    """``oob_resolvable``: the doubt is about the beneficiary's identity only, so a HIGH payment may still
    use a route that can hold the money (it is then handled like MEDIUM, never paid directly).

    ``unavailable`` maps a route id to why its rail cannot be used now (``RAIL_DOWN``, ``KILL_SWITCH``).
    Rerouting answers an operational problem only: a rail that is down never changes the tier.

    ``limits`` apply only when the route the payer would normally get is unavailable: the replacement
    must stay within the fees and the delay the payer accepts, otherwise the payment waits.
    """
    action_tier = Tier.MEDIUM if tier == Tier.HIGH and oob_resolvable else tier
    unavailable = unavailable or {}
    cost_by_id = {
        e.route.id: round(route_cost(e.route, amount, model), 2) for e in norms.routes if e.status == PASS
    }
    permitted = [e.route.id for e in norms.routes if e.status == PASS and tier_exclusion(action_tier, e.route) is None]
    usual = min(permitted, key=lambda route_id: (cost_by_id[route_id], route_id), default=None)
    rerouting = limits is not None and usual is not None and usual in unavailable

    scores: list[dict[str, Any]] = []
    allowed: list[tuple[float, str, RouteEval]] = []
    legal: list[tuple[float, str, RouteEval]] = []
    over_limit: list[str] = []
    for evaluation in norms.routes:
        route = evaluation.route
        comparison = _route_comparison(route, amount, model, norms.fx_eur_ghs)
        if evaluation.status != PASS:
            scores.append({"routeId": route.id, "s": None, "excludedBy": evaluation.excluded_by, **comparison})
            continue
        s = cost_by_id[route.id]
        if route.id in unavailable:
            scores.append({"routeId": route.id, "s": s, "excludedBy": unavailable[route.id], **comparison})
            continue
        legal.append((s, route.id, evaluation))
        exclusion = tier_exclusion(action_tier, route)
        if exclusion is None and rerouting and limits.exceeded_by(route, amount):
            exclusion = PAYER_LIMIT
            over_limit.append(route.id)
        scores.append({"routeId": route.id, "s": s, "excludedBy": exclusion, **comparison})
        if exclusion is None:
            allowed.append((s, route.id, evaluation))

    swift = cost_by_id.get("R1")
    if not allowed:
        if over_limit:
            blocked_by = PAYER_LIMIT
            reason = texts.NO_ROUTE_LIMITS.format(
                usual=usual, routes=", ".join(over_limit), fees=limits.max_fees_eur, days=limits.max_days, symbol=symbol
            )
        elif action_tier >= Tier.HIGH or not unavailable:
            blocked_by, reason = "TIER", texts.NO_ROUTE_DETAIL.format(tier=action_tier.name)
        else:
            blocked_by, reason = "RAILS", texts.NO_ROUTE_RAILS.format(routes=", ".join(sorted(unavailable)))
        return RouteDecision(
            tier=action_tier,
            route_eval=None,
            scores=scores,
            reason=reason,
            settlement=None,
            fees_eur=None,
            s_selected=None,
            s_swift=swift,
            price_of_safety=0.0,
            blocked_by=blocked_by,
        )

    best_s, best_id, best = min(allowed, key=lambda c: (c[0], c[1]))
    cheapest_legal = min(legal, key=lambda c: (c[0], c[1]))[0]
    price_of_safety = round(best_s - cheapest_legal, 2)
    if action_tier == Tier.LOW:
        excluded = [(e.route.id, e.excluded_by or "") for e in norms.routes if e.status != PASS]
        reason = texts.route_reason_low(best_id, best_s, swift, excluded, symbol)
        settlement = "DIRECT"
    else:
        holding = [(c[2].route.id, c[2].route.settlement) for c in sorted(allowed, key=lambda c: c[1])]
        reason = texts.route_reason_medium(best_id, best_s, swift, holding, price_of_safety, symbol)
        settlement = best.route.settlement
    reason += texts.rails_unavailable(unavailable)
    cost = route_cost_breakdown(best.route, amount, model)
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
        cost=cost,
        eta_minutes=best.route.minutes,
        mid_rate_eur_ghs=norms.fx_eur_ghs,
        recipient_gets_ghs=(
            round(amount * (1 - best.route.fx_margin_pct) * norms.fx_eur_ghs, 2)
            if norms.fx_eur_ghs is not None
            else None
        ),
    )
