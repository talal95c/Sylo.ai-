"""Integrity evaluation and the metrics endpoint (roadmap A2.6)."""

import json

from jsonschema import Draft202012Validator

from sylo_spec import SPEC_DIR

from sylo import integrity
from sylo.metrics import load_metrics


async def test_no_changed_or_replayed_payment_gets_through():
    report = await integrity.evaluate(cases_per_kind=4, seed=7)
    assert (report["cases"], report["diverted"], report["diversionRate"]) == (16, 0, 0.0)
    assert report["simulated"] is True and report["chain"] == "mock"
    for kind in integrity.KINDS:
        result = report["byKind"][kind]
        assert result["refusedByAdapter"] == result["revertedOnChain"] == result["cases"] == 4 and result["diverted"] == 0
    assert report["byKind"]["I1_substitution"]["adapterReasons"] == ["INTENT_HASH_MISMATCH"]
    assert report["byKind"]["I1_substitution"]["chainReasons"] == ["CommitmentMismatch"]
    assert report["byKind"]["I2_replay"]["adapterReasons"] == ["NONCE_USED"]
    assert report["byKind"]["I2_replay"]["chainReasons"] == ["InvalidTransition"]
    assert report["byKind"]["I3_modified_amount"]["adapterReasons"] == ["INTENT_HASH_MISMATCH"]
    assert report["byKind"]["I4_tampered_leg"]["adapterReasons"] == ["INTENT_HASH_MISMATCH"]


async def test_the_evaluation_is_reproducible():
    assert await integrity.evaluate(cases_per_kind=2, seed=3) == await integrity.evaluate(cases_per_kind=2, seed=3)


def test_the_committed_report_says_zero_diversions_over_400_cases():
    report = json.loads(integrity.REPORT_PATH.read_text(encoding="utf-8"))
    assert report["cases"] == 400 and report["diverted"] == 0 and report["diversionRate"] == 0.0


def test_metrics_serve_the_labelled_sample_until_measured_numbers_exist(tmp_path):
    schema = Draft202012Validator(json.loads((SPEC_DIR / "metrics.schema.json").read_text(encoding="utf-8")))
    missing = tmp_path / "missing.json"
    sample = load_metrics(measured=missing, integrity=missing)
    assert sample["sample"] is True and sample["source"] == "spec/metrics.sample.json" and "integrity" not in sample
    assert not list(schema.iter_errors(sample))

    result = tmp_path / "integrity.json"
    result.write_text(json.dumps({"cases": 300, "diverted": 0, "diversionRate": 0.0, "simulated": True}), encoding="utf-8")
    merged = load_metrics(measured=missing, integrity=result)
    assert merged["integrity"]["cases"] == 300 and merged["metrics"]["diversionRate"] == 0.0 and merged["sample"] is True

    measured = tmp_path / "metrics.json"
    measured.write_text(json.dumps({**sample, "sample": False, "modelVersion": "gbm-test"}), encoding="utf-8")
    real = load_metrics(measured=measured, integrity=result)
    assert real["sample"] is False and real["source"] == "ml/reports/metrics.json" and real["modelVersion"] == "gbm-test"

    measured.write_text("not json", encoding="utf-8")
    assert load_metrics(measured=measured, integrity=missing)["sample"] is True, "an unreadable file never passes for a measurement"
