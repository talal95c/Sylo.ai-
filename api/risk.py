from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from api.risk_fallback import evaluate_rules
from api.risk_tiers import tier_for

TIER_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}


def _plain(value: Any) -> Any:
    return value.model_dump() if isinstance(value, BaseModel) else value


def _run_fallback(
    order: Any, ctx: Any, *, dependency_failure: bool = False
) -> tuple[dict[str, Any], bool]:
    result = evaluate_rules(order, ctx)
    result.pop("approvalBlocked", None)
    if dependency_failure:
        result["tier"] = max(
            (result["tier"], "MEDIUM"), key=TIER_ORDER.get
        )
        result["modelVersion"] = "fallback-rules"
    return result, dependency_failure


def score_with_status(order: Any, ctx: Any) -> tuple[dict[str, Any], bool]:
    order_data = _plain(order)
    context = _plain(ctx)
    try:
        from ml.score import score as model_score
    except ImportError:
        return _run_fallback(order_data, context)

    try:
        model_result = model_score(order_data, context)
        result = dict(model_result)
        result["score"] = max(0, min(100, int(result["score"])))
        fired = evaluate_rules(order_data, context)
        rules = list(dict.fromkeys([*result.get("rulesFired", []), *fired["rulesFired"]]))
        result["rulesFired"] = rules
        model_floor = result.get("tier", tier_for(result["score"]))
        result["tier"] = max(
            (tier_for(result["score"]), model_floor, fired["tier"]),
            key=TIER_ORDER.get,
        )
        result["topReasons"] = list(
            dict(
                (reason["ref"], reason)
                for reason in [
                    *result.get("topReasons", []),
                    *fired["topReasons"],
                ]
            ).values()
        )[:3]
        result["modelVersion"] = str(result.get("modelVersion", "ml-model"))
        result.pop("approvalBlocked", None)
        return result, False
    except Exception:
        return _run_fallback(order_data, context, dependency_failure=True)


def score(order: Any, ctx: Any) -> dict[str, Any]:
    return score_with_status(order, ctx)[0]
