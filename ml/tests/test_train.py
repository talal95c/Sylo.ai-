import numpy as np

from sylo_risk.scores import probability_to_score
from sylo_risk.train import _thresholds


def test_thresholds_support_saturated_isotonic_probabilities():
    labels = np.asarray([0, 0, 0, 1, 1])
    probabilities = np.asarray([0.0, 0.0, 0.0, 1.0, 1.0])

    t_med, t_high, fpr_medium, precision_high, target_met = _thresholds(
        probabilities, labels
    )

    assert 0.0 < t_med < t_high == 1.0
    assert fpr_medium == 0.0
    assert precision_high == 1.0
    assert target_met


def test_thresholds_fall_back_to_highest_precision_when_target_is_unavailable():
    labels = np.asarray([0] * 100 + [1, 1])
    probabilities = np.asarray([*np.linspace(0.1, 0.49, 98), 0.5, 0.8, 0.8, 0.8])

    _, t_high, _, precision_high, target_met = _thresholds(probabilities, labels)

    assert t_high == 0.8
    assert precision_high == 2 / 3
    assert not target_met


def test_score_uses_logit_probability_bands_and_caps_below_critical():
    assert probability_to_score(0.2, 0.2, 0.8) == 40
    assert probability_to_score(0.8, 0.2, 0.8) == 70
    assert probability_to_score(0.0, 0.2, 0.8) == 0
    assert probability_to_score(1.0, 0.2, 0.8) == 89

    scores = [probability_to_score(p, 0.2, 0.8) for p in np.linspace(0.0, 1.0, 101)]
    assert scores == sorted(scores)
    assert set(scores) <= set(range(90))
