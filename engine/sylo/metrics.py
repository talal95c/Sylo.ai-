"""``GET /v1/metrics``: Lane B's evaluation merged with the engine's integrity result (roadmap A2.6).

Measured numbers come from ``ml/reports/metrics.json`` (written by ``make eval``). Until that file
exists the labelled sample of the spec is served, and it says ``sample: true``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sylo_spec import SPEC_DIR

from . import ENGINE_DIR, REPO_DIR

MEASURED_PATH = REPO_DIR / "ml" / "reports" / "metrics.json"
SAMPLE_PATH = SPEC_DIR / "metrics.sample.json"
INTEGRITY_PATH = ENGINE_DIR / "reports" / "integrity.json"


def _read(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def load_metrics(
    measured: Path = MEASURED_PATH, sample: Path = SAMPLE_PATH, integrity: Path = INTEGRITY_PATH
) -> dict[str, Any]:
    data = _read(measured)
    source = "ml/reports/metrics.json"
    if data is None:
        data, source = _read(sample) or {"sample": True, "metrics": {}}, "spec/metrics.sample.json"
        data["sample"] = True  # never let a sample pass for a measurement
    data["source"] = source
    result = _read(integrity)
    if result is not None:
        data["integrity"] = result
        # The diversion rate is measured by the engine's adapters, whatever the source of the other numbers.
        data.setdefault("metrics", {})["diversionRate"] = result.get("diversionRate")
    return data
