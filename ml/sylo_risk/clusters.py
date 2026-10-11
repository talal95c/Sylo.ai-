from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache
from hashlib import sha256
from typing import Any

import networkx as nx

from sylo_spec import SPEC_DIR
from sylo_spec.models import Account, Cluster, ClusterCentroid, ClusterPoint, WindowPayment
from sylo_spec.scenarios import ACCOUNTS

from .geo import GH_REGION_CENTROIDS, GH_REGION_ISO, institution_geography

YOUNG_ACCOUNT_DAYS = 120
THIN_HISTORY_PAYMENTS = 10
MIN_LINKED_PAYMENTS = 3


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


@lru_cache(maxsize=1)
def _institutions() -> dict[str, Mapping[str, Any]]:
    geo = json.loads((SPEC_DIR / "geo" / "institutions.json").read_text(encoding="utf-8"))
    return {institution["id"]: institution for institution in geo["institutions"]}


class WindowClusterDetector:
    """``ClusterPort`` over the engine's window of recent payments (``WindowPayment``: ids, amount, time).

    The window carries no payer and no history, so the offline rule "three payers into one young
    account" becomes: payments into young or thin accounts at a border-region bank, linked through
    that bank. A group that at least three payments point to is reported. Unknown accounts and
    unknown banks count as suspicious (missing data is pessimistic).
    """

    name = "networkx-mule-clusters"

    def __init__(self, accounts: Mapping[str, Account] | None = None) -> None:
        self.accounts = ACCOUNTS if accounts is None else accounts

    def _suspicious(self, payment: WindowPayment) -> bool:
        if not institution_geography(payment.institution_id).border:
            return False
        account = self.accounts.get(payment.account_id)
        if account is None:
            return True
        at = datetime.fromisoformat(payment.at.replace("Z", "+00:00")).date()
        age = (at - date.fromisoformat(account.first_seen)).days
        return age < YOUNG_ACCOUNT_DAYS or account.successful_payments < THIN_HISTORY_PAYMENTS

    def detect(self, window: list[WindowPayment]) -> list[Cluster]:
        suspicious = [payment for payment in window if self._suspicious(payment)]
        graph = nx.Graph()
        for payment in suspicious:
            graph.add_edge(("payment", payment.payment_id), ("account", payment.account_id))
            graph.add_edge(("account", payment.account_id), ("bank", payment.institution_id))

        found: list[tuple[str, list[str], list[str], list[str]]] = []
        for component in nx.connected_components(graph):
            payments = sorted(node[1] for node in component if node[0] == "payment")
            if len(payments) < MIN_LINKED_PAYMENTS:
                continue
            accounts = sorted(node[1] for node in component if node[0] == "account")
            banks = sorted(node[1] for node in component if node[0] == "bank")
            found.append((self._place(banks), accounts, banks, payments))

        per_place: Counter[str] = Counter()
        clusters = []
        for place, accounts, banks, payments in sorted(found):
            per_place[place] += 1
            clusters.append(self._cluster(f"CL-{place}-{per_place[place]:02d}", accounts, banks, payments, suspicious))
        return clusters

    @staticmethod
    def _place(banks: list[str]) -> str:
        city = _institutions().get(banks[0], {}).get("city") or banks[0]
        return "".join(ch for ch in str(city).upper() if ch.isalnum())

    @staticmethod
    def _cluster(
        cluster_id: str, accounts: list[str], banks: list[str], payments: list[str], window: Sequence[WindowPayment]
    ) -> Cluster:
        per_bank = Counter(payment.institution_id for payment in window if payment.payment_id in payments)
        located = [bank for bank in banks if bank in _institutions()]
        points = [
            ClusterPoint(
                lat=round(float(_institutions()[bank]["lat"]), 2),
                lng=round(float(_institutions()[bank]["lng"]), 2),
                weight=per_bank[bank] / max(per_bank.values()),
            )
            for bank in located
        ]
        region = institution_geography(banks[0]).region
        if points:
            centroid = ClusterCentroid(lat=points[0].lat, lng=points[0].lng)
        elif region in GH_REGION_CENTROIDS:
            centroid = ClusterCentroid(lat=GH_REGION_CENTROIDS[region][0], lng=GH_REGION_CENTROIDS[region][1])
        else:
            centroid = ClusterCentroid(lat=0.0, lng=0.0)
        city = _institutions().get(banks[0], {}).get("city")
        region_name = f"{region} Region" if region else "Unknown region"
        if city:
            region_name += f" ({city} border)"
        return Cluster(
            cluster_id=cluster_id,
            accounts=accounts,
            agents=[],
            region=GH_REGION_ISO.get(region or "", "Unknown"),
            region_name=region_name,
            institutions=banks,
            centroid=centroid,
            points=points,
            linked_payments=payments,
        )


def detect(
    payments: Sequence[Mapping[str, Any] | WindowPayment],
    window_days: int = 2,
) -> list[Cluster]:
    """The engine passes ``WindowPayment`` (spec ``ClusterPort``); the evaluation passes simulator rows."""
    if payments and all(isinstance(payment, WindowPayment) for payment in payments):
        return WindowClusterDetector().detect(list(payments))  # type: ignore[arg-type]
    return NetworkXClusterDetector().detect(payments, window_days)  # type: ignore[arg-type]


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
