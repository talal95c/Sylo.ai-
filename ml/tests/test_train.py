import numpy as np

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
    labels = np.asarray([0] * 50 + [1, 1])
    probabilities = np.asarray([*np.linspace(0.1, 0.49, 49), 0.5, 0.5, 0.5])

    _, t_high, _, precision_high, target_met = _thresholds(probabilities, labels)

    assert t_high == 0.5
    assert precision_high == 2 / 3
    assert not target_met
