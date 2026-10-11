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
from ..geo import BORDER_REGIONS, GH_REGIONS

SEEDS = {"A": 20261001, "B": 20261002, "C": 20261003}
PAYER_BANKS = tuple(f"fr-bank-{index}" for index in range(6))
TYPOLOGY_RATES = {"T1": 0.003, "T2": 0.002, "T3": 0.003, "T4": 0.002}
TRUSTED_PROVENANCE = ("verified_registry", "payment_history", "psp_attestation")


def _temporal_history(
    payer_ids: np.ndarray,
    payee_ids: np.ndarray,
    days: np.ndarray,
    amounts: np.ndarray,
    history_mask: np.ndarray | None = None,
    target_mask: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    size = len(payer_ids)
    history_mask = np.ones(size, dtype=bool) if history_mask is None else history_mask
    target_mask = np.ones(size, dtype=bool) if target_mask is None else target_mask
    history_count = np.zeros(size, dtype=np.int32)
    history_median = np.full(size, np.nan, dtype=float)
    pair_payments_24h = np.zeros(size, dtype=np.int16)
    positions = np.arange(size)
    pairs = pd.DataFrame(
        {"payer_id": payer_ids, "payee_id": payee_ids, "position": positions}
    )
    for group in pairs.groupby(["payer_id", "payee_id"], sort=False).indices.values():
        pair_positions = np.asarray(group, dtype=int)
        targets = pair_positions[target_mask[pair_positions]]
        if not len(targets):
            continue
        history = pair_positions[history_mask[pair_positions]]
        target_days = np.unique(days[targets])
        for day in target_days:
            current = targets[days[targets] == day]
            previous = history[days[history] < day]
            if len(previous):
                history_count[current] = len(previous)
                history_median[current] = float(np.median(amounts[previous]))
            same_day = np.sort(pair_positions[days[pair_positions] == day])
            pair_payments_24h[current] = np.searchsorted(same_day, current, side="left")
    return history_count, history_median, pair_payments_24h


def _truncated_beta(rng: np.random.Generator, size: int, minimum: float) -> np.ndarray:
    samples = rng.beta(18, 1.5, size=size)
    rejected = samples < minimum
    while rejected.any():
        samples[rejected] = rng.beta(18, 1.5, size=int(rejected.sum()))
        rejected = samples < minimum
    return samples


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
    cluster_count = max(10, round(n_rows * 0.0002))
    cluster_number = rng.integers(0, cluster_count, size=n_rows)
    cluster_ids = np.full(n_rows, "", dtype=object)
    cluster_ids[is_t3] = np.asarray(
        [f"{seed}-cluster-{number:03d}" for number in cluster_number[is_t3]], dtype=object
    )
    payee_ids[is_t3] = np.char.add("mule-", np.char.zfill(cluster_number[is_t3].astype(str), 3))

    # Most beneficiary details come from a known, previously used supplier account.
    provenance = np.asarray(rng.choice(TRUSTED_PROVENANCE, n_rows, p=(0.68, 0.19, 0.13)), dtype=object)
    sender_domain = np.empty(n_rows, dtype=object)
    known_domain = np.asarray([f"exporter{number:04d}.gh" for number in payee_number], dtype=object)
    sender_domain[:] = known_domain

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

    account_age_days = rng.lognormal(mean=np.log(900), sigma=1.7, size=n_rows).clip(1, 10_000)
    successful_payments = rng.poisson(20, size=n_rows)
    account_owned_by_payee = rng.random(n_rows) < 0.97
    nominated = rng.random(n_rows) < 0.85
    name_match = np.clip(rng.beta(18, 1.5, size=n_rows), 0.4, 1.0)
    sim_swap = rng.random(n_rows) < 0.005
    new_device = rng.random(n_rows) < 0.05
    session_country = np.full(n_rows, "FR", dtype=object)
    foreign_session = rng.random(n_rows) < 0.04
    session_country[foreign_session] = rng.choice(
        ("GH", "GB", "DE"), size=int(foreign_session.sum())
    )
    amount = rng.lognormal(mean=np.log(80_000), sigma=0.45, size=n_rows).clip(500, 500_000)
    norms = np.where(rng.random(n_rows) < 0.005, "R1", "").astype(object)
    declared_split = np.zeros(n_rows, dtype=bool)
    non_border_regions = np.asarray(
        [index for index, region in enumerate(GH_REGIONS) if region not in BORDER_REGIONS]
    )
    known_bank_region = rng.choice(non_border_regions, size=n_rows)
    account_institution = np.asarray(
        [f"gh-bank-{number:02d}" for number in known_bank_region], dtype=object
    )
    natural_border = (typology == "none") & (rng.random(n_rows) < 0.03)
    border_banks = np.asarray(("gh-bank-06", "gh-bank-07", "mule_bank"), dtype=object)
    account_institution[natural_border] = rng.choice(
        border_banks, size=int(natural_border.sum())
    )
    supplier_region = rng.integers(0, len(GH_REGIONS), size=n_rows)
    supplier_institution = np.asarray(
        [f"gh-supplier-{number:02d}" for number in supplier_region], dtype=object
    )
    payee_names = np.asarray(
        [f"Ghana Exporter {number:04d}" for number in payee_number], dtype=object
    )
    account_holder_names = np.asarray(
        [f"Account holder {index:06d}" for index in range(n_rows)], dtype=object
    )
    natural_under_cap = (typology == "none") & (rng.random(n_rows) < 0.005)
    amount[natural_under_cap] = rng.uniform(
        9_500, 10_000, size=int(natural_under_cap.sum())
    )

    legitimate_indices = np.flatnonzero(typology == "none")
    onboarding_rate = 0.06 if seed == "C" else 0.04
    onboarding_count = round(onboarding_rate * len(legitimate_indices))
    onboarding = rng.choice(legitimate_indices, size=onboarding_count, replace=False)
    is_onboarding = np.zeros(n_rows, dtype=bool)
    is_onboarding[onboarding] = True
    payee_ids[onboarding] = [
        f"{seed}-payee-onboarding-{index:06d}" for index in onboarding
    ]
    payee_names[onboarding] = [
        f"New Ghana Supplier {index:06d}" for index in onboarding
    ]
    known_domain[onboarding] = [
        f"new-exporter{index:06d}.gh" for index in onboarding
    ]
    onboarding_owned = rng.random(len(onboarding)) < 0.5
    account_owned_by_payee[onboarding] = onboarding_owned
    successful_payments[onboarding] = 0
    account_age_days[onboarding] = rng.lognormal(
        mean=np.log(400), sigma=0.8, size=len(onboarding)
    ).clip(5, 3_000)
    onboarding_provenance = np.where(
        rng.random(len(onboarding)) < 0.70, "invoice_pdf_email", "user_input"
    )
    provenance[onboarding] = onboarding_provenance
    sender_is_known = rng.random(len(onboarding)) < 0.85
    sender_domain[onboarding] = np.where(
        sender_is_known, known_domain[onboarding], "gmail.com"
    )

    small_supplier_count = round(0.03 * len(legitimate_indices))
    small_supplier_candidates = legitimate_indices[~is_onboarding[legitimate_indices]]
    young_small_suppliers = rng.choice(
        small_supplier_candidates, size=small_supplier_count, replace=False
    )
    is_young_small_supplier = np.zeros(n_rows, dtype=bool)
    is_young_small_supplier[young_small_suppliers] = True
    account_owned_by_payee[young_small_suppliers] = True
    account_age_days[young_small_suppliers] = rng.uniform(
        10, 200, size=len(young_small_suppliers)
    )
    successful_payments[young_small_suppliers] = rng.integers(
        0, 7, size=len(young_small_suppliers)
    )
    name_match[young_small_suppliers] = np.clip(
        rng.beta(18, 1.5, size=len(young_small_suppliers)), 0.4, 1.0
    )
    young_supplier_border = rng.random(len(young_small_suppliers)) < 0.10
    account_institution[young_small_suppliers[young_supplier_border]] = rng.choice(
        border_banks, size=int(young_supplier_border.sum())
    )

    # T1 supplier impersonation includes both obvious and vendor-master-poisoned cases.
    t1_evasive = evasive[is_t1]
    ordinary_t1 = t1_indices[~t1_evasive]
    evasive_indices = t1_indices[t1_evasive]
    account_owned_by_payee[t1_indices] = False
    account_owned_by_payee[ordinary_t1] = rng.random(len(ordinary_t1)) < 0.10
    account_owned_by_payee[evasive_indices] = rng.random(len(evasive_indices)) < 0.35
    nominated[t1_indices] = False
    nominated[ordinary_t1] = rng.random(len(ordinary_t1)) < 0.10
    nominated[evasive_indices] = rng.random(len(evasive_indices)) < 0.20
    account_age_days[ordinary_t1] = rng.lognormal(
        mean=np.log(18), sigma=0.8, size=len(ordinary_t1)
    ).clip(1, 60)
    account_age_days[evasive_indices] = rng.lognormal(
        mean=np.log(40), sigma=0.8, size=len(evasive_indices)
    ).clip(5, 400)
    successful_payments[t1_indices] = 0
    successful_payments[evasive_indices] = rng.integers(0, 4, size=len(evasive_indices))
    name_match[ordinary_t1] = rng.uniform(0.2, 0.75, size=len(ordinary_t1))
    near_name = rng.random(len(ordinary_t1)) < 0.30
    name_match[ordinary_t1[near_name]] = rng.uniform(0.85, 1.0, size=int(near_name.sum()))
    name_match[evasive_indices] = _truncated_beta(rng, len(evasive_indices), 0.85)
    lookalike = rng.random(len(ordinary_t1)) < 0.60
    lookalike_indices = ordinary_t1[lookalike]
    domain_suffix = "-invoice.com" if seed != "C" else "-billing.co.uk"
    sender_domain[lookalike_indices] = [
        f"exporter{payee_number[index]:04d}{domain_suffix}" for index in lookalike_indices
    ]
    sender_domain[ordinary_t1[~lookalike]] = "secure-invoice-mail.com"
    sender_known = rng.random(len(evasive_indices)) < 0.60
    sender_domain[evasive_indices] = np.where(
        sender_known, known_domain[evasive_indices], "gmail.com"
    )
    provenance[evasive_indices] = np.where(
        rng.random(len(evasive_indices)) < 0.85,
        "invoice_pdf_email",
        "user_input",
    )
    norms[t1_indices] = ""
    norms[ordinary_t1[rng.random(len(ordinary_t1)) < 0.80]] = "R1"
    norms[evasive_indices[rng.random(len(evasive_indices)) < 0.30]] = "R1"
    t1_border = np.zeros(len(t1_indices), dtype=bool)
    t1_border[~t1_evasive] = rng.random(len(ordinary_t1)) < 0.50
    t1_border[t1_evasive] = rng.random(len(evasive_indices)) < 0.15
    t1_bank_idx = t1_indices[t1_border]
    account_institution[t1_bank_idx] = rng.choice(
        border_banks, size=len(t1_bank_idx)
    )
    amount[is_t1] = rng.lognormal(mean=np.log(82_000), sigma=0.5, size=int(is_t1.sum()))

    # Account takeover adds a new account to a previously known payer/payee relationship.
    t2_indices = np.flatnonzero(is_t2)
    account_owned_by_payee[t2_indices] = False
    nominated[t2_indices] = rng.random(len(t2_indices)) < 0.10
    account_age_days[t2_indices] = rng.lognormal(
        mean=np.log(60), sigma=0.8, size=len(t2_indices)
    ).clip(1, 900)
    successful_payments[t2_indices] = 0
    sim_swap[t2_indices] = rng.random(len(t2_indices)) < 0.45
    new_device[t2_indices] = rng.random(len(t2_indices)) < 0.55
    foreign_t2 = rng.random(len(t2_indices)) < 0.30
    session_country[t2_indices] = "FR"
    session_country[t2_indices[foreign_t2]] = rng.choice(
        ("GH", "GB", "DE"), size=int(foreign_t2.sum())
    )
    provenance[t2_indices] = np.where(
        rng.random(len(t2_indices)) < 0.75, "payment_history", "invoice_pdf_email"
    )

    # Mule accounts belong to the mule payee but are concentrated near a border.
    t3_indices = np.flatnonzero(is_t3)
    account_owned_by_payee[t3_indices] = True
    account_age_days[t3_indices] = rng.uniform(1, 120, size=len(t3_indices))
    successful_payments[t3_indices] = rng.integers(0, 7, size=len(t3_indices))
    name_match[t3_indices] = rng.uniform(0.5, 0.95, size=len(t3_indices))
    t3_border = rng.random(len(t3_indices)) < 0.70
    account_institution[t3_indices[t3_border]] = rng.choice(
        border_banks, size=int(t3_border.sum())
    )

    # Structuring is represented by repeated transfers below the cap, not a norm signal.
    amount[is_t4] = rng.uniform(9_000, 10_000, size=int(is_t4.sum()))
    norms[is_t4] = ""

    # Honest counterexamples: one or two risk-like signals with countervailing context.
    hard_negative = np.zeros(n_rows, dtype=bool)
    eligible = np.flatnonzero(
        (typology == "none") & ~is_onboarding & ~is_young_small_supplier
    )
    negative_indices = rng.choice(eligible, size=round(n_rows * 0.03), replace=False)
    hard_negative[negative_indices] = True
    negative_type = rng.integers(1, 6, size=len(negative_indices))
    bank_change_positions = rng.choice(
        len(negative_indices),
        size=round(0.01 * len(legitimate_indices)),
        replace=False,
    )
    negative_type[bank_change_positions] = 0
    hard_negative_type = np.full(n_rows, "", dtype=object)
    hard_negative_type[negative_indices] = np.asarray(
        ("bank_change", "trading_name", "travel", "new_supplier", "seasonal", "declared_split"),
        dtype=object,
    )[negative_type]
    bank_change = negative_indices[negative_type == 0]
    account_age_days[bank_change] = rng.lognormal(
        mean=np.log(40), sigma=0.8, size=len(bank_change)
    ).clip(5, 400)
    successful_payments[bank_change] = rng.integers(0, 4, size=len(bank_change))
    provenance[bank_change] = np.where(
        rng.random(len(bank_change)) < 0.80, "invoice_pdf_email", "user_input"
    )
    account_owned_by_payee[bank_change] = rng.random(len(bank_change)) < 0.50
    nominated[bank_change] = rng.random(len(bank_change)) < 0.30
    name_match[bank_change] = _truncated_beta(rng, len(bank_change), 0.85)
    bank_change_sender_known = rng.random(len(bank_change)) < 0.90
    sender_domain[bank_change] = np.where(
        bank_change_sender_known, known_domain[bank_change], "gmail.com"
    )
    bank_change_border = rng.random(len(bank_change)) < 0.05
    account_institution[bank_change] = np.asarray(
        [f"gh-bank-{number:02d}" for number in known_bank_region[bank_change]],
        dtype=object,
    )
    account_institution[bank_change[bank_change_border]] = rng.choice(
        border_banks, size=int(bank_change_border.sum())
    )
    norms[bank_change] = ""
    trading_name = negative_indices[negative_type == 1]
    name_match[trading_name] = rng.uniform(0.6, 0.85, size=len(trading_name))
    travel = negative_indices[negative_type == 2]
    session_country[travel] = rng.choice(("GH", "GB", "DE"), size=len(travel))
    new_supplier = negative_indices[negative_type == 3]
    payee_ids[new_supplier] = [
        f"{seed}-payee-hard-negative-{index:06d}" for index in new_supplier
    ]
    payee_names[new_supplier] = [
        f"Verified New Ghana Supplier {index:06d}" for index in new_supplier
    ]
    known_domain[new_supplier] = [
        f"verified-new-exporter{index:06d}.gh" for index in new_supplier
    ]
    provenance[new_supplier] = "invoice_pdf_email"
    account_age_days[new_supplier] = rng.uniform(365, 1800, size=len(new_supplier))
    nominated[new_supplier] = True
    account_owned_by_payee[new_supplier] = True
    name_match[new_supplier] = rng.uniform(0.9, 1.0, size=len(new_supplier))
    known_sender = rng.random(len(new_supplier)) < 0.85
    sender_domain[new_supplier] = np.where(
        known_sender, known_domain[new_supplier], "gmail.com"
    )
    seasonal = negative_indices[negative_type == 4]
    amount[seasonal] *= 2.0
    split = negative_indices[negative_type == 5]
    amount[split] = rng.uniform(9_000, 10_000, size=len(split))
    declared_split[split] = True
    norms[split] = ""

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
    account_ids[onboarding] = [
        f"{seed}-account-onboarding-{index:06d}" for index in onboarding
    ]
    account_ids[bank_change] = [
        f"{seed}-account-verified-change-{index:06d}" for index in bank_change
    ]

    day = rng.integers(1, 31, size=n_rows)
    cluster_start_day = rng.integers(1, 30, size=cluster_count)
    day[t3_indices] = np.minimum(
        cluster_start_day[cluster_number[t3_indices]]
        + rng.integers(0, 2, size=len(t3_indices)),
        30,
    )
    if len(bank_change):
        prior_candidates = np.flatnonzero(
            (typology == "none") & ~hard_negative & ~is_onboarding & (day < 30)
        )
        prior_rows = rng.choice(prior_candidates, size=len(bank_change), replace=True)
        payer_ids[bank_change] = payer_ids[prior_rows]
        payer_banks[bank_change] = payer_banks[prior_rows]
        payee_ids[bank_change] = payee_ids[prior_rows]
        payee_names[bank_change] = payee_names[prior_rows]
        known_domain[bank_change] = known_domain[prior_rows]
        supplier_institution[bank_change] = supplier_institution[prior_rows]
        day[bank_change] = day[prior_rows] + 1
        sender_domain[bank_change] = np.where(
            bank_change_sender_known, known_domain[bank_change], "gmail.com"
        )

    t4_indices = np.flatnonzero(is_t4)
    t4_groups: list[np.ndarray] = []
    cursor = 0
    remaining = len(t4_indices)
    while remaining:
        group_size = remaining if remaining <= 4 else int(rng.integers(2, 5))
        if remaining - group_size == 1:
            group_size -= 1
        t4_groups.append(t4_indices[cursor : cursor + group_size])
        cursor += group_size
        remaining -= group_size
    if t4_groups:
        prior_candidates = np.flatnonzero(
            (typology == "none")
            & (~is_onboarding)
            & (~hard_negative)
            & account_owned_by_payee
            & nominated
            & (day < 30)
        )
        prior_rows = rng.choice(prior_candidates, size=len(t4_groups), replace=False)
        for group, prior in zip(t4_groups, prior_rows):
            payer_ids[group] = payer_ids[prior]
            payee_ids[group] = payee_ids[prior]
            payer_banks[group] = payer_banks[prior]
            payee_names[group] = payee_names[prior]
            known_domain[group] = known_domain[prior]
            supplier_institution[group] = supplier_institution[prior]
            account_ids[group] = account_ids[prior]
            account_holder_names[group] = account_holder_names[prior]
            bene_bank = account_institution[prior]
            account_institution[group] = bene_bank
            account_owned_by_payee[group] = account_owned_by_payee[prior]
            successful_payments[group] = successful_payments[prior]
            account_age_days[group] = account_age_days[prior]
            name_match[group] = name_match[prior]
            nominated[group] = nominated[prior]
            provenance[group] = provenance[prior]
            sender_domain[group] = sender_domain[prior]
            day[group] = int(rng.integers(int(day[prior]) + 1, 31))
            norms[group] = ""
            declared_split[group] = False

    if seed == "C":
        amount[~is_t4 & ~declared_split] *= 1.5

    # T2 account-takeover amounts are scaled against actual prior pair history when available.
    _, t2_history_median, _ = _temporal_history(
        payer_ids,
        payee_ids,
        day,
        amount,
        history_mask=~is_t2,
        target_mask=is_t2,
    )
    t2_ratios = rng.uniform(1.0, 4.0, size=len(t2_indices))
    normal_level = rng.random(len(t2_indices)) < 0.20
    t2_ratios[normal_level] = rng.uniform(0.9, 1.1, size=int(normal_level.sum()))
    known_history = np.isfinite(t2_history_median[t2_indices])
    amount[t2_indices[known_history]] = (
        t2_history_median[t2_indices[known_history]] * t2_ratios[known_history]
    )
    no_t2_history = t2_indices[~known_history]
    amount[no_t2_history] = rng.lognormal(
        mean=np.log(80_000), sigma=0.45, size=len(no_t2_history)
    ) * (1.5 if seed == "C" else 1.0)

    history_count, history_median, pair_payments_24h = _temporal_history(
        payer_ids, payee_ids, day, amount
    )
    amount_vs_history = amount / np.where(history_median > 0, history_median, np.nan)
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
            "payee_name": payee_names,
            "payee_country": "GH",
            "supplier_institution_id": supplier_institution,
            "known_domain": known_domain,
            "account_id": account_ids,
            "account_holder_name": account_holder_names,
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
            "pair_payments_24h": pair_payments_24h,
            "label": label,
            "typology": typology,
            "evasive": evasive,
            "hard_negative": hard_negative,
            "hard_negative_type": hard_negative_type,
            "legit_young_small_supplier": is_young_small_supplier,
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
