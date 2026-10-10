import numpy as np

from sylo_risk.train import _thresholds


def test_thresholds_support_saturated_isotonic_probabilities():
    labels = np.asarray([0, 0, 0, 1, 1])
    probabilities = np.asarray([0.0, 0.0, 0.0, 1.0, 1.0])

    t_med, t_high, fpr_medium, precision_high = _thresholds(probabilities, labels)

    assert 0.0 < t_med < t_high == 1.0
    assert fpr_medium == 0.0
    assert precision_high == 1.0
