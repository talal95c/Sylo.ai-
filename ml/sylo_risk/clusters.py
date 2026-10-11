from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any

import networkx as nx

from sylo_spec.models import Cluster, ClusterCentroid, ClusterPoint

from .geo import GH_REGION_CENTROIDS, institution_geography


@dataclass
class _ClusterState:
    cluster_id: str
    detected_at_day: int
    accounts: set[str] = field(default_factory=set)
    payments: dict[str, Mapping[str, Any]] = field(default_factory=dict)
    regions: dict[str, str] = field(default_factory=dict)


def _region(record: Mapping[str, Any]) -> str:
    geography = institution_geography(
        str(record.get("bene_bank_institution_id") or "") or None
    )
    if geography.known and geography.region:
        return geography.region
    holder_geography = institution_geography(
        str(record.get("supplier_institution_id") or "") or None
    )
    if holder_geography.known and holder_geography.region:
        return holder_geography.region
    return "Unknown"


def _cluster_id(accounts: set[str]) -> str:
    identity = "\0".join(sorted(accounts))
    return f"cluster-{sha256(identity.encode('utf-8')).hexdigest()[:12]}"


def _join_groups(graph: nx.Graph, groups: Mapping[Any, set[str]]) -> None:
    for accounts in groups.values():
        ordered = sorted(accounts)
        if len(ordered) > 1:
            graph.add_edges_from((ordered[0], account) for account in ordered[1:])


class NetworkXClusterDetector:
    name = "networkx-mule-clusters"

    def detect(
        self,
        payments: list[Mapping[str, Any]],
        window_days: int = 2,
    ) -> list[Cluster]:
        if window_days < 1:
            raise ValueError("window_days must be positive")

        by_day: dict[int, list[tuple[int, Mapping[str, Any]]]] = defaultdict(list)
        for index, payment in enumerate(payments):
            by_day[int(payment.get("day", 0))].append((index, payment))

        clusters: dict[str, _ClusterState] = {}
        account_cluster: dict[str, str] = {}
        for day in sorted(by_day):
            window = [
                (index, payment)
                for window_day in sorted(by_day)
                if day - window_days + 1 <= window_day <= day
                for index, payment in by_day[window_day]
            ]
            payer_account = nx.Graph()
            account_records: dict[str, list[tuple[int, Mapping[str, Any]]]] = defaultdict(list)
            for index, payment in window:
                payer_id = str(payment.get("payer_id") or "")
                account_id = str(payment.get("account_id") or "")
                if not payer_id or not account_id:
                    continue
                payer_node = ("payer", payer_id)
                account_node = ("account", account_id)
                payer_account.add_node(payer_node, bipartite=0)
                payer_account.add_node(account_node, bipartite=1)
                payer_account.add_edge(payer_node, account_node)
                account_records[account_id].append((index, payment))

            candidates: dict[str, list[tuple[int, Mapping[str, Any]]]] = {}
            for account_id, records in account_records.items():
                account_node = ("account", account_id)
                payers = {
                    node[1]
                    for node in payer_account.neighbors(account_node)
                    if node[0] == "payer"
                }
                latest = max(
                    records,
                    key=lambda item: (int(item[1].get("day", 0)), item[0]),
                )[1]
                try:
                    age = float(latest.get("account_age_days", 0))
                    successes = int(latest.get("successful_payments", 0))
                except (TypeError, ValueError):
                    continue
                if len(payers) >= 3 and (age < 120 or successes < 10):
                    candidates[account_id] = records

            if not candidates:
                continue

            linked = nx.Graph()
            linked.add_nodes_from(candidates)
            payer_groups: dict[str, set[str]] = defaultdict(set)
            border_bank_groups: dict[str, set[str]] = defaultdict(set)
            border_holder_groups: dict[str, set[str]] = defaultdict(set)
            for account_id, records in candidates.items():
                for _, payment in records:
                    payer = str(payment.get("payer_id") or "")
                    if payer:
                        payer_groups[payer].add(account_id)
                    bank_id = str(payment.get("bene_bank_institution_id") or "")
                    geography = institution_geography(bank_id or None)
                    if geography.known and geography.border and bank_id:
                        border_bank_groups[bank_id].add(account_id)
                        holder_id = str(
                            payment.get("holder_id") or payment.get("payee_id") or ""
                        )
                        if holder_id:
                            border_holder_groups[holder_id].add(account_id)
            _join_groups(linked, payer_groups)
            _join_groups(linked, border_bank_groups)
            _join_groups(linked, border_holder_groups)

            for component in nx.connected_components(linked):
                accounts = set(component)
                existing = {
                    account_cluster[account]
                    for account in accounts
                    if account in account_cluster
                }
                if existing:
                    state_id = min(
                        existing,
                        key=lambda value: clusters[value].detected_at_day,
                    )
                    state = clusters[state_id]
                    for other_id in existing - {state_id}:
                        other = clusters.pop(other_id)
                        state.accounts.update(other.accounts)
                        state.payments.update(other.payments)
                        state.regions.update(other.regions)
                        for account in other.accounts:
                            account_cluster[account] = state_id
                else:
                    state_id = _cluster_id(accounts)
                    state = _ClusterState(state_id, day)
                    clusters[state_id] = state
                state.detected_at_day = min(state.detected_at_day, day)
                new_accounts = accounts - state.accounts
                if new_accounts:
                    for account in new_accounts:
                        account_cluster[account] = state_id
                        records = candidates[account]
                        state.regions[account] = _region(
                            max(
                                records,
                                key=lambda item: (
                                    int(item[1].get("day", 0)),
                                    item[0],
                                ),
                            )[1]
                        )
                        state.payments.update(
                            {
                                str(record.get("payment_id") or f"row-{index}"): record
                                for index, record in records
                            }
                        )
                    state.accounts.update(new_accounts)

        output: list[Cluster] = []
        for state in sorted(
            clusters.values(),
            key=lambda item: (item.detected_at_day, item.cluster_id),
        ):
            region_counts = Counter(state.regions.values())
            known_regions = {
                region: count
                for region, count in region_counts.items()
                if region in GH_REGION_CENTROIDS
            }
            if known_regions:
                region = min(
                    known_regions,
                    key=lambda value: (-known_regions[value], value),
                )
                lat, lng = GH_REGION_CENTROIDS[region]
                points = [
                    ClusterPoint(
                        lat=GH_REGION_CENTROIDS[point_region][0],
                        lng=GH_REGION_CENTROIDS[point_region][1],
                        weight=float(weight),
                    )
                    for point_region, weight in sorted(known_regions.items())
                ]
            else:
                region = "Unknown"
                lat, lng = 0.0, 0.0
                points = []
            output.append(
                Cluster(
                    cluster_id=state.cluster_id,
                    accounts=sorted(state.accounts),
                    agents=[],
                    region=region,
                    centroid=ClusterCentroid(lat=lat, lng=lng),
                    points=points,
                    linked_payments=sorted(state.payments),
                    detected_at_day=state.detected_at_day,
                )
            )
        return output


def detect(
    payments: Sequence[Mapping[str, Any]],
    window_days: int = 2,
) -> list[Cluster]:
    """Detect mule clusters from simulator or engine record rows."""
    return NetworkXClusterDetector().detect(list(payments), window_days)


def detect_isolated_by_payer_bank(
    payments: list[Mapping[str, Any]],
    window_days: int = 2,
) -> list[Cluster]:
    by_bank: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for payment in payments:
        bank = str(payment.get("payer_bank") or "")
        if bank:
            by_bank[bank].append(payment)
    output: list[Cluster] = []
    detector = NetworkXClusterDetector()
    for bank in sorted(by_bank):
        for cluster in detector.detect(by_bank[bank], window_days):
            cluster.cluster_id = f"{bank}:{cluster.cluster_id}"
            output.append(cluster)
    return output
