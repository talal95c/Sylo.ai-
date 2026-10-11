"""Integrity evaluation (roadmap A2.6, PRD §17.3): a changed or replayed payment must never get through.

    python -m sylo.integrity             # 300 cases, writes engine/reports/integrity.json
    python -m sylo.integrity --cases 30  # quicker
    python -m sylo.integrity --check     # exit 1 if a case got through

Three kinds of cases, each on a freshly committed payment (mock chain, simulated adapters, seed 42):
I1 the beneficiary of a leg or of the intent is substituted; I2 an executed leg and the signed intent
are replayed; I3 the amount is modified. A case is "diverted" when the rail adapter sends the leg or
the chain accepts the call. The expected diversion rate is 0.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import random
import sys
from datetime import datetime, timezone
from typing import Any

from sylo_spec.devkeys import dev_address
from sylo_spec.ports import ChainReverted

from . import ENGINE_DIR
from .config import Settings
from .orchestrator import Orchestrator, PaymentRun, build_orchestrator
from .pacer import VirtualPacer
from .rails import LegRejected

REPORT_PATH = ENGINE_DIR / "reports" / "integrity.json"
START = datetime(2026, 10, 11, 9, 0, 0, tzinfo=timezone.utc)
KINDS = ("I1_substitution", "I2_replay", "I3_modified_amount")
SUBSTITUTIONS = (
    {"creditor_account": "GH•• •••• 6660"},
    {"creditor_name": "ATTACKER HOLDINGS LTD"},
    {"creditor_bank": "momo_gh"},
    {"creditor_account": "GH•• •••• 6660", "creditor_name": "ATTACKER HOLDINGS LTD", "creditor_bank": "mule_bank"},
)


def _adapter_refuses(orchestrator: Orchestrator, run: PaymentRun, leg: Any) -> str | None:
    try:
        orchestrator.rails.adapter(run.decision.route.id).initiate(leg)
    except LegRejected as err:
        return err.reason
    return None


def _chain_reverts(call: Any, *args: Any) -> str | None:
    try:
        call(*args)
    except ChainReverted as err:
        return err.reason
    return None


async def _case(orchestrator: Orchestrator, kind: str, rng: random.Random) -> dict[str, Any]:
    scenario, answer = ("legit", "deny") if rng.random() < 0.5 else ("diverted", "confirm")
    run = await orchestrator.run_to_end(scenario, auto=True, auto_answer=answer)
    assert run.intent is not None and run.intent_signature is not None
    hop = orchestrator._payout_hop(run)
    genuine = orchestrator._leg_message(run, hop, run.hops[hop])
    attacker = dev_address("attacker")

    if kind == "I1_substitution":
        leg = dataclasses.replace(genuine, **rng.choice(SUBSTITUTIONS))
        tampered = run.intent.model_copy(update={"beneficiary": attacker})
        adapter = _adapter_refuses(orchestrator, run, leg)
        chain = _chain_reverts(orchestrator.chain.deposit, tampered, orchestrator.payer_address)
    elif kind == "I2_replay":
        adapter = _adapter_refuses(orchestrator, run, genuine)
        chain = _chain_reverts(orchestrator.chain.commit, run.intent, run.intent_signature)
    else:
        delta = rng.choice((-1, 1)) * rng.randrange(1, 5_000_000_000)
        tampered = run.intent.model_copy(update={"amount": max(1, run.intent.amount + delta)})
        adapter = _adapter_refuses(orchestrator, run, dataclasses.replace(genuine, intent=tampered))
        chain = _chain_reverts(orchestrator.chain.deposit, tampered, orchestrator.payer_address)
    orchestrator.rails.reset()
    return {"kind": kind, "scenario": scenario, "adapter": adapter, "chain": chain}


async def evaluate(cases_per_kind: int = 100, seed: int = 42) -> dict[str, Any]:
    rng = random.Random(seed)
    orchestrator = build_orchestrator(
        Settings(seed=seed), env={}, pacer_factory=lambda speed: VirtualPacer(START, speed)
    )
    by_kind: dict[str, dict[str, Any]] = {}
    diverted = 0
    for kind in KINDS:
        results = [await _case(orchestrator, kind, rng) for _ in range(cases_per_kind)]
        got_through = sum(1 for r in results if r["adapter"] is None or r["chain"] is None)
        diverted += got_through
        by_kind[kind] = {
            "cases": len(results),
            "refusedByAdapter": sum(1 for r in results if r["adapter"] is not None),
            "revertedOnChain": sum(1 for r in results if r["chain"] is not None),
            "adapterReasons": sorted({r["adapter"] for r in results if r["adapter"]}),
            "chainReasons": sorted({r["chain"] for r in results if r["chain"]}),
            "diverted": got_through,
        }
    total = cases_per_kind * len(KINDS)
    return {
        "simulated": True,
        "chain": orchestrator.chain.mode,
        "seed": seed,
        "cases": total,
        "byKind": by_kind,
        "diverted": diverted,
        "diversionRate": diverted / total if total else 0.0,
        "note": "Mock chain and simulated rail adapters. A case is diverted when the adapter sends the leg or the chain accepts the call.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", type=int, default=300, help="total number of cases (a multiple of 3)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--check", action="store_true", help="do not write the report; fail if a case got through")
    args = parser.parse_args(argv)

    report = asyncio.run(evaluate(max(1, args.cases // len(KINDS)), args.seed))
    summary = f"{report['cases']} cases, {report['diverted']} diverted, diversion rate {report['diversionRate']:.4f}"
    if not args.check:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote engine/reports/integrity.json: {summary}")
    else:
        print(f"integrity: {summary}")
    if report["diverted"]:
        print("integrity evaluation FAILED: at least one changed or replayed payment got through", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
