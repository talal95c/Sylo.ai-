from __future__ import annotations

import numpy as np


def probability_to_score(probability: float, t_med: float, t_high: float) -> int:
    epsilon = 1e-12
    probability = float(np.clip(probability, 0.0, 1.0))

    def logit(value: float) -> float:
        value = float(np.clip(value, epsilon, 1.0 - epsilon))
        return float(np.log(value) - np.log1p(-value))

    if probability < t_med and t_med <= epsilon:
        return 0
    score_probability = logit(probability)
    medium_boundary = logit(t_med)
    high_boundary = logit(t_high)
    if probability < t_med:
        lower_boundary = logit(epsilon)
        scaled = (score_probability - lower_boundary) / (medium_boundary - lower_boundary)
        return min(39, max(0, int(scaled * 40)))
    if probability < t_high:
        scaled = (score_probability - medium_boundary) / (high_boundary - medium_boundary)
        return min(69, max(40, 40 + int(scaled * 30)))
    # The model alone is deliberately capped below CRITICAL; deterministic controls own that tier.
    upper_boundary = logit(1.0 - epsilon)
    scaled = (score_probability - high_boundary) / (upper_boundary - high_boundary)
    return min(89, max(70, 70 + int(scaled * 20)))
