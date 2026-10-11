import json

from jsonschema import Draft202012Validator

from sylo_spec import SPEC_DIR


def test_traffic_fixture_contains_300_valid_simulated_samples():
    schema = json.loads((SPEC_DIR / "events.schema.json").read_text(encoding="utf-8"))
    traffic_schema = {
        "$schema": schema["$schema"],
        "$defs": schema["$defs"],
        **schema["$defs"]["TrafficSample"],
    }
    validator = Draft202012Validator(traffic_schema)
    rows = [
        json.loads(line)
        for line in (SPEC_DIR / "fixtures" / "traffic.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]

    assert len(rows) == 300
    for row in rows:
        assert {"paymentId", "amountEur", "routeId", "arcs", "simulated"} <= row.keys()
        assert row["simulated"] is True
        validator.validate(row)
