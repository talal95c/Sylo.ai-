from sylo_risk.clusters import detect, detect_isolated_by_payer_bank
from sylo_risk.geo import GH_REGION_CENTROIDS
from sylo_spec.models import WindowPayment


def _payment(
    payment_id,
    payer_id,
    *,
    account_id="young-account",
    day=1,
    age=30,
    successes=5,
    payer_bank="fr-bank-0",
    bank="mule_bank",
):
    return {
        "payment_id": payment_id,
        "payer_id": payer_id,
        "payee_id": account_id,
        "account_id": account_id,
        "bene_bank_institution_id": bank,
        "account_age_days": age,
        "successful_payments": successes,
        "day": day,
        "payer_bank": payer_bank,
    }


def test_three_payers_to_young_account_detect_one_region_level_cluster():
    payments = [
        _payment("pay-1", "payer-1", day=1),
        _payment("pay-2", "payer-2", day=2),
        _payment("pay-3", "payer-3", day=2),
    ]

    clusters = detect(payments, window_days=2)

    assert len(clusters) == 1
    cluster = clusters[0]
    assert cluster.accounts == ["young-account"]
    assert cluster.linked_payments == ["pay-1", "pay-2", "pay-3"]
    assert cluster.detected_at_day == 2
    assert cluster.region == "GH-TV"
    assert cluster.region_name == "Volta Region (Aflao border)"
    assert cluster.institutions == ["mule_bank"]
    assert (cluster.centroid.lat, cluster.centroid.lng) == GH_REGION_CENTROIDS["Volta"]
    assert {
        (point.lat, point.lng) for point in cluster.points
    } == {GH_REGION_CENTROIDS["Volta"]}


def test_three_window_payments_to_distinct_suspect_accounts_detect_on_third_payment():
    payments = [
        WindowPayment(
            payment_id=f"wave-{index}",
            payer_id=f"payer-{index}",
            account_id=f"account-{index}",
            institution_id="mule_bank",
            amount_eur=100.0,
            at=f"2026-10-11T09:00:0{index}.000Z",
        )
        for index in range(1, 4)
    ]

    clusters = detect(payments, window_days=2)

    assert len(clusters) == 1
    assert clusters[0].accounts == ["account-1", "account-2", "account-3"]
    assert clusters[0].linked_payments == ["wave-1", "wave-2", "wave-3"]
    assert clusters[0].detected_at_day == 0
    assert clusters[0].region == "GH-TV"
    assert clusters[0].region_name == "Volta Region (Aflao border)"
    assert clusters[0].institutions == ["mule_bank"]


def test_probe_and_border_fan_in_below_three_accounts_return_no_cluster():
    assert detect([WindowPayment(
        payment_id="probe",
        account_id="probe-account",
        institution_id="mule_bank",
        amount_eur=1.0,
        at="2026-10-11T09:00:00.000Z",
    )]) == []
    assert detect(
        [
            WindowPayment(
                payment_id=f"wave-{index}",
                payer_id=f"payer-{index}",
                account_id=f"account-{index}",
                institution_id="mule_bank",
                amount_eur=100.0,
                at="2026-10-11T09:00:00.000Z",
            )
            for index in range(1, 3)
        ]
    ) == []


def test_old_popular_supplier_is_not_flagged():
    payments = [
        _payment(
            f"pay-{index}",
            f"payer-{index}",
            age=500,
            successes=80,
            day=1 + index % 2,
        )
        for index in range(8)
    ]

    assert detect(payments, window_days=2) == []


def test_related_suspicious_accounts_merge_by_shared_payer():
    payments = [
        _payment("a1", "payer-1", account_id="account-a"),
        _payment("a2", "payer-2", account_id="account-a"),
        _payment("a3", "payer-shared", account_id="account-a"),
        _payment("b1", "payer-shared", account_id="account-b"),
        _payment("b2", "payer-4", account_id="account-b"),
        _payment("b3", "payer-5", account_id="account-b"),
    ]

    clusters = detect(payments)

    assert len(clusters) == 1
    assert clusters[0].accounts == ["account-a", "account-b"]


def test_isolated_bank_view_requires_three_payers_of_one_bank():
    payments = [
        _payment("a1", "payer-1", payer_bank="bank-a"),
        _payment("a2", "payer-2", payer_bank="bank-a"),
        _payment("b1", "payer-3", payer_bank="bank-b"),
        _payment("b2", "payer-4", payer_bank="bank-b"),
    ]
    assert detect_isolated_by_payer_bank(payments) == []

    payments.append(_payment("a3", "payer-5", payer_bank="bank-a"))
    clusters = detect_isolated_by_payer_bank(payments)
    assert len(clusters) == 1
    assert set(clusters[0].linked_payments) == {"a1", "a2", "a3"}
