import numpy as np
import pandas as pd
import pytest
from sylo_spec.models import TRUSTED_PROVENANCE

from sylo_risk.evasion import (
    PRESERVED_FIELDS,
    SAMPLE_SEED_OFFSET,
    generate_evasion_levels,
)
from sylo_risk.features import raw_from_order
from sylo_risk.sim.generator import SEEDS, generate_dataset, row_to_order_ctx


@pytest.fixture(scope="module")
def seed_b_small():
    return generate_dataset("B", small=True)


@pytest.fixture(scope="module")
def levels(seed_b_small):
    return generate_evasion_levels("B", n=64, source_frame=seed_b_small)


def test_evasion_generation_is_deterministic(seed_b_small):
    first = generate_evasion_levels("B", n=64, source_frame=seed_b_small)
    second = generate_evasion_levels("B", n=64, source_frame=seed_b_small)
    for level in first:
        pd.testing.assert_frame_equal(first[level], second[level])


def test_e0_matches_existing_small_seed_b_t1_draws(seed_b_small, levels):
    source_t1 = seed_b_small.loc[
        (seed_b_small["typology"] == "T1") & (seed_b_small["label"] == 1)
    ]
    rng = np.random.default_rng(SEEDS["B"] + SAMPLE_SEED_OFFSET)
    expected = source_t1.iloc[
        rng.integers(0, len(source_t1), size=len(levels["E0"]))
    ].reset_index(drop=True)
    pd.testing.assert_frame_equal(levels["E0"], expected)


def test_evasion_levels_have_their_observed_field_properties(levels):
    e0, e1, e2, e3 = (levels[name] for name in ("E0", "E1", "E2", "E3"))

    assert e1["provenance"].isin(TRUSTED_PROVENANCE).all()
    for name in ("E1", "E2", "E3"):
        pd.testing.assert_frame_equal(
            levels[name].loc[:, list(PRESERVED_FIELDS)],
            e0.loc[:, list(PRESERVED_FIELDS)],
        )

    assert (e2["account_age_days"] >= 90).all()
    assert (e2["successful_payments"] >= 3).all()
    assert not e2["account_owned_by_payee"].any()
    assert (e2["history_count"] >= 1).all()
    assert (
        e2["last_account_id"]
        == "acc-" + e2["payee_id"].astype(str) + "-nominated"
    ).all()
    assert (e2["account_id"] != e2["last_account_id"]).all()

    assert e3["account_owned_by_payee"].all()
    assert (e3["last_account_id"] == e3["account_id"]).all()
    assert (e3["history_count"] >= 1).all()

    e2_order, e2_context = row_to_order_ctx(e2.iloc[0].to_dict())
    e3_order, e3_context = row_to_order_ctx(e3.iloc[0].to_dict())
    assert e2_context.account_age_hours >= 90 * 24
    assert e2_context.account.successful_payments >= 3
    assert not e2_context.payee.owns(e2_context.account.id)
    assert e2_context.history.last_account_id == e2["last_account_id"].iloc[0]
    assert raw_from_order(e2_order, e2_context)["account_changed_since_last"] == 1.0
    assert e3_context.payee.owns(e3_context.account.id)
    assert e3_context.history.last_account_id == e3_context.account.id
    assert e3_context.history.successful_count >= 1
    assert raw_from_order(e3_order, e3_context)["account_changed_since_last"] == 0.0
