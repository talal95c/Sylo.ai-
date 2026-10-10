import numpy as np

from sylo_risk.features import FEATURE_NAMES, raw_from_order
from sylo_risk.history import history_from_row
from sylo_risk.sim import generate_dataset, row_to_order_ctx


def test_simulator_features_match_engine_object_feature_pipeline():
    frame = generate_dataset("A", small=True)
    sample = frame.sample(n=200, random_state=83)
    for _, row in sample.iterrows():
        order, context = row_to_order_ctx(row)
        actual = raw_from_order(order, context, history_from_row(row))
        expected = row.loc[FEATURE_NAMES].to_numpy(dtype=float)
        np.testing.assert_allclose(
            np.asarray([actual[name] for name in FEATURE_NAMES]),
            expected,
            rtol=1e-10,
            atol=1e-10,
            equal_nan=True,
        )


def test_repeated_seed_is_deterministic():
    first = generate_dataset("B", small=True)
    second = generate_dataset("B", small=True)
    assert first.equals(second)


def test_typology_rates_and_seeded_mule_clusters():
    from_a = generate_dataset("A", small=True)
    from_b = generate_dataset("B", small=True)
    for frame in (from_a, from_b):
        rates = frame["typology"].value_counts(normalize=True)
        assert abs(rates["T1"] - 0.003) < 0.0001
        assert abs(rates["T2"] - 0.002) < 0.0001
        assert abs(rates["T3"] - 0.003) < 0.0001
        assert abs(rates["T4"] - 0.002) < 0.0001
        assert abs(frame["hard_negative"].mean() - 0.03) < 0.0001
        t1 = frame["typology"] == "T1"
        assert abs(frame.loc[t1, "evasive"].mean() - 0.30) < 0.08
    clusters_a = set(from_a.loc[from_a["cluster_id"] != "", "cluster_id"])
    clusters_b = set(from_b.loc[from_b["cluster_id"] != "", "cluster_id"])
    assert clusters_a
    assert clusters_b
    assert clusters_a.isdisjoint(clusters_b)


def test_ood_seed_has_half_evasive_t1_cases():
    frame = generate_dataset("C", small=True)
    t1 = frame["typology"] == "T1"
    assert abs(frame.loc[t1, "evasive"].mean() - 0.50) < 0.08
