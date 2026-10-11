"""SIM-swap mock and Orange CAMARA Playground adapter for rule R-OOB-01.

Both expose CAMARA-shaped ``check(phoneNumber, maxAge)`` and ``retrieve_date`` methods.
The mock is scenario-driven; Orange uses static sandbox profiles.
"""

from __future__ import annotations

import base64
import logging
import os
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

log = logging.getLogger("sylo.telecom")


class SimSwapMock:
    simulated = True
    source = "mock"

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._changes: dict[str, datetime] = {}

    def declare_swap(self, msisdn: str, *, hours_ago: float) -> None:
        """Scenario set-up: the SIM behind ``msisdn`` changed ``hours_ago`` hours before now."""
        self._changes[msisdn] = self._clock() - timedelta(hours=hours_ago)

    def clear(self) -> None:
        self._changes.clear()

    def retrieve_date(self, msisdn: str) -> datetime | None:
        """CAMARA ``retrieve-date``: the latest SIM change, or None when none is known."""
        return self._changes.get(msisdn)

    def check(self, msisdn: str, max_age_hours: int = 240) -> bool:
        """CAMARA ``check``: True when the SIM changed within the last ``max_age_hours`` hours."""
        changed = self._changes.get(msisdn)
        if changed is None:
            return False
        return self._clock() - changed <= timedelta(hours=max_age_hours)


class OrangeSimSwap:
    """SIM-swap checks against Orange's CAMARA Playground test data."""

    simulated = True
    source = "Orange CAMARA Playground (sandbox data)"
    TOKEN_URL = "https://api.orange.com/openidconnect/playground/v1.0/token"
    CHECK_URL = "https://api.orange.com/camara/playground/api/sim-swap/v1/check"
    RETRIEVE_DATE_URL = "https://api.orange.com/camara/playground/api/sim-swap/v1/retrieve-date"
    TIMEOUT_SECONDS = 3.0

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        *,
        post: Callable[..., Any] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client_id = (
            client_id if client_id is not None else os.getenv("ORANGE_CLIENT_ID", "")
        )
        self._client_secret = (
            client_secret if client_secret is not None else os.getenv("ORANGE_CLIENT_SECRET", "")
        )
        self._post = post or httpx.post
        self._monotonic = monotonic
        self._access_token: str | None = None
        self._token_expires_at = 0.0
        self.degraded = False

    def clear(self) -> None:
        """The Playground has no per-scenario mutable state to clear."""

    def declare_swap(self, msisdn: str, *, hours_ago: float) -> None:
        """Scenario declarations cannot change fixed Playground profiles."""
        log.info("Orange CAMARA Playground ignores scenario-declared SIM swaps")

    def _request_json(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json_body: dict[str, Any] | None = None,
        form_body: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        response = self._post(
            url,
            headers=headers,
            json=json_body,
            data=form_body,
            timeout=self.TIMEOUT_SECONDS,
        )
        status = getattr(response, "status_code", None)
        if status != 200:
            raise RuntimeError(f"HTTP {status}")
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("response body must be a JSON object")
        return body

    def _token(self) -> str:
        if self._access_token and self._monotonic() < self._token_expires_at:
            return self._access_token
        if not self._client_id or not self._client_secret:
            raise RuntimeError("ORANGE_CLIENT_ID and ORANGE_CLIENT_SECRET are required")
        credentials = base64.b64encode(
            f"{self._client_id}:{self._client_secret}".encode("utf-8")
        ).decode("ascii")
        body = self._request_json(
            self.TOKEN_URL,
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            form_body={"grant_type": "client_credentials"},
        )
        access_token = body.get("access_token")
        expires_in = body.get("expires_in")
        if not isinstance(access_token, str) or not access_token:
            raise ValueError("token response did not contain an access token")
        if not isinstance(expires_in, (int, float)) or expires_in <= 0:
            raise ValueError("token response did not contain a valid expiry")
        self._access_token = access_token
        self._token_expires_at = self._monotonic() + float(expires_in)
        return access_token

    def _failed(self, operation: str, error: Exception) -> None:
        self.degraded = True
        log.warning("Orange CAMARA Playground %s failed: %s", operation, error)

    def check(self, msisdn: str, max_age_hours: int = 240) -> bool:
        try:
            body = self._request_json(
                self.CHECK_URL,
                headers={
                    "Authorization": f"Bearer {self._token()}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json_body={"phoneNumber": msisdn, "maxAge": max_age_hours},
            )
            swapped = body.get("swapped")
            if not isinstance(swapped, bool):
                raise ValueError("SIM-swap response did not contain a boolean swapped value")
            return swapped
        except Exception as error:
            self._failed("check", error)
            return True

    def retrieve_date(self, msisdn: str) -> datetime | None:
        try:
            body = self._request_json(
                self.RETRIEVE_DATE_URL,
                headers={
                    "Authorization": f"Bearer {self._token()}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json_body={"phoneNumber": msisdn},
            )
            latest = body.get("latestSimChange")
            if not isinstance(latest, str) or not latest:
                raise ValueError("SIM-swap response did not contain latestSimChange")
            changed = datetime.fromisoformat(latest.replace("Z", "+00:00"))
            return changed.replace(tzinfo=timezone.utc) if changed.tzinfo is None else changed
        except Exception as error:
            self._failed("retrieve-date", error)
            return None
