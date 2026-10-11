from sylo_spec.conformance import run_risk_conformance

from sylo_risk import ModelRisk


def test_model_risk_passes_the_risk_conformance_suite():
    run_risk_conformance(ModelRisk())
