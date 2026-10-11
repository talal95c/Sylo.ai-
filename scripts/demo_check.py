#!/usr/bin/env python3
"""Demo check (roadmap A1.9): run the demo scenes against an engine and assert what the jury will see.

    make demo-check                      # uses the engine on ENGINE_PORT, or starts a temporary one
    cd engine && uv run python ../scripts/demo_check.py --url http://localhost:8000 --speed 20

It runs, with ``auto: true``: the legitimate payment; the diverted invoice with the supplier's denial;
the three attacks on the revoked payment; the diverted invoice with a confirmation; the SIM-swap
variant. It then reads the proof of the last payment. Exit code 0 when everything matches.

The same checks pass in every mode (rules or model, mock or Fuji, with or without a case writer):
only the event types and the facts that must not change are asserted.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ENGINE_DIR = Path(__file__).resolve().parents[1] / "engine"

DECISION = ["scenario.started", "payment.created", "norms.checked", "risk.scored", "route.selected"]
COMMITTED = ["approval.granted", "intent.committed"]
LEGS = ["leg.sent", "leg.settled"]
LEGIT = DECISION + COMMITTED + LEGS * 5 + ["intent.executed", "payment.credited"]
HELD = DECISION + COMMITTED + LEGS * 2 + ["leg.sent", "escrow.deposited", "payment.held", "verification.requested"]
REVOKED = ["case.action", "intent.revoked", "escrow.refunded", "payment.stopped"]
DENIED = HELD + ["verification.recorded"] + REVOKED
CONFIRMED = HELD + ["verification.recorded", "escrow.released", "intent.executed", "leg.settled", "leg.sent", "leg.settled", "payment.credited"]
SIM_SWAPPED = HELD + REVOKED
# Not part of the story line: asked more than once, told to people, or written by a (possibly slow) case writer.
SIDE_EVENTS = {"approval.required", "alert.raised", "case.ready", "system.mode", "session.reset"}


class CheckFailed(Exception):
    pass


class Engine:
    def __init__(self, url: str, timeout: float) -> None:
        self.url = url.rstrip("/")
        self.timeout = timeout

    def get(self, path: str) -> Any:
        with urllib.request.urlopen(self.url + path, timeout=10) as response:
            return json.loads(response.read())

    def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        request = urllib.request.Request(
            self.url + path,
            data=json.dumps(body or {}).encode(),
            headers={"content-type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as err:
            raise CheckFailed(f"POST {path} answered {err.code}: {err.read().decode(errors='replace')}") from None

    def events_until(self, stop_type: str) -> list[dict[str, Any]]:
        """The session's events, from its start up to the first ``stop_type``."""
        deadline = time.monotonic() + self.timeout
        events: list[dict[str, Any]] = []
        with urllib.request.urlopen(self.url + "/v1/stream", timeout=self.timeout) as stream:
            for raw in stream:
                if time.monotonic() > deadline:
                    break
                line = raw.decode("utf-8").strip()
                if not line.startswith("data:"):
                    continue
                event = json.loads(line[5:])
                events.append(event)
                if event["type"] == stop_type:
                    return events
        seen = [e["type"] for e in events][-6:]
        raise CheckFailed(f"no {stop_type} within {self.timeout:.0f} s (last events: {seen})")


def story(events: list[dict[str, Any]]) -> list[str]:
    return [e["type"] for e in events if e["type"] not in SIDE_EVENTS]


def first(events: list[dict[str, Any]], type_: str) -> dict[str, Any]:
    found = next((e["data"] for e in events if e["type"] == type_), None)
    if found is None:
        raise CheckFailed(f"no {type_} event")
    return found


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailed(message)


def expect_story(events: list[dict[str, Any]], expected: list[str]) -> None:
    got = story(events)
    if got != expected:
        index = next((i for i, (a, b) in enumerate(zip(got, expected)) if a != b), min(len(got), len(expected)))
        raise CheckFailed(
            f"event sequence differs at position {index}: got {got[index : index + 3]}, expected {expected[index : index + 3]}"
        )


def run_scenario(engine: Engine, name: str, speed: float, stop: str, answer: str = "deny") -> list[dict[str, Any]]:
    engine.post("/v1/reset")
    engine.post(f"/v1/scenarios/{name}/run", {"speed": speed, "auto": True, "autoAnswer": answer})
    return engine.events_until(stop)


def no_email(events: list[dict[str, Any]]) -> None:
    for event in events:
        if event["type"] == "alert.raised":
            expect(event["data"]["channel"] in ("IN_APP", "SMS", "NETWORK"), f"an alert used {event['data']['channel']}")


def check_legit(engine: Engine, speed: float) -> str:
    events = run_scenario(engine, "legit", speed, "payment.credited")
    expect_story(events, LEGIT)
    expect(first(events, "risk.scored")["tier"] == "LOW", "the legitimate payment is not LOW")
    routes = {r["routeId"]: r for r in first(events, "norms.checked")["routes"]}
    expect(routes["R4"]["excludedBy"] == "GH_FX_EXPORT_PROCEEDS_NOMINATED_BANK", "R4 is not excluded by Ghana's rule")
    selected = first(events, "route.selected")
    expect(first(events, "payment.credited")["at"] == "supplier_ssx", "the money did not reach the supplier")
    return f"LOW, route {selected['routeId']}, credited at the supplier"


def check_denied(engine: Engine, speed: float) -> str:
    events = run_scenario(engine, "diverted", speed, "payment.stopped", "deny")
    expect_story(events, DENIED)
    risk = first(events, "risk.scored")
    expect(risk["tier"] == "MEDIUM" and 40 <= risk["score"] <= 69, f"diverted is {risk['tier']} {risk['score']}, not MEDIUM 40-69")
    expect(len(first(events, "payment.held")["reasons"]) >= 3, "fewer than three reasons on the alert")
    expect(first(events, "approval.granted")["conditional"] is True, "the approval of a MEDIUM payment is not conditional")
    requested = first(events, "verification.requested")
    expect(requested["simSwapChecked"] and requested["channel"] == "SMS", "the known contact was not checked and texted")
    expect(first(events, "intent.revoked")["reasonCode"] == "SUPPLIER_DENIED", "wrong revocation reason")
    expect(any(e["type"] == "case.ready" for e in events), "no case file")
    no_email(events)
    return f"MEDIUM {risk['score']}, {len(risk['reasons'])} reasons, held, revoked, refunded"


def check_attacks(engine: Engine, payment_id: str) -> str:
    release = engine.post("/v1/attacks/release_revoked", {"paymentId": payment_id})
    expect(release["reverted"] and release["reason"] == "PaymentNotReleasable", f"release of a revoked payment: {release}")
    swap = engine.post("/v1/attacks/swap_beneficiary", {"paymentId": payment_id})
    expect(swap.get("legRejected") == "INTENT_HASH_MISMATCH", f"the adapter did not refuse the changed leg: {swap}")
    expect(swap["reverted"] and swap["reason"] == "CommitmentMismatch", f"deposit of a modified intent: {swap}")
    replay = engine.post("/v1/attacks/replay", {"paymentId": payment_id})
    expect(replay["reverted"] and replay["reason"] in ("InvalidTransition", "NonceUsed"), f"replayed intent: {replay}")
    return f"release → {release['reason']}; swap → {swap['legRejected']} then {swap['reason']}; replay → {replay['reason']}"


def check_confirmed(engine: Engine, speed: float) -> str:
    events = run_scenario(engine, "diverted", speed, "payment.credited", "confirm")
    expect_story(events, CONFIRMED)
    expect(first(events, "verification.recorded")["result"] == "CONFIRMED", "the supplier's confirmation was not recorded")
    return "held, confirmed by the supplier, released, credited"


def check_sim_swap(engine: Engine, speed: float) -> str:
    events = run_scenario(engine, "diverted_simswap", speed, "payment.stopped")
    expect_story(events, SIM_SWAPPED)
    requested = first(events, "verification.requested")
    expect(requested["simSwapRecent"] and requested["channel"] == "ANALYST", "a recently swapped number was texted")
    expect(first(events, "intent.revoked")["reasonCode"] == "ANALYST_DECISION", "wrong revocation reason")
    return "SIM swap on the known contact: nobody texted, the analyst revoked"


def check_proof(engine: Engine, payment_id: str) -> str:
    proof = engine.get(f"/v1/payments/{payment_id}/proof")
    kinds = [signed["type"] for signed in proof["signed"]]
    expect(kinds[:1] == ["PaymentIntent"] and "Revocation" in kinds, f"signed messages: {kinds}")
    expect(all(len(signed["signature"]) == 132 for signed in proof["signed"]), "a signature is not 65 bytes")
    expect(len(proof["log"]) > 0 and proof["logHead"].startswith("0x"), "the decision log is empty")
    previous = None
    for entry in proof["log"]:
        expect(previous is None or entry["seq"] > previous, "log entries are out of order")
        previous = entry["seq"]
    return f"{len(kinds)} signed messages, {len(proof['transactions'])} transactions, {len(proof['log'])} log entries"


def reachable(url: str) -> bool:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/health", timeout=2) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError):
        return False


def spawn_engine() -> tuple[subprocess.Popen[bytes], str]:
    """A temporary engine on a free port, with the current environment (so the flags of .env apply)."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {**os.environ, "JOURNAL_PATH": "off"}
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "sylo.main:app", "--port", str(port), "--log-level", "warning"],
        cwd=ENGINE_DIR,
        env=env,
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise CheckFailed("the temporary engine exited at start-up")
        if reachable(url):
            return process, url
        time.sleep(0.2)
    process.terminate()
    raise CheckFailed("the temporary engine did not answer within 30 s")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default=f"http://localhost:{os.environ.get('ENGINE_PORT') or 8000}")
    parser.add_argument("--speed", type=float, default=20.0)
    parser.add_argument("--timeout", type=float, default=120.0, help="seconds allowed per scenario")
    parser.add_argument("--no-spawn", action="store_true", help="fail instead of starting a temporary engine")
    args = parser.parse_args(argv)

    process: subprocess.Popen[bytes] | None = None
    url = args.url
    try:
        if not reachable(url):
            if args.no_spawn:
                print(f"demo check FAILED: no engine answers at {url} (run `make engine`)", file=sys.stderr)
                return 1
            print(f"no engine at {url}: starting a temporary one")
            process, url = spawn_engine()
        engine = Engine(url, args.timeout)
        mode = engine.get("/health")["mode"]
        flags = f"risk={mode['risk']} chain={mode['chain']} llm={mode['llm']}"
        print(f"engine {url}: {flags} degraded={mode['degraded'] or 'nothing'}")

        diverted = "PAY-2026-0002"
        steps = [
            ("Scene 1  legitimate payment", lambda: check_legit(engine, args.speed)),
            ("Scene 2  diverted, supplier denies", lambda: check_denied(engine, args.speed)),
            ("Scene 2b three attacks", lambda: check_attacks(engine, diverted)),
            ("Proof    typed data, signatures, log", lambda: check_proof(engine, diverted)),
            ("Scene 2  diverted, supplier confirms", lambda: check_confirmed(engine, args.speed)),
            ("Scene 2  SIM swap on the known contact", lambda: check_sim_swap(engine, args.speed)),
        ]
        failures = 0
        for label, step in steps:
            try:
                print(f"  ok    {label}: {step()}")
            except CheckFailed as err:
                failures += 1
                print(f"  FAIL  {label}: {err}")
        engine.post("/v1/reset")
        if failures:
            print(f"demo check FAILED: {failures} of {len(steps)} checks ({flags})", file=sys.stderr)
            return 1
        print(f"demo check OK: {len(steps)} checks ({flags})")
        return 0
    except CheckFailed as err:
        print(f"demo check FAILED: {err}", file=sys.stderr)
        return 1
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
