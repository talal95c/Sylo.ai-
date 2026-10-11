import json

import pytest
from jsonschema import Draft202012Validator

from sylo_spec import SPEC_DIR

SCHEMA = json.loads((SPEC_DIR / "events.schema.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA)
FIXTURES = [
    "scene1-legit",
    "scene2-diverted",
    "scene2-deny",
    "scene2-confirm",
    "scene2-simswap",
    "scene2b-release-revoked",
    "scene2b-swap-beneficiary",
    "scene2b-replay",
    "samples-v1",
    "samples-scene3-mule-wave",
    "samples-scene4-guardian",
    "samples-scene5-outage",
]
V1_TYPES = {"approval.required", "leg.rejected", "case.ready", "case.action", "alert.raised"}


def load(name: str) -> list[dict]:
    path = SPEC_DIR / "fixtures" / f"{name}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_schema_is_a_valid_draft_2020_12_schema():
    Draft202012Validator.check_schema(SCHEMA)


@pytest.mark.parametrize("name", FIXTURES)
def test_every_fixture_event_validates(name):
    events = load(name)
    assert events, f"{name} is empty"
    for event in events:
        errors = sorted(VALIDATOR.iter_errors(event), key=lambda e: list(e.path))
        assert not errors, f"{name} seq {event.get('seq')} ({event.get('type')}): {errors[0].message}"


def test_numbering_starts_at_one_and_branches_continue():
    legit, diverted = load("scene1-legit"), load("scene2-diverted")
    deny, confirm, attack = load("scene2-deny"), load("scene2-confirm"), load("scene2b-release-revoked")
    assert legit[0]["seq"] == 1 and diverted[0]["seq"] == 1
    assert deny[0]["seq"] == diverted[-1]["seq"] + 1 == confirm[0]["seq"]
    assert attack[0]["seq"] == deny[-1]["seq"] + 1
    for events in (legit, diverted, deny, confirm, attack):
        seqs = [e["seq"] for e in events]
        assert seqs == list(range(seqs[0], seqs[0] + len(seqs)))
        assert all(e["id"] == f"evt-{e['seq']:06d}" for e in events)


def test_scene2_branches_start_after_the_shared_case_ready():
    diverted = load("scene2-diverted")
    deny, confirm = load("scene2-deny"), load("scene2-confirm")
    case_ready = diverted[-1]
    verification = [event for event in diverted if event["type"] == "verification.requested"]
    assert case_ready["type"] == "case.ready"
    assert verification and verification[-1]["seq"] < case_ready["seq"]
    for branch in (deny, confirm):
        assert branch[0]["seq"] == case_ready["seq"] + 1
        assert not any(event["type"] == "case.ready" for event in branch)
        responses = [
            event
            for event in branch
            if event["type"].startswith("supplier.") or event["type"] == "verification.recorded"
        ]
        assert all(case_ready["seq"] < event["seq"] for event in responses)


def test_every_attack_fixture_continues_the_deny_branch():
    after_deny = load("scene2-deny")[-1]["seq"] + 1
    for name in ("scene2b-release-revoked", "scene2b-swap-beneficiary", "scene2b-replay"):
        events = load(name)
        assert events[0]["seq"] == after_deny and events[0]["type"] == "attack.attempted", name
        assert events[-1]["type"] == "tx.reverted", name


def test_the_v1_sample_shows_every_v1_event_and_every_attack():
    sample = load("samples-v1")
    assert sample[0]["seq"] == 1 and V1_TYPES <= {e["type"] for e in sample}
    assert [e["data"]["attack"] for e in sample if e["type"] == "attack.attempted"] == [
        "release_revoked",
        "swap_beneficiary",
        "replay",
    ]
    asked = [e["data"]["pending"] for e in sample if e["type"] == "approval.required"]
    assert asked == [["claire", "marc"], ["marc"]]


def test_no_alert_in_any_fixture_uses_email():
    for name in FIXTURES:
        for event in load(name):
            if event["type"] == "alert.raised":
                assert event["data"]["channel"] in ("IN_APP", "SMS", "NETWORK"), name


def test_schema_rejects_an_alert_by_email_and_an_unknown_leg_rejection_reason():
    base = {"v": 1, "seq": 1, "id": "evt-000001", "ts": "2026-10-11T09:00:00.000Z", "paymentId": "PAY-1", "simulated": True}
    alert = {**base, "type": "alert.raised", "data": {"audience": "payer", "to": "Claire", "channel": "EMAIL", "text": "x"}}
    assert list(VALIDATOR.iter_errors(alert))
    rejected = {**base, "type": "leg.rejected", "data": {"hop": 3, "rail": "R3", "reason": "BECAUSE"}}
    assert list(VALIDATOR.iter_errors(rejected))
    rejected["data"]["reason"] = "INTENT_HASH_MISMATCH"
    assert not list(VALIDATOR.iter_errors(rejected))


def test_schema_rejects_a_held_event_without_headline():
    bad = {
        "v": 1,
        "seq": 3,
        "id": "evt-000003",
        "ts": "2026-10-11T09:00:12.300Z",
        "type": "payment.held",
        "paymentId": "PAY-2026-0002",
        "simulated": True,
        "data": {"hop": 2, "at": "escrow", "tier": "MEDIUM"},
    }
    assert list(VALIDATOR.iter_errors(bad))


def test_schema_accepts_unknown_extra_fields():
    event = {
        "v": 1,
        "seq": 1,
        "id": "evt-000001",
        "ts": "2026-10-11T09:00:00.000Z",
        "type": "session.reset",
        "paymentId": None,
        "simulated": False,
        "data": {"futureField": 1},
        "futureEnvelopeField": True,
    }
    assert not list(VALIDATOR.iter_errors(event))


def types_of(name: str) -> list[str]:
    return [event["type"] for event in load(name)]


def test_scene_3_sample_goes_from_three_payments_to_a_breaker_and_a_stopped_payment():
    kinds = types_of("samples-scene3-mule-wave")
    assert kinds[:6] == ["scenario.started", "traffic.sample", "traffic.sample", "traffic.sample", "cluster.detected", "breaker.on"]
    assert "payment.held" not in kinds[6:] and kinds[-1] == "case.ready"
    assert "payment.stopped" in kinds[6:]
    scored = next(e["data"] for e in load("samples-scene3-mule-wave") if e["type"] == "risk.scored")
    assert scored["score"] == 77 and scored["tier"] == "CRITICAL"
    assert "R-CB-01" in scored["rulesFired"]
    detected = [e["data"] for e in load("samples-scene3-mule-wave") if e["type"] == "cluster.detected"]
    assert detected and all(event["detector"] == "networkx-mule-clusters" for event in detected)
    stamps = [e["ts"] for e in load("samples-scene3-mule-wave")]
    assert stamps == sorted(stamps), "one timeline, even with two scenarios in the file"


def test_scene_4_sample_shows_the_incident_then_the_refused_release():
    kinds = types_of("samples-scene4-guardian")
    assert kinds.index("payment.held") < kinds.index("guardian.incident") < kinds.index("tx.reverted")
    assert "escrow.released" not in kinds and kinds[-1] == "payment.stopped"


def test_scene_5_sample_reroutes_then_restores_the_rail():
    events = load("samples-scene5-outage")
    kinds = [e["type"] for e in events]
    assert kinds[1] == "rail.down" and kinds[-1] == "rail.up"
    assert next(e["data"]["routeId"] for e in events if e["type"] == "route.selected") == "R1"


def test_the_cluster_sample_is_a_valid_cluster_with_coarse_points():
    from sylo_spec.models import Cluster

    raw = json.loads((SPEC_DIR / "fixtures" / "cluster-sample.json").read_text(encoding="utf-8"))
    cluster = Cluster.model_validate(raw)
    assert len(cluster.accounts) == 6 and len(cluster.agents) == 3 and len(raw["wave"]) == 3
    assert all(abs(point.lat - cluster.centroid.lat) < 0.5 and abs(point.lng - cluster.centroid.lng) < 0.5 for point in cluster.points)
    assert all(round(point.lat, 2) == point.lat and round(point.lng, 2) == point.lng for point in cluster.points)
