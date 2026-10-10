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


class HistoryIndex:
    def __init__(self, entries: Mapping[str, Mapping[str, Any]] | None = None) -> None:
        self.entries: dict[str, HistoryEntry] = {
            key: HistoryEntry(
                int(value["count"]),
                float(value["median_amount"]),
                int(value.get("pair_payments_24h", 0)),
            )
            for key, value in (entries or {}).items()
        }

    @staticmethod
    def key(payer_id: str, payee_id: str) -> str:
        return f"{payer_id}\t{payee_id}"

    def get(self, payer_id: str, payee_id: str) -> HistoryEntry | None:
        return self.entries.get(self.key(payer_id, payee_id))

    def to_dict(self) -> dict[str, dict[str, int | float]]:
        return {
            key: {
                "count": item.count,
                "median_amount": item.median_amount,
                "pair_payments_24h": item.pair_payments_24h,
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
    grouped = frame.groupby(["payer_id", "payee_id"], sort=True)["amount_eur"].agg(
        ["count", "median"]
    )
    entries = {
        HistoryIndex.key(str(payer), str(payee)): {
            "count": int(record["count"]),
            "median_amount": float(record["median"]),
            "pair_payments_24h": 0,
        }
        for (payer, payee), record in grouped.iterrows()
        if record["median"] > 0
    }
    entries.update(DEMO_HISTORY)
    return HistoryIndex(entries)


def history_from_row(row: Mapping[str, Any]) -> dict[str, dict[str, int | float]]:
    count = int(row.get("history_count", 0) or 0)
    pair_payments_24h = int(row.get("pair_payments_24h", 0) or 0)
    median = row.get("history_median_amount")
    if count <= 0 and pair_payments_24h <= 0:
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
        }
    }
