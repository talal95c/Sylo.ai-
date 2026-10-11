from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .clusters import detect, detect_isolated_by_payer_bank
from .sim.generator import PAYER_BANKS, SEEDS, generate_dataset

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "reports" / "metrics.json"
BEFORE_BORDER_FAN_IN = {
    "B": {
        "campaignDetectionRate": 1.0,
        "campaignsDetected": 30,
        "campaignCount": 30,
        "paymentsToDetect": {"p50": 7.0, "p90": 10.1},
        "falseClusters": {"legit": 0, "popularSupplier": 0, "youngPopular": 30},
        "isolatedInstitution": {
            "campaignDetectionRate": 1.0,
            "campaignsDetected": 30,
            "paymentsToDetect": {"p50": 11.5, "p90": 16.1},
        },
    },
    "C": {
        "campaignDetectionRate": 1.0,
        "campaignsDetected": 30,
        "campaignCount": 30,
        "paymentsToDetect": {"p50": 7.5, "p90": 10.2},
        "falseClusters": {"legit": 0, "popularSupplier": 0, "youngPopular": 30},
        "isolatedInstitution": {
            "campaignDetectionRate": 29 / 30,
            "campaignsDetected": 29,
            "paymentsToDetect": {"p50": 10.0, "p90": 15.2},
        },
    },
}


def _seed_frame(seed: str) -> pd.DataFrame:
    path = ROOT / "data" / f"payments-{seed}.csv.gz"
    if path.exists():
        return pd.read_csv(path, low_memory=False)
    return generate_dataset(seed, small=False)


def _hard_negatives(seed: str) -> pd.DataFrame:
    rng = np.random.default_rng(SEEDS[seed] + 1_000_003)
    rows: list[dict[str, Any]] = []
    for kind in ("popular_supplier", "young_popular"):
        for account_index in range(30):
            account_id = f"eval-{seed}-{kind}-{account_index:02d}"
            payee_id = f"eval-{seed}-{kind}-supplier-{account_index:02d}"
            if kind == "popular_supplier":
                payer_count = int(rng.integers(4, 16))
                age, successes = 365 + int(rng.integers(0, 365)), 50 + int(rng.integers(0, 50))
            else:
                payer_count = int(rng.integers(3, 7))
                age, successes = int(rng.integers(30, 120)), int(rng.integers(3, 10))
            days = rng.integers(1, 3, size=payer_count)
            for payer_index, day in enumerate(days):
                rows.append(
                    {
                        "payment_id": f"{account_id}-payment-{payer_index:02d}",
                        "payer_id": f"{account_id}-payer-{payer_index:02d}",
                        "payer_bank": str(rng.choice(PAYER_BANKS)),
                        "payee_id": payee_id,
                        "account_id": account_id,
                        "bene_bank_institution_id": "gh-bank-04",
                        "account_age_days": age,
                        "successful_payments": successes,
                        "account_owned_by_payee": True,
                        "day": int(day),
                        "label": 0,
                        "typology": "none",
                        "evasive": False,
                        "hard_negative": True,
                        "hard_negative_type": kind,
                        "cluster_id": "",
                    }
                )
    return pd.DataFrame(rows)


def _campaign_summary(
    frame: pd.DataFrame,
    clusters,
    campaign_ids: set[str],
) -> dict[str, Any]:
    payment_lookup = {
        str(row.payment_id): row
        for row in frame.itertuples(index=False)
    }
    campaign_detection_days: dict[str, int] = {}
    for cluster in clusters:
        linked_by_campaign: dict[str, list[int]] = {}
        for payment_id in cluster.linked_payments:
            row = payment_lookup.get(payment_id)
            if row is None:
                continue
            campaign_id = str(row.cluster_id)
            if campaign_id in campaign_ids:
                linked_by_campaign.setdefault(campaign_id, []).append(int(row.day))
        for campaign_id, linked_days in linked_by_campaign.items():
            detected_day = max(linked_days)
            campaign_detection_days[campaign_id] = min(
                detected_day,
                campaign_detection_days.get(campaign_id, detected_day),
            )

    campaign_counts = (
        frame.loc[frame["cluster_id"].astype(str).isin(campaign_ids)]
        .groupby("cluster_id")
        .size()
        .to_dict()
    )
    payments_to_detect = [
        int(
            frame.loc[
                (frame["cluster_id"].astype(str) == campaign_id)
                & (frame["day"] <= detected_day),
                "payment_id",
            ].count()
        )
        for campaign_id, detected_day in campaign_detection_days.items()
    ]
    return {
        "campaigns": len(campaign_ids),
        "detectedCampaigns": len(campaign_detection_days),
        "campaignDetectionRate": (
            len(campaign_detection_days) / len(campaign_ids) if campaign_ids else 0.0
        ),
        "paymentsToDetect": {
            "p50": float(np.percentile(payments_to_detect, 50))
            if payments_to_detect
            else None,
            "p90": float(np.percentile(payments_to_detect, 90))
            if payments_to_detect
            else None,
        },
        "detectionDayCounts": campaign_detection_days,
        "campaignPaymentCounts": {
            str(key): int(value) for key, value in campaign_counts.items()
        },
    }


def _false_cluster_counts(frame: pd.DataFrame, clusters) -> dict[str, int]:
    lookup = {
        str(row.payment_id): row
        for row in frame.itertuples(index=False)
    }
    counts = {"legit": 0, "popularSupplier": 0, "youngPopular": 0}
    for cluster in clusters:
        linked = [
            lookup[payment_id]
            for payment_id in cluster.linked_payments
            if payment_id in lookup
        ]
        if any(
            int(row.label) == 0
            and not bool(row.hard_negative)
            for row in linked
        ):
            counts["legit"] += 1
        if any(row.hard_negative_type == "popular_supplier" for row in linked):
            counts["popularSupplier"] += 1
        if any(row.hard_negative_type == "young_popular" for row in linked):
            counts["youngPopular"] += 1
    return counts


def evaluate_seed(seed: str) -> dict[str, Any]:
    frame = _seed_frame(seed)
    evaluation = pd.concat([frame, _hard_negatives(seed)], ignore_index=True)
    records = evaluation.to_dict(orient="records")
    campaigns = set(
        frame.loc[frame["typology"] == "T3", "cluster_id"].astype(str).unique()
    )

    started = time.perf_counter()
    clusters = detect(records, window_days=2)
    isolated_clusters = detect_isolated_by_payer_bank(records, window_days=2)
    duration = time.perf_counter() - started
    all_metrics = _campaign_summary(evaluation, clusters, campaigns)
    isolated_metrics = _campaign_summary(evaluation, isolated_clusters, campaigns)
    t3 = frame.loc[frame["typology"] == "T3"]
    fan_in = (
        t3.groupby("cluster_id")["payer_id"].nunique().to_numpy()
        if not t3.empty
        else np.array([])
    )
    return {
        "payments": int(len(frame)),
        "campaignDetectionRate": all_metrics["campaignDetectionRate"],
        "campaignsDetected": all_metrics["detectedCampaigns"],
        "campaignCount": all_metrics["campaigns"],
        "paymentsToDetect": all_metrics["paymentsToDetect"],
        "falseClusters": _false_cluster_counts(evaluation, clusters),
        "isolatedInstitution": {
            "campaignDetectionRate": isolated_metrics["campaignDetectionRate"],
            "campaignsDetected": isolated_metrics["detectedCampaigns"],
            "paymentsToDetect": isolated_metrics["paymentsToDetect"],
        },
        "t3FanInP50": float(np.percentile(fan_in, 50)) if len(fan_in) else None,
        "detectedClusters": len(clusters),
        "isolatedClusters": len(isolated_clusters),
        "runtimeSeconds": duration,
        "hardNegativeAccounts": {
            "popularSupplier": 30,
            "youngPopular": 30,
        },
    }


def main() -> None:
    results = {seed: evaluate_seed(seed) for seed in ("B", "C")}
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    report["clusters"] = {
        "method": "NetworkX payer-account bipartite windows; per-account and border-institution fan-in; age <120 days or <10 successes",
        "beforeBorderFanIn": BEFORE_BORDER_FAN_IN,
        "hardNegatives": "30 old popular suppliers and 30 young popular accounts per seed; evaluation only",
        "hardNegativeSeedFormula": "np.random.default_rng(SEEDS[seed] + 1_000_003)",
        "hardNegativeSeeds": {
            seed: SEEDS[seed] + 1_000_003 for seed in ("B", "C")
        },
        "results": results,
        "limits": [
            "Synthetic T3 accounts concentrate payer fan-in and are easy to detect.",
            "Region points are coarse region centroids, not account locations.",
        ],
    }
    REPORT_PATH.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report["clusters"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
