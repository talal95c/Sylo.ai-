"""Rules-based fraud risk (`RulesRisk`, the v0 implementation of `RiskPort`).

Deterministic rules give a floor tier and a score. From v1 a model adds its own score,
and the engine keeps max(rule floor, model band): a model can only make things stricter.
Fraud risk decides the action and restricts the routes; it never enters the route score.
"""

from dataclasses import dataclass
from typing import Callable

from sylo_spec.models import PaymentOrder, RiskContext, RiskReason, RiskResult, Tier
from sylo_spec.scenarios import TRUSTED_PROVENANCE

from . import texts

BASE_SCORE = 10
SANCTIONS_SCORE = 95
BANDS = ((90, Tier.CRITICAL), (70, Tier.HIGH), (40, Tier.MEDIUM), (0, Tier.LOW))


def band(score: int) -> Tier:
    """0–39 LOW, 40–69 MEDIUM, 70–89 HIGH, 90–100 CRITICAL."""
    return next(tier for floor, tier in BANDS if score >= floor)


@dataclass(frozen=True)
class Rule:
    id: str
    ref: str  # signal family shown next to the reason
    floor: Tier
    weight: int
    applies: Callable[[PaymentOrder, RiskContext], bool]
    text: Callable[[PaymentOrder, RiskContext], str]


def _untrusted(order: PaymentOrder) -> bool:
    return order.provenance not in TRUSTED_PROVENANCE


def _supplier(ctx: RiskContext, order: PaymentOrder) -> str:
    return (ctx.payee.short_name or ctx.payee.legal_name) if ctx.payee else order.creditor.payee_name


RULES: tuple[Rule, ...] = (
    Rule(
        "R-PV-01", "V", Tier.MEDIUM, 20,
        lambda o, c: _untrusted(o),
        lambda o, c: texts.reason_pv_01(_supplier(c, o)),
    ),
    Rule(
        "R-FL-01", "B", Tier.MEDIUM, 15,
        lambda o, c: c.account.successful_payments == 0 and _untrusted(o) and c.amount_eur >= 10_000,
        lambda o, c: texts.reason_fl_01(c.amount_eur),
    ),
    Rule(
        "R-FL-02", "B", Tier.MEDIUM, 10,
        lambda o, c: c.account_age_hours < 72 and c.amount_eur >= 5_000,
        lambda o, c: texts.reason_fl_02(c.amount_eur),
    ),
    Rule(
        "R-FL-03", "B", Tier.MEDIUM, 12,
        lambda o, c: c.name_match < 0.85,
        lambda o, c: texts.reason_fl_03(c.account.holder_name, o.creditor.payee_name, c.name_match),
    ),
    Rule(
        "R-NM-01", "R", Tier.MEDIUM, 7,
        lambda o, c: "R1" in c.norm_signals,
        lambda o, c: texts.REASON_NM_01,
    ),
)


class RulesRisk:
    name = "rules-v0"

    def score(self, order: PaymentOrder, ctx: RiskContext) -> RiskResult:
        if "SANCTIONS" in ctx.norm_signals:  # R-HB-01: blocking
            return RiskResult(
                score=SANCTIONS_SCORE,
                tier=Tier.CRITICAL,
                floor_tier=Tier.CRITICAL,
                rules_fired=["R-HB-01"],
                reasons=[RiskReason(ref="R", text=texts.REASON_HB_01, rule_id="R-HB-01")],
                model=self.name,
            )

        fired = sorted((r for r in RULES if r.applies(order, ctx)), key=lambda r: -r.weight)
        score = min(100, BASE_SCORE + sum(r.weight for r in fired))
        floor = max((r.floor for r in fired), default=Tier.LOW)
        reasons = [RiskReason(ref=r.ref, text=r.text(order, ctx), rule_id=r.id) for r in fired]

        if not fired:  # the card always explains the decision, also when it is good news
            known = ctx.account.successful_payments > 0 and ctx.account.first_seen is not None
            if known and ctx.account.nominated_for_exports:
                reasons.append(RiskReason(ref="B", text=texts.reason_known_supplier(ctx.account.successful_payments, ctx.account.first_seen.year)))
            if order.provenance == "verified_registry":
                reasons.append(RiskReason(ref="V", text=texts.REASON_VERIFIED_REGISTRY))
            if not reasons:
                reasons.append(RiskReason(ref="H", text=texts.REASON_NO_RULE))

        return RiskResult(
            score=score,
            tier=max(floor, band(score)),
            floor_tier=floor,
            rules_fired=[r.id for r in fired],
            reasons=reasons,
            model=self.name,
        )
