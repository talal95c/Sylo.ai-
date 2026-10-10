from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

RAILS_PATH = Path(__file__).with_name("rails.yaml")


def _plain(value: Any) -> Any:
    return value.model_dump() if isinstance(value, BaseModel) else value


def load_rails() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with RAILS_PATH.open(encoding="utf-8") as file:
        config = yaml.safe_load(file)
    return config["scoring"], config["routes"]


def _amount_eur(order: Any) -> float:
    order_data = _plain(order)
    amount = order_data["amount"]
    if amount["currency"] != "EUR":
        raise ValueError("FR-GH routing requires an EUR-denominated amount")
    return float(amount["value"])


def score_route(route: dict[str, Any], amount_eur: float, risk: Any = None) -> float:
    scoring, _ = load_rails()
    cost = float(route.get("baseCostEUR", 0)) + float(route.get("costRate", 0)) * amount_eur
    capital = scoring["costOfCapitalPerDay"] * amount_eur * float(route["timeDays"])
    failures = scoring["failureWeight"] * amount_eur * float(route["pFail"])
    unusable = scoring["unusableWeight"] * amount_eur * float(route["pUnusable"])
    operational_risk = scoring["routeRiskWeight"] * float(route["routeRisk"])
    return cost + capital + failures + unusable + operational_risk


def score_routes(
    amount_eur: float,
    routes: list[dict[str, Any]] | None = None,
    risk: Any = None,
) -> dict[str, float]:
    _, configured = load_rails()
    candidates = routes if routes is not None else configured
    return {
        route["id"]: score_route(route, amount_eur)
        for route in candidates
    }


def _route_norm_status(
    route_id: str, norm_checks: list[dict[str, Any]]
) -> tuple[bool, str | None]:
    checks = [check for check in norm_checks if check.get("routeId") == route_id]
    failure = next(
        (check for check in checks if check.get("result") != "PASS"),
        None,
    )
    if failure:
        return False, failure["ruleId"]
    return True, None


def select_route(
    order: Any,
    risk_result: Any,
    norm_checks: list[dict[str, Any]] | None = None,
    *,
    kill_switched: set[str] | None = None,
    rail_status: dict[str, str] | None = None,
) -> dict[str, Any]:
    order_data = _plain(order)
    risk_data = _plain(risk_result)
    amount = _amount_eur(order_data)
    scoring, routes = load_rails()
    checks = norm_checks or []
    killed = kill_switched or set()
    statuses = rail_status or {}
    tier = risk_data["tier"]
    candidates: list[dict[str, Any]] = []
    eligible_routes: list[tuple[dict[str, Any], float]] = []
    route_scores = score_routes(amount, routes, risk_result)

    for route in routes:
        route_id = route["id"]
        route_score = route_scores[route_id]
        norm_ok, failed_rule = _route_norm_status(route_id, checks)
        status = statuses.get(route_id, route["status"])
        amount_cap = route.get("maxAmountEUR", scoring.get("amountCapEUR"))
        cap_ok = amount_cap is None or amount <= float(amount_cap)
        exclusion = None
        if status != "UP":
            exclusion = "RAIL_DOWN"
        elif route_id in killed:
            exclusion = "ROUTE_KILL_SWITCH"
        elif not cap_ok:
            exclusion = "CAP_EXCEEDED"
        elif not norm_ok:
            exclusion = failed_rule or "NORM_CHECK_FAILED"
        elif tier in {"HIGH", "CRITICAL"}:
            exclusion = "TIER_HIGH_OR_CRITICAL"
        elif tier == "MEDIUM" and not route.get("conditionalSettlement"):
            exclusion = "TIER_REQUIRES_CONDITIONAL_SETTLEMENT"
        else:
            eligible_routes.append((route, route_score))

        candidates.append(
            {
                "routeId": route_id,
                "S": round(route_score, 2) if exclusion is None else None,
                "excludedBy": exclusion,
            }
        )

    if not eligible_routes:
        return {
            "chosen": "",
            "candidates": candidates,
            "settlement": "NONE",
            "quoteValidUntil": (
                datetime.now(timezone.utc)
                + timedelta(seconds=scoring["quoteValiditySeconds"])
            ).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "reason": "No route satisfies the current norms, tier and rail constraints.",
            "priceOfSafety": None,
        }

    eligible_routes.sort(key=lambda item: item[1])
    chosen, chosen_score = eligible_routes[0]
    best_low_score = min(
        (
            route_scores[route["id"]]
            for route in routes
            if route["id"] not in killed
            and statuses.get(route["id"], route["status"]) == "UP"
            and _route_norm_status(route["id"], checks)[0]
            and (
                route.get("maxAmountEUR") is None
                or amount <= float(route["maxAmountEUR"])
            )
        ),
        default=chosen_score,
    )
    price_of_safety = max(0.0, chosen_score - best_low_score)
    conditional_settlement = chosen.get("conditionalSettlement")
    settlement = (
        conditional_settlement
        if tier == "MEDIUM" and conditional_settlement
        else "DIRECT"
    )
    reason = (
        f"Selected {chosen['id']} ({settlement}) at the lowest eligible S "
        f"({chosen_score:.2f}); price of safety at {tier}: "
        f"€{price_of_safety:.2f}."
    )
    return {
        "chosen": chosen["id"],
        "candidates": candidates,
        "settlement": settlement,
        "quoteValidUntil": (
            datetime.now(timezone.utc)
            + timedelta(seconds=scoring["quoteValiditySeconds"])
        ).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "reason": reason,
        "priceOfSafety": round(price_of_safety, 2),
    }