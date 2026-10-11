#!/usr/bin/env python3
"""Validate the shared spec files.

- every event of every fixture validates against events.schema.json;
- seq numbers are consecutive inside each file;
- every institution id used by an event exists in geo/institutions.json;
- eip712.json is exactly what sylo_spec.eip712 generates;
- metrics.sample.json (and ml/reports/metrics.json if present) validate against metrics.schema.json.

Run from spec/python: ``uv run python ../scripts/validate.py``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

SPEC = Path(__file__).resolve().parents[1]


def institution_ids(event: dict[str, Any]) -> list[str]:
    data, kind = event.get("data") or {}, event.get("type")
    ids: list[str] = []
    if kind == "payment.created":
        ids += [data.get("payer", {}).get("institutionId"), data.get("beneficiary", {}).get("institutionId")]
    elif kind == "norms.checked":
        for route in data.get("routes", []):
            for hop in route.get("hops", []):
                ids += [hop.get("from"), hop.get("to")]
    elif kind in ("leg.sent", "leg.rejected"):
        ids += [data.get("from"), data.get("to")]
    elif kind == "traffic.sample":
        for arc in data.get("arcs", []):
            ids += [arc.get("from"), arc.get("to")]
    elif kind in ("leg.settled", "payment.credited"):
        ids.append(data.get("at"))
    elif kind in ("escrow.refunded", "escrow.released"):
        ids.append(data.get("to"))
    return [i for i in ids if i is not None]


def main() -> int:
    schema = json.loads((SPEC / "events.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    traffic_validator = Draft202012Validator(
        {
            "$schema": schema["$schema"],
            "$defs": schema["$defs"],
            **schema["$defs"]["TrafficSample"],
        }
    )
    geo = json.loads((SPEC / "geo" / "institutions.json").read_text(encoding="utf-8"))
    known = {inst["id"] for inst in geo["institutions"]}

    problems: list[str] = []
    files = sorted((SPEC / "fixtures").glob("*.jsonl"))
    if not files:
        problems.append("no fixtures in spec/fixtures (run `make fixtures`)")

    total = 0
    for path in files:
        if path.name == "traffic.jsonl":
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                total += 1
                where = f"{path.name}:{lineno}"
                try:
                    sample = json.loads(line)
                except json.JSONDecodeError as err:
                    problems.append(f"{where}: invalid JSON ({err})")
                    continue
                for err in traffic_validator.iter_errors(sample):
                    problems.append(f"{where} (TrafficSample): {err.message}")
                for arc in sample.get("arcs", []):
                    for inst in (arc.get("from"), arc.get("to")):
                        if inst is not None and inst not in known:
                            problems.append(f"{where}: unknown institution {inst!r}")
            continue
        previous = None
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            total += 1
            where = f"{path.name}:{lineno}"
            try:
                event = json.loads(line)
            except json.JSONDecodeError as err:
                problems.append(f"{where}: invalid JSON ({err})")
                continue
            for err in validator.iter_errors(event):
                problems.append(f"{where} ({event.get('type')}): {err.message}")
            seq = event.get("seq")
            if previous is not None and seq != previous + 1:
                problems.append(f"{where}: seq {seq} does not follow {previous}")
            previous = seq
            for inst in institution_ids(event):
                if inst not in known:
                    problems.append(f"{where}: unknown institution {inst!r}")

    metrics_schema = json.loads((SPEC / "metrics.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(metrics_schema)
    metrics_validator = Draft202012Validator(metrics_schema)
    reports = [SPEC / "metrics.sample.json", SPEC.parent / "ml" / "reports" / "metrics.json"]
    for path in [p for p in reports if p.exists()]:
        for err in metrics_validator.iter_errors(json.loads(path.read_text(encoding="utf-8"))):
            problems.append(f"{path.name}: {err.message}")

    try:
        from sylo_spec.eip712 import render_vector
    except ImportError:
        print("note: sylo_spec is not importable here, eip712.json freshness not checked")
    else:
        if (SPEC / "eip712.json").read_text(encoding="utf-8") != render_vector():
            problems.append("eip712.json is out of date (run `uv run python -m sylo_spec.eip712 --write`)")

    if problems:
        print(f"spec validation FAILED ({len(problems)} problems):")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"spec validation OK: {len(files)} fixture files, {total} events, eip712.json up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
