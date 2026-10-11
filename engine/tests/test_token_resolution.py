import logging

from sylo import orchestrator as orchestrator_module
from sylo.config import Settings
from sylo.orchestrator import build_orchestrator
from sylo.risk_rules import RulesRisk

CHAIN_TOKEN = "0x0000000000000000000000000000000000000001"
SETTINGS_TOKEN = "0x0000000000000000000000000000000000000002"


class _FakeChain:
    def __init__(self, token_address: str, mode: str = "mock") -> None:
        self.token_address = token_address
        self.mode = mode


def _build_with_chain(monkeypatch, chain: _FakeChain, settings: Settings, env: dict[str, str]):
    def load_ports(settings, *, signer, clock):
        return RulesRisk(), chain, []

    monkeypatch.setattr(orchestrator_module, "load_ports", load_ports)
    return build_orchestrator(settings, env=env)


def test_orchestrator_uses_chain_token_when_token_address_is_unset(monkeypatch):
    chain = _FakeChain(CHAIN_TOKEN)
    orchestrator = _build_with_chain(
        monkeypatch,
        chain,
        Settings(chain_mode="mock", journal_path=None, cluster_mode="sample"),
        {},
    )

    assert orchestrator.token == CHAIN_TOKEN


def test_settings_token_address_takes_precedence_over_chain_token(monkeypatch):
    chain = _FakeChain(CHAIN_TOKEN)
    orchestrator = _build_with_chain(
        monkeypatch,
        chain,
        Settings(chain_mode="mock", token_address=SETTINGS_TOKEN, journal_path=None, cluster_mode="sample"),
        {},
    )

    assert orchestrator.token == SETTINGS_TOKEN


def test_real_fuji_chain_warns_for_missing_casp_and_vasp_addresses(monkeypatch, caplog):
    chain = _FakeChain(CHAIN_TOKEN, mode="fuji")
    with caplog.at_level(logging.WARNING, logger="sylo.orchestrator"):
        _build_with_chain(
            monkeypatch,
            chain,
            Settings(chain_mode="mock", journal_path=None, cluster_mode="sample"),
            {},
        )

    assert "EU_CASP_ADDRESS" in caplog.text
    assert "GH_VASP_ADDRESS" in caplog.text
