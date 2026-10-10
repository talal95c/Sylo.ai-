"""Evaluate the committed Lane B model across validation and OOD seeds."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from .features import FEATURE_NAMES, features_from_frame
from .sim.generator import generate_dataset


def _calibrate(probabilities: np.ndarray, artifact: dict[str, Any]) -> np.ndarray:
    isotonic = artifact["isotonic"]
    return np.interp(probabilities, isotonic["x"], isotonic["y"])


def _dataset_metrics(
    frame: pd.DataFrame, probabilities: np.ndarray, t_med: float, t_high: float
) -> dict[str, float]:
    labels = frame["label"].to_numpy(dtype=int)
    typology = frame["typology"].astype(str).to_numpy()
    evasive = frame["evasive"].to_numpy(dtype=bool)
    medium = probabilities >= t_med
    high = probabilities >= t_high
    positives = labels == 1
    negatives = labels == 0
    hard_negatives = frame["hard_negative"].to_numpy(dtype=bool) & negatives

    def recall(mask: np.ndarray) -> float:
        return float(np.mean(medium[mask])) if np.any(mask) else 0.0

    return {
        "auc": float(roc_auc_score(labels, probabilities)),
        "fpr_legit_medium_plus": float(np.mean(medium[negatives])),
        "precision_high_plus": float(labels[high].mean()) if np.any(high) else 0.0,
        "recall_medium_plus_all": recall(positives),
        "recall_medium_plus_T1": recall(typology == "T1"),
        "recall_medium_plus_T1_evasive": recall((typology == "T1") & evasive),
        "recall_medium_plus_T2": recall(typology == "T2"),
        "recall_medium_plus_T3": recall(typology == "T3"),
        "recall_medium_plus_T4": recall(typology == "T4"),
        "fpr_hard_negatives_medium_plus": (
            float(np.mean(medium[hard_negatives])) if np.any(hard_negatives) else 0.0
        ),
    }


def _score(
    booster: lgb.Booster, artifact: dict[str, Any], frame: pd.DataFrame
) -> np.ndarray:
    matrix = features_from_frame(frame)
    raw = booster.predict(matrix.loc[:, FEATURE_NAMES])
    return _calibrate(np.asarray(raw, dtype=float), artifact)


def build_report(
    artifact: dict[str, Any],
    model_path: Path,
    small: bool = False,
) -> dict[str, Any]:
    booster = lgb.Booster(model_file=str(model_path))
    thresholds = artifact["thresholds"]
    t_med = float(thresholds["t_med"])
    t_high = float(thresholds["t_high"])
    metrics: dict[str, dict[str, float]] = {}

    for seed in ("A", "B", "C"):
        frame = generate_dataset(seed, small=small)
        if seed == "A":
            frame = frame.loc[frame["day"].between(21, 25)].copy()
        metrics["A-val" if seed == "A" else seed] = _dataset_metrics(
            frame, _score(booster, artifact, frame), t_med, t_high
        )

    gain = booster.feature_importance(importance_type="gain")
    top_features = sorted(
        zip(FEATURE_NAMES, gain), key=lambda item: (-float(item[1]), item[0])
    )[:10]
    return {
        "thresholds": {
            "t_med": t_med,
            "t_high": t_high,
            "high_precision_target_met": bool(
                thresholds.get("precision_target_met", False)
            ),
        },
        "metrics": metrics,
        "top10_gain_importance": [
            {"feature": name, "gain": float(value)} for name, value in top_features
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Report Lane B A/B/C evaluation metrics")
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "models",
    )
    parser.add_argument("--small", action="store_true", help="use 20k-row datasets for a quick check")
    args = parser.parse_args()
    with (args.model_dir / "model.json").open(encoding="utf-8") as handle:
        artifact = json.load(handle)
    result = build_report(
        artifact,
        args.model_dir / artifact["tree_model"],
        small=args.small,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
