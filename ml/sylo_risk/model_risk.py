"""ModelRisk: calibrated fraud model behind RiskPort (Lane B builds it in v1)."""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
from sylo_spec.models import PaymentOrder, RiskContext, RiskResult
from sylo_spec.models import RiskReason, Tier, band

from .features import FEATURES, raw_from_order, to_matrix
from .geo import institution_geography
from .history import HistoryIndex
from .scores import probability_to_score


@lru_cache(maxsize=1)
def _load_artifacts() -> tuple[lgb.Booster, dict[str, Any], HistoryIndex]:
    model_dir = Path(__file__).resolve().parents[1] / "models"
    artifact = json.loads((model_dir / "model.json").read_text(encoding="utf-8"))
    booster = lgb.Booster(model_file=str(model_dir / artifact["tree_model"]))
    return booster, artifact, HistoryIndex(artifact.get("history", {}))


def _reason_text(feature: str, value: float, order: PaymentOrder, ctx: RiskContext) -> tuple[str, str] | None:
    account = ctx.account
    payee = ctx.payee
    provenance = order.provenance.get("creditorAccount", "unknown source")
    sender = order.documents.sender_domain or "unknown sender"
    known_domain = payee.known_domain if payee else "unknown"
    if feature == "account_owned_by_payee":
        state = "not recorded as supplier-owned" if value < 0.5 else "recorded as supplier-owned"
        return "B", f"Beneficiary bank account is {state}"
    if feature == "log1p_successful_payments":
        return "B", f"Only {account.successful_payments if account else 0} successful payments on this account"
    if feature == "log1p_account_age_days":
        return "B", f"Bank account opened {ctx.account_age_hours / 24:.0f} days ago"
    if feature == "first_payment":
        return (
            "B",
            "No successful payments to this bank account yet"
            if value
            else "Prior payments exist on this account",
        )
    if feature == "name_match":
        return "B", f"Beneficiary account name match score is {ctx.name_match:.0%}"
    if feature == "nominated_for_exports":
        state = "not nominated" if value < 0.5 else "nominated"
        return "B", f"Account is {state} for this supplier's exports"
    if feature == "provenance_untrusted":
        return "V", f"Bank details arrived through unverified {provenance} provenance"
    if feature in {"prov_invoice_email", "prov_user_input", "prov_inbound_call"}:
        return "V", f"Bank details were supplied through {provenance}"
    if feature == "sender_domain_differs":
        return "V", f"Invoice sender domain {sender} differs from registered domain {known_domain}"
    if feature == "domain_lookalike":
        return "V", f"Invoice sender domain {sender} resembles registered domain {known_domain}"
    if feature == "sim_swap_72h":
        return "P", "Payer phone had a SIM swap in the last 72 hours"
    if feature == "new_device_24h":
        return "P", "Payment was initiated from a new device in the last 24 hours"
    if feature == "session_foreign":
        return "P", f"Payer session country {ctx.payer_session.country} differs from home country {order.debtor.country}"
    if feature in {"bene_bank_border_region", "bene_bank_region_mismatch"}:
        geography = institution_geography(
            account.institution_id if account else order.creditor.institution_id
        )
        region = geography.region or "unknown"
        if feature == "bene_bank_border_region":
            return "G", f"Beneficiary bank is in Ghana's {region} border region"
        return "G", f"Beneficiary bank region {region} differs from the supplier's registered region"
    if feature == "log_amount":
        return "H", f"Payment amount is EUR {order.amount.as_float:,.0f}"
    if feature == "amount_vs_history":
        return "H", f"Payment is {value:.1f}× the historical payer-to-supplier median"
    if feature == "under_cap":
        return "S", f"Undeclared payment of EUR {order.amount.as_float:,.0f} is just below a EUR 10,000 cap"
    if feature.startswith("norm_R"):
        return "R", f"Payment triggered norm signal {feature.removeprefix('norm_')}"
    return None


def _oob_resolvable(raw: dict[str, float], score: int, sanctions_hit: bool = False) -> bool:
    history_ratio = raw["amount_vs_history"]
    undeclared_under_cap = bool(raw["under_cap"] and not raw["declared_split"])
    return (
        score < 90
        and not sanctions_hit
        and not raw["sim_swap_72h"]
        and not raw["new_device_24h"]
        and not raw["session_foreign"]
        and not undeclared_under_cap
        and raw["pair_payments_24h"] == 0
        and (math.isnan(history_ratio) or history_ratio <= 3.0)
    )


class ModelRisk:
    """RiskPort backed by the committed, calibrated model bundle."""

    def __init__(self) -> None:
        self._booster, self._artifact, self._history = _load_artifacts()
        self.name = str(self._artifact["version"])

    def score(self, order: PaymentOrder, ctx: RiskContext) -> RiskResult:
        raw = raw_from_order(order, ctx, self._history)
        matrix = to_matrix(raw)
        shap_values = self._booster.predict(matrix, pred_contrib=True, num_threads=1)[0]
        raw_logit = float(np.sum(shap_values))
        probability = 1.0 / (1.0 + np.exp(-raw_logit))
        probability = float(
            np.interp(
                probability,
                self._artifact["isotonic"]["x"],
                self._artifact["isotonic"]["y"],
            )
        )
        thresholds = self._artifact["thresholds"]
        score = probability_to_score(probability, thresholds["t_med"], thresholds["t_high"])

        reasons: list[RiskReason] = []
        if score >= 40:
            positive = sorted(
                (
                    (float(contribution), feature[0], raw[feature[0]])
                    for contribution, feature in zip(shap_values[:-1], FEATURES)
                    if contribution > 1e-10
                ),
                reverse=True,
            )
            for _, feature, value in positive:
                explanation = _reason_text(feature, value, order, ctx)
                if explanation is None:
                    continue
                family, text = explanation
                reasons.append(RiskReason(ref=family, text=text, rule_id=None))
                if len(reasons) == 3:
                    break

        return RiskResult(
            score=score,
            tier=band(score),
            floor_tier=Tier.LOW,
            rules_fired=[],
            reasons=reasons,
            model=self.name,
            oob_resolvable=_oob_resolvable(raw, score, ctx.sanctions_hit),
        )
