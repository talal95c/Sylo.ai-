from sylo_spec.conformance import run_risk_conformance
from sylo_spec.ports import RiskPort

from sylo.risk_rules import RulesRisk


def test_rules_risk_passes_the_risk_conformance_suite():
    run_risk_conformance(RulesRisk())


def test_rules_risk_implements_the_port():
    assert isinstance(RulesRisk(), RiskPort)
