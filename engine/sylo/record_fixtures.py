"""Record the demo fixtures into spec/fixtures (v0 spec §4.8, roadmap A1.9).

    python -m sylo.record_fixtures          # write the files
    python -m sylo.record_fixtures --check  # exit 1 if re-recording would change them

Virtual clock from 2026-10-11T09:00:00.000Z, seed 42, speed 1, default settings and dev keys (the
environment is ignored so the files do not depend on the machine). The scenes run with ``auto``;
``samples-v1`` is the diverted scenario with every human step done by hand, and the three
``samples-scene*`` files are the v2 scenes (mule wave and breaker, stolen verifier key and guardian,
rail outage). ``samples-hold-expiry`` and ``samples-time-lock`` show the demo clock.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from typing import Any

from . import REPO_DIR
from .config import Settings
from .orchestrator import Orchestrator, PaymentRun, build_orchestrator
from .pacer import VirtualPacer

FIXTURES_DIR = REPO_DIR / "spec" / "fixtures"
START = datetime(2026, 10, 11, 9, 0, 0, tzinfo=timezone.utc)
SEED = 42
DIVERTED = "PAY-2026-0002"
AFTER_REVOCATION = ("release_revoked", "swap_beneficiary", "replay")
"""The attacks of Scene 2b, tried on a payment that was revoked. Scene 4 has its own file."""
NAMES = (
    "scene1-legit",
    "scene2-diverted",
    "scene2-deny",
    "scene2-confirm",
    "scene2-simswap",
    "scene2b-release-revoked",
    "scene2b-swap-beneficiary",
    "scene2b-replay",
    "samples-v1",
    "samples-scene3-mule-wave",
    "samples-scene4-guardian",
    "samples-scene5-outage",
    "samples-hold-expiry",
    "samples-time-lock",
)


class _Timeline:
    """Pacer factory whose clocks follow one another, for files that hold more than one scenario."""

    def __init__(self) -> None:
        self._last: VirtualPacer | None = None

    def __call__(self, speed: float) -> VirtualPacer:
        self._last = VirtualPacer(self._last.now() if self._last else START, speed)
        return self._last


def _orchestrator(timeline: _Timeline | None = None, **settings: Any) -> Orchestrator:
    settings.setdefault("cluster_mode", "sample")  # the files must not depend on Lane B's package being installed
    return build_orchestrator(
        Settings(seed=SEED, **settings), env={}, pacer_factory=timeline or (lambda speed: VirtualPacer(START, speed))
    )


async def _until(orchestrator: Orchestrator, payment_id: str, status: str, timeout: float = 10.0) -> PaymentRun:
    """Let the background scenario run until it waits for a person."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = orchestrator._runs.get(payment_id)
        if run is not None and run.status == status:
            return run
        await asyncio.sleep(0.001)
    raise RuntimeError(f"{payment_id} never reached {status}")


async def _denied_then(attack: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Diverted + deny on a fresh engine, then one attack. Returns (scenario events, attack events)."""
    orchestrator = _orchestrator()
    await orchestrator.run_to_end("diverted", auto=True, auto_answer="deny")
    scenario = orchestrator.bus.events
    await orchestrator.attack(attack, DIVERTED)
    return scenario, orchestrator.bus.events[len(scenario) :]


async def _manual_sample() -> list[dict[str, Any]]:
    """The diverted scenario with ``HUMAN_STEPS=manual``: two approvals, the supplier, the analyst, three attacks."""
    orchestrator = _orchestrator(human_steps="manual")
    payment_id = orchestrator.start("diverted", auto=False)
    run = await _until(orchestrator, payment_id, "awaiting_approval")
    await run.pacer.wait(1800)
    orchestrator.approve(payment_id, "claire")
    await run.pacer.wait(2400)
    orchestrator.approve(payment_id, "marc")
    await _until(orchestrator, payment_id, "awaiting_supplier")
    await run.pacer.wait(4200)
    orchestrator.supplier_response(payment_id, "deny")
    await _until(orchestrator, payment_id, "awaiting_analyst")
    await run.pacer.wait(2600)
    await orchestrator.case_action(payment_id, "CONFIRM_REVOCATION")
    assert orchestrator._task is not None
    await orchestrator._task
    for attack in AFTER_REVOCATION:
        await run.pacer.wait(1500)
        await orchestrator.attack(attack, payment_id)
    return orchestrator.bus.events


async def _mule_wave_sample() -> list[dict[str, Any]]:
    """Scene 3: the wave, the breaker confirmed, then the diverted payment into the same region."""
    orchestrator = _orchestrator(_Timeline())
    await orchestrator.run_wave(auto=True)
    await orchestrator.run_to_end("diverted", auto=True, auto_answer="deny")
    return orchestrator.bus.events


async def _guardian_sample() -> list[dict[str, Any]]:
    """Scene 4: a stolen verifier key confirms the held payment; the guardian freezes it and pauses the
    corridor, the thief's release reverts, the analyst revokes and the payer is refunded."""
    orchestrator = _orchestrator()
    payment_id = orchestrator.start("diverted", auto=False)
    run = await _until(orchestrator, payment_id, "awaiting_supplier")
    await run.pacer.wait(2500)
    await orchestrator.attack("stolen_verifier_key", payment_id)
    assert orchestrator._task is not None
    await orchestrator._task
    return orchestrator.bus.events


async def record() -> dict[str, list[dict[str, Any]]]:
    legit = _orchestrator()
    await legit.run_to_end("legit", auto=True)

    deny_events, release_attack = await _denied_then("release_revoked")
    split = next(i for i, e in enumerate(deny_events) if e["type"] == "verification.requested") + 1

    confirmed = _orchestrator()
    await confirmed.run_to_end("diverted", auto=True, auto_answer="confirm")
    confirm_events = confirmed.bus.events
    if confirm_events[:split] != deny_events[:split]:
        raise RuntimeError("the diverted scenario is not deterministic up to verification.requested")

    simswap = _orchestrator()
    await simswap.run_to_end("diverted_simswap", auto=True)

    recorded = {
        "scene1-legit": legit.bus.events,
        "scene2-diverted": deny_events[:split],
        "scene2-deny": deny_events[split:],
        "scene2-confirm": confirm_events[split:],
        "scene2-simswap": simswap.bus.events,
        "scene2b-release-revoked": release_attack,
    }
    for attack, name in (("swap_beneficiary", "scene2b-swap-beneficiary"), ("replay", "scene2b-replay")):
        scenario, attack_events = await _denied_then(attack)
        if scenario != deny_events:
            raise RuntimeError("the diverted + deny scenario is not deterministic")
        recorded[name] = attack_events
    recorded["samples-v1"] = await _manual_sample()
    recorded["samples-scene3-mule-wave"] = await _mule_wave_sample()
    recorded["samples-scene4-guardian"] = await _guardian_sample()
    outage = _orchestrator()
    await outage.run_to_end("outage", auto=True)
    recorded["samples-scene5-outage"] = outage.bus.events
    # Demo clock: nobody answers and the hold expires; then a confirmed first payment to a new account,
    # held at the bank because the escrow route is down, waits for its 24-hour time-lock.
    expiry = _orchestrator()
    await expiry.run_to_end("diverted_expiry", auto=True)
    recorded["samples-hold-expiry"] = expiry.bus.events
    locked = _orchestrator()
    await locked.run_to_end("diverted_timelock", auto=True, auto_answer="confirm")
    recorded["samples-time-lock"] = locked.bus.events
    return recorded


def render(events: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="fail if the recorded files would change")
    args = parser.parse_args(argv)

    recorded = {name: render(events) for name, events in asyncio.run(record()).items()}
    assert set(recorded) == set(NAMES), "NAMES must list every recorded file"
    if args.check:
        stale = [
            name
            for name, content in recorded.items()
            if not (FIXTURES_DIR / f"{name}.jsonl").exists()
            or (FIXTURES_DIR / f"{name}.jsonl").read_text(encoding="utf-8") != content
        ]
        if stale:
            print(f"fixtures out of date: {', '.join(stale)} (run `make fixtures`)", file=sys.stderr)
            return 1
        print(f"fixtures up to date ({len(recorded)} files)")
        return 0

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    for name, content in recorded.items():
        (FIXTURES_DIR / f"{name}.jsonl").write_text(content, encoding="utf-8")
        print(f"wrote spec/fixtures/{name}.jsonl ({content.count(chr(10))} events)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
