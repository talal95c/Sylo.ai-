"""B-owned payer/payee payment history aggregates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

import pandas as pd


@dataclass(frozen=True)
class HistoryEntry:
    count: int
    median_amount: float
    pair_payments_24h: int = 0
    last_account_id: str | None = None


class HistoryIndex:
    def __init__(self, entries: Mapping[str, Mapping[str, Any]] | None = None) -> None:
        self.entries: dict[str, HistoryEntry] = {
            key: HistoryEntry(
                int(value["count"]),
                float(value["median_amount"]),
                int(value.get("pair_payments_24h", 0)),
                (
                    None
                    if value.get("last_account_id") is None
                    or pd.isna(value.get("last_account_id"))
                    else str(value["last_account_id"])
                ),
            )
            for key, value in (entries or {}).items()
        }

    @staticmethod
    def key(payer_id: str, payee_id: str) -> str:
        return f"{payer_id}\t{payee_id}"

    def get(self, payer_id: str, payee_id: str) -> HistoryEntry | None:
        return self.entries.get(self.key(payer_id, payee_id))

    def to_dict(self) -> dict[str, dict[str, int | float | str | None]]:
        return {
            key: {
                "count": item.count,
                "median_amount": item.median_amount,
                "pair_payments_24h": item.pair_payments_24h,
                "last_account_id": item.last_account_id,
            }
            for key, item in sorted(self.entries.items())
        }


DEMO_HISTORY = {
    "payer_rhone\tpayee-ssx": {"count": 14, "median_amount": 85_000.0},
}


def build_history(rows: pd.DataFrame | Iterable[Mapping[str, Any]], max_day: int = 20) -> HistoryIndex:
    frame = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    if frame.empty:
        return HistoryIndex(DEMO_HISTORY)
    if "day" in frame:
        frame = frame.loc[frame["day"] <= max_day]
    latest_account_ids: dict[str, str | None] = {}
    if "account_id" in frame:
        ordered = frame.copy()
        ordered["_history_order"] = range(len(ordered))
        if "day" in ordered:
            ordered = ordered.sort_values(["day", "_history_order"])
        latest = ordered.groupby(
            ["payer_id", "payee_id"], sort=False
        ).tail(1)
        for _, row in latest.iterrows():
            key = HistoryIndex.key(str(row["payer_id"]), str(row["payee_id"]))
            account_id = row["account_id"]
            latest_account_ids[key] = (
                None if account_id is None or pd.isna(account_id) else str(account_id)
            )
    grouped = frame.groupby(["payer_id", "payee_id"], sort=True)["amount_eur"].agg(
        ["count", "median"]
    )
    entries = {}
    for (payer, payee), record in grouped.iterrows():
        if record["median"] <= 0:
            continue
        key = HistoryIndex.key(str(payer), str(payee))
        entries[key] = {
            "count": int(record["count"]),
            "median_amount": float(record["median"]),
            "pair_payments_24h": 0,
            "last_account_id": latest_account_ids.get(key),
        }
    entries.update(DEMO_HISTORY)
    return HistoryIndex(entries)


def history_from_row(
    row: Mapping[str, Any],
) -> dict[str, dict[str, int | float | str | None]]:
    count = int(row.get("history_count", 0) or 0)
    pair_payments_24h = int(row.get("pair_payments_24h", 0) or 0)
    median = row.get("history_median_amount")
    last_account_id = row.get("last_account_id")
    if (
        count <= 0
        and pair_payments_24h <= 0
        and (last_account_id is None or pd.isna(last_account_id))
    ):
        return {}
    return {
        HistoryIndex.key(str(row["payer_id"]), str(row["payee_id"])): {
            "count": count,
            "median_amount": (
                float(median)
                if median is not None and not pd.isna(median) and float(median) > 0
                else float("nan")
            ),
            "pair_payments_24h": pair_payments_24h,
            "last_account_id": (
                None
                if last_account_id is None or pd.isna(last_account_id)
                else str(last_account_id)
            ),
        }
    }
