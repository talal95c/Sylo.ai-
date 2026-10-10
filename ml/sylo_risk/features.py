"""Shared raw feature pipeline for simulator rows and RiskPort inference."""

from __future__ import annotations

import difflib
import math
import re
from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from sylo_spec.models import PaymentOrder, RiskContext, TRUSTED_PROVENANCE

from .geo import geography_features

# (name, family, monotone direction); zero means no declared monotonicity.
FEATURES: list[tuple[str, str, int]] = [
    ("account_owned_by_payee", "B", -1),
    ("log1p_successful_payments", "B", -1),
    ("log1p_account_age_days", "B", -1),
    ("first_payment", "B", 1),
    ("name_match", "B", -1),
    ("nominated_for_exports", "B", -1),
    ("provenance_untrusted", "V", 1),
    ("prov_invoice_email", "V", 1),
    ("prov_user_input", "V", 1),
    ("prov_inbound_call", "V", 1),
    ("sender_domain_differs", "V", 1),
    ("domain_lookalike", "V", 1),
    ("sim_swap_72h", "P", 1),
    ("new_device_24h", "P", 1),
    ("session_foreign", "P", 1),
    ("bene_bank_border_region", "G", 1),
    ("bene_bank_region_mismatch", "G", 1),
    ("log_amount", "H", 0),
    ("amount_vs_history", "H", 0),
    ("under_cap", "S", 1),
    ("declared_split", "S", -1),
    ("norm_R1", "R", 1),
    ("norm_R2", "R", 1),
    ("norm_R3", "R", 1),
    ("norm_R4", "R", 1),
]
FEATURE_NAMES = [feature[0] for feature in FEATURES]
MONOTONE_CONSTRAINTS = [feature[2] for feature in FEATURES]


def _domain_normalized(domain: str | None) -> str:
    if not domain:
        return ""
    value = domain.lower().strip().removeprefix("www.")
    value = re.sub(r"\.(com|net|org|gh|fr|co\.uk)$", "", value)
    return re.sub(r"[^a-z0-9]", "", value)


def _domain_similarity(sender: str | None, known: str | None) -> float:
    left, right = _domain_normalized(sender), _domain_normalized(known)
    return difflib.SequenceMatcher(None, left, right).ratio() if left and right else 0.0


def _history_entry(history: Any, payer_id: str, payee_id: str) -> Any:
    if history is None:
        return None
    if isinstance(history, Mapping):
        for key in (f"{payer_id}\t{payee_id}", (payer_id, payee_id)):
            result = history.get(key)
            if result is not None:
                return result
        return None
    if hasattr(history, "get"):
        try:
            result = history.get(payer_id, payee_id)
            if result is not None:
                return result
        except TypeError:
            pass
    return None


def _history_value(entry: Any, key: str, default: Any = None) -> Any:
    if entry is None:
        return default
    if isinstance(entry, Mapping):
        return entry.get(key, default)
    return getattr(entry, key, default)


def _derive(values: Mapping[str, Any]) -> dict[str, float]:
    provenance = str(values.get("provenance") or "")
    sender_domain = values.get("sender_domain")
    known_domain = values.get("known_domain")
    amount = float(values.get("amount_eur") or 0.0)
    median = values.get("history_median_amount")
    median = float(median) if median is not None and not pd.isna(median) else math.nan
    norms = set(values.get("norm_signals") or [])
    if isinstance(values.get("norm_signals"), str):
        norms = set(filter(None, re.split(r"[,| ]+", values["norm_signals"])))
    border, mismatch = geography_features(
        values.get("bene_bank_institution_id"), values.get("supplier_institution_id")
    )
    sender_differs = bool(sender_domain and known_domain and sender_domain.lower() != known_domain.lower())
    return {
        "account_owned_by_payee": float(bool(values.get("account_owned_by_payee", False))),
        "log1p_successful_payments": math.log1p(max(0.0, float(values.get("successful_payments") or 0))),
        "log1p_account_age_days": math.log1p(max(0.0, float(values.get("account_age_days") or 0))),
        "first_payment": float(float(values.get("successful_payments") or 0) == 0),
        "name_match": float(values.get("name_match") or 0.0),
        "nominated_for_exports": float(bool(values.get("nominated_for_exports", False))),
        "provenance_untrusted": float(provenance not in TRUSTED_PROVENANCE),
        "prov_invoice_email": float(provenance == "invoice_pdf_email"),
        "prov_user_input": float(provenance == "user_input"),
        "prov_inbound_call": float(provenance == "inbound_call"),
        "sender_domain_differs": float(sender_differs),
        "domain_lookalike": float(sender_differs and _domain_similarity(sender_domain, known_domain) >= 0.6),
        "sim_swap_72h": float(bool(values.get("sim_swap_72h", False))),
        "new_device_24h": float(bool(values.get("new_device_24h", False))),
        "session_foreign": float(
            bool(values.get("session_country"))
            and bool(values.get("payer_country"))
            and values["session_country"] != values["payer_country"]
        ),
        "bene_bank_border_region": border,
        "bene_bank_region_mismatch": mismatch,
        "log_amount": math.log1p(max(0.0, amount)),
        "amount_vs_history": amount / median if median > 0 else math.nan,
        "under_cap": float(9500 <= amount < 10_000),
        "declared_split": float(bool(values.get("declared_split", False))),
        **{f"norm_R{number}": float(f"R{number}" in norms) for number in range(1, 5)},
    }


def raw_from_order(
    order: PaymentOrder, ctx: RiskContext, history: Any = None
) -> dict[str, float]:
    account = ctx.account
    payee = ctx.payee
    entry = _history_entry(history, order.debtor.id, order.payee_id)
    age_days = max(0.0, float(ctx.account_age_hours) / 24.0)
    provenance = order.provenance.get("creditorAccount", "")
    return _derive(
        {
            "account_owned_by_payee": bool(payee and account and payee.owns(account.id)),
            "successful_payments": account.successful_payments if account else 0,
            "account_age_days": age_days,
            "name_match": ctx.name_match,
            "nominated_for_exports": account.nominated_for_exports if account else False,
            "provenance": provenance,
            "sender_domain": order.documents.sender_domain,
            "known_domain": payee.known_domain if payee else None,
            "sim_swap_72h": ctx.payer_session.sim_swap_72h,
            "new_device_24h": ctx.payer_session.new_device_24h,
            "session_country": ctx.payer_session.country,
            "payer_country": order.debtor.country,
            "bene_bank_institution_id": account.institution_id if account else order.creditor.institution_id,
            "supplier_institution_id": payee.institution_id if payee else None,
            "amount_eur": order.amount.as_float,
            "history_median_amount": _history_value(entry, "median_amount"),
            "declared_split": order.purpose == "DECLARED_SPLIT",
            "norm_signals": ctx.norm_signals,
        }
    )


def features_from_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Vectorized equivalent of ``raw_from_order`` for synthetic raw-input columns."""
    output = pd.DataFrame(index=frame.index)
    output["account_owned_by_payee"] = frame["account_owned_by_payee"].astype(float)
    output["log1p_successful_payments"] = np.log1p(frame["successful_payments"].clip(lower=0))
    output["log1p_account_age_days"] = np.log1p(frame["account_age_days"].clip(lower=0))
    output["first_payment"] = (frame["successful_payments"] == 0).astype(float)
    output["name_match"] = frame["name_match"].astype(float)
    output["nominated_for_exports"] = frame["nominated_for_exports"].astype(float)
    provenance = frame["provenance"].fillna("")
    output["provenance_untrusted"] = (~provenance.isin(TRUSTED_PROVENANCE)).astype(float)
    output["prov_invoice_email"] = (provenance == "invoice_pdf_email").astype(float)
    output["prov_user_input"] = (provenance == "user_input").astype(float)
    output["prov_inbound_call"] = (provenance == "inbound_call").astype(float)
    sender = frame["sender_domain"].fillna("").str.lower()
    known = frame["known_domain"].fillna("").str.lower()
    differs = sender.ne(known) & sender.ne("") & known.ne("")
    output["sender_domain_differs"] = differs.astype(float)
    pairs = pd.DataFrame({"sender": sender, "known": known}).drop_duplicates()
    similarity = {
        (row.sender, row.known): _domain_similarity(row.sender, row.known)
        for row in pairs.itertuples(index=False)
    }
    output["domain_lookalike"] = [
        float(differs.iloc[index] and similarity[(sender.iloc[index], known.iloc[index])] >= 0.6)
        for index in range(len(frame))
    ]
    output["sim_swap_72h"] = frame["sim_swap_72h"].astype(float)
    output["new_device_24h"] = frame["new_device_24h"].astype(float)
    output["session_foreign"] = (
        frame["session_country"].fillna("").ne(frame["payer_country"].fillna(""))
        & frame["session_country"].fillna("").ne("")
        & frame["payer_country"].fillna("").ne("")
    ).astype(float)
    geo = [
        geography_features(bank, supplier)
        for bank, supplier in zip(frame["bene_bank_institution_id"], frame["supplier_institution_id"])
    ]
    output["bene_bank_border_region"] = [row[0] for row in geo]
    output["bene_bank_region_mismatch"] = [row[1] for row in geo]
    output["log_amount"] = np.log1p(frame["amount_eur"].clip(lower=0))
    output["amount_vs_history"] = frame["amount_eur"] / frame["history_median_amount"].where(
        frame["history_median_amount"] > 0
    )
    output["under_cap"] = ((frame["amount_eur"] >= 9500) & (frame["amount_eur"] < 10_000)).astype(float)
    output["declared_split"] = frame["declared_split"].astype(float)
    norm_values = frame["norm_signals"].fillna("")
    for number in range(1, 5):
        output[f"norm_R{number}"] = norm_values.map(
            lambda value: float(f"R{number}" in set(filter(None, re.split(r"[,| ]+", value))))
        )
    return output.loc[:, FEATURE_NAMES]


def to_matrix(rows: pd.DataFrame | Mapping[str, Any] | list[Mapping[str, Any]]) -> np.ndarray:
    if isinstance(rows, pd.DataFrame):
        frame = rows
        if not set(FEATURE_NAMES).issubset(frame.columns):
            frame = features_from_frame(frame)
        values = frame.loc[:, FEATURE_NAMES].to_numpy(dtype=np.float64, copy=False)
    else:
        records = [rows] if isinstance(rows, Mapping) else rows
        values = np.asarray([[record[name] for name in FEATURE_NAMES] for record in records], dtype=np.float64)
    return values
