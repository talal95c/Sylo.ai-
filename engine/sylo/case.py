"""Analyst case file: the engine calls the case writer and emits ``case.ready`` (roadmap A1.7, plan/README.md).

The writer belongs to Lane B (``sylo_risk.case.CaseWriter``, the Mistral investigator): the engine
only calls ``write(payment_id, events)`` and checks what comes back. Without a writer, or when its
answer cannot be used, the file is built here from the rules that fired, and every sentence cites
its rule or event. A case file informs the analyst; it never changes a decision.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from sylo_spec import SPEC_DIR
from sylo_spec.models import PaymentOrder, RiskResult
from sylo_spec.scenarios import ACCOUNTS, PAYEES, PAYER

from . import texts

log = logging.getLogger("sylo.case")

MAX_WORDS = 120
LLM_MODES = ("off", "cached", "live")


@dataclass
class CaseFile:
    summary: str
    citations: list[dict[str, str]]
    llm: str = "off"
    explanation: str | None = None
    report_draft: str | None = None

    def to_event_data(self) -> dict[str, Any]:
        data: dict[str, Any] = {"summary": self.summary, "citations": self.citations, "llm": self.llm}
        if self.explanation:
            data["explanation"] = self.explanation
        if self.report_draft:
            data["reportDraft"] = self.report_draft
        return data


@lru_cache(maxsize=1)
def _institution_names() -> dict[str, str]:
    geo = json.loads((SPEC_DIR / "geo" / "institutions.json").read_text(encoding="utf-8"))
    return {institution["id"]: institution["name"] for institution in geo["institutions"]}


def institution_name(institution_id: str) -> str:
    """Display name of a (fictional) institution, from the shared geography; the id when it is unknown."""
    return _institution_names().get(institution_id, institution_id)


def _event_id(events: list[dict[str, Any]], type_: str) -> str | None:
    return next((e["id"] for e in reversed(events) if e["type"] == type_), None)


def rules_case_file(order: PaymentOrder, risk: RiskResult, events: list[dict[str, Any]]) -> CaseFile:
    """Deterministic case file: one sentence per fired rule, each with its citation. No model involved."""
    payee = PAYEES.get(order.payee_id)
    account = ACCOUNTS.get(order.creditor_account_id)
    payee_name = payee.legal_name if payee else order.creditor.name
    amount = texts.eur(order.amount.as_float)
    scored = _event_id(events, "risk.scored")
    held = _event_id(events, "payment.held") or _event_id(events, "payment.stopped")

    citations: list[dict[str, str]] = []
    sentences = [
        texts.CASE_OPENING.format(
            payment=order.id, amount=amount, payee=payee_name, tier=risk.tier.name, score=risk.score, ref=scored or "risk"
        )
    ]
    if scored:
        citations.append({"ref": scored, "source": "event"})
    for reason in risk.reasons:
        if reason.rule_id is None:
            continue
        sentences.append(f"{reason.text.rstrip('.')} [{reason.rule_id}].")
        citations.append({"ref": reason.rule_id, "source": "rule"})
    if held:
        sentences.append(texts.CASE_CLOSING.format(ref=held))
        citations.append({"ref": held, "source": "event"})

    holder = account.holder_name if account else order.creditor.name
    masked = account.account_masked if account else "unknown"
    bank = institution_name(account.institution_id if account else order.creditor.institution_id)
    draft = texts.CASE_REPORT_DRAFT.format(
        payment=order.id,
        uetr=order.uetr,
        payer=PAYER.name,
        amount=amount,
        payee=payee_name,
        holder=holder,
        account=masked,
        bank=bank,
        rules=", ".join(risk.rules_fired) or "none",
    )
    return CaseFile(
        summary=" ".join(sentences),
        citations=citations,
        llm="off",
        explanation=texts.CASE_EXPLANATION if risk.rules_fired else None,
        report_draft=draft,
    )


def validate_case(raw: Any, *, known_refs: set[str]) -> CaseFile:
    """Check a writer's answer. Raises ValueError when it cannot be shown to an analyst as is."""
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump(by_alias=True)
    if not isinstance(raw, dict):
        raise ValueError("the case writer did not return an object")
    summary = raw.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("the case file has no summary")
    if len(summary.split()) > MAX_WORDS:
        raise ValueError(f"the summary is longer than {MAX_WORDS} words")
    citations = raw.get("citations")
    if not isinstance(citations, list) or not citations:
        raise ValueError("the case file cites nothing")
    clean: list[dict[str, str]] = []
    for citation in citations:
        if hasattr(citation, "model_dump"):
            citation = citation.model_dump(by_alias=True)
        ref = citation.get("ref") if isinstance(citation, dict) else None
        if not isinstance(ref, str) or ref not in known_refs:
            raise ValueError(f"the case file cites {ref!r}, which is not a rule, signal or event of this payment")
        clean.append({"ref": ref, "source": str(citation.get("source") or "rule")})
    llm = raw.get("llm")
    if llm not in LLM_MODES:
        raise ValueError(f"unknown llm label {llm!r}")
    explanation = raw.get("explanation")
    if isinstance(explanation, str) and len(explanation.split()) > MAX_WORDS:
        raise ValueError(f"the explanation is longer than {MAX_WORDS} words")
    report = raw.get("reportDraft", raw.get("report_draft"))
    return CaseFile(
        summary=summary.strip(),
        citations=clean,
        llm=llm,
        explanation=explanation if isinstance(explanation, str) and explanation.strip() else None,
        report_draft=report if isinstance(report, str) and report.strip() else None,
    )


def known_refs(risk: RiskResult, events: list[dict[str, Any]]) -> set[str]:
    refs = set(risk.rules_fired)
    refs.update(reason.ref for reason in risk.reasons)
    refs.update(event["id"] for event in events)
    for event in events:
        if event["type"] == "norms.checked":
            refs.update(signal["code"] for signal in event["data"].get("signals", []))
            refs.update(signal["ruleId"] for signal in event["data"].get("signals", []))
    return refs


class CaseService:
    """``mode`` is the requested ``LLM_MODE``; ``writer`` is Lane B's case writer, or None when it is not installed."""

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

    def write(self, order: PaymentOrder, risk: RiskResult, events: list[dict[str, Any]]) -> CaseFile:
        """Blocking (the writer may call an LLM): run it in a worker thread."""
        if self.writer is not None:
            try:
                return validate_case(self.writer.write(order.id, events), known_refs=known_refs(risk, events))
            except Exception as err:
                log.warning("case writer unusable (%s); using the case file built from the rules", err)
        return rules_case_file(order, risk, events)
