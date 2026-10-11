import numpy as np
import pandas as pd
from sylo_spec.models import PairHistory
from sylo_spec.scenarios import golden_case

from sylo_risk.features import FEATURES, FEATURE_NAMES, raw_from_order
from sylo_risk.history import HistoryIndex, build_history, history_from_row
from sylo_risk.sim import generate_dataset, row_to_order_ctx


def test_account_change_is_a_positive_monotone_business_feature():
    assert ("account_changed_since_last", "B", 1) in FEATURES


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


def test_new_legitimate_supplier_profiles_overlap_with_fraud_profiles():
    frame = generate_dataset("A", small=True)
    legit = frame.loc[frame["label"] == 0]
    changes = legit.loc[legit["hard_negative_type"] == "bank_change"]
    young = legit.loc[legit["legit_young_small_supplier"]]

    assert abs(len(changes) / len(legit) - 0.01) < 0.002
    assert changes["history_count"].mean() > 0.9
    assert changes["account_age_days"].between(5, 400).all()
    assert changes["successful_payments"].between(0, 3).all()
    assert abs(changes["account_owned_by_payee"].mean() - 0.5) < 0.08
    assert abs(changes["nominated_for_exports"].mean() - 0.3) < 0.08
    assert (changes["name_match"] >= 0.85).all()
    assert abs((changes["sender_domain"] == changes["known_domain"]).mean() - 0.9) < 0.08
    assert abs(changes["bene_bank_border_region"].mean() - 0.05) < 0.04

    assert abs(len(young) / len(legit) - 0.03) < 0.002
    assert young["account_owned_by_payee"].all()
    assert young["account_age_days"].between(10, 200).all()
    assert young["successful_payments"].between(0, 6).all()


def test_seed_c_keeps_structuring_and_declared_splits_below_cap():
    frame = generate_dataset("C", small=True)
    t4 = frame.loc[frame["typology"] == "T4", "amount_eur"]
    declared_split = frame.loc[frame["declared_split"].astype(bool), "amount_eur"]

    assert t4.between(9_000, 10_000, inclusive="left").all()
    assert declared_split.between(9_000, 10_000, inclusive="left").all()


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
        temporal_before = frame.loc[
            same_pair
            & (
                (frame["day"] < row["day"])
                | ((frame["day"] == row["day"]) & (frame.index < index))
            )
        ]
        assert row["history_count"] == len(earlier)
        assert row["pair_payments_24h"] == len(same_day_before)
        if len(earlier):
            assert row["history_median_amount"] == np.median(earlier)
        else:
            assert np.isnan(row["history_median_amount"])
        if temporal_before.empty:
            assert pd.isna(row["last_account_id"])
        else:
            previous = temporal_before.assign(
                _row_order=temporal_before.index
            ).sort_values(["day", "_row_order"]).iloc[-1]
            assert row["last_account_id"] == previous["account_id"]


def test_missing_history_keeps_amount_ratio_missing_and_velocity_defaults_to_zero():
    frame = generate_dataset("A", small=True)
    row = frame.loc[(frame["history_count"] == 0) & (frame["pair_payments_24h"] == 0)].iloc[0]
    order, context = row_to_order_ctx(row)
    raw = raw_from_order(order, context, history_from_row(row))
    index = HistoryIndex({"payer\tpayee": {"count": 3, "median_amount": 42_000}})

    assert np.isnan(raw["amount_vs_history"])
    assert raw["pair_payments_24h"] == 0
    assert index.get("payer", "payee").pair_payments_24h == 0


def test_account_change_feature_uses_context_history_index_or_established_proxy():
    order, context = golden_case("legit")
    assert context.account is not None

    changed_context = context.model_copy(
        update={
            "history": PairHistory(
                median_amount_eur=85_000.0,
                last_account_id="previous-account",
            )
        }
    )
    unchanged_context = context.model_copy(
        update={
            "history": PairHistory(
                median_amount_eur=85_000.0,
                last_account_id=context.account.id,
            )
        }
    )
    no_prior_context = context.model_copy(
        update={"history": PairHistory(last_account_id=None)}
    )
    no_history_context = context.model_copy(update={"history": None})
    pair_key = HistoryIndex.key(order.debtor.id, order.payee_id)
    history = HistoryIndex(
        {
            pair_key: {
                "count": 1,
                "median_amount": 85_000.0,
                "last_account_id": "previous-account",
            }
        }
    )

    assert raw_from_order(order, changed_context)["account_changed_since_last"] == 1.0
    assert raw_from_order(order, unchanged_context)["account_changed_since_last"] == 0.0
    assert raw_from_order(order, no_prior_context)["account_changed_since_last"] == 0.0
    assert (
        raw_from_order(order, no_history_context, history)["account_changed_since_last"]
        == 1.0
    )
    assert (
        raw_from_order(order, no_history_context, HistoryIndex({}))[
            "account_changed_since_last"
        ]
        == 0.0
    )

    diverted_order, diverted_context = golden_case("diverted")
    diverted_context = diverted_context.model_copy(update={"history": None})
    assert (
        raw_from_order(diverted_order, diverted_context, HistoryIndex({}))[
            "account_changed_since_last"
        ]
        == 1.0
    )


def test_history_index_persists_latest_pair_account_in_temporal_order():
    frame = pd.DataFrame(
        {
            "payer_id": ["payer", "payer", "payer", "payer"],
            "payee_id": ["payee", "payee", "payee", "payee"],
            "day": [2, 1, 2, 1],
            "amount_eur": [20.0, 10.0, 30.0, 15.0],
            "account_id": [
                "same-day-first",
                "day-one-last",
                "same-day-last",
                "day-one-first",
            ],
        }
    )
    built = build_history(frame)
    entry = built.get("payer", "payee")
    assert entry is not None
    assert entry.last_account_id == "same-day-last"
    assert (
        built.to_dict()[HistoryIndex.key("payer", "payee")]["last_account_id"]
        == "same-day-last"
    )

    row_history = history_from_row(
        {
            "payer_id": "payer",
            "payee_id": "payee",
            "history_count": 1,
            "history_median_amount": 15.0,
            "pair_payments_24h": 0,
            "last_account_id": "prior-account",
        }
    )
    assert (
        row_history[HistoryIndex.key("payer", "payee")]["last_account_id"]
        == "prior-account"
    )
