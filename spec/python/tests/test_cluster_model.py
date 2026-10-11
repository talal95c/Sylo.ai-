from sylo_spec.models import Cluster, WindowPayment
from sylo_spec.ports import ClusterPort


def test_cluster_model_serializes_roadmap_fields_with_camel_case_aliases():
    cluster = Cluster(
        cluster_id="cluster-1",
        accounts=["account-1"],
        region="Volta",
        centroid={"lat": 6.6, "lng": 0.6},
        points=[{"lat": 6.6, "lng": 0.6, "weight": 1}],
        linked_payments=["payment-1"],
        detected_at_day=3,
    )

    assert cluster.agents == []
    assert cluster.to_json_dict() == {
        "clusterId": "cluster-1",
        "accounts": ["account-1"],
        "agents": [],
        "region": "Volta",
        "regionName": None,
        "institutions": [],
        "centroid": {"lat": 6.6, "lng": 0.6},
        "points": [{"lat": 6.6, "lng": 0.6, "weight": 1.0}],
        "linkedPayments": ["payment-1"],
        "detectedAtDay": 3,
    }


def test_cluster_port_is_a_runtime_protocol():
    class Detector:
        name = "test-detector"

        def detect(self, payments, window_days=2):
            return []

    assert isinstance(Detector(), ClusterPort)


def test_window_payment_adds_optional_payer_and_account_history_with_camel_case_aliases():
    payment = WindowPayment(
        payment_id="payment-1",
        account_id="account-1",
        institution_id="mule_bank",
        amount_eur=100.0,
        at="2026-10-11T09:00:00.000Z",
        payer_id="payer-1",
        account_age_days=12.5,
        successful_payments=2,
    )
    assert payment.to_json_dict() == {
        "paymentId": "payment-1",
        "accountId": "account-1",
        "institutionId": "mule_bank",
        "amountEur": 100.0,
        "at": "2026-10-11T09:00:00.000Z",
        "payerId": "payer-1",
        "accountAgeDays": 12.5,
        "successfulPayments": 2,
    }
    assert WindowPayment(
        payment_id="payment-2",
        account_id="account-2",
        institution_id="mule_bank",
        amount_eur=10.0,
        at="2026-10-11T09:00:00.000Z",
    ).payer_id is None
