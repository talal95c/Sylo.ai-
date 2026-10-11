"""Run-time fail-safes: unexpected errors, a case writer that falls back, contract refusals over HTTP,
flags with a typo, Fuji without real keys, and what Reset clears."""

import pytest
from fastapi.testclient import TestClient
from sylo_spec.ports import ChainReverted

from sylo import texts
from sylo.config import Settings
from sylo.main import create_app
from sylo.orchestrator import build_orchestrator

from .conftest import events_of, make_orchestrator


async def test_an_unexpected_error_stops_the_payment_and_turns_the_banner_amber(monkeypatch):
    orchestrator = make_orchestrator()

    def broken(order):
        raise RuntimeError("norms pack unreadable")

    monkeypatch.setattr(orchestrator.norms, "evaluate", broken)
    run = await orchestrator.run_to_end("legit")
    assert run.status == "stopped"
    assert "engine" in orchestrator.degraded
    stopped = events_of(orchestrator, "payment.stopped")
    assert stopped and stopped[-1]["data"]["headline"] == texts.ENGINE_ERROR_HEADLINE
    assert events_of(orchestrator, "alert.raised")[-1]["data"]["audience"] == "analyst"


async def test_reset_clears_degradations_that_happened_while_running():
    orchestrator = make_orchestrator()
    at_start = list(orchestrator.degraded)
    orchestrator._degrade("llm")
    orchestrator.incidents.append({"incidentId": "INC-x"})
    await orchestrator.reset()
    assert orchestrator.degraded == at_start and orchestrator.incidents == []
    assert events_of(orchestrator, "system.mode")[-1]["data"]["degraded"] == at_start


async def test_a_case_writer_answering_from_a_lower_rung_degrades_llm():
    class Offline:
        def write(self, payment_id, events):
            raise RuntimeError("no network")

    orchestrator = make_orchestrator()
    orchestrator.case.requested = "live"
    orchestrator.case.writer = Offline()
    await orchestrator.run_to_end("diverted", auto=True, auto_answer="deny")
    assert events_of(orchestrator, "case.ready")[-1]["data"]["llm"] == "off"
    assert "llm" in orchestrator.degraded


def test_a_contract_refusal_is_a_409_not_a_500(monkeypatch):
    settings = Settings(journal_path=None, cluster_mode="sample")
    orchestrator = build_orchestrator(settings, env={})

    async def refused(name, payment_id):
        raise ChainReverted("PaymentNotReleasable", function="release")

    monkeypatch.setattr(orchestrator, "attack", refused)
    with TestClient(create_app(settings, orchestrator=orchestrator)) as client:
        response = client.post("/v1/attacks/release_revoked", json={"paymentId": "PAY-2026-0002"})
    assert response.status_code == 409
    assert response.json()["reason"] == "PaymentNotReleasable"


@pytest.mark.parametrize("name", ["RISK_MODE", "CHAIN_MODE", "LLM_MODE", "TELECOM_MODE"])
def test_a_typo_in_a_mode_flag_stops_the_engine_at_start_up(name):
    with pytest.raises(ValueError, match=name):
        Settings.from_env({name: "modle"})


def test_fuji_without_the_real_keys_uses_the_mock_chain_and_says_so():
    orchestrator = build_orchestrator(Settings(chain_mode="fuji", journal_path=None, cluster_mode="sample"), env={})
    assert orchestrator.chain.mode == "mock"
    assert "chain" in orchestrator.degraded
