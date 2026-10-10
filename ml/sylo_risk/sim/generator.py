"""Deterministic synthetic payment generator; all records are fictional."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from sylo_spec.models import (
    Account,
    Channel,
    Documents,
    Money,
    Party,
    Payee,
    PaymentOrder,
    PayerSession,
    RiskContext,
)

from ..features import features_from_frame
from ..geo import GH_REGIONS

SEEDS = {"A": 20261001, "B": 20261002, "C": 20261003}
PAYER_BANKS = tuple(f"fr-bank-{index}" for index in range(6))
TYPOLOGY_RATES = {"T1": 0.003, "T2": 0.002, "T3": 0.003, "T4": 0.002}
TRUSTED_PROVENANCE = ("verified_registry", "payment_history", "psp_attestation")


def _make_integrity_cases(seed: str, output: Path) -> None:
    cases = {
        "I1": ("creditor_account_id", "acc-nominated", "acc-substituted"),
        "I2": ("payment_id", f"{seed}-INTENT-000", f"{seed}-INTENT-000-replay"),
        "I3": ("amount_eur", 85000.0, 85001.0),
    }
    with (output / "integrity_cases.jsonl").open("w", encoding="utf-8") as handle:
        for case, (field, original, tampered) in cases.items():
            for index in range(100):
                record = {
                    "case": case,
                    "paymentId": f"{seed}-INTEGRITY-{case}-{index:03d}",
                    "field": field,
                    "original": original,
                    "tampered": tampered,
                }
                handle.write(json.dumps(record, separators=(",", ":")) + "\n")


def generate_dataset(seed: str = "A", small: bool = False) -> pd.DataFrame:
    """Generate a full 150k row dataset, or a 20k row test dataset."""
    if seed not in SEEDS:
        raise ValueError(f"unknown seed {seed!r}; choose A, B, or C")
    n_rows = 20_000 if small else 150_000
    rng = np.random.default_rng(SEEDS[seed])
    typology = np.full(n_rows, "none", dtype=object)
    cursor = 0
    for kind, rate in TYPOLOGY_RATES.items():
        count = round(n_rows * rate)
        typology[cursor : cursor + count] = kind
        cursor += count
    rng.shuffle(typology)
    is_t1, is_t2, is_t3, is_t4 = (typology == kind for kind in ("T1", "T2", "T3", "T4"))
    label = (typology != "none").astype(np.int8)

    payer_number = rng.integers(0, 1500, size=n_rows)
    payer_ids = np.char.add("payer-", np.char.zfill(payer_number.astype(str), 4)).astype(object)
    payer_banks = np.asarray(PAYER_BANKS)[rng.integers(0, len(PAYER_BANKS), size=n_rows)]
    payee_number = payer_number % 1200
    payee_ids = np.char.add("payee-", np.char.zfill(payee_number.astype(str), 4)).astype(object)
    payee_ids[is_t2] = np.char.add("new-payee-", np.char.zfill(np.flatnonzero(is_t2).astype(str), 6))
    cluster_number = rng.integers(0, 100, size=n_rows)
    cluster_ids = np.full(n_rows, "", dtype=object)
    cluster_ids[is_t3] = np.asarray(
        [f"{seed}-cluster-{number:03d}" for number in cluster_number[is_t3]], dtype=object
    )
    payee_ids[is_t3] = np.char.add("mule-", np.char.zfill(cluster_number[is_t3].astype(str), 3))

    # Ordinary repeat suppliers dominate. A small slice is a first payment through an email invoice.
    provenance = np.asarray(rng.choice(TRUSTED_PROVENANCE, n_rows, p=(0.68, 0.19, 0.13)), dtype=object)
    sender_domain = np.empty(n_rows, dtype=object)
    known_domain = np.asarray([f"exporter{number:04d}.gh" for number in payee_number], dtype=object)
    sender_domain[:] = known_domain
    first_invoice = (typology == "none") & (rng.random(n_rows) < 0.015)
    provenance[first_invoice] = "invoice_pdf_email"

    evasive_rate = 0.50 if seed == "C" else 0.30
    evasive = np.zeros(n_rows, dtype=bool)
    t1_indices = np.flatnonzero(is_t1)
    evasive_count = round(evasive_rate * len(t1_indices))
    evasive[rng.choice(t1_indices, size=evasive_count, replace=False)] = True

    provenance[is_t1] = rng.choice(
        ("invoice_pdf_email", "user_input", "inbound_call"),
        size=int(is_t1.sum()),
        p=(0.88, 0.07, 0.05),
    )
    provenance[is_t2] = rng.choice(
        ("payment_history", "invoice_pdf_email"), size=int(is_t2.sum()), p=(0.75, 0.25)
    )
    provenance[is_t3] = rng.choice(
        ("payment_history", "verified_registry"), size=int(is_t3.sum()), p=(0.8, 0.2)
    )

    account_age_days = rng.lognormal(mean=np.log(900), sigma=0.55, size=n_rows).clip(60, 5000)
    successful_payments = rng.integers(2, 50, size=n_rows)
    account_owned_by_payee = np.ones(n_rows, dtype=bool)
    nominated = np.ones(n_rows, dtype=bool)
    name_match = rng.uniform(0.92, 1.0, size=n_rows)
    sim_swap = np.zeros(n_rows, dtype=bool)
    new_device = np.zeros(n_rows, dtype=bool)
    session_country = np.full(n_rows, "FR", dtype=object)
    amount = rng.lognormal(mean=np.log(80_000), sigma=0.45, size=n_rows).clip(500, 500_000)
    norms = np.full(n_rows, "", dtype=object)
    declared_split = np.zeros(n_rows, dtype=bool)
    known_bank_region = rng.integers(0, len(GH_REGIONS), size=n_rows)
    account_institution = np.asarray(
        [f"gh-bank-{number:02d}" for number in known_bank_region], dtype=object
    )
    supplier_region = rng.integers(0, len(GH_REGIONS), size=n_rows)
    supplier_institution = np.asarray(
        [f"gh-supplier-{number:02d}" for number in supplier_region], dtype=object
    )

    # Standard T1 supplier impersonation; evasive cases retain untrusted provenance but fewer signals.
    t1_evasive = evasive[is_t1]
    ordinary_t1 = t1_indices[~t1_evasive]
    evasive_indices = t1_indices[t1_evasive]
    account_owned_by_payee[t1_indices] = False
    nominated[t1_indices] = False
    account_age_days[ordinary_t1] = rng.uniform(1, 30, size=len(ordinary_t1))
    account_age_days[evasive_indices] = rng.uniform(60, 200, size=len(evasive_indices))
    successful_payments[t1_indices] = 0
    name_match[ordinary_t1] = rng.uniform(0.2, 0.7, size=len(ordinary_t1))
    near_name = rng.random(len(ordinary_t1)) < 0.25
    name_match[ordinary_t1[near_name]] = rng.uniform(0.85, 1.0, size=int(near_name.sum()))
    name_match[evasive_indices] = rng.uniform(0.9, 1.0, size=len(evasive_indices))
    successful_payments[evasive_indices] = rng.integers(1, 5, size=len(evasive_indices))
    lookalike = rng.random(len(ordinary_t1)) < 0.70
    lookalike_indices = ordinary_t1[lookalike]
    domain_suffix = "-invoice.com" if seed != "C" else "-billing.co"
    sender_domain[lookalike_indices] = [
        f"exporter{payee_number[index]:04d}{domain_suffix}" for index in lookalike_indices
    ]
    sender_domain[ordinary_t1[~lookalike]] = "secure-invoice-mail.com"
    sender_domain[evasive_indices] = known_domain[evasive_indices]
    t1_r1 = rng.random(len(t1_indices)) < 0.85
    if len(evasive_indices):
        t1_r1[np.flatnonzero(t1_evasive)] = rng.random(len(evasive_indices)) < 0.30
    norms[t1_indices[t1_r1]] = "R1"
    t1_border = rng.random(len(t1_indices)) < 0.60
    t1_border[np.flatnonzero(t1_evasive)] = rng.random(len(evasive_indices)) < 0.25
    t1_bank_idx = t1_indices[t1_border]
    account_institution[t1_bank_idx] = "mule_bank"
    amount[is_t1] = rng.lognormal(mean=np.log(82_000), sigma=0.5, size=int(is_t1.sum()))

    # Account takeover: new destination, a payer-session signal, and an anomalous value.
    t2_indices = np.flatnonzero(is_t2)
    account_owned_by_payee[t2_indices] = False
    nominated[t2_indices] = False
    account_age_days[t2_indices] = rng.uniform(1, 45, size=len(t2_indices))
    successful_payments[t2_indices] = 0
    sim_swap[t2_indices] = rng.random(len(t2_indices)) < 0.55
    new_device[t2_indices] = rng.random(len(t2_indices)) < 0.65
    foreign_t2 = rng.random(len(t2_indices)) < 0.40
    session_country[t2_indices[foreign_t2]] = rng.choice(("GH", "GB", "DE"), size=int(foreign_t2.sum()))
    amount[t2_indices] = rng.uniform(140_000, 360_000, size=len(t2_indices))

    # Mule accounts are young and geographically concentrated in the border region.
    t3_indices = np.flatnonzero(is_t3)
    account_age_days[t3_indices] = rng.uniform(1, 13.9, size=len(t3_indices))
    successful_payments[t3_indices] = 0
    name_match[t3_indices] = rng.uniform(0.45, 0.82, size=len(t3_indices))
    account_institution[t3_indices] = "mule_bank"
    amount[t3_indices] = rng.uniform(5_000, 70_000, size=len(t3_indices))

    # Structuring uses repeated undeclared transfers just below a EUR 10k cap.
    amount[is_t4] = rng.uniform(9_500, 9_999, size=int(is_t4.sum()))
    norms[is_t4] = "R4"

    # Honest counterexamples: one or two risk-like signals with countervailing context.
    hard_negative = np.zeros(n_rows, dtype=bool)
    eligible = np.flatnonzero(typology == "none")
    negative_indices = rng.choice(eligible, size=round(n_rows * 0.03), replace=False)
    hard_negative[negative_indices] = True
    negative_type = rng.integers(0, 6, size=len(negative_indices))
    bank_change = negative_indices[negative_type == 0]
    account_age_days[bank_change] = rng.uniform(5, 25, size=len(bank_change))
    successful_payments[bank_change] = 0
    provenance[bank_change] = "invoice_pdf_email"
    name_match[bank_change] = rng.uniform(0.96, 1.0, size=len(bank_change))
    sender_domain[bank_change] = known_domain[bank_change]
    account_institution[bank_change] = np.asarray(
        [f"gh-bank-{number:02d}" for number in known_bank_region[bank_change]], dtype=object
    )
    trading_name = negative_indices[negative_type == 1]
    name_match[trading_name] = rng.uniform(0.6, 0.85, size=len(trading_name))
    travel = negative_indices[negative_type == 2]
    session_country[travel] = rng.choice(("GH", "GB", "DE"), size=len(travel))
    new_supplier = negative_indices[negative_type == 3]
    provenance[new_supplier] = "invoice_pdf_email"
    account_age_days[new_supplier] = rng.uniform(365, 1800, size=len(new_supplier))
    nominated[new_supplier] = True
    name_match[new_supplier] = rng.uniform(0.9, 1.0, size=len(new_supplier))
    seasonal = negative_indices[negative_type == 4]
    amount[seasonal] *= 2.0
    split = negative_indices[negative_type == 5]
    amount[split] = rng.uniform(9_500, 9_999, size=len(split))
    declared_split[split] = True
    norms[split] = ""

    if seed == "C":
        amount *= 1.5

    # Stable known history on repeat payer/payee pairs; training replaces this with seed-A aggregates.
    history_median = amount.copy()
    history_count = rng.integers(4, 18, size=n_rows)
    no_history = is_t2 | first_invoice
    history_median[no_history] = np.nan
    history_count[no_history] = 0
    history_median[is_t4] = 9_750.0

    account_ids = np.asarray(
        [f"acc-{str(payee_ids[index])}-nominated" for index in range(n_rows)], dtype=object
    )
    account_ids[t1_indices] = [
        f"{seed}-account-t1-{index:06d}" for index in t1_indices
    ]
    account_ids[t2_indices] = [f"{seed}-account-t2-{index:06d}" for index in t2_indices]
    account_ids[t3_indices] = [
        f"{seed}-account-{str(cluster_ids[index])}" for index in t3_indices
    ]
    day = rng.integers(1, 31, size=n_rows)
    day[t3_indices] = cluster_number[t3_indices] % 30 + 1
    t4_indices = np.flatnonzero(is_t4)
    for pair_number, start in enumerate(range(0, len(t4_indices), 2)):
        pair = t4_indices[start : start + 2]
        payer_ids[pair] = f"payer-struct-{pair_number:04d}"
        payee_ids[pair] = f"payee-struct-{pair_number:04d}"
        day[pair] = int(rng.integers(1, 31))
    account_ids[t4_indices] = [
        f"acc-{str(payee_ids[index])}-nominated" for index in t4_indices
    ]
    account_ids[bank_change] = [
        f"{seed}-account-verified-change-{index:06d}" for index in bank_change
    ]
    amount_vs_history = amount / history_median
    payer_id_array = payer_ids.astype(object)
    frame = pd.DataFrame(
        {
            "payment_id": [f"{seed}-PAY-{index:06d}" for index in range(n_rows)],
            "uetr": [f"{seed.lower()}-{index:032x}" for index in range(n_rows)],
            "corridor": "FR-GH",
            "payer_id": payer_id_array,
            "payer_name": "Synthetic French exporter",
            "payer_country": "FR",
            "payer_bank": payer_banks,
            "payee_id": payee_ids,
            "payee_name": [f"Ghana Exporter {number:04d}" for number in payee_number],
            "payee_country": "GH",
            "supplier_institution_id": supplier_institution,
            "known_domain": known_domain,
            "account_id": account_ids,
            "account_holder_name": [f"Account holder {index:06d}" for index in range(n_rows)],
            "bene_bank_institution_id": account_institution,
            "account_owned_by_payee": account_owned_by_payee,
            "successful_payments": successful_payments,
            "account_age_days": account_age_days,
            "name_match": name_match,
            "nominated_for_exports": nominated,
            "provenance": provenance,
            "sender_domain": sender_domain,
            "sim_swap_72h": sim_swap,
            "new_device_24h": new_device,
            "session_country": session_country,
            "amount_eur": amount,
            "purpose": np.where(declared_split, "DECLARED_SPLIT", "GOODS"),
            "declared_split": declared_split,
            "norm_signals": norms,
            "history_count": history_count,
            "history_median_amount": history_median,
            "amount_vs_history": amount_vs_history,
            "label": label,
            "typology": typology,
            "evasive": evasive,
            "hard_negative": hard_negative,
            "day": day,
            "account_id_meta": account_ids,
            "cluster_id": cluster_ids,
            "payer_bank_meta": payer_banks,
        }
    )
    # Keep only one copy of identifiers requested for the evaluation metadata.
    frame["account_id"] = frame.pop("account_id_meta")
    frame["payer_bank"] = frame.pop("payer_bank_meta")
    engineered = features_from_frame(frame)
    for name in engineered:
        frame[name] = engineered[name]
    return frame


def row_to_order_ctx(row: Any) -> tuple[PaymentOrder, RiskContext]:
    """Reconstruct the exact engine-facing objects for a simulator row."""
    get = row.get
    text = lambda key, default="": default if pd.isna(get(key, default)) else str(get(key, default))
    account_id = text("account_id")
    account = Account(
        id=account_id,
        holder_name=text("account_holder_name"),
        institution_id=text("bene_bank_institution_id"),
        account_masked="GH•• •••• 0000",
        first_seen="2026-01-01",
        successful_payments=int(get("successful_payments", 0)),
        nominated_for_exports=bool(get("nominated_for_exports", False)),
    )
    owned = bool(get("account_owned_by_payee", False))
    payee = Payee(
        id=text("payee_id"),
        legal_name=text("payee_name"),
        country="GH",
        institution_id=text("supplier_institution_id"),
        known_domain=text("known_domain"),
        accounts=[account] if owned else [],
    )
    amount_eur = float(get("amount_eur"))
    order = PaymentOrder(
        id=text("payment_id"),
        uetr=text("uetr"),
        corridor="FR-GH",
        debtor=Party(id=text("payer_id"), name=text("payer_name"), country="FR", institution_id=text("payer_bank")),
        creditor=Party(id=text("payee_id"), name=text("payee_name"), country="GH", institution_id=text("bene_bank_institution_id")),
        payee_id=text("payee_id"),
        creditor_account_id=account_id,
        amount=Money(value=f"{amount_eur:.8f}", currency="EUR"),
        purpose=text("purpose", "GOODS"),
        documents=Documents(sender_domain=text("sender_domain") or None),
        provenance={"creditorAccount": text("provenance")},
        channel=Channel(device_id="synthetic-device", msisdn="+33 •• •• 00 00", session_country=text("session_country")),
    )
    norm_signals = text("norm_signals")
    context = RiskContext(
        payee=payee,
        account=account,
        norm_signals=list(filter(None, norm_signals.replace(",", "|").split("|"))),
        payer_session=PayerSession(
            sim_swap_72h=bool(get("sim_swap_72h", False)),
            new_device_24h=bool(get("new_device_24h", False)),
            country=text("session_country", "FR"),
        ),
        name_match=float(get("name_match")),
        account_age_hours=float(get("account_age_days")) * 24,
        amount_eur=amount_eur,
    )
    return order, context


def write_dataset(seed: str, small: bool, output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    frame = generate_dataset(seed, small=small)
    path = output / f"payments-{seed}{'-small' if small else ''}.csv.gz"
    frame.to_csv(path, index=False, compression="gzip")
    _make_integrity_cases(seed, output)
    return path


def default_output_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "data"
