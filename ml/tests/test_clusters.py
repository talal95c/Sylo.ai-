from sylo_risk.clusters import detect, detect_isolated_by_payer_bank
from sylo_risk.geo import GH_REGION_CENTROIDS


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
    assert cluster.region == "Volta"
    assert (cluster.centroid.lat, cluster.centroid.lng) == GH_REGION_CENTROIDS["Volta"]
    assert {
        (point.lat, point.lng) for point in cluster.points
    } == {GH_REGION_CENTROIDS["Volta"]}


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


def _window(*rows, at="2026-10-11T09:00:00.000Z"):
    from sylo_spec.models import WindowPayment

    return [
        WindowPayment(payment_id=payment_id, account_id=account, institution_id=bank, amount_eur=20_000.0, at=at)
        for payment_id, account, bank in rows
    ]


WAVE = (
    ("PAY-2026-0101", "acc-aflao-02", "mule_bank"),
    ("PAY-2026-0102", "acc-aflao-04", "mule_bank"),
    ("PAY-2026-0103", "acc-aflao-05", "mule_bank"),
)


def test_engine_window_detector_is_a_cluster_port_and_finds_the_wave():
    from sylo_spec.ports import ClusterPort

    from sylo_risk.clusters import WindowClusterDetector

    detector = WindowClusterDetector()
    assert isinstance(detector, ClusterPort)
    [cluster] = detect(_window(("PAY-2026-0002", "acc-mensah-aflao", "mule_bank"), *WAVE))

    assert cluster.cluster_id == "CL-AFLAO-01"
    assert cluster.institutions == ["mule_bank"], "the breaker scopes on these institutions"
    assert cluster.linked_payments == ["PAY-2026-0002", "PAY-2026-0101", "PAY-2026-0102", "PAY-2026-0103"]
    assert cluster.accounts == ["acc-aflao-02", "acc-aflao-04", "acc-aflao-05", "acc-mensah-aflao"]
    assert cluster.agents == [], "payments do not reveal cash-out agents"
    assert (cluster.region, cluster.region_name) == ("GH-TV", "Volta Region (Aflao border)")
    assert (cluster.centroid.lat, cluster.centroid.lng) == (6.12, 1.19)


def test_engine_window_needs_three_linked_payments():
    assert detect(_window(*WAVE[:2])) == []
    assert detect(_window(("probe", "probe", "probe"))) == []


def test_engine_window_ignores_a_verified_supplier_at_an_inland_bank():
    rows = [(f"P{i}", "acc-ssx-nominated", "bank_gh") for i in range(5)]
    assert detect(_window(*rows)) == []


def test_engine_window_ignores_an_old_busy_account_at_a_border_bank():
    from sylo_spec.models import Account

    from sylo_risk.clusters import WindowClusterDetector

    old = Account(
        id="acc-aflao-shop", holder_name="AFLAO HARDWARE", institution_id="mule_bank",
        account_masked="GH•• 0001", first_seen="2019-01-01", successful_payments=250,
    )
    detector = WindowClusterDetector(accounts={old.id: old})
    rows = [(f"P{i}", "acc-aflao-shop", "mule_bank") for i in range(4)]
    assert detector.detect(_window(*rows)) == []
    assert len(detector.detect(_window(*rows, ("P9", "acc-new", "mule_bank"), ("P8", "acc-new", "mule_bank"), ("P7", "acc-new2", "mule_bank")))) == 1
