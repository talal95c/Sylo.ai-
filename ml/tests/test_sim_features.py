import numpy as np

from sylo_risk.features import FEATURE_NAMES, raw_from_order
from sylo_risk.history import HistoryIndex, history_from_row
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


def test_legitimate_data_has_realistic_overlap_with_risk_signals():
    frame = generate_dataset("A", small=True)
    legit = frame.loc[frame["label"] == 0]

    assert (~legit["account_owned_by_payee"].astype(bool)).mean() >= 0.01
    assert (legit["account_age_days"] < 30).mean() >= 0.01
    assert (legit["name_match"] < 0.85).mean() >= 0.03
    assert legit["provenance"].isin(
        ("invoice_pdf_email", "user_input", "inbound_call")
    ).mean() >= 0.02
    assert legit["bene_bank_border_region"].mean() >= 0.02
    assert (
        (legit["session_country"] != "FR") | legit["new_device_24h"].astype(bool)
    ).mean() >= 0.03

    evasive_t1 = frame.loc[
        (frame["typology"] == "T1") & frame["evasive"]
    ]
    assert evasive_t1["account_owned_by_payee"].mean() >= 0.20


def test_temporal_history_uses_strictly_earlier_days_and_same_day_velocity():
    frame = generate_dataset("A", small=True)
    sample = frame.sample(n=50, random_state=171)
    for index, row in sample.iterrows():
        same_pair = (frame["payer_id"] == row["payer_id"]) & (
            frame["payee_id"] == row["payee_id"]
        )
        earlier = frame.loc[same_pair & (frame["day"] < row["day"]), "amount_eur"]
        same_day_before = frame.loc[
            same_pair & (frame["day"] == row["day"]) & (frame.index < index)
        ]
        assert row["history_count"] == len(earlier)
        assert row["pair_payments_24h"] == len(same_day_before)
        if len(earlier):
            assert row["history_median_amount"] == np.median(earlier)
        else:
            assert np.isnan(row["history_median_amount"])


def test_missing_history_keeps_amount_ratio_missing_and_velocity_defaults_to_zero():
    frame = generate_dataset("A", small=True)
    row = frame.loc[(frame["history_count"] == 0) & (frame["pair_payments_24h"] == 0)].iloc[0]
    order, context = row_to_order_ctx(row)
    raw = raw_from_order(order, context, history_from_row(row))
    index = HistoryIndex({"payer\tpayee": {"count": 3, "median_amount": 42_000}})

    assert np.isnan(raw["amount_vs_history"])
    assert raw["pair_payments_24h"] == 0
    assert index.get("payer", "payee").pair_payments_24h == 0
