"""Numpy-only logistic-regression fallback for degraded risk scoring."""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from sylo_spec.models import PaymentOrder, RiskContext, RiskReason, RiskResult, Tier, band

from .features import FEATURE_NAMES, raw_from_order
from .history import HistoryIndex
from .model_risk import _oob_resolvable


FALLBACK_REASON = (
    "The main risk model is unavailable; a simpler backup model is in use."
)


@lru_cache(maxsize=1)
def _load_artifact() -> tuple[dict[str, Any], HistoryIndex]:
    path = Path(__file__).resolve().parents[1] / "models" / "fallback_lr.json"
    artifact = json.loads(path.read_text(encoding="utf-8"))
    return artifact, HistoryIndex(artifact.get("history", {}))


def _score_from_probability(probability: float, t_med: float, t_high: float) -> int:
    probability = float(np.clip(probability, 0.0, 1.0))
    if probability >= t_high:
        if t_high >= 1.0:
            return 70
        return min(89, 70 + int(19 * (probability - t_high) / (1.0 - t_high)))
    if probability >= t_med:
        if t_high <= t_med:
            return 40
        return min(69, 40 + int(29 * (probability - t_med) / (t_high - t_med)))
    if t_med <= 0.0:
        return 0
    return min(39, max(0, int(39 * probability / t_med)))


class FallbackRisk:
    """RiskPort backed by a compact logistic model that does not require LightGBM."""

    def __init__(self) -> None:
        self._artifact, self._history = _load_artifact()
        self.name = str(self._artifact["version"])
        self._feature_order = list(self._artifact["feature_order"])
        self._missing_indicator_indices = [
            self._feature_order.index(name)
            for name in self._artifact["missing_indicator_features"]
        ]

    def score(self, order: PaymentOrder, ctx: RiskContext) -> RiskResult:
        raw = raw_from_order(order, ctx, self._history)
        values = np.asarray(
            [[raw[name] for name in self._feature_order]], dtype=float
        )
        missing = np.isnan(values)
        imputed = np.where(
            missing,
            np.asarray(self._artifact["imputer_statistics"], dtype=float),
            values,
        )
        if self._missing_indicator_indices:
            indicators = missing[:, self._missing_indicator_indices].astype(float)
            imputed = np.concatenate((imputed, indicators), axis=1)
        scaled = (
            imputed - np.asarray(self._artifact["scaler_mean"], dtype=float)
        ) / np.asarray(self._artifact["scaler_scale"], dtype=float)
        logit = float(
            np.dot(
                scaled[0],
                np.asarray(self._artifact["coefficients"], dtype=float),
            )
            + self._artifact["intercept"]
        )
        probability = (
            1.0 / (1.0 + math.exp(-logit))
            if logit >= 0
            else math.exp(logit) / (1.0 + math.exp(logit))
        )
        thresholds = self._artifact["degraded_thresholds"]
        score = _score_from_probability(
            probability, thresholds["t_med"], thresholds["t_high"]
        )
        return RiskResult(
            score=score,
            tier=band(score),
            floor_tier=Tier.LOW,
            rules_fired=[],
            reasons=[RiskReason(ref="M", text=FALLBACK_REASON)],
            model=self.name,
            oob_resolvable=_oob_resolvable(raw, score, ctx.sanctions_hit),
        )
