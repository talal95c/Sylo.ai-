"""Intake: invoice or e-mail text -> a fixed set of fields with provenance (PRD §14, P1-6; roadmap A3.2).

This is the deterministic boundary of the engine, not an LLM. Text from an invoice or an e-mail is data:
it is read line by line for a few labelled fields, and nothing else in it can reach a rule. The result
has no field that says "verified", "approved" or "release". A field that is missing, or given twice with
different values, is left empty and a person is asked. Whatever the text says, the tier and the route are
decided from the registries and the structured order, so an injected instruction cannot move them.

Lane B's extraction agent, when it exists, plugs in behind the same fixed fields.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Any

from sylo_spec.models import PaymentOrder
from sylo_spec.scenarios import ACCOUNTS, ORDERS, PAYEES

SOURCE = "invoice_pdf_email"
MAX_TEXT = 20_000
HUMAN_BELOW = 0.9

# One labelled value alone on its line. Anything after the value makes the line not a field.
_FIELDS: dict[str, re.Pattern[str]] = {
    "invoiceRef": re.compile(r"^\s*invoice\s*(?:no\.?|number|ref(?:erence)?)?\s*[:#]\s*([A-Z0-9][A-Z0-9/-]{2,30})\s*$", re.I),
    "locRef": re.compile(r"^\s*LOC\s*(?:ref(?:erence)?)?\s*[:#]\s*([A-Z0-9-]{4,30})\s*$", re.I),
    "amount": re.compile(r"^\s*(?:amount(?:\s+due)?|total(?:\s+due)?)\s*:\s*((?:EUR|USD|GHS|NGN)\s*[0-9][0-9,]*(?:\.[0-9]{2})?)\s*$", re.I),
    "accountHolder": re.compile(r"^\s*(?:beneficiary|account\s+holder|account\s+name)\s*:\s*([^:]{2,80}?)\s*$", re.I),
    "account": re.compile(r"^\s*(?:account(?:\s+number)?|iban)\s*:\s*([A-Z0-9 •*.-]{4,40}?)\s*$", re.I),
}
_SENDER = re.compile(r"^\s*from\s*:.*?@([a-z0-9][a-z0-9.-]{1,80}\.[a-z]{2,24})\b", re.I)
_CHANGED = re.compile(r"\b(new|changed|updated|different)\s+(bank|account|payment)\s+(details|information|number)\b|\bbank details have changed\b", re.I)
_URGENCY = ("urgent", "immediately", "today", "asap", "right away", "do not call", "strictly confidential", "final notice")
_INSTRUCTIONS = re.compile(
    r"ignore (?:all |any )?(?:previous|prior|above) instructions|disregard (?:the )?(?:rules|above|previous)|"
    r"mark (?:this |it |the \w+ )?as (?:verified|approved|trusted|low risk)|set (?:the )?(?:risk|tier|score)|"
    r"\b(?:approve|release|execute) (?:this |the )?(?:payment|funds|transfer)\b|\bsystem\s*:|\bassistant\s*:|"
    r"you are (?:now )?(?:an?|the) |skip (?:the )?(?:verification|check|hold|escrow)|do not (?:hold|verify|flag|escalate)|"
    r"override|bypass|whitelist|already (?:been )?verified|pre-?approved",
    re.I,
)


@dataclass(frozen=True)
class IntakeField:
    value: str | None
    provenance: str
    confidence: float
    conflict: bool = False

    def to_json(self) -> dict[str, Any]:
        return {"value": self.value, "provenance": self.provenance, "confidence": self.confidence, "conflict": self.conflict}


@dataclass(frozen=True)
class IntakeResult:
    """The fixed schema. There is deliberately nothing here that could approve, verify or release."""

    fields: dict[str, IntakeField]
    sender_domain: IntakeField
    changed_details: bool
    lookalike_domain: str | None
    urgency_cues: list[str] = field(default_factory=list)
    instruction_like_lines: int = 0
    truncated: bool = False

    @property
    def needs_human(self) -> bool:
        return any(f.confidence < HUMAN_BELOW for f in self.fields.values())

    def value(self, name: str) -> str | None:
        return self.fields[name].value

    def to_json(self) -> dict[str, Any]:
        return {
            "fields": {name: f.to_json() for name, f in self.fields.items()},
            "senderDomain": self.sender_domain.to_json(),
            "changedDetails": self.changed_details,
            "lookalikeDomain": self.lookalike_domain,
            "urgencyCues": list(self.urgency_cues),
            "instructionLikeLines": self.instruction_like_lines,
            "needsHuman": self.needs_human,
            "truncated": self.truncated,
        }


def _lookalike(domain: str | None) -> str | None:
    """The known domain this one imitates, if it is close to a payee's domain without being it."""
    if not domain:
        return None
    for payee in PAYEES.values():
        known = getattr(payee, "known_domain", None)
        if not known or domain == known:
            continue
        if difflib.SequenceMatcher(None, domain.replace("-", ""), known.replace("-", "")).ratio() >= 0.75:
            return known
    return None


def extract(text: str, sender_domain: str | None = None) -> IntakeResult:
    """Read the labelled fields of an invoice or an e-mail. Never raises on content: odd text gives empty fields."""
    truncated = len(text) > MAX_TEXT
    lines = text[:MAX_TEXT].splitlines()
    found: dict[str, list[str]] = {name: [] for name in _FIELDS}
    senders: list[str] = []
    instructions = 0
    for line in lines:
        if _INSTRUCTIONS.search(line):
            instructions += 1  # counted, shown to the analyst as data, never acted on
        sender = _SENDER.match(line)
        if sender:
            senders.append(sender.group(1).lower())
        for name, pattern in _FIELDS.items():
            match = pattern.match(line)
            if match:
                found[name].append(" ".join(match.group(1).split()))

    fields: dict[str, IntakeField] = {}
    for name, values in found.items():
        distinct = list(dict.fromkeys(values))
        if len(distinct) == 1:
            fields[name] = IntakeField(distinct[0], SOURCE, 1.0)
        elif not distinct:
            fields[name] = IntakeField(None, SOURCE, 0.0)
        else:
            fields[name] = IntakeField(None, SOURCE, 0.5, conflict=True)  # two answers: nobody guesses

    domains = list(dict.fromkeys(senders))
    if sender_domain:
        domain = IntakeField(sender_domain.strip().lower(), "mail_header", 1.0)
    elif len(domains) == 1:
        domain = IntakeField(domains[0], SOURCE, 0.8)  # a From line inside the text can be forged
    else:
        domain = IntakeField(None, SOURCE, 0.0, conflict=len(domains) > 1)
    lowered = text[:MAX_TEXT].lower()
    return IntakeResult(
        fields=fields,
        sender_domain=domain,
        changed_details=bool(_CHANGED.search(lowered)),
        lookalike_domain=_lookalike(domain.value),
        urgency_cues=[cue for cue in _URGENCY if cue in lowered],
        instruction_like_lines=instructions,
        truncated=truncated,
    )


def _last_digits(value: str | None) -> str:
    return re.sub(r"[^0-9]", "", value or "")[-4:]


def match_order(result: IntakeResult) -> PaymentOrder | None:
    """The recorded order this document is about, by invoice reference and account. Only two things are
    taken from the document: which order it is, and the sender's domain. Bank details that the payee does
    not already own keep the provenance of the document, so they are never treated as verified."""
    reference, account_digits = result.value("invoiceRef"), _last_digits(result.value("account"))
    if not reference or len(account_digits) < 4:
        return None
    for order in ORDERS.values():
        account = ACCOUNTS.get(order.creditor_account_id)
        if account is None or order.documents.invoice_ref != reference or _last_digits(account.account_masked) != account_digits:
            continue
        payee = PAYEES.get(order.payee_id)
        owned = bool(payee and payee.owns(account.id))
        documents = order.documents.model_copy(update={"sender_domain": result.sender_domain.value or order.documents.sender_domain})
        provenance = dict(order.provenance) if owned else {**order.provenance, "creditorAccount": SOURCE}
        return order.model_copy(update={"documents": documents, "provenance": provenance})
    return None
