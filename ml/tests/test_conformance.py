"""Runs the shared risk conformance suite against ModelRisk (skipped until Lane B implements it)."""

import pytest

from sylo_spec.conformance import run_risk_conformance
from sylo_spec.scenarios import golden_case


def _model():
    from sylo_risk import ModelRisk

    try:
        return ModelRisk()
    except NotImplementedError as err:
        pytest.skip(str(err))


def test_model_risk_passes_the_conformance_suite():
    run_risk_conformance(_model())


def test_golden_cases_are_available_to_lane_b():
    # Not skipped: the golden cases are the contract Lane B builds against.
    legit_order, legit_ctx = golden_case("legit")
    diverted_order, diverted_ctx = golden_case("diverted")
    assert legit_ctx.account.nominated_for_exports and not diverted_ctx.account.nominated_for_exports
    assert legit_order.amount.value == diverted_order.amount.value == "85000.00"
