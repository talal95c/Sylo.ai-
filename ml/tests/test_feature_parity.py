import numpy as np
import pandas as pd

from sylo_risk.features import FEATURE_NAMES, features_from_frame, raw_from_order
from sylo_risk.model_risk import ModelRisk
from sylo_risk.sim import generate_dataset, row_to_order_ctx


def test_online_features_match_frame_features_across_seed_b_strata():
    frame = generate_dataset("B", small=True)
    frame["parity_stratum"] = frame["typology"].where(
        frame["typology"] != "none",
        np.where(frame["hard_negative"].astype(bool), "hard_negative", "legit"),
    )

    selected = [
        group.sample(n=min(300, len(group)), random_state=index)
        for index, (_, group) in enumerate(
            frame.loc[frame["parity_stratum"].isin(("T1", "T2", "T3", "T4", "hard_negative"))]
            .groupby("parity_stratum", sort=True)
        )
    ]
    sample = pd.concat(selected)
    remaining = 2_000 - len(sample)
    if remaining:
        ordinary_legit = frame.loc[frame["parity_stratum"] == "legit"]
        sample = pd.concat(
            [sample, ordinary_legit.sample(n=remaining, random_state=91)]
        )

    assert len(sample) == 2_000
    assert {"T1", "T2", "T3", "T4", "hard_negative"}.issubset(
        set(sample["parity_stratum"])
    )

    model = ModelRisk()
    expected = features_from_frame(sample).loc[:, FEATURE_NAMES].to_numpy(dtype=float)
    actual = np.asarray(
        [
            [
                raw_from_order(order, context, model._history)[name]
                for name in FEATURE_NAMES
            ]
            for _, row in sample.iterrows()
            for order, context in [row_to_order_ctx(row)]
        ],
        dtype=float,
    )
    matches = np.isclose(actual, expected, rtol=1e-10, atol=1e-10, equal_nan=True)
    mismatched = {
        name: int((~matches[:, index]).sum())
        for index, name in enumerate(FEATURE_NAMES)
        if not matches[:, index].all()
    }
    assert matches.all(), f"online/frame feature mismatches: {mismatched}"


def test_row_context_carries_optional_pair_history_account_id():
    row = generate_dataset("B", small=True).iloc[0].copy()
    _, context = row_to_order_ctx(row.drop(labels=["last_account_id"]))
    assert context.history.last_account_id is None

    row["last_account_id"] = "prior-account"
    _, context = row_to_order_ctx(row)
    assert context.history.last_account_id == "prior-account"
