from sylo_spec.models import Cluster
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
