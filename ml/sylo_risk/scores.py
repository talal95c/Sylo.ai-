from __future__ import annotations

import numpy as np


def probability_to_score(probability: float, t_med: float, t_high: float) -> int:
    probability = float(np.clip(probability, 0.0, 1.0))
    if probability < t_med:
        scaled = probability / t_med * 40 if t_med > 0 else 0
        return min(39, max(0, int(scaled)))
    if probability < t_high:
        width = max(t_high - t_med, 1e-12)
        return min(69, max(40, 40 + int((probability - t_med) / width * 30)))
    # The model alone is deliberately capped below CRITICAL; deterministic controls own that tier.
    width = max(1.0 - t_high, 1e-12)
    return min(89, max(70, 70 + int((probability - t_high) / width * 20)))
