from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

from sylo_spec import SPEC_DIR

from .sim.generator import SEEDS, generate_dataset

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = SPEC_DIR / "fixtures" / "traffic.jsonl"


def legal_routes() -> list[dict[str, Any]]:
    fixture = SPEC_DIR / "fixtures" / "scene1-legit.jsonl"
    for line in fixture.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event.get("type") == "norms.checked":
            return [
                route
                for route in event["data"]["routes"]
                if route.get("status") == "PASS"
            ]
    raise RuntimeError("scene1 fixture has no legal corridor routes")


def generate_traffic(output: Path = DEFAULT_OUTPUT) -> Path:
    frame = generate_dataset("B", small=False)
    legitimate = frame.loc[frame["label"] == 0].reset_index(drop=True)
    rng = np.random.default_rng(SEEDS["B"] + 2_003_003)
    selected = rng.choice(len(legitimate), size=300, replace=False)
    routes = legal_routes()
    route_indices = rng.integers(0, len(routes), size=300)

    rows: list[dict[str, Any]] = []
    for row_index, route_index in zip(selected, route_indices, strict=True):
        sample = legitimate.iloc[int(row_index)]
        route = routes[int(route_index)]
        rows.append(
            {
                "paymentId": str(sample["payment_id"]),
                "amountEur": round(float(sample["amount_eur"]), 2),
                "routeId": route["routeId"],
                "arcs": [
                    {"from": hop["from"], "to": hop["to"], "kind": hop["kind"]}
                    for hop in route["hops"]
                ],
                "simulated": True,
            }
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Write 300 deterministic legitimate seed-B traffic samples"
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(f"wrote {generate_traffic(args.out)}")


if __name__ == "__main__":
    main()
