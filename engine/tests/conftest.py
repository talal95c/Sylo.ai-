import asyncio
import json
import time
from datetime import datetime, timezone

import pytest
from jsonschema import Draft202012Validator

from sylo import REPO_DIR
from sylo.config import Settings
from sylo.orchestrator import build_orchestrator
from sylo.pacer import VirtualPacer

START = datetime(2026, 10, 11, 9, 0, 0, tzinfo=timezone.utc)

DECISION = ["scenario.started", "payment.created", "norms.checked", "risk.scored", "route.selected"]
# Dual control: asked, asked again for the second approver, granted.
APPROVAL = ["approval.required", "approval.required", "approval.granted"]
FIRST_NINE = DECISION + APPROVAL + ["intent.committed"]
LEGIT_SEQUENCE = FIRST_NINE + ["leg.sent", "leg.settled"] * 5 + ["intent.executed", "payment.credited"]
DIVERTED_PREFIX = FIRST_NINE + ["leg.sent", "leg.settled"] * 2 + [
    "leg.sent",
    "escrow.deposited",
    "payment.held",
    "alert.raised",
    "case.ready",
    "verification.requested",
]
REVOKE_SEQUENCE = ["case.action", "intent.revoked", "escrow.refunded", "alert.raised", "alert.raised", "payment.stopped"]
DENY_SEQUENCE = ["verification.recorded"] + REVOKE_SEQUENCE
CONFIRM_SEQUENCE = [
    "verification.recorded",
    "escrow.released",
    "intent.executed",
    "leg.settled",
    "leg.sent",
    "leg.settled",
    "payment.credited",
]
ATTACK_SEQUENCE = ["attack.attempted", "tx.reverted"]
SWAP_SEQUENCE = ["attack.attempted", "leg.rejected", "tx.reverted"]


def make_orchestrator(**settings):
    """Orchestrator with a virtual clock, default settings and dev keys (ignores the environment)."""
    return build_orchestrator(Settings(**settings), env={}, pacer_factory=lambda speed: VirtualPacer(START, speed))


def types(orchestrator):
    return [e["type"] for e in orchestrator.bus.events]


def events_of(orchestrator, type_):
    return [e for e in orchestrator.bus.events if e["type"] == type_]


async def until(orchestrator, payment_id, status, timeout=5.0):
    """Let the background scenario run until the payment reaches ``status``."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = orchestrator._runs.get(payment_id)
        if run is not None and run.status == status:
            return run
        await asyncio.sleep(0.001)
    run = orchestrator._runs.get(payment_id)
    raise AssertionError(f"payment {payment_id} is {run.status if run else 'unknown'}, expected {status}")


@pytest.fixture
def orchestrator():
    return make_orchestrator()


@pytest.fixture(scope="session")
def event_validator():
    schema = json.loads((REPO_DIR / "spec" / "events.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema)
