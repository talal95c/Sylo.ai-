"""Analyst case file: the engine calls ``CasePort`` and emits ``case.ready`` (plan/README.md, roadmap A1.7).

The writer belongs to Lane B (``sylo_risk.CaseWriter``, the Mistral investigator): the engine only
calls ``write(payment_id, events)`` and checks what comes back. Without a writer, or when its
answer cannot be used, the file is built here from the rules that fired, and every sentence cites
its rule or event. A case file informs the analyst; no decision ever reads it.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any

from sylo_spec import SPEC_DIR
from sylo_spec.models import (
    CaseFile,
    CaseSentence,
    Citation,
    Event,
    PaymentOrder,
    RiskResult,
    Tier,
    TimelineEntry,
)
from sylo_spec.scenarios import ACCOUNTS, PAYEES, PAYER

from . import texts

log = logging.getLogger("sylo.case")

MAX_WORDS = 120
LLM_MODES = ("off", "cached", "live")
RULES_PROMPT_VERSION = "rules-v1"
RULES_MODEL = "rules"
IMPERSONATION_RULES = frozenset({"R-PV-01", "R-FL-01", "R-FL-02", "R-FL-03", "R-NM-01"})
CLOSINGS = {
    "held": (texts.CASE_CLOSING_HELD, "RELEASE_AFTER_CONFIRMATION"),
    "analyst": (texts.CASE_CLOSING_ANALYST, "CONFIRM_REVOCATION"),
    "blocked": (texts.CASE_CLOSING_BLOCKED, "ESCALATE_AML"),
}


@lru_cache(maxsize=1)
def _institution_names() -> dict[str, str]:
    geo = json.loads((SPEC_DIR / "geo" / "institutions.json").read_text(encoding="utf-8"))
    return {institution["id"]: institution["name"] for institution in geo["institutions"]}


def institution_name(institution_id: str) -> str:
    """Display name of a (fictional) institution, from the shared geography; the id when it is unknown."""
    return _institution_names().get(institution_id, institution_id)


def _last(events: list[dict[str, Any]], *types: str) -> dict[str, Any] | None:
    return next((event for event in reversed(events) if event["type"] in types), None)


def _timeline(events: list[dict[str, Any]]) -> list[TimelineEntry]:
    entries = []
    for event in events:
        template = texts.CASE_TIMELINE.get(event["type"])
        if template is None:
            continue
        try:
            text = template.format(**event["data"])
        except (KeyError, IndexError):
            text = template.split("{")[0].strip() or event["type"]
        entries.append(TimelineEntry(at=event["ts"], event_id=event["id"], text=text))
    return entries


def rules_case_file(
    order: PaymentOrder, risk: RiskResult, events: list[dict[str, Any]], situation: str = "held"
) -> CaseFile:
    """Deterministic case file: one sentence per fired rule, each with its citation. No model involved."""
    payee = PAYEES.get(order.payee_id)
    account = ACCOUNTS.get(order.creditor_account_id)
    payee_name = payee.legal_name if payee else order.creditor.name
    amount = texts.eur(order.amount.as_float)
    scored = _last(events, "risk.scored")
    stopped = _last(events, "payment.held", "payment.stopped")
    closing, recommended = CLOSINGS.get(situation, CLOSINGS["held"])

    sentences: list[CaseSentence] = []
    citations: list[Citation] = []

    def add(text: str, ref: str, source: str) -> None:
        sentences.append(CaseSentence(text=text if text.endswith(".") else f"{text}.", refs=[ref]))
        if all(citation.ref != ref for citation in citations):
            citations.append(Citation(ref=ref, source=source))

    opening = texts.CASE_OPENING.format(
        payment=order.id, amount=amount, payee=payee_name, tier=risk.tier.name, score=risk.score
    )
    if scored:
        add(opening, scored["id"], "event")
    for reason in risk.reasons:
        if reason.rule_id is not None:
            add(reason.text, reason.rule_id, "rule")
    if stopped:
        add(closing, stopped["id"], "event")
    if not sentences:
        raise ValueError("a case file needs at least one event of the payment to cite")

    holder = account.holder_name if account else order.creditor.name
    masked = account.account_masked if account else "unknown"
    bank = institution_name(account.institution_id if account else order.creditor.institution_id)
    fired = set(risk.rules_fired)
    if risk.tier == Tier.CRITICAL:
        recommended = "ESCALATE_AML"
    return CaseFile(
        payment_id=order.id,
        summary=" ".join(f"{sentence.text.rstrip('.')} [{sentence.refs[0]}]." for sentence in sentences),
        sentences=sentences,
        timeline=_timeline(events),
        typology="T1" if fired & IMPERSONATION_RULES else "UNCLASSIFIED",
        recommended_action=recommended,
        explanation=texts.CASE_EXPLANATION if fired else texts.CASE_EXPLANATION_NEUTRAL,
        citations=citations,
        report_draft=texts.CASE_REPORT_DRAFT.format(
            payment=order.id,
            uetr=order.uetr,
            payer=PAYER.name,
            amount=amount,
            payee=payee_name,
            holder=holder,
            account=masked,
            bank=bank,
            rules=", ".join(risk.rules_fired) or "none",
        ),
        llm="off",
        prompt_version=RULES_PROMPT_VERSION,
        model=RULES_MODEL,
    )


def known_refs(risk: RiskResult, events: list[dict[str, Any]]) -> set[str]:
    """Everything a case file may cite: the rules that fired, reason refs, norm signals and the payment's events."""
    refs = set(risk.rules_fired)
    refs.update(reason.ref for reason in risk.reasons)
    refs.update(event["id"] for event in events)
    for event in events:
        if event["type"] == "norms.checked":
            refs.update(signal["code"] for signal in event["data"].get("signals", []))
            refs.update(signal["ruleId"] for signal in event["data"].get("signals", []))
    return refs


def validate_case(raw: Any, *, known_refs: set[str]) -> CaseFile:
    """Check a writer's answer. Raises ValueError when it cannot be shown to an analyst as is."""
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump(by_alias=True)
    if not isinstance(raw, dict):
        raise ValueError("the case writer did not return a case file")
    case = CaseFile.model_validate(raw)  # pydantic's ValidationError is a ValueError
    if not case.summary.strip():
        raise ValueError("the case file has no summary")
    for name, text in (("summary", case.summary), ("explanation", case.explanation)):
        if len(text.split()) > MAX_WORDS:
            raise ValueError(f"the {name} is longer than {MAX_WORDS} words")
    if not case.citations:
        raise ValueError("the case file cites nothing")
    cited = [citation.ref for citation in case.citations] + [ref for sentence in case.sentences for ref in sentence.refs]
    unknown = sorted(set(cited) - known_refs)
    if unknown:
        raise ValueError(f"the case file cites {unknown}, which are not rules, signals or events of this payment")
    return case


class CaseService:
    """``mode`` is the requested ``LLM_MODE``; ``writer`` is Lane B's ``CasePort``, or None when it is not installed."""

    def __init__(self, mode: str = "off", writer: Any | None = None) -> None:
        self.requested = mode if mode in LLM_MODES else "off"
        self.writer = writer if self.requested != "off" else None

    @property
    def mode(self) -> str:
        """What ``system.mode.llm`` shows: the requested mode only when a writer can serve it."""
        return self.requested if self.writer is not None else "off"

    @property
    def degraded(self) -> bool:
        return self.requested != "off" and self.writer is None

    def write(
        self, order: PaymentOrder, risk: RiskResult, events: list[dict[str, Any]], situation: str = "held"
    ) -> CaseFile:
        """Blocking (the writer may call an LLM): run it in a worker thread."""
        if self.writer is not None:
            try:
                answer = self.writer.write(order.id, [Event.model_validate(event) for event in events])
                return validate_case(answer, known_refs=known_refs(risk, events))
            except Exception as err:
                log.warning("case writer unusable (%s); using the case file built from the rules", err)
        return rules_case_file(order, risk, events, situation)
