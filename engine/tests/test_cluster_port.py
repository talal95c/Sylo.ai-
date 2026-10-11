"""Scene 3 with Lane B's cluster detector behind the engine's ``ClusterPort`` (and the sample as fallback)."""

import pytest

from sylo_spec.models import Cluster, Tier, WindowPayment
from sylo_spec.ports import ClusterPort

from sylo.clusters import DetectorClusterPort, SampleClusterPort, detector_record, load_cluster_port, region_name

from .conftest import events_of, make_orchestrator

AT = "2026-10-11T09:00:00.000Z"


def seen(payment_id, payer, account="acc-young", bank="mule_bank", **kw):
    return WindowPayment(payment_id=payment_id, account_id=account, institution_id=bank, amount_eur=1000.0, at=AT, payer_id=payer, **kw)


def test_a_window_payment_becomes_the_record_the_detector_reads():
    record = detector_record(seen("P1", "payer-1", payee_id="payee-9", account_age_days=9, successful_payments=2))
    assert record == {
        "payment_id": "P1",
        "payer_id": "payer-1",
        "payee_id": "payee-9",
        "account_id": "acc-young",
        "bene_bank_institution_id": "mule_bank",
        "account_age_days": 9,
        "successful_payments": 2,
        "amount_eur": 1000.0,
        "day": 20737,
    }


def test_what_the_engine_does_not_know_counts_as_a_new_account():
    record = detector_record(WindowPayment(payment_id="P1", account_id="a", institution_id="b", amount_eur=1.0, at=AT))
    assert (record["account_age_days"], record["successful_payments"], record["payer_id"], record["payee_id"]) == (0.0, 0, "", "a")


def test_the_adapter_completes_a_cluster_with_its_institutions_and_a_region_name():
    received = []

    def detect(records):
        received.extend(records)
        return [{"clusterId": "c1", "accounts": ["acc-young", "acc-other"], "region": "Volta", "centroid": {"lat": 6.6, "lng": 0.6}}]

    port = DetectorClusterPort(detect, "fake")
    assert isinstance(port, ClusterPort)
    found = port.detect([seen("P1", "p1"), seen("P2", "p2", account="acc-other", bank="bank_gh"), seen("P3", "p3", account="acc-far", bank="x")])
    assert [r["payment_id"] for r in received] == ["P1", "P2", "P3"]
    assert isinstance(found[0], Cluster) and found[0].institutions == ["bank_gh", "mule_bank"]
    assert found[0].region_name == "Volta Region" and region_name("Unknown") == "Unknown region"


def test_the_sample_can_be_forced_and_is_the_fallback():
    port, stub = load_cluster_port("sample")
    assert stub and isinstance(port, SampleClusterPort)
    orchestrator = make_orchestrator(cluster_mode="sample")
    assert orchestrator.cluster_stub and orchestrator.mode()["clusters"] == "sample"
    assert "clusters" not in orchestrator.mode_event()["data"]["degraded"]


def test_auto_mode_reports_a_missing_detector_as_degraded(monkeypatch):
    import builtins

    original_import = builtins.__import__

    def fail_cluster_detector(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "sylo_risk" and fromlist and "clusters" in fromlist:
            raise ImportError("simulated missing Lane B detector")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fail_cluster_detector)
    orchestrator = make_orchestrator(cluster_mode="auto")

    assert orchestrator.cluster_stub
    assert "clusters" in orchestrator.degraded
    mode_event = orchestrator.mode_event()
    assert mode_event["type"] == "system.mode"
    assert "clusters" in mode_event["data"]["degraded"]


def with_detector():
    orchestrator = make_orchestrator(cluster_mode="auto")
    if orchestrator.cluster_stub:
        pytest.skip("Lane B's cluster detector (sylo_risk.clusters) is not installed here")
    return orchestrator


def test_the_detector_needs_three_payers_on_one_young_account():
    port = with_detector().cluster_port
    young = {"account_age_days": 9, "successful_payments": 0}
    assert port.detect([seen("P1", "p1", **young), seen("P2", "p2", **young)]) == []
    assert port.detect([seen("P1", "p1", **young), seen("P2", "p1", **young), seen("P3", "p1", **young)]) == []
    old = {"account_age_days": 900, "successful_payments": 80}
    assert port.detect([seen("P1", "p1", **old), seen("P2", "p2", **old), seen("P3", "p3", **old)]) == []
    found = port.detect([seen("P1", "p1", **young), seen("P2", "p2", **young), seen("P3", "p3", **young)])
    assert len(found) == 1 and found[0].accounts == ["acc-young"] and found[0].linked_payments == ["P1", "P2", "P3"]
    assert found[0].region == "Volta" and found[0].institutions == ["mule_bank"]


async def test_scene_3_with_the_real_detector_proposes_the_breaker_and_holds_the_next_payment(event_validator):
    orchestrator = with_detector()
    assert orchestrator.mode()["clusters"] == "detector"
    await orchestrator.run_wave()
    detected = events_of(orchestrator, "cluster.detected")[0]["data"]
    assert detected["detector"] == "networkx-mule-clusters" and detected["accounts"] == 1
    assert detected["linkedPayments"] == ["PAY-2026-0101", "PAY-2026-0102", "PAY-2026-0103"]
    assert (detected["region"], detected["regionName"], detected["institutions"]) == ("Volta", "Volta Region", ["mule_bank"])
    assert detected["clusterId"].startswith("cluster-") and detected["proposedBreaker"]["breakerId"] == f"CB-{detected['clusterId']}"
    on = events_of(orchestrator, "breaker.on")[0]["data"]
    assert on["scope"]["institutions"] == ["mule_bank"] and on["thresholdsDelta"] == -20

    run = await orchestrator.run_to_end("diverted")
    assert "R-CB-01" in run.risk.rules_fired and run.tier >= Tier.HIGH and run.status == "stopped"
    legit = await orchestrator.run_to_end("legit")
    assert legit.tier == Tier.LOW and legit.status == "credited"  # the nominated bank is outside the breaker's scope
    for event in orchestrator.bus.events:
        errors = list(event_validator.iter_errors(event))
        assert not errors, f"{event['type']}: {errors[0].message}"


async def test_the_payer_own_payments_alone_never_make_a_cluster():
    orchestrator = with_detector()
    await orchestrator.run_to_end("diverted")
    await orchestrator.run_to_end("diverted")
    await orchestrator.run_to_end("legit")
    assert not events_of(orchestrator, "cluster.detected")
