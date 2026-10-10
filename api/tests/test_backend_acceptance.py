import asyncio
import json
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.agents.investigator import investigate
from api.chain.client import ChainRevert, FakeChain
from api.events import EventBus
from api.journal import HashChainJournal
from api.main import app
from api.orchestrator import Orchestrator
from api.risk import score_with_status

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "shared" / "fixtures"


def _expected_types(path: Path) -> list[str]:
    return [json.loads(line)["type"] for line in path.read_text().splitlines()]


@pytest.mark.parametrize("scene", ["1", "2", "2b"])
def test_scene_event_sequences_and_scene_one_latency(scene, monkeypatch):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    bus = EventBus()
    backend = Orchestrator(bus=bus, chain=FakeChain(), delay_ms=0)
    started = time.perf_counter()
    result = asyncio.run(backend.play_scene(scene))
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert [event["type"] for event in result["events"]] == _expected_types(
        FIXTURES / f"events-scene{scene}.jsonl"
    )
    if scene == "1":
        assert elapsed_ms < 300
        assert result["payment"]["status"] == "SETTLED"
    elif scene == "2":
        assert result["payment"]["status"] == "REFUNDED"
        assert result["payment"]["decision"]["risk"]["score"] == 74
        assert result["payment"]["decision"]["risk"]["tier"] == "MEDIUM"
        assert backend.cases["case_scene2"]["cached"] is True


@pytest.mark.parametrize("attack", ["A", "B", "C"])
def test_attacks_fail_closed(attack):
    bus = EventBus()
    backend = Orchestrator(bus=bus, chain=FakeChain(), delay_ms=0)
    asyncio.run(backend.play_scene("2b"))
    events = bus.snapshot()
    assert [event["type"] for event in events] == _expected_types(
        FIXTURES / "events-scene2b.jsonl"
    )
    if attack == "A":
        assert events[0]["data"]["revertReason"] == "PaymentNotReleasable"
    elif attack == "B":
        assert events[1]["type"] == "leg.rejected"
        assert events[2]["data"]["revertReason"] == "CommitmentMismatch"
        assert events[3]["type"] == "killswitch.on"
    else:
        assert events[4]["data"]["reason"] == "nonce already consumed"
        assert events[5]["type"] == "log.tampered"


def test_hash_chain_journal_detects_and_emits_tampering():
    bus = EventBus()
    journal = HashChainJournal(bus=bus, payment_id="p1", uetr="u1", scene="2b")
    entry = journal.append("decision", {"tier": "MEDIUM"})
    assert journal.verify() is True
    entry["payload"]["tier"] = "LOW"
    assert journal.verify() is False
    assert bus.snapshot()[-1]["type"] == "log.tampered"


def test_chain_dependency_failure_forces_medium_and_holds_payment():
    bus = EventBus()
    backend = Orchestrator(bus=bus, chain=FakeChain(), delay_ms=0)
    backend.chain = None
    backend.chain_error = "ConnectionError"
    fixture = json.loads((FIXTURES / "scene1.json").read_text())
    result = asyncio.run(backend.submit_order(fixture))
    assert result["decision"]["risk"]["tier"] == "MEDIUM"
    for approver in result["approvalsRequired"]:
        result = asyncio.run(backend.approve_payment(result["paymentId"], approver))
    assert result["status"] == "DEGRADED_HOLD"
    assert not any(event["type"] == "leg.sent" for event in bus.snapshot())


def test_model_exception_uses_stricter_fallback(monkeypatch):
    import sys
    import types

    model = types.ModuleType("ml.score")

    def raise_model_error(*args, **kwargs):
        raise RuntimeError("model unavailable")

    model.score = raise_model_error
    monkeypatch.setitem(sys.modules, "ml.score", model)
    fixture = json.loads((FIXTURES / "scene1.json").read_text())
    result, degraded = score_with_status(
        fixture["order"],
        fixture["riskContext"],
    )
    assert degraded is True
    assert result["tier"] == "MEDIUM"
    assert result["modelVersion"] == "fallback-rules"


def test_investigator_uses_valid_cached_fallback(monkeypatch):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    result = asyncio.run(
        investigate([], {"R-FL-01", "R-FL-03", "R-NM-01"})
    )
    assert result["cached"] is True
    assert set(result["citations"]).issubset(
        {"R-FL-01", "R-FL-03", "R-NM-01"}
    )
    assert len(result["explanation"].split()) <= 120


def test_investigator_rejects_unfired_citations_from_mocked_mistral(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "summary": "Invalid citation",
                                    "explanation": "This is short.",
                                    "citations": ["R-UNKNOWN"],
                                    "reportDraft": "draft",
                                }
                            )
                        }
                    }
                ]
            }

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr("api.agents.investigator.httpx.AsyncClient", Client)
    result = asyncio.run(investigate([], {"R-FL-01"}))
    assert result["cached"] is True
    assert set(result["citations"]).issubset({"R-FL-01"})


def _intent(payment_id="chain-test", nonce=5):
    return {
        "paymentId": payment_id,
        "corridorId": "FR-GH",
        "beneficiary": "0x0000000000000000000000000000000000000001",
        "token": "0x0000000000000000000000000000000000000002",
        "amount": 85_000_000_000,
        "offchainHash": "0x" + "1" * 64,
        "decisionHash": "0x" + "2" * 64,
        "approvalHash": "0x" + "3" * 64,
        "tier": "MEDIUM",
        "validUntil": int(time.time()) + 600,
        "nonce": nonce,
    }


def test_fake_chain_enforces_escrow_release_and_nonce_invariants():
    chain = FakeChain()
    intent = _intent()
    chain.commit(intent)
    chain.escrowDeposit(intent["paymentId"], intent=intent)
    with pytest.raises(ChainRevert, match="PaymentNotReleasable"):
        chain.escrowRelease(intent["paymentId"])
    chain.confirm(intent["paymentId"])
    chain.escrowRelease(intent["paymentId"])
    assert chain.escrows[intent["paymentId"]]["status"] == "RELEASED"

    with pytest.raises(ChainRevert, match="NonceUsed"):
        chain.commit(_intent(payment_id="second-payment", nonce=5))


def test_shared_eip712_vector_when_present():
    vector_path = REPO_ROOT / "shared" / "eip712_vector.json"
    if not vector_path.exists():
        pytest.skip("shared/eip712_vector.json is not present")
    from api.chain.signer import signer

    vector = json.loads(vector_path.read_text())
    message = vector.get("message", vector.get("intent"))
    typed_data = signer.build_typed_data(
        "PaymentIntent",
        message,
        verifying_contract=vector.get("domain", {}).get("verifyingContract"),
    )
    assert signer.struct_hash("PaymentIntent", message) == vector["structHash"]


def test_payment_api_honors_idempotency_and_serves_metrics(monkeypatch):
    from api.orchestrator import orchestrator

    monkeypatch.setattr(orchestrator, "delay_ms", 0)
    client = TestClient(app)
    fixture = json.loads((FIXTURES / "scene1.json").read_text())
    client.post("/v1/sim/reset")
    first = client.post(
        "/v1/payments",
        json=fixture,
        headers={"Idempotency-Key": "test-idempotency"},
    )
    second = client.post(
        "/v1/payments",
        json=fixture,
        headers={"Idempotency-Key": "test-idempotency"},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["paymentId"] == second.json()["paymentId"]
    assert client.get("/v1/metrics").json() == {"status": "pending"}
