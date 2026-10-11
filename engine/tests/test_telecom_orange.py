from __future__ import annotations

import base64
import os
from datetime import datetime, timezone

import httpx
import pytest

from sylo.config import Settings, orange_playground_number
from sylo.orchestrator import build_orchestrator
from sylo.pacer import VirtualPacer
from sylo.telecom import OrangeSimSwap

from .conftest import events_of, make_orchestrator


class _Response:
    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


def test_orange_simswap_checks_swapped_and_not_swapped_numbers(monkeypatch):
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        if url == OrangeSimSwap.TOKEN_URL:
            return _Response(200, {"access_token": "token", "expires_in": 3600})
        return _Response(200, {"swapped": kwargs["json"]["phoneNumber"].endswith("001")})

    monkeypatch.setattr(httpx, "post", post)
    telecom = OrangeSimSwap("client", "secret")

    assert telecom.check("+990100000001", max_age_hours=168) is True
    assert telecom.check("+990100000000", max_age_hours=168) is False
    assert calls[0][1]["headers"]["Authorization"] == (
        "Basic " + base64.b64encode(b"client:secret").decode("ascii")
    )
    assert calls[0][1]["data"] == {"grant_type": "client_credentials"}
    assert calls[1][1]["json"] == {"phoneNumber": "+990100000001", "maxAge": 168}
    assert all(call[1]["timeout"] == 3.0 for call in calls)
    assert telecom.degraded is False


def test_orange_simswap_caches_token_until_expiry(monkeypatch):
    now = [0.0]
    token_calls = []

    def post(url, **kwargs):
        if url == OrangeSimSwap.TOKEN_URL:
            token_calls.append(url)
            return _Response(200, {"access_token": f"token-{len(token_calls)}", "expires_in": 10})
        return _Response(200, {"swapped": False})

    monkeypatch.setattr(httpx, "post", post)
    telecom = OrangeSimSwap("client", "secret", monotonic=lambda: now[0])

    assert telecom.check("+990100000000") is False
    now[0] = 9.999
    assert telecom.check("+990100000000") is False
    now[0] = 10.0
    assert telecom.check("+990100000000") is False

    assert len(token_calls) == 2


def test_orange_simswap_parses_latest_change_date(monkeypatch):
    def post(url, **kwargs):
        if url == OrangeSimSwap.TOKEN_URL:
            return _Response(200, {"access_token": "token", "expires_in": 3600})
        return _Response(200, {"latestSimChange": "2020-03-15T00:00:00Z"})

    monkeypatch.setattr(httpx, "post", post)
    changed = OrangeSimSwap("client", "secret").retrieve_date("+990100000000")

    assert changed == datetime(2020, 3, 15, tzinfo=timezone.utc)


def test_orange_simswap_fails_safe_on_timeout(monkeypatch):
    def post(*args, **kwargs):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(httpx, "post", post)
    telecom = OrangeSimSwap("client", "secret")

    assert telecom.check("+990100000001") is True
    assert telecom.degraded is True


def test_orange_simswap_fails_safe_on_403(monkeypatch):
    def post(url, **kwargs):
        if url == OrangeSimSwap.TOKEN_URL:
            return _Response(200, {"access_token": "token", "expires_in": 3600})
        return _Response(403, {"error": "not a playground number"})

    monkeypatch.setattr(httpx, "post", post)
    telecom = OrangeSimSwap("client", "secret")

    assert telecom.check("+233000000000") is True
    assert telecom.degraded is True


def test_orange_simswap_fails_safe_without_credentials(monkeypatch):
    def post(*args, **kwargs):
        pytest.fail("credentials must be checked before making a request")

    monkeypatch.setattr(httpx, "post", post)
    telecom = OrangeSimSwap("", "")

    assert telecom.check("+990100000000") is True
    assert telecom.degraded is True


def test_orange_playground_mapping_uses_swapped_number_only_for_simswap_scene():
    contact = "+233 •• ••• 4471"

    assert orange_playground_number(contact, "diverted_simswap") == "+990100000001"
    assert orange_playground_number(contact, "diverted") == "+990100000000"
    assert orange_playground_number(contact, "legit") == "+990100000000"


def test_telecom_mode_defaults_to_mock_and_accepts_orange_playground():
    assert Settings.from_env({}).telecom_mode == "mock"
    assert (
        Settings.from_env({"TELECOM_MODE": "ORANGE-PLAYGROUND"}).telecom_mode
        == "orange-playground"
    )
    with pytest.raises(ValueError, match="TELECOM_MODE"):
        Settings.from_env({"TELECOM_MODE": "unknown"})


async def test_mock_verification_event_labels_its_source():
    orchestrator = make_orchestrator()

    await orchestrator.run_to_end("diverted")

    requested = events_of(orchestrator, "verification.requested")[0]["data"]
    assert requested["simSwapSource"] == "mock"


async def test_orange_check_failure_degrades_and_routes_contact_to_analyst(monkeypatch):
    def post(*args, **kwargs):
        pytest.fail("missing Orange credentials must not trigger HTTP")

    monkeypatch.setattr(httpx, "post", post)
    orchestrator = make_orchestrator(telecom_mode="orange-playground")

    run = await orchestrator.run_to_end("diverted")

    assert run.status == "stopped"
    assert "telecom" in orchestrator.mode()["degraded"]
    assert "telecom" in events_of(orchestrator, "system.mode")[0]["data"]["degraded"]
    requested = events_of(orchestrator, "verification.requested")[0]["data"]
    assert requested["channel"] == "ANALYST"
    assert requested["simSwapRecent"] is True
    assert requested["simSwapSource"] == "Orange CAMARA Playground (sandbox data)"
    held = events_of(orchestrator, "payment.held")[0]["data"]
    assert held["reasons"][-1]["ruleId"] == "R-OOB-01"
    assert "unavailable" in held["nextStep"]


async def test_orange_playground_uses_mapped_swapped_number(monkeypatch):
    check_requests = []

    def post(url, **kwargs):
        if url == OrangeSimSwap.TOKEN_URL:
            return _Response(200, {"access_token": "token", "expires_in": 3600})
        if url == OrangeSimSwap.CHECK_URL:
            check_requests.append(kwargs["json"])
            body = {"swapped": kwargs["json"]["phoneNumber"] == "+990100000001"}
        else:
            body = {"latestSimChange": "2026-10-11T04:00:00Z"}
        return _Response(200, body)

    monkeypatch.setattr(httpx, "post", post)
    orchestrator = build_orchestrator(
        Settings(telecom_mode="orange-playground"),
        env={"ORANGE_CLIENT_ID": "client", "ORANGE_CLIENT_SECRET": "secret"},
        pacer_factory=lambda speed: VirtualPacer(
            datetime(2026, 10, 11, 9, 0, 0, tzinfo=timezone.utc), speed
        ),
    )

    run = await orchestrator.run_to_end("diverted_simswap")

    assert run.status == "stopped"
    assert check_requests == [{"phoneNumber": "+990100000001", "maxAge": 240}]
    requested = events_of(orchestrator, "verification.requested")[0]["data"]
    assert requested["simSwapSource"] == "Orange CAMARA Playground (sandbox data)"
    assert "telecom" not in orchestrator.mode()["degraded"]


@pytest.mark.skipif(
    os.getenv("RUN_LIVE") != "1", reason="set RUN_LIVE=1 to call Orange Playground"
)
def test_orange_playground_live_swapped_profile():
    telecom = OrangeSimSwap()

    assert telecom.check("+990100000001", max_age_hours=240) is True
    assert telecom.degraded is False
    assert telecom.retrieve_date("+990100000001") is not None
    assert telecom.degraded is False
