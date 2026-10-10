"""Record the scenario event fixtures into /spec/fixtures (Lane A only).

    python -m sylo.record_fixtures            # (re)write the five fixture files
    python -m sylo.record_fixtures --check    # fail if re-recording would change them

Recorded with a virtual clock starting at 2026-10-11T09:00:00.000Z, seed 42, speed 1, auto
answers, rules-based risk and the mock chain: recording twice gives byte-identical files.
"""

import asyncio
import json
import sys
from typing import Any

from sylo_spec import FIXTURES_DIR
from sylo_spec.scenarios import DEMO_NOW

from .config import Settings
from .main import Core, build_core
from .pacer import VirtualPacer

SEED = 42
SPEED = 1.0


def fresh_core() -> Core:
    # Explicit settings, independent of the developer's environment.
    return build_core(Settings(seed=SEED, demo_speed=SPEED), VirtualPacer(DEMO_NOW, SPEED))


def _split_after(events: list[dict[str, Any]], type_: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    index = next(i for i, event in enumerate(events) if event["type"] == type_)
    return events[: index + 1], events[index + 1 :]


async def record() -> dict[str, list[dict[str, Any]]]:
    files: dict[str, list[dict[str, Any]]] = {}

    core = fresh_core()
    core.orchestrator.start("legit", speed=SPEED, auto=True)
    await core.orchestrator.wait_idle()
    files["scene1-legit.jsonl"] = core.bus.events()

    core = fresh_core()
    payment_id = core.orchestrator.start("diverted", speed=SPEED, auto=True, auto_answer="deny")
    await core.orchestrator.wait_idle()
    diverted, deny = _split_after(core.bus.events(), "verification.requested")
    files["scene2-diverted.jsonl"] = diverted
    files["scene2-deny.jsonl"] = deny
    before_attack = core.bus.last_seq
    await core.orchestrator.attack("release_revoked", payment_id)
    files["scene2b-release-revoked.jsonl"] = core.bus.events(after=before_attack)

    core = fresh_core()
    core.orchestrator.start("diverted", speed=SPEED, auto=True, auto_answer="confirm")
    await core.orchestrator.wait_idle()
    again, confirm = _split_after(core.bus.events(), "verification.requested")
    if render(again) != render(diverted):
        raise SystemExit("recording is not deterministic: the two diverted runs differ before the supplier answer")
    files["scene2-confirm.jsonl"] = confirm
    return files


def render(events: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n" for event in events)


def main(argv: list[str]) -> int:
    rendered = {name: render(events) for name, events in asyncio.run(record()).items()}
    if "--check" in argv:
        stale = [n for n, text in rendered.items() if not (FIXTURES_DIR / n).exists() or (FIXTURES_DIR / n).read_text(encoding="utf-8") != text]
        if stale:
            print("fixtures are out of date (run `make fixtures`): " + ", ".join(stale), file=sys.stderr)
            return 1
        print(f"fixtures are up to date ({len(rendered)} files)")
        return 0
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    for name, text in rendered.items():
        (FIXTURES_DIR / name).write_text(text, encoding="utf-8")
        print(f"wrote {name}: {text.count(chr(10))} events")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
