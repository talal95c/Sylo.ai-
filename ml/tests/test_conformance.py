import pytest

from sylo_spec.conformance import run_risk_conformance


def _model_or_skip():
    from sylo_risk import ModelRisk

    try:
        return ModelRisk()
    except NotImplementedError as err:
        pytest.skip(str(err))


def test_model_risk_passes_the_risk_conformance_suite():
    run_risk_conformance(_model_or_skip())
