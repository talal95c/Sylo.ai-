from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from api.risk_tiers import tier_for

UNTRUSTED_PROVENANCE = {"invoice_pdf_email", "inbound_call", "user_input"}
TIER_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
RULE_POINTS = {
    "R-FL-01": 26,
    "R-FL-02": 12,
    "R-FL-03": 18,
    "R-FL-04": 10,
    "R-NM-01": 12,
}
RULE_REASONS = {
    "R-FL-01": "New payee and untrusted invoice email for a high-value payment.",
    "R-FL-02": "The beneficiary account is less than 72 hours old.",
    "R-FL-03": "Account holder name match is below 0.85.",
    "R-FL-04": "A SIM swap was detected on the payer's line.",
    "R-NM-01": "Export proceeds are directed outside the nominated bank.",
    "R-OOB-01": "The supplier's known contact had a recent SIM swap; OOB is invalid.",
}


def _plain(value: Any) -> Any:
    return value.model_dump() if isinstance(value, BaseModel) else value


def _amount_eur(order: dict[str, Any], ctx: dict[str, Any]) -> float:
    if ctx.get("amount_eur") is not None:
        return float(ctx["amount_eur"])
    amount = order.get("amount", {})
    if amount.get("currency") == "EUR":
        return float(amount.get("value", 0))
    return 0.0


def evaluate_rules(order: Any, ctx: Any) -> dict[str, Any]:
    order_data = _plain(order)
    context = _plain(ctx)
    amount = _amount_eur(order_data, context)
    provenance = context.get(
        "provenance",
        order_data.get("provenance", {}).get("creditor.accountId", "verified_registry"),
    )
    untrusted = provenance in UNTRUSTED_PROVENANCE
    account_age = context.get("account_age_days")
    rules: list[str] = []
    approval_blocked = bool(
        untrusted
        and (
            context.get("payee_is_new")
            or context.get("account_first_seen_days") == 0
        )
    )

    if context.get("sanctions_hit"):
        rules.append("R-HB-01")
    if context.get("linked_confirmed_fraud"):
        rules.append("R-HB-02")
    if approval_blocked:
        rules.append("R-PV-01")
    if context.get("payee_is_new") and untrusted and amount >= 10_000:
        rules.append("R-FL-01")
    if account_age is not None and float(account_age) < 3 and amount >= 5_000:
        rules.append("R-FL-02")
    if float(context.get("name_match", 1.0)) < 0.85:
        rules.append("R-FL-03")
    if context.get("payer_sim_swap_72h"):
        rules.append("R-FL-04")
    if context.get("norm_r1"):
        rules.append("R-NM-01")
    if context.get("supplier_contact_sim_swap_7d"):
        rules.append("R-OOB-01")

    score = 18
    floor = "LOW"
    reasons: list[dict[str, str]] = []
    for rule in rules:
        if rule in {"R-HB-01", "R-HB-02"}:
            score = 100
            floor = "CRITICAL"
            reasons.append(
                {
                    "ref": rule,
                    "text": (
                        "Sanctions screening returned a hit."
                        if rule == "R-HB-01"
                        else "The account is linked to a confirmed fraud case."
                    ),
                }
            )
        elif rule == "R-PV-01":
            floor = max((floor, "MEDIUM"), key=TIER_ORDER.get)
        elif rule in RULE_POINTS:
            score += RULE_POINTS[rule]
            floor = max((floor, "MEDIUM"), key=TIER_ORDER.get)
            if rule == "R-FL-03":
                name_match = float(context.get("name_match", 0))
                reason_text = f"Account holder name match is only {name_match:.2f}."
            else:
                reason_text = RULE_REASONS[rule]
            reasons.append({"ref": rule, "text": reason_text})
        elif rule == "R-OOB-01":
            reasons.append({"ref": rule, "text": RULE_REASONS[rule]})

    score = min(100, score)
    tier = max((floor, tier_for(score)), key=TIER_ORDER.get)
    selected_reasons = [
        reason for reason in reasons if reason["ref"] != "R-PV-01"
    ][:3]
    return {
        "score": score,
        "tier": tier,
        "rulesFired": rules,
        "topReasons": selected_reasons,
        "modelVersion": "rules-v1",
        "approvalBlocked": approval_blocked,
    }


def score(order: Any, ctx: Any) -> dict[str, Any]:
    result = evaluate_rules(order, ctx)
    result.pop("approvalBlocked", None)
    return result
