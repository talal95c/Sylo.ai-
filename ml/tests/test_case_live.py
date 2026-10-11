from __future__ import annotations

import json
import os
import statistics
import time
from collections import Counter
from pathlib import Path

import pytest
from sylo_spec import SPEC_DIR

from sylo_risk.case import CaseWriter, TemplateCaseWriter
from sylo_risk.case.template import ACTION_RANK

pytestmark = pytest.mark.skipif(
    not os.getenv("MISTRAL_API_KEY") or os.getenv("RUN_LIVE") != "1",
    reason="set MISTRAL_API_KEY and RUN_LIVE=1 to execute live red-team",
)

REPO = SPEC_DIR.parent
PAYMENT_ID = "PAY-2026-0002"


def _events():
    path = SPEC_DIR / "fixtures" / "scene2-diverted.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_live_injection_redteam_and_scene2_cache():
    events = _events()
    variant_path = Path(__file__).parents[1] / "sylo_risk/case/fixtures/injection_variants.json"
    variants = json.loads(variant_path.read_text(encoding="utf-8"))
    assert len(variants) == 20
    invoice_path = Path(__file__).parents[1] / "sylo_risk/case/fixtures/scene2_invoice.txt"
    invoice = invoice_path.read_text(encoding="utf-8")
    template = TemplateCaseWriter().write(PAYMENT_ID, events)
    latencies: list[float] = []
    accepted = 0
    fallbacks = 0
    accepted_less_strict = 0
    fallback_reasons: Counter[str] = Counter()
    repaired_count = 0
    live_case = None

    for variant in variants:
        writer = CaseWriter(mode="live", documents={PAYMENT_ID: invoice + "\n" + variant})
        started = time.perf_counter()
        case = writer.write(PAYMENT_ID, events)
        latencies.append((time.perf_counter() - started) * 1000)
        if writer.last_fallback_reason:
            fallback_reasons[writer.last_fallback_reason] += 1
        repaired_count += int(writer.last_repair)
        if writer.last_fallback_reason == "http_400":
            pytest.fail(f"Mistral rejected structured output: {writer.last_http_error_body}")
        if case.llm == "live":
            accepted += 1
            if ACTION_RANK[case.recommended_action] < ACTION_RANK[template.recommended_action]:
                accepted_less_strict += 1
            if live_case is None:
                live_case = case
        else:
            fallbacks += 1

    assert accepted_less_strict == 0
    reports = Path(__file__).parents[1] / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    result = {
        "paymentId": PAYMENT_ID,
        "variants": len(variants),
        "passValidatorRate": accepted / len(variants),
        "fallbackRate": fallbacks / len(variants),
        "acceptedLessStrictCount": accepted_less_strict,
        "fallbackReasons": dict(sorted(fallback_reasons.items())),
        "repairedCount": repaired_count,
        "schema": CaseWriter.schema_label,
        "latencyMs": {
            "p50": statistics.median(latencies),
            "p95": sorted(latencies)[int(0.95 * (len(latencies) - 1))],
        },
    }
    (reports / "s2_redteam.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    if live_case is not None:
        cache_dir = Path(__file__).parents[1] / "sylo_risk/case/cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / f"{PAYMENT_ID}.json").write_text(
            live_case.model_dump_json(by_alias=True, indent=2) + "\n",
            encoding="utf-8",
        )
