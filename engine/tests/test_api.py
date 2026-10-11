"""API tests against a real uvicorn server (httpx's ASGI transport buffers streams and would hang)."""

import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn

from sylo.config import Settings
from sylo.main import create_app
from sylo.orchestrator import build_orchestrator

from .conftest import LEGIT_SEQUENCE


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _serve(settings: Settings):
    app = create_app(settings, orchestrator=build_orchestrator(settings, env={}))
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "uvicorn did not start"
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture(scope="module")
def base_url():
    yield from _serve(Settings())


@pytest.fixture(scope="module")
def manual_url():
    """An engine where the payer approvals and the analyst's decision must come through the API."""
    yield from _serve(Settings(human_steps="manual"))


def read_stream_until(base_url: str, stop_type: str, timeout: float = 15.0) -> list[dict]:
    events: list[dict] = []
    with httpx.Client(timeout=httpx.Timeout(timeout)) as client:
        with client.stream("GET", f"{base_url}/v1/stream") as response:
            assert response.status_code == 200
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                event = json.loads(line[len("data:") :].strip())
                events.append(event)
                if event["type"] == stop_type:
                    break
    return events


def test_health(base_url):
    body = httpx.get(f"{base_url}/health").json()
    assert body["ok"] is True
    assert body["mode"]["risk"] == "rules" and body["mode"]["chain"] == "mock" and body["mode"]["rails"] == "simulated"


def test_legit_payment_over_the_stream(base_url):
    httpx.post(f"{base_url}/v1/reset")
    response = httpx.post(f"{base_url}/v1/scenarios/legit/run", json={"speed": 50})
    assert response.status_code == 200 and response.json() == {"paymentId": "PAY-2026-0001"}
    events = read_stream_until(base_url, "payment.credited")
    assert events[0]["type"] == "system.mode" and events[0]["seq"] == 0
    session = [e for e in events if e["type"] not in ("system.mode", "session.reset")]
    assert [e["type"] for e in session] == LEGIT_SEQUENCE
    info = httpx.get(f"{base_url}/v1/payments/PAY-2026-0001").json()
    assert info["status"] == "credited" and info["chainStatus"] == "EXECUTED" and info["routeId"] == "R3"


def test_conflicts_errors_and_reset(base_url):
    httpx.post(f"{base_url}/v1/reset")
    assert httpx.post(f"{base_url}/v1/scenarios/diverted/run", json={"speed": 50}).status_code == 200
    assert httpx.post(f"{base_url}/v1/scenarios/legit/run", json={"speed": 50}).status_code == 409
    assert httpx.post(f"{base_url}/v1/scenarios/unknown/run").status_code == 404
    read_stream_until(base_url, "verification.requested")
    attack = httpx.post(f"{base_url}/v1/attacks/release_revoked", json={"paymentId": "PAY-2026-0002"})
    assert attack.status_code == 409
    assert httpx.post(f"{base_url}/v1/attacks/other", json={"paymentId": "PAY-2026-0002"}).status_code == 404

    answer = httpx.post(f"{base_url}/v1/payments/PAY-2026-0002/supplier-response", json={"answer": "deny"})
    assert answer.status_code == 200
    read_stream_until(base_url, "payment.stopped")
    again = httpx.post(f"{base_url}/v1/payments/PAY-2026-0002/supplier-response", json={"answer": "deny"})
    assert again.status_code == 409
    attack = httpx.post(f"{base_url}/v1/attacks/release_revoked", json={"paymentId": "PAY-2026-0002"})
    assert attack.json() == {"ok": True, "reverted": True, "reason": "PaymentNotReleasable"}

    assert httpx.post(f"{base_url}/v1/reset").json() == {"ok": True}
    assert httpx.get(f"{base_url}/v1/payments/PAY-2026-0002").status_code == 404
    events = read_stream_until(base_url, "session.reset")
    assert [e["type"] for e in events] == ["system.mode", "session.reset"]
    assert httpx.post(f"{base_url}/v1/scenarios/legit/run", json={"speed": 50}).status_code == 200
    read_stream_until(base_url, "payment.credited")


def test_reconnect_with_last_event_id_only_sends_newer_events(base_url):
    httpx.post(f"{base_url}/v1/reset")
    assert httpx.post(f"{base_url}/v1/scenarios/legit/run", json={"speed": 50}).status_code == 200
    events = read_stream_until(base_url, "payment.credited")
    last = events[-1]["seq"]
    with httpx.Client(timeout=5) as client:
        with client.stream("GET", f"{base_url}/v1/stream", headers={"Last-Event-ID": str(last - 2)}) as response:
            seqs = []
            for line in response.iter_lines():
                if line.startswith("data:"):
                    seqs.append(json.loads(line[5:])["seq"])
                    if len(seqs) == 3:
                        break
    assert seqs == [0, last - 1, last]


DIVERTED = "PAY-2026-0002"


def post(base_url: str, path: str, body: dict | None = None) -> httpx.Response:
    return httpx.post(f"{base_url}{path}", json=body)


def test_scene_2_with_every_human_step_through_the_api(manual_url):
    assert httpx.get(f"{manual_url}/health").json()["mode"]["humanSteps"] == "manual"
    post(manual_url, "/v1/reset")
    assert post(manual_url, "/v1/scenarios/diverted/run", {"speed": 50}).json() == {"paymentId": DIVERTED}
    asked = read_stream_until(manual_url, "approval.required")[-1]["data"]
    assert asked["pending"] == ["claire", "marc"]
    assert httpx.get(f"{manual_url}/v1/payments/{DIVERTED}").json()["status"] == "awaiting_approval"

    assert post(manual_url, f"/v1/payments/{DIVERTED}/approve", {"approver": "marc"}).status_code == 409
    assert post(manual_url, f"/v1/payments/{DIVERTED}/approve", {"approver": "mallory"}).status_code == 409
    assert post(manual_url, f"/v1/payments/{DIVERTED}/approve", {"approver": "claire"}).json() == {"ok": True, "pending": ["marc"]}
    twice = post(manual_url, f"/v1/payments/{DIVERTED}/approve", {"approver": "claire"})
    assert twice.status_code == 409 and "second approver" in twice.json()["detail"]
    assert post(manual_url, f"/v1/payments/{DIVERTED}/approve", {"approver": "Marc"}).json() == {"ok": True, "pending": []}

    read_stream_until(manual_url, "verification.requested")
    assert post(manual_url, f"/v1/payments/{DIVERTED}/approve", {"approver": "claire"}).status_code == 409
    assert post(manual_url, f"/v1/cases/{DIVERTED}/actions", {"action": "RELEASE"}).status_code == 409
    assert post(manual_url, f"/v1/cases/{DIVERTED}/actions", {"action": "PAY_ANYWAY"}).status_code == 422
    assert post(manual_url, f"/v1/payments/{DIVERTED}/supplier-response", {"answer": "deny"}).status_code == 200
    read_stream_until(manual_url, "verification.recorded")
    info = httpx.get(f"{manual_url}/v1/payments/{DIVERTED}").json()
    assert info["hold"] == "escrow" and info["chainStatus"] == "DENIED" and info["caseReady"] is True

    assert post(manual_url, f"/v1/cases/{DIVERTED}/actions", {"action": "CONFIRM_REVOCATION"}).json() == {"ok": True}
    events = read_stream_until(manual_url, "payment.stopped")
    kinds = [e["type"] for e in events]
    assert kinds.index("case.action") < kinds.index("intent.revoked") < kinds.index("escrow.refunded")
    assert post(manual_url, f"/v1/cases/{DIVERTED}/actions", {"action": "CONFIRM_REVOCATION"}).status_code == 409


def test_the_three_attacks_and_the_proof_over_http(manual_url):
    # Continues the previous test: PAY-2026-0002 is revoked and refunded.
    swap = post(manual_url, "/v1/attacks/swap_beneficiary", {"paymentId": DIVERTED}).json()
    assert swap == {"ok": True, "reverted": True, "reason": "CommitmentMismatch", "legRejected": "INTENT_HASH_MISMATCH"}
    assert post(manual_url, "/v1/attacks/replay", {"paymentId": DIVERTED}).json()["reason"] == "InvalidTransition"
    assert post(manual_url, "/v1/attacks/release_revoked", {"paymentId": DIVERTED}).json()["reason"] == "PaymentNotReleasable"

    response = httpx.get(f"{manual_url}/v1/payments/{DIVERTED}/proof")
    assert response.status_code == 200
    proof = response.json()
    assert [s["type"] for s in proof["signed"]] == ["PaymentIntent", "VerificationAttestation", "Revocation"]
    assert proof["signed"][0]["typedData"]["message"]["amount"] == "85000000000"
    assert proof["chainStatus"] == "REVOKED" and len(proof["transactions"]) == 5
    assert proof["log"][-1]["type"] == "tx.reverted" and proof["logHead"] == proof["log"][-1]["hash"]


def test_unknown_payments_and_names_are_404(base_url):
    assert post(base_url, "/v1/payments/PAY-0000/approve", {"approver": "claire"}).status_code == 404
    assert post(base_url, "/v1/cases/PAY-0000/actions", {"action": "FREEZE"}).status_code == 404
    assert httpx.get(f"{base_url}/v1/payments/PAY-0000/proof").status_code == 404
    assert post(base_url, "/v1/attacks/replay", {"paymentId": "PAY-0000"}).status_code == 404
    unknown = post(base_url, "/v1/scenarios/nope/run")
    assert unknown.status_code == 404 and "diverted_simswap" in unknown.json()["detail"]


def test_with_auto_the_whole_scenario_runs_even_when_human_steps_are_manual(manual_url):
    post(manual_url, "/v1/reset")
    body = {"speed": 100, "auto": True, "autoAnswer": "confirm"}
    assert post(manual_url, "/v1/scenarios/diverted_simswap/run", body).status_code == 200
    events = read_stream_until(manual_url, "payment.stopped")
    assert [e["data"]["channel"] for e in events if e["type"] == "verification.requested"] == ["ANALYST"]
