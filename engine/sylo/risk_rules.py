"""Rules-based risk (v0 spec §5.6), implementing RiskPort.

Fraud risk decides the tier and therefore which settlement modes are allowed; it never enters
the route score.
"""

from __future__ import annotations

from sylo_spec.models import TRUSTED_PROVENANCE, PaymentOrder, RiskContext, RiskReason, RiskResult, Tier, band
from sylo_spec.ports import RiskPort

from . import texts


class RulesRisk:
    name = "rules-v0"

    def __init__(self, *, strict: bool = False) -> None:
        # strict: used when a dependency (the model) is missing; adds 10 points whenever a rule fires.
        self.strict = strict

    def score(self, order: PaymentOrder, ctx: RiskContext) -> RiskResult:
        if ctx.sanctions_hit:
            return RiskResult(
                score=95,
                tier=Tier.CRITICAL,
                floor_tier=Tier.CRITICAL,
                rules_fired=["R-HB-01"],
                reasons=[RiskReason(ref="S", text=texts.REASON_SANCTIONS, rule_id="R-HB-01")],
                oob_resolvable=False,
                model=self.name,
            )

        fired: list[tuple[str, int, str, str]] = []
        account = ctx.account
        provenance = order.provenance.get("creditorAccount", "unknown")
        untrusted = provenance not in TRUSTED_PROVENANCE
        session_cause = (
            ctx.payer_session.sim_swap_72h
            or ctx.payer_session.new_device_24h
            or ctx.payer_session.country != order.debtor.country
        )
        structuring_cause = (
            9_000 <= ctx.amount_eur < 10_000 and order.purpose != "DECLARED_SPLIT"
        )
        velocity_cause = ctx.history is not None and ctx.history.payments_24h > 2
        spike_cause = (
            ctx.history is not None
            and ctx.history.median_amount_eur is not None
            and ctx.amount_eur > 3 * ctx.history.median_amount_eur
        )
        degraded_cause = (
            session_cause or structuring_cause or velocity_cause or spike_cause
        )
        allowlisted = (
            not untrusted
            and account is not None
            and ctx.payee is not None
            and ctx.payee.owns(account.id)
            and account.successful_payments >= 3
            and ctx.account_age_hours >= 720
            and ctx.history is not None
            and ctx.history.median_amount_eur is not None
            and not degraded_cause
        )

        if untrusted:
            fired.append(("R-PV-01", 20, "V", texts.reason_untrusted_provenance(provenance, ctx.payee)))
        first_payment = account is None or account.successful_payments == 0
        if first_payment and untrusted and ctx.amount_eur >= 10_000:
            fired.append(("R-FL-01", 15, "B", texts.reason_first_payment(ctx.amount_eur)))
        if ctx.account_age_hours < 72 and ctx.amount_eur >= 5_000:
            fired.append(("R-FL-02", 10, "B", texts.reason_young_account(ctx.account_age_hours, ctx.amount_eur)))
        established_owned_account = (
            account is not None
            and account.successful_payments >= 1
            and ctx.payee is not None
            and ctx.payee.owns(account.id)
        )
        if ctx.name_match < 0.85 and not established_owned_account:
            holder = account.holder_name if account else order.creditor.name
            payee_name = ctx.payee.legal_name if ctx.payee else order.creditor.name
            fired.append(("R-FL-03", 12, "B", texts.reason_name_mismatch(holder, payee_name, ctx.name_match)))
        if "R1" in ctx.norm_signals:
            fired.append(("R-NM-01", 7, "R", texts.REASON_NOT_NOMINATED))
        if self.strict and not allowlisted:
            fired.append(
                (
                    "R-DG-01",
                    0,
                    "P" if session_cause else "B",
                    texts.REASON_MODEL_UNAVAILABLE,
                )
            )

        fired.sort(key=lambda rule: -rule[1])
        bonus = 10 if self.strict and fired else 0
        score = min(100, 10 + sum(rule[1] for rule in fired) + bonus)
        floor = Tier.MEDIUM if fired else Tier.LOW
        if self.strict and any(rule[0] == "R-DG-01" for rule in fired):
            floor = Tier(max(floor, Tier.MEDIUM))
        if self.strict and degraded_cause:
            floor = Tier(max(floor, Tier.HIGH))
        tier = Tier(max(floor, band(score)))

        reasons = [RiskReason(ref=ref, text=text, rule_id=rule_id) for rule_id, _, ref, text in fired]
        if not fired and account is not None and ctx.payee is not None and ctx.payee.owns(account.id):
            reasons = [
                RiskReason(ref="B", text=texts.reason_known_supplier(account)),
                RiskReason(ref="V", text=texts.REASON_VERIFIED_REGISTRY),
            ]
        return RiskResult(
            score=score,
            tier=tier,
            floor_tier=floor,
            rules_fired=[rule[0] for rule in fired],
            reasons=reasons,
            oob_resolvable=all(
                rule[0]
                in {"R-PV-01", "R-FL-01", "R-FL-02", "R-FL-03", "R-NM-01", "R-DG-01"}
                for rule in fired
            )
            and not (self.strict and degraded_cause),
            model=self.name,
        )


class CombinedRisk:
    """Rules give the floor tier and the fired rules; the model gives the score and extra reasons.

    The final score is the higher of the two and the tier is never below the rules' own tier: the
    model can only make a decision stricter. If the model raises, the strict rules decide and
    ``failed`` is set, so the orchestrator reports ``risk`` as degraded.
    """

    def __init__(self, rules: RulesRisk, model: RiskPort) -> None:
        self.rules = rules
        self.model = model
        self.name = f"{rules.name}+{model.name}"
        self.failed = False
        self._strict = rules if rules.strict else RulesRisk(strict=True)

    def score(self, order: PaymentOrder, ctx: RiskContext) -> RiskResult:
        base = self.rules.score(order, ctx)
        try:
            learned = RiskResult.model_validate(self.model.score(order, ctx))
        except Exception:
            self.failed = True
            return self._strict.score(order, ctx)
        known = {r.text for r in base.reasons}
        extra = [r for r in learned.reasons if r.text not in known]
        score = max(base.score, learned.score)
        return RiskResult(
            score=score,
            tier=Tier(max(base.tier, band(score))),
            floor_tier=base.floor_tier,
            rules_fired=base.rules_fired,
            reasons=base.reasons + extra,
            oob_resolvable=base.oob_resolvable and learned.oob_resolvable,
            model=learned.model,
        )
