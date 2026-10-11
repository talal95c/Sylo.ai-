from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError
from sylo_spec.models import CaseFile

from .template import ACTION_RANK, event_dict

NUMBER = re.compile(r"\d[\d,.\s]*\d|\d")
TYPOLOGIES = {
    "T1 supplier impersonation",
    "T2 account takeover",
    "T3 mule cash-out",
    "T4 structuring",
    "none",
}


def _numbers(value: str) -> set[str]:
    return {match.group(0).replace(" ", "").replace(",", "") for match in NUMBER.finditer(value)}


def _strip_refs(value: str, refs: set[str]) -> str:
    for ref in sorted(refs, key=len, reverse=True):
        value = value.replace(ref, "")
    return value


def validate_case(
    value: CaseFile | Mapping[str, Any],
    events: list[Any],
    template: CaseFile,
) -> CaseFile | None:
    try:
        case = value if isinstance(value, CaseFile) else CaseFile.model_validate(value)
    except (ValidationError, TypeError, ValueError):
        return None
    if len(case.explanation.split()) > 120:
        return None

    normalized = [event_dict(event) for event in events]
    event_ids = {str(event.get("id")) for event in normalized if event.get("id")}
    risk_data: Mapping[str, Any] = next(
        (event.get("data", {}) for event in normalized if event.get("type") == "risk.scored"), {}
    )
    rules = {str(rule) for rule in risk_data.get("rulesFired", [])}
    families = {
        str(reason.get("ref"))
        for reason in risk_data.get("reasons", [])
        if isinstance(reason, Mapping) and reason.get("ref")
    }
    allowed = event_ids | rules | families

    for sentence in case.sentences:
        if not sentence.refs or any(ref not in allowed for ref in sentence.refs):
            return None

    distinct_refs = {ref for sentence in case.sentences for ref in sentence.refs}
    citations = {citation.ref: citation.source for citation in case.citations}
    if set(citations) != distinct_refs or len(citations) != len(case.citations):
        return None
    for ref, source in citations.items():
        expected = f"event:{ref}" if ref in event_ids else f"rule:{ref}" if ref in rules else f"reason:{ref}"
        if ref not in allowed or source != expected:
            return None

    events_json = json.dumps(normalized, ensure_ascii=False, sort_keys=True, default=str)
    available_numbers = _numbers(events_json)
    for text in [case.summary, case.explanation, *(sentence.text for sentence in case.sentences)]:
        text_numbers = _numbers(_strip_refs(text, allowed))
        if not text_numbers.issubset(available_numbers):
            return None

    if ACTION_RANK[case.recommended_action] < ACTION_RANK[template.recommended_action]:
        return None
    if case.typology not in TYPOLOGIES:
        case = case.model_copy(update={"typology": template.typology})
    return case
