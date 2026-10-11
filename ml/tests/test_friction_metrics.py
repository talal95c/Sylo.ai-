import numpy as np
import pandas as pd

from sylo_spec.models import Tier

from sylo_risk.evaluate import _evaluate_predictions


def test_action_tier_friction_metrics_include_oob_demotions_and_hard_negatives():
    frame = pd.DataFrame(
        {
            "label": [0, 0, 0, 0, 0, 1],
            "amount_eur": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0],
            "typology": ["none", "none", "none", "none", "none", "T1"],
            "evasive": [False, False, False, False, False, True],
            "hard_negative": [False, True, False, False, True, True],
        }
    )
    tiers = np.asarray(
        [Tier.HIGH, Tier.HIGH, Tier.MEDIUM, Tier.LOW, Tier.HIGH, Tier.CRITICAL],
        dtype=np.int8,
    )
    oob_resolvable = np.asarray([False, True, False, False, False, False])

    metrics = _evaluate_predictions(
        frame,
        np.asarray([5, 10, 40, 0, 70, 100], dtype=np.int16),
        tiers,
        oob_resolvable=oob_resolvable,
        include_ci=False,
    )

    assert metrics["hardBlockRateLegit"] == 0.4
    assert metrics["verificationRateLegit"] == 0.4
    assert metrics["frictionTotalLegit"] == 0.8
    assert metrics["hardBlockRateHardNegatives"] == 0.5
    assert metrics["verificationRateHardNegatives"] == 0.5
    assert metrics["frictionTotalHardNegatives"] == 1.0
