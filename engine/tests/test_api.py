"""The HTTP API and the event stream, through a real server and a real HTTP client.

(The stream is not tested through httpx's ASGI transport: it buffers streaming responses.)
"""

import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn

from sylo.config import Settings
from sylo.main import build_core, create_app
from sylo_spec import validate_event

LEGIT_EVENTS = 19


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def base_url():
    app = create_app(build_core(Settings(seed=42, chain_mode="mock", risk_mode="rules")))
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started:
        assert time.time() < deadline, "the server did not start"
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


def _read_stream(base_url: str, until: str, headers=None, timeout: float = 20.0) -> list[dict]:
    events = []
    with httpx.stream("GET", f"{base_url}/v1/stream", headers=headers or {}, timeout=timeout) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        for line in response.iter_lines():
            if line.startswith("data:"):
                event = json.loads(line[5:].strip())
                events.append(event)
                if event["type"] == until:
                    break
    return events


def _wait_status(base_url: str, payment_id: str, status: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while True:
        view = httpx.get(f"{base_url}/v1/payments/{payment_id}").json()
        if view.get("status") == status:
            return view
        assert time.time() < deadline, f"payment never reached {status}: {view}"
        time.sleep(0.02)


def test_health_and_cors(base_url):
    response = httpx.get(f"{base_url}/health", headers={"Origin": "http://localhost:3000"})
    assert response.json() == {"ok": True, "mode": {"risk": "rules", "chain": "mock", "llm": "off", "rails": "simulated", "degraded": []}}
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_legit_scenario_over_the_stream(base_url):
    run = httpx.post(f"{base_url}/v1/scenarios/legit/run", json={"speed": 50})
    assert run.status_code == 200 and run.json() == {"paymentId": "PAY-2026-0001"}
    events = _read_stream(base_url, until="payment.credited")
    for event in events:
        validate_event(event)
    assert events[0]["type"] == "system.mode" and events[0]["seq"] == 0
    assert [e["seq"] for e in events[1:]] == list(range(1, LEGIT_EVENTS + 1))
    assert events[1]["type"] == "scenario.started" and events[1]["data"]["speed"] == 50

    # a reconnecting browser sends Last-Event-ID and only gets what it missed
    tail = _read_stream(base_url, until="payment.credited", headers={"Last-Event-ID": "17"})
    assert [e["seq"] for e in tail] == [0, 18, 19]

    # an id from a previous engine process (larger than anything this one sent) is ignored
    stale = _read_stream(base_url, until="payment.credited", headers={"Last-Event-ID": "999"})
    assert [e["seq"] for e in stale] == list(range(0, LEGIT_EVENTS + 1))

    view = httpx.get(f"{base_url}/v1/payments/PAY-2026-0001").json()
    assert view == {"paymentId": "PAY-2026-0001", "status": "credited", "tier": "LOW", "routeId": "R3", "chainStatus": "EXECUTED", "lastSeq": 19}


def test_conflicts_not_found_and_reset(base_url):
    assert httpx.post(f"{base_url}/v1/scenarios/nope/run").status_code == 404
    assert httpx.post(f"{base_url}/v1/scenarios/diverted/run", json={"speed": 50}).status_code == 200
    assert httpx.post(f"{base_url}/v1/scenarios/legit/run").status_code == 409  # a scenario is running
    assert httpx.post(f"{base_url}/v1/payments/PAY-0000/supplier-response", json={"answer": "deny"}).status_code == 404
    assert httpx.post(f"{base_url}/v1/payments/PAY-2026-0002/supplier-response", json={"answer": "maybe"}).status_code == 422
    assert httpx.post(f"{base_url}/v1/attacks/nope", json={"paymentId": "PAY-2026-0002"}).status_code == 404
    _wait_status(base_url, "PAY-2026-0002", "awaiting_supplier")
    assert httpx.post(f"{base_url}/v1/attacks/release_revoked", json={"paymentId": "PAY-2026-0002"}).status_code == 409

    assert httpx.post(f"{base_url}/v1/reset").json() == {"ok": True}
    assert httpx.get(f"{base_url}/v1/payments/PAY-2026-0002").status_code == 404
    events = _read_stream(base_url, until="session.reset")
    assert [e["type"] for e in events] == ["system.mode", "session.reset"]
    assert httpx.post(f"{base_url}/v1/scenarios/legit/run", json={"speed": 50}).status_code == 200  # free again


def test_diverted_deny_and_attack_over_http(base_url):
    assert httpx.post(f"{base_url}/v1/scenarios/diverted/run", json={"speed": 50}).json() == {"paymentId": "PAY-2026-0002"}
    held = _wait_status(base_url, "PAY-2026-0002", "awaiting_supplier")
    assert (held["tier"], held["routeId"], held["chainStatus"]) == ("MEDIUM", "R3", "COMMITTED")
    assert httpx.post(f"{base_url}/v1/payments/PAY-2026-0002/supplier-response", json={"answer": "deny"}).json() == {"ok": True}
    assert httpx.post(f"{base_url}/v1/payments/PAY-2026-0002/supplier-response", json={"answer": "deny"}).status_code == 409
    stopped = _wait_status(base_url, "PAY-2026-0002", "stopped")
    assert stopped["chainStatus"] == "REVOKED"
    attack = httpx.post(f"{base_url}/v1/attacks/release_revoked", json={"paymentId": "PAY-2026-0002"})
    assert attack.json() == {"ok": True, "reverted": True, "reason": "PaymentNotReleasable"}
    events = _read_stream(base_url, until="tx.reverted")
    assert [e["type"] for e in events][-6:] == ["verification.recorded", "intent.revoked", "escrow.refunded", "payment.stopped", "attack.attempted", "tx.reverted"]
    for event in events:
        validate_event(event)
