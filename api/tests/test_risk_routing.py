import json
from pathlib import Path

from api.norms import evaluate
from api.risk import score
from api.routing import load_rails, score_routes, select_route
from shared.types import PaymentOrder, RiskContext

FIXTURES = Path(__file__).parents[2] / "shared" / "fixtures"


def _scene(number: int):
    return json.loads((FIXTURES / f"scene{number}.json").read_text())


def test_scene_two_fallback_has_expected_score_and_citations():
    fixture = _scene(2)
    result = score(
        PaymentOrder.model_validate(fixture["order"]),
        RiskContext.model_validate(fixture["riskContext"]),
    )

    assert result["score"] == 74
    assert result["tier"] == "MEDIUM"
    assert "R-PV-01" in result["rulesFired"]
    assert {reason["ref"] for reason in result["topReasons"]} == {
        "R-FL-01",
        "R-FL-03",
        "R-NM-01",
    }
    assert result["topReasons"][1]["text"] == "Account holder name match is only 0.21."


def test_scene_one_router_candidates_and_norm_exclusion():
    fixture = _scene(1)
    risk_result = score(
        PaymentOrder.model_validate(fixture["order"]),
        RiskContext.model_validate(fixture["riskContext"]),
    )
    _, routes = load_rails()
    checks, _ = evaluate(fixture["order"], routes, fixture["payeeRegistry"])
    result = select_route(
        fixture["order"],
        fixture["expectedRisk"],
        checks,
    )
    candidates = {candidate["routeId"]: candidate for candidate in result["candidates"]}

    assert result["chosen"] == "R3"
    assert risk_result["tier"] == "LOW"
    assert candidates["R1"]["S"] == 216
    assert candidates["R2"]["S"] == 937.48
    assert candidates["R3"]["S"] == 178.7
    assert candidates["R4"]["excludedBy"] == "GH_FX_EXPORT_PROCEEDS_NOMINATED_BANK"


def test_route_scores_do_not_depend_on_fraud_risk():
    _, routes = load_rails()
    lower = score_routes(85_000, routes, {"score": 0, "tier": "LOW"})
    higher = score_routes(85_000, routes, {"score": 100, "tier": "CRITICAL"})

    assert lower == higher


def test_scene_two_keeps_conditional_routes_and_emits_norm_signal():
    fixture = _scene(2)
    _, routes = load_rails()
    checks, _ = evaluate(fixture["order"], routes, fixture["payeeRegistry"])
    result = select_route(fixture["order"], fixture["expectedRisk"], checks)
    candidates = {candidate["routeId"]: candidate for candidate in result["candidates"]}

    assert result["chosen"] == "R3"
    assert candidates["R1"]["excludedBy"] is None
    assert candidates["R2"]["excludedBy"] == "GH_FX_EXPORT_PROCEEDS_NOMINATED_BANK"
    assert candidates["R4"]["excludedBy"] == "GH_FX_EXPORT_PROCEEDS_NOMINATED_BANK"
