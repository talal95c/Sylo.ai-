"""Measure frozen-model and full-engine behavior on synthetic T1 evasion levels."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sylo_spec.models import TRUSTED_PROVENANCE, Tier

from .features import FEATURES, features_from_frame, raw_from_order, to_matrix
from .model_risk import ModelRisk, _reason_text
from .sim.generator import SEEDS, generate_dataset, row_to_order_ctx


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "reports" / "evasion.json"
DEFAULT_N = 2_000
SAMPLE_SEED_OFFSET = 1_000_003
EXPECTED_MODEL_VERSION = "gbm-20261011"
PRESERVED_FIELDS = (
    "amount_eur",
    "day",
    "sim_swap_72h",
    "new_device_24h",
    "session_country",
    "name_match",
)
PROVENANCE_FEATURES = {
    "provenance_untrusted",
    "prov_invoice_email",
    "prov_user_input",
    "prov_inbound_call",
}
ACCOUNT_HISTORY_FEATURES = {
    "account_changed_since_last",
    "log1p_successful_payments",
    "log1p_account_age_days",
    "first_payment",
}
LEVEL_DEFINITION = (
    "levels set on observed aggregate fields; prior-payment history is implied, "
    "not simulated as events"
)
LEVEL_DEFINITIONS = {
    "E0": "Current seed-B T1 rows, unchanged.",
    "E1": "E0 plus provenance=verified_registry.",
    "E2": (
        "E1 plus account_age_days>=90, successful_payments>=3 (aggregate), "
        "account not owned by payee, and last_account_id set to the supplier's "
        "previous nominated account; history_count is at least 1."
    ),
    "E3": (
        "E2 plus account owned by payee, last_account_id=account_id, "
        "and history_count>=1."
    ),
}
PREVALENCES = (0.01, 0.001, 0.0001)


def _evaluate_components():
    from .evaluate import ROW_FIELDS, _action_tiers, _score_engine

    return ROW_FIELDS, _action_tiers, _score_engine


def generate_evasion_levels(
    seed: str = "B",
    n: int = DEFAULT_N,
    *,
    source_frame: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    """Bootstrap existing seed T1 rows and apply the observed-field definitions."""
    if seed not in SEEDS:
        raise ValueError(f"unknown seed {seed!r}; choose A, B, or C")
    if n <= 0:
        raise ValueError("n must be positive")

    source = source_frame if source_frame is not None else generate_dataset(seed, small=False)
    t1 = source.loc[(source["typology"] == "T1") & (source["label"] == 1)]
    if t1.empty:
        raise ValueError(f"seed {seed} contains no T1 rows")

    rng = np.random.default_rng(SEEDS[seed] + SAMPLE_SEED_OFFSET)
    positions = rng.integers(0, len(t1), size=n)
    e0 = t1.iloc[positions].reset_index(drop=True).copy()

    e1 = e0.copy()
    e1["provenance"] = "verified_registry"

    e2 = e1.copy()
    e2["account_age_days"] = pd.to_numeric(
        e2["account_age_days"], errors="coerce"
    ).fillna(0).clip(lower=90)
    e2["successful_payments"] = (
        pd.to_numeric(e2["successful_payments"], errors="coerce")
        .fillna(0)
        .astype(int)
        .clip(lower=3)
    )
    e2["account_owned_by_payee"] = False
    e2["last_account_id"] = (
        "acc-" + e2["payee_id"].astype(str) + "-nominated"
    )
    e2["history_count"] = (
        pd.to_numeric(e2["history_count"], errors="coerce")
        .fillna(0)
        .astype(int)
        .clip(lower=1)
    )

    e3 = e2.copy()
    e3["account_owned_by_payee"] = True
    e3["last_account_id"] = e3["account_id"].astype(str)
    e3["history_count"] = (
        pd.to_numeric(e3["history_count"], errors="coerce")
        .fillna(0)
        .astype(int)
        .clip(lower=1)
    )

    levels = {"E0": e0, "E1": e1, "E2": e2, "E3": e3}
    baseline_draws = e0.loc[:, PRESERVED_FIELDS].reset_index(drop=True)
    for name, level in levels.items():
        if name == "E0":
            continue
        level_features = features_from_frame(level)
        refresh = PROVENANCE_FEATURES
        if name in {"E2", "E3"}:
            refresh = refresh | ACCOUNT_HISTORY_FEATURES
        for feature in refresh:
            level[feature] = level_features[feature]
        if not level.loc[:, PRESERVED_FIELDS].reset_index(drop=True).equals(
            baseline_draws
        ):
            raise AssertionError("evasion levels changed a preserved T1 draw")

    if not e1["provenance"].isin(TRUSTED_PROVENANCE).all():
        raise AssertionError("E1 must use trusted provenance")
    if not (
        (e2["account_age_days"] >= 90)
        & (e2["successful_payments"] >= 3)
        & ~e2["account_owned_by_payee"]
        & e2["last_account_id"].ne(e2["account_id"])
        & (e2["history_count"] >= 1)
    ).all():
        raise AssertionError("E2 observed-field definition was not applied")
    if not (
        e3["account_owned_by_payee"]
        & e3["last_account_id"].eq(e3["account_id"])
        & (e3["history_count"] >= 1)
    ).all():
        raise AssertionError("E3 observed-field definition was not applied")
    return levels


def _top_rules(rule_ids: np.ndarray) -> list[dict[str, Any]]:
    counts = Counter(rule_id for fired in rule_ids for rule_id in fired)
    return [
        {"rule_id": rule_id, "count": count}
        for rule_id, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:5]
    ]


def _model_only_tiers(
    frame: pd.DataFrame, model: ModelRisk, row_fields: tuple[str, ...]
) -> np.ndarray:
    tiers = np.empty(len(frame), dtype=np.int8)
    for index, values in enumerate(
        frame.loc[:, row_fields].itertuples(index=False, name=None)
    ):
        row = dict(zip(row_fields, values))
        order, context = row_to_order_ctx(row)
        tiers[index] = int(model.score(order, context).tier)
    return tiers


def _top_shap_reasons(
    frame: pd.DataFrame, model: ModelRisk, row_fields: tuple[str, ...]
) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    total_contribution: Counter[str] = Counter()
    examples: dict[str, dict[str, str]] = {}

    for values in frame.loc[:, row_fields].itertuples(index=False, name=None):
        row = dict(zip(row_fields, values))
        order, context = row_to_order_ctx(row)
        raw = raw_from_order(order, context, model._history)
        contributions = model._booster.predict(
            to_matrix(raw), pred_contrib=True, num_threads=1
        )[0]
        positive = sorted(
            (
                (float(contribution), feature[0], raw[feature[0]])
                for contribution, feature in zip(contributions[:-1], FEATURES)
                if contribution > 1e-10
            ),
            reverse=True,
        )
        found = 0
        for contribution, feature, value in positive:
            explanation = _reason_text(feature, value, order, context)
            if explanation is None:
                continue
            ref, text = explanation
            counts[feature] += 1
            total_contribution[feature] += contribution
            examples.setdefault(feature, {"ref": ref, "text": text})
            found += 1
            if found == 3:
                break

    return [
        {
            "feature": feature,
            "count": count,
            "mean_shap_contribution": total_contribution[feature] / count,
            "ref": examples[feature]["ref"],
            "example": examples[feature]["text"],
        }
        for feature, count in sorted(
            counts.items(), key=lambda item: (-item[1], item[0])
        )[:5]
    ]


def _score_level(
    level: str, frame: pd.DataFrame, model: ModelRisk
) -> dict[str, Any]:
    row_fields, action_tiers_fn, score_engine = _evaluate_components()
    full = score_engine(frame)
    tiers = full["tiers"]
    oob = full["oobResolvable"]
    action_tiers = action_tiers_fn(tiers, oob)
    model_tiers = _model_only_tiers(frame, model, row_fields)
    result: dict[str, Any] = {
        "level": level,
        "n": len(frame),
        "recall_medium_plus": float((tiers >= int(Tier.MEDIUM)).mean()),
        "recall_high_plus": float((tiers >= int(Tier.HIGH)).mean()),
        "escrow_share": float(((tiers == int(Tier.HIGH)) & oob).mean()),
        "blocked_share": float((action_tiers >= int(Tier.HIGH)).mean()),
        "model_only_recall_medium_plus": float(
            (model_tiers >= int(Tier.MEDIUM)).mean()
        ),
        "top_fired_rules": _top_rules(full["ruleIds"]),
    }
    if level == "E3":
        result["shap_reason_method"] = (
            "counts among each payment's top three positive SHAP feature reasons; "
            "not gated by the user-facing score threshold"
        )
        result["top_shap_reasons"] = _top_shap_reasons(frame, model, row_fields)
    return result


def _prevalence_rows(tpr: float, fpr: float) -> list[dict[str, float]]:
    results = []
    for prevalence in PREVALENCES:
        true_positive_rate = tpr * prevalence
        false_positive_rate = fpr * (1 - prevalence)
        precision = (
            true_positive_rate / (true_positive_rate + false_positive_rate)
            if true_positive_rate + false_positive_rate
            else 0.0
        )
        holds_per_fraud = (
            false_positive_rate / true_positive_rate if true_positive_rate else 0.0
        )
        results.append(
            {
                "prevalence": prevalence,
                "precision": precision,
                "legitimate_holds_per_fraud_caught": holds_per_fraud,
            }
        )
    return results


def _high_plus_rates(frame: pd.DataFrame) -> dict[str, Any]:
    _, _, score_engine = _evaluate_components()
    full = score_engine(frame)
    high = full["tiers"] >= int(Tier.HIGH)
    labels = frame["label"].to_numpy(dtype=bool)
    legitimate = ~labels
    return {
        "tpr": float(high[labels].mean()),
        "fpr": float(high[legitimate].mean()),
        "true_positives": int((high & labels).sum()),
        "fraud_count": int(labels.sum()),
        "false_positives": int((high & legitimate).sum()),
        "legitimate_count": int(legitimate.sum()),
    }


def evaluate_evasion(seed: str = "B", n: int = DEFAULT_N) -> dict[str, Any]:
    if seed != "B":
        raise ValueError("the published prevalence baseline is defined for seed B")

    source = generate_dataset(seed, small=False)
    levels = generate_evasion_levels(seed, n, source_frame=source)
    model = ModelRisk()
    if model.name != EXPECTED_MODEL_VERSION:
        raise RuntimeError(
            f"expected frozen model {EXPECTED_MODEL_VERSION}, found {model.name}"
        )

    level_results = [
        _score_level(level, frame, model) for level, frame in levels.items()
    ]
    high_rates = _high_plus_rates(source)
    metrics_path = ROOT / "reports" / "metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    medium_tpr = float(metrics["metrics"]["recallAll"])
    medium_fpr = float(metrics["metrics"]["fprMediumPlus"])
    if metrics["modelVersion"] != model.name:
        raise RuntimeError("metrics.json model version does not match the frozen model")

    return {
        "definition": LEVEL_DEFINITION,
        "level_definitions": LEVEL_DEFINITIONS,
        "seed": seed,
        "seed_value": SEEDS[seed],
        "n_per_level": n,
        "model_version": model.name,
        "frozen_thresholds": model._artifact["thresholds"],
        "sampling": {
            "source": "seed-B simulator T1 rows",
            "source_t1_count": int(((source["typology"] == "T1") & (source["label"] == 1)).sum()),
            "method": "deterministic bootstrap with replacement",
            "sampler_seed": SEEDS[seed] + SAMPLE_SEED_OFFSET,
        },
        "levels": level_results,
        "prevalence_table": {
            "method": (
                "precision = TPR*pi / (TPR*pi + FPR*(1-pi)); "
                "legitimate holds per fraud caught = FPR*(1-pi) / (TPR*pi)"
            ),
            "medium_plus": {
                "tpr": medium_tpr,
                "fpr": medium_fpr,
                "source_paths": {
                    "tpr": "ml/reports/metrics.json#/metrics/recallAll",
                    "fpr": "ml/reports/metrics.json#/metrics/fprMediumPlus",
                },
                "rows": _prevalence_rows(medium_tpr, medium_fpr),
            },
            "high_plus": {
                **high_rates,
                "source_paths": {
                    "tpr": (
                        "ml/sylo_risk/evasion.py::_high_plus_rates: "
                        "seed-B labels and frozen `_score_engine` tier output"
                    ),
                    "fpr": (
                        "ml/sylo_risk/evasion.py::_high_plus_rates: "
                        "seed-B legitimate labels and frozen `_score_engine` tier output"
                    ),
                    "population": "ml/reports/metrics.json#/evaluationRows/B",
                },
                "method": (
                    "metrics.json has no legitimate HIGH+ FPR; replay the existing "
                    "seed-B synthetic dataset through evaluate._score_engine using "
                    "the committed model artifacts, then count HIGH+ among fraud "
                    "and legitimate rows. No retraining."
                ),
                "rows": _prevalence_rows(
                    high_rates["tpr"], high_rates["fpr"]
                ),
            },
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate deterministic T1 evasion levels using the frozen model"
    )
    parser.add_argument("--seed", required=True, choices=("B",))
    parser.add_argument("--n", type=int, default=DEFAULT_N)
    parser.add_argument("--out", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    report = evaluate_evasion(args.seed, args.n)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
