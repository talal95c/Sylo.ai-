"""DEMO_PUBLIC: on the shared public URL the operator endpoints are closed; the demo buttons still work."""

import pytest
from fastapi.testclient import TestClient

from sylo.config import Settings
from sylo.main import create_app
from sylo.orchestrator import build_orchestrator

OPERATOR = [
    ("/v1/payments/PAY-2026-0002/approve", {"approver": "claire"}),
    ("/v1/cases/PAY-2026-0002/actions", {"action": "FREEZE"}),
    ("/v1/sim/rails/R3/down", {}),
    ("/v1/payees/payee-savanna/verify", {"accountId": "acc-x", "action": "record", "result": "confirmed"}),
    ("/v1/sim/events", {"type": "rail_down", "routeId": "R3"}),
    ("/v1/rails/R3/webhook", {"idempotencyKey": "k", "status": "SETTLED"}),
    ("/v1/sim/clock", {"advanceHours": 1}),
    ("/v1/breakers/CB-x/lift", {}),
    ("/v1/guardian/incidents", {"rule": "stolen key", "action": "FREEZE_AND_PAUSE"}),
]


def _client(public: bool) -> TestClient:
    settings = Settings(demo_public=public, journal_path=None, cluster_mode="sample")
    return TestClient(create_app(settings, orchestrator=build_orchestrator(settings, env={})))


@pytest.mark.parametrize("path,body", OPERATOR)
def test_operator_endpoints_are_closed_on_the_public_demo(path, body):
    with _client(public=True) as client:
        response = client.post(path, json=body)
    assert response.status_code == 403, response.text
    assert "DEMO_PUBLIC" in response.json()["detail"]


@pytest.mark.parametrize("path,body", OPERATOR)
def test_operator_endpoints_stay_open_by_default(path, body):
    with _client(public=False) as client:
        assert client.post(path, json=body).status_code != 403


def test_the_demo_buttons_still_work_on_the_public_demo():
    with _client(public=True) as client:
        assert client.post("/v1/reset").status_code == 200
        assert client.get("/health").json()["ok"] is True
        assert client.post("/v1/quotes", json={"order": "legit"}).status_code == 200


def test_the_flag_is_read_from_the_environment():
    assert Settings.from_env({"DEMO_PUBLIC": "1"}).demo_public is True
    assert Settings.from_env({}).demo_public is False
