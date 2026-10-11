import json
from datetime import datetime, timezone

import pytest
from jsonschema import Draft202012Validator

from sylo import REPO_DIR
from sylo.config import Settings
from sylo.orchestrator import build_orchestrator
from sylo.pacer import VirtualPacer

START = datetime(2026, 10, 11, 9, 0, 0, tzinfo=timezone.utc)

FIRST_SEVEN = [
    "scenario.started",
    "payment.created",
    "norms.checked",
    "risk.scored",
    "route.selected",
    "approval.granted",
    "intent.committed",
]
LEGIT_SEQUENCE = FIRST_SEVEN + ["leg.sent", "leg.settled"] * 5 + ["intent.executed", "payment.credited"]
DIVERTED_PREFIX = FIRST_SEVEN + ["leg.sent", "leg.settled"] * 2 + [
    "leg.sent",
    "escrow.deposited",
    "payment.held",
    "case.ready",
    "verification.requested",
]
DENY_SEQUENCE = ["verification.recorded", "case.ready", "intent.revoked", "escrow.refunded", "payment.stopped"]
CONFIRM_SEQUENCE = [
    "verification.recorded",
    "case.ready",
    "escrow.released",
    "intent.executed",
    "leg.settled",
    "leg.sent",
    "leg.settled",
    "payment.credited",
]
ATTACK_SEQUENCE = ["attack.attempted", "tx.reverted"]


def make_orchestrator():
    """Orchestrator with a virtual clock, default settings and dev keys (ignores the environment)."""
    return build_orchestrator(Settings(), env={}, pacer_factory=lambda speed: VirtualPacer(START, speed))


@pytest.fixture
def orchestrator():
    return make_orchestrator()


@pytest.fixture(scope="session")
def event_validator():
    schema = json.loads((REPO_DIR / "spec" / "events.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema)
