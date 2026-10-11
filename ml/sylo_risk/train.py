"""Deterministic LightGBM training, isotonic calibration, and score thresholds."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

from .features import FEATURES, FEATURE_NAMES, MONOTONE_CONSTRAINTS, features_from_frame, to_matrix
from .history import build_history
from .scores import probability_to_score
from .sim.generator import generate_dataset


def _thresholds(
    probabilities: np.ndarray, labels: np.ndarray
) -> tuple[float, float, float, float, bool]:
    legit = labels == 0
    legit_scores = np.sort(probabilities[legit])
    if not len(legit_scores):
        raise ValueError("threshold tuning requires legitimate validation examples")
    tolerated_false_positives = int(np.floor(0.01 * len(legit_scores)))
    boundary_index = len(legit_scores) - tolerated_false_positives - 1
    t_med = float(np.nextafter(legit_scores[boundary_index], np.inf))
    values = np.unique(probabilities)
    candidates = values[values > t_med]
    t_high: float | None = None
    precision_target_met = False
    for value in candidates:
        predicted = probabilities >= value
        precision = float(labels[predicted].mean()) if predicted.any() else 0.0
        if precision >= 0.90:
            t_high = float(value)
            precision_target_met = True
            break
    if t_high is None:
        candidate_precisions: list[tuple[float, float]] = []
        for value in candidates:
            predicted = probabilities >= value
            precision = float(labels[predicted].mean()) if predicted.any() else 0.0
            candidate_precisions.append((precision, float(value)))
        if candidate_precisions:
            _, t_high = max(candidate_precisions, key=lambda result: (result[0], -result[1]))
        else:
            t_high = float(np.nextafter(t_med, np.inf))
    fpr_medium = float(np.mean(probabilities[legit] >= t_med))
    predicted = probabilities >= t_high
    precision_high = float(labels[predicted].mean()) if predicted.any() else 0.0
    return t_med, t_high, fpr_medium, precision_high, precision_target_met


def evaluate(
    probabilities: np.ndarray, frame: pd.DataFrame, t_med: float, t_high: float
) -> dict[str, float]:
    labels = frame["label"].to_numpy(dtype=int)
    typology = frame["typology"].astype(str).to_numpy()
    evasive = frame["evasive"].to_numpy(dtype=bool)
    legit = labels == 0
    med = probabilities >= t_med
    high = probabilities >= t_high
    t1 = typology == "T1"
    return {
        "fpr_legit_medium_plus": float(np.mean(med[legit])),
        "precision_high": float(labels[high].mean()) if high.any() else 0.0,
        "recall_t1_medium_plus": float(np.mean(med[t1])) if t1.any() else 0.0,
        "recall_t1_evasive_medium_plus": float(np.mean(med[t1 & evasive])) if np.any(t1 & evasive) else 0.0,
        "recall_all_medium_plus": float(np.mean(med[labels == 1])) if np.any(labels == 1) else 0.0,
        "t_med": float(t_med),
        "t_high": float(t_high),
    }


def train_model(frame: pd.DataFrame, model_dir: Path | None = None) -> dict[str, Any]:
    if model_dir is None:
        model_dir = Path(__file__).resolve().parents[1] / "models"
    model_dir.mkdir(parents=True, exist_ok=True)

    history = build_history(frame, max_day=20)
    prepared = frame.copy()
    features = features_from_frame(prepared)
    prepared.loc[:, FEATURE_NAMES] = features
    train_mask = prepared["day"] <= 20
    validation_mask = prepared["day"].between(21, 25)
    train_rows = prepared.loc[train_mask]
    validation_rows = prepared.loc[validation_mask]
    if train_rows.empty or validation_rows.empty:
        raise ValueError("training requires seed-A payment rows from days 1–25")

    classifier = lgb.LGBMClassifier(
        objective="binary",
        n_estimators=240,
        learning_rate=0.05,
        num_leaves=15,
        max_depth=-1,
        min_child_samples=35,
        reg_lambda=1.0,
        random_state=20261001,
        n_jobs=1,
        deterministic=True,
        force_col_wise=True,
        monotone_constraints=MONOTONE_CONSTRAINTS,
        verbosity=-1,
    )
    classifier.fit(
        to_matrix(train_rows),
        train_rows["label"].to_numpy(dtype=int),
        feature_name=FEATURE_NAMES,
    )
    raw_validation = classifier.predict_proba(validation_rows[FEATURE_NAMES])[:, 1]
    valid_labels = validation_rows["label"].to_numpy(dtype=int)
    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrated = calibrator.fit_transform(raw_validation, valid_labels)
    t_med, t_high, _, precision_high, precision_target_met = _thresholds(
        raw_validation, valid_labels
    )
    metrics = evaluate(raw_validation, validation_rows, t_med, t_high)
    metrics["precision_high"] = precision_high
    metrics["brier_raw"] = float(np.mean((raw_validation - valid_labels) ** 2))
    metrics["brier_isotonic"] = float(np.mean((calibrated - valid_labels) ** 2))

    version_date = datetime.now(timezone.utc).strftime("%Y%m%d")
    version = f"gbm-{version_date}"
    model_path = model_dir / f"{version}.txt"
    classifier.booster_.save_model(str(model_path))
    artifact = {
        "version": version,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "feature_list": [
            {"name": name, "family": family, "monotone": monotone}
            for name, family, monotone in FEATURES
        ],
        "thresholds": {
            "t_med": t_med,
            "t_high": t_high,
            "precision_target_met": precision_target_met,
        },
        "isotonic": {
            "x": calibrator.X_thresholds_.tolist(),
            "y": calibrator.y_thresholds_.tolist(),
        },
        "history": history.to_dict(),
        "validation_metrics": metrics,
        "validation_rows": int(len(validation_rows)),
        "training_rows": int(len(train_rows)),
        "tree_model": model_path.name,
    }
    with (model_dir / "model.json").open("w", encoding="utf-8") as handle:
        json.dump(artifact, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the calibrated Lane B risk model")
    parser.add_argument("--data", type=Path, help="optional seed-A CSV or CSV.GZ")
    parser.add_argument("--model-dir", type=Path, default=Path(__file__).resolve().parents[1] / "models")
    args = parser.parse_args()
    frame = pd.read_csv(args.data) if args.data else generate_dataset("A")
    artifact = train_model(frame, args.model_dir)
    print(json.dumps({"version": artifact["version"], **artifact["validation_metrics"]}, indent=2))


if __name__ == "__main__":
    main()
