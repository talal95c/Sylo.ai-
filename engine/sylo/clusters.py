"""Mule clusters: the engine's stub ``ClusterPort`` and the payments of the mule-wave simulation (roadmap A2.1).

Lane B's detector (``sylo_risk.clusters``, task B2.1) replaces the stub when it is installed. The
stub knows one cluster, read from ``spec/fixtures/cluster-sample.json``, and reports it once three
payments of the window go to its accounts.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any

from sylo_spec import SPEC_DIR
from sylo_spec.models import Cluster, WindowPayment
from sylo_spec.ports import ClusterPort

log = logging.getLogger("sylo.clusters")

SAMPLE_PATH = SPEC_DIR / "fixtures" / "cluster-sample.json"
MIN_LINKED_PAYMENTS = 3
# Lane B's detector is used only if it reads the spec's WindowPayment; otherwise the stub stays.
_PROBE = WindowPayment(payment_id="probe", account_id="probe", institution_id="probe", amount_eur=1.0, at="2026-10-11T00:00:00.000Z")


@lru_cache(maxsize=1)
def cluster_sample() -> dict[str, Any]:
    return json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))


def wave_payments() -> list[dict[str, Any]]:
    """The three synthetic payments of ``POST /v1/sim/mule-wave`` (other payers, accounts of the same cluster)."""
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


def load_cluster_port() -> tuple[ClusterPort, bool]:
    """Lane B's detector when it is installed, otherwise the stub. Returns (port, is_stub)."""
    try:
        from sylo_risk import clusters as lane_b

        detect = getattr(lane_b, "detect", None)
        if detect is None:
            raise ImportError("sylo_risk.clusters has no detect()")
        port = lane_b if isinstance(lane_b, ClusterPort) else _FunctionPort(detect)
        port.detect([_PROBE])
        return port, False
    except Exception as err:
        log.info("cluster detector of Lane B not available (%s); using the sample cluster", err)
        return SampleClusterPort(), True


class _FunctionPort:
    """Wraps a module-level ``detect(window)`` function as a ``ClusterPort``."""

    name = "sylo_risk.clusters"

    def __init__(self, detect: Any) -> None:
        self._detect = detect

    def detect(self, window: list[WindowPayment]) -> list[Cluster]:
        return [Cluster.model_validate(c.model_dump(by_alias=True) if hasattr(c, "model_dump") else c) for c in self._detect(window)]
