"""Record the demo fixtures into spec/fixtures (v0 spec §4.8).

    python -m sylo.record_fixtures          # write the five files
    python -m sylo.record_fixtures --check  # exit 1 if re-recording would change them

Virtual clock from 2026-10-11T09:00:00.000Z, seed 42, speed 1, auto answers, default settings and
dev keys (the environment is ignored so the files do not depend on the machine).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from typing import Any

from . import REPO_DIR
from .config import Settings
from .orchestrator import build_orchestrator
from .pacer import VirtualPacer

FIXTURES_DIR = REPO_DIR / "spec" / "fixtures"
START = datetime(2026, 10, 11, 9, 0, 0, tzinfo=timezone.utc)
SEED = 42
NAMES = ("scene1-legit", "scene2-diverted", "scene2-deny", "scene2-confirm", "scene2b-release-revoked")


def _orchestrator():
    return build_orchestrator(Settings(seed=SEED), env={}, pacer_factory=lambda speed: VirtualPacer(START, speed))


async def record() -> dict[str, list[dict[str, Any]]]:
    legit = _orchestrator()
    await legit.run_to_end("legit", auto=True)

    denied = _orchestrator()
    await denied.run_to_end("diverted", auto=True, auto_answer="deny")
    deny_events = denied.bus.events
    split = next(i for i, e in enumerate(deny_events) if e["type"] == "verification.requested") + 1
    await denied.attack("release_revoked", "PAY-2026-0002")
    attack_events = denied.bus.events[len(deny_events) :]

    confirmed = _orchestrator()
    await confirmed.run_to_end("diverted", auto=True, auto_answer="confirm")
    confirm_events = confirmed.bus.events
    if confirm_events[:split] != deny_events[:split]:
        raise RuntimeError("the diverted scenario is not deterministic up to verification.requested")

    return {
        "scene1-legit": legit.bus.events,
        "scene2-diverted": deny_events[:split],
        "scene2-deny": deny_events[split:],
        "scene2-confirm": confirm_events[split:],
        "scene2b-release-revoked": attack_events,
    }


def render(events: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="fail if the recorded files would change")
    args = parser.parse_args(argv)

    recorded = {name: render(events) for name, events in asyncio.run(record()).items()}
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
