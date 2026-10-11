"""Mule clusters: Lane B's detector behind the spec's ``ClusterPort``, the fallback sample, and the payments
of the mule-wave simulation (roadmap A2.1).

``sylo_risk.clusters.detect`` reads plain records (payer, account, bank, account age, history), so the
adapter builds them from the engine's ``WindowPayment`` and completes each cluster with what only the
engine knows: which institutions hold its accounts, and a region name for people. Without Lane B's
package (or with ``CLUSTER_MODE=sample``) the stub knows one cluster, read from
``spec/fixtures/cluster-sample.json``, and reports it once three payments of the window go to its accounts.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime
from functools import lru_cache
from typing import Any

from sylo_spec import SPEC_DIR
from sylo_spec.models import Cluster, WindowPayment
from sylo_spec.ports import ClusterPort

log = logging.getLogger("sylo.clusters")

SAMPLE_PATH = SPEC_DIR / "fixtures" / "cluster-sample.json"
MIN_LINKED_PAYMENTS = 3
_PROBE = WindowPayment(payment_id="probe", account_id="probe", institution_id="probe", amount_eur=1.0, at="2026-10-11T00:00:00.000Z")


@lru_cache(maxsize=1)
def cluster_sample() -> dict[str, Any]:
    return json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))


def wave_payments() -> list[dict[str, Any]]:
    """The three synthetic payments of ``POST /v1/sim/mule-wave`` (three payers, one young account)."""
    return list(cluster_sample()["wave"])


class SampleClusterPort:
    """Stub detector: one known cluster, found when at least three window payments reach its accounts."""

    name = "cluster-sample"

    def __init__(self, sample: dict[str, Any] | None = None) -> None:
        self._sample = sample or cluster_sample()
        self._accounts = set(self._sample["accounts"])

    def detect(self, window: list[WindowPayment]) -> list[Cluster]:
        linked = [payment.payment_id for payment in window if payment.account_id in self._accounts]
        if len(linked) < MIN_LINKED_PAYMENTS:
            return []
        return [Cluster.model_validate({**self._sample, "linkedPayments": linked})]


def detector_record(payment: WindowPayment) -> dict[str, Any]:
    """One window payment as Lane B's detector reads it. What the engine does not know is given its
    stricter value: an account of unknown age counts as new, with no payment history."""
    at = datetime.fromisoformat(payment.at.replace("Z", "+00:00"))
    return {
        "payment_id": payment.payment_id,
        "payer_id": payment.payer_id or "",
        "payee_id": payment.payee_id or payment.account_id,
        "account_id": payment.account_id,
        "bene_bank_institution_id": payment.institution_id,
        "account_age_days": payment.account_age_days if payment.account_age_days is not None else 0.0,
        "successful_payments": payment.successful_payments if payment.successful_payments is not None else 0,
        "amount_eur": payment.amount_eur,
        "day": int(at.timestamp() // 86_400),
    }


def region_name(region: str) -> str:
    return "Unknown region" if not region or region == "Unknown" else f"{region} Region"


class DetectorClusterPort:
    """Lane B's ``detect(records)`` as a ``ClusterPort``."""

    def __init__(self, detect: Callable[[list[dict[str, Any]]], list[Any]], name: str = "sylo_risk.clusters") -> None:
        self._detect = detect
        self.name = name

    def detect(self, window: list[WindowPayment]) -> list[Cluster]:
        bank_of = {payment.account_id: payment.institution_id for payment in window}
        clusters: list[Cluster] = []
        for found in self._detect([detector_record(payment) for payment in window]):
            cluster = Cluster.model_validate(found.model_dump(by_alias=True) if hasattr(found, "model_dump") else found)
            institutions = sorted({bank_of[account] for account in cluster.accounts if account in bank_of})
            clusters.append(
                cluster.model_copy(
                    update={
                        "institutions": cluster.institutions or institutions,
                        "region_name": cluster.region_name or region_name(cluster.region),
                    }
                )
            )
        return clusters


def load_cluster_port(mode: str = "auto") -> tuple[ClusterPort, bool]:
    """Lane B's detector when it is installed (``auto``), otherwise the sample. Returns (port, is_stub)."""
    if mode == "sample":
        return SampleClusterPort(), True
    try:
        from sylo_risk import clusters as lane_b

        detect = getattr(lane_b, "detect", None)
        if detect is None:
            raise ImportError("sylo_risk.clusters has no detect()")
        name = getattr(getattr(lane_b, "NetworkXClusterDetector", None), "name", "sylo_risk.clusters")
        port = DetectorClusterPort(detect, name)
        port.detect([_PROBE])
        return port, False
    except Exception as err:
        log.warning("cluster detector of Lane B not available (%s); using the sample cluster", err)
        return SampleClusterPort(), True
