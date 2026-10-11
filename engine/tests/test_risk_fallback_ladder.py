import sys
from types import ModuleType

from sylo.config import Settings
from sylo.risk_rules import CombinedRisk, RulesRisk
from sylo.ports_loader import load_ports
from sylo.signer import Signer


class _RiskStub:
    name = "stub"

    def __init__(self):
        pass


class _BrokenRisk:
    def __init__(self):
        raise RuntimeError("model artifact unavailable")


def _risk_package(**attributes):
    package = ModuleType("sylo_risk")
    for name, value in attributes.items():
        setattr(package, name, value)
    return package


def _load():
    return load_ports(
        Settings(risk_mode="model"),
        signer=Signer(env={}),
        clock=lambda: 0.0,
    )


def test_model_mode_uses_normal_risk_on_first_rung(monkeypatch):
    monkeypatch.setitem(sys.modules, "sylo_risk", _risk_package(ModelRisk=_RiskStub))

    risk, _, degraded = _load()

    assert isinstance(risk, CombinedRisk)
    assert risk.rules.strict is False
    assert isinstance(risk.model, _RiskStub)
    assert degraded == []


def test_model_mode_uses_strict_rules_and_fallback_lr_on_second_rung(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "sylo_risk",
        _risk_package(ModelRisk=_BrokenRisk, FallbackRisk=_RiskStub),
    )

    risk, _, degraded = _load()

    assert isinstance(risk, CombinedRisk)
    assert risk.rules.strict is True
    assert isinstance(risk.model, _RiskStub)
    assert degraded == ["risk"]


def test_model_mode_uses_strict_rules_only_on_last_rung(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "sylo_risk",
        _risk_package(ModelRisk=_BrokenRisk, FallbackRisk=_BrokenRisk),
    )

    risk, _, degraded = _load()

    assert isinstance(risk, RulesRisk)
    assert risk.strict is True
    assert degraded == ["risk"]
