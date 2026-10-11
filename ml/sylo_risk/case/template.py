from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sylo_spec.models import CaseFile

from .text_screen import TextSignals


RULE_FAMILIES = {
    "R-PV-01": "V",
    "R-FL-01": "B",
    "R-FL-02": "B",
    "R-FL-03": "B",
    "R-NM-01": "R",
    "R-HB-01": "S",
}
ACTION_RANK = {
    "NO_ACTION": 0,
    "RELEASE_AFTER_CONFIRMATION": 1,
    "CONFIRM_REVOCATION": 2,
    "ESCALATE_AML": 3,
}
CASE_EVENT_TYPES = {
    "payment.held",
    "verification.requested",
    "verification.recorded",
}


def event_dict(event: Any) -> dict[str, Any]:
    if isinstance(event, Mapping):
        return dict(event)
    if hasattr(event, "model_dump"):
        return event.model_dump(by_alias=True, mode="json")
    raise TypeError("events must contain dictionaries or spec Event models")


def _data(event: Mapping[str, Any]) -> Mapping[str, Any]:
    value = event.get("data")
    return value if isinstance(value, Mapping) else {}


def _family_for_rule(rule_id: str) -> str | None:
    if rule_id in RULE_FAMILIES:
        return RULE_FAMILIES[rule_id]
    if "SESSION" in rule_id.upper() or "SIM" in rule_id.upper() or "DEVICE" in rule_id.upper():
        return "P"
    return None


def _typology(events: list[dict[str, Any]], risk_data: Mapping[str, Any]) -> str:
    reasons = risk_data.get("reasons", [])
    rules = {str(rule) for rule in risk_data.get("rulesFired", [])}
    families = {str(reason.get("ref", "")) for reason in reasons if isinstance(reason, Mapping)}
    if "R-HB-01" in rules:
        families.discard("S")
    if "P" in families or any(_family_for_rule(rule) == "P" for rule in rules):
        return "T2 account takeover"
    if families.intersection({"V", "B"}) or any(rule.startswith(("R-PV-", "R-FL-", "R-NM-")) for rule in rules):
        return "T1 supplier impersonation"
    if "S" in families or any("STRUCT" in rule.upper() for rule in rules):
        return "T4 structuring"
    if any(str(event.get("type")) == "cluster.detected" for event in events):
        return "T3 mule cash-out"
    return "none"


def _recommended_action(events: list[dict[str, Any]], risk_data: Mapping[str, Any], typology: str) -> str:
    event_types = [str(event.get("type", "")) for event in events]
    rules = {str(rule) for rule in risk_data.get("rulesFired", [])}
    risk_tier = str(risk_data.get("tier", "")).upper()
    if (
        "R-HB-01" in rules
        or risk_tier == "CRITICAL"
        or typology in {"T3 mule cash-out", "T4 structuring"}
    ):
        return "ESCALATE_AML"
    for event in events:
        if event.get("type") == "verification.recorded":
            result = str(_data(event).get("result", "")).upper()
            answer = str(_data(event).get("answer", "")).upper()
            if result in {"DENIED", "NO_ANSWER", "NO_ANSWER_TIMEOUT"} or answer in {
                "DENY",
                "NO_ANSWER",
                "NO_ANSWER_TIMEOUT",
            }:
                return "CONFIRM_REVOCATION"
    if any(kind in event_types for kind in ("intent.revoked", "escrow.refunded")):
        return "CONFIRM_REVOCATION"
    if any(
        kind == "payment.held"
        or kind == "verification.requested"
        or (kind == "verification.recorded" and str(_data(event).get("result", "")).upper() == "CONFIRMED")
        for kind, event in zip(event_types, events)
    ):
        return "RELEASE_AFTER_CONFIRMATION"
    if risk_tier == "LOW":
        return "NO_ACTION"
    return "RELEASE_AFTER_CONFIRMATION"


def _timeline_text(event: Mapping[str, Any]) -> str:
    kind = str(event.get("type", "event"))
    data = _data(event)
    if kind == "risk.scored":
        return f"Risk scored {data.get('tier', 'unknown')}."
    if kind == "payment.held":
        return "Payment held for out-of-band confirmation."
    if kind == "verification.requested":
        return "Out-of-band verification requested."
    if kind == "verification.recorded":
        return f"Verification recorded: {data.get('result', 'unknown')}."
    if kind == "escrow.refunded":
        return "Escrow refunded."
    if kind == "escrow.released":
        return "Escrow released after confirmation."
    if kind == "intent.revoked":
        return "Payment intent revoked."
    if kind == "payment.created":
        return "Payment instruction received."
    if kind == "norms.checked":
        return "Payment route checked against corridor norms."
    if kind == "route.selected":
        return "A compliant settlement route was selected."
    if kind == "escrow.deposited":
        return "Funds deposited into escrow."
    if kind == "payment.stopped":
        return "Payment stopped."
    if kind == "payment.credited":
        return "Payment credited."
    return kind.replace(".", " ").capitalize() + "."


def _text_screen_sentences(
    signals: TextSignals | None, action: str
) -> list[dict[str, Any]]:
    if signals is None:
        return []
    prompts = {
        "change": (
            "TX-CHANGE",
            "the document announces new bank details",
        ),
        "pressure": (
            "TX-PRESSURE",
            "the document uses payment-fraud pressure",
        ),
        "injection": (
            "TX-INJECTION",
            "the document contains instructions addressed to an automated system",
        ),
    }
    sentences: list[dict[str, Any]] = []
    for name, (ref, description) in prompts.items():
        score = getattr(signals, name)
        if score is None or score < 0.5:
            continue
        text = f"Text screening (Jev): {description} (p={score:.2f})."
        if action == "RELEASE_AFTER_CONFIRMATION":
            text = f"Text screening (Jev): {description} (p={score:.2f}); verification is still required."
        sentences.append({"text": text, "refs": [ref]})
    if signals.source == "unavailable":
        sentences.append(
            {
                "text": "Text screening unavailable: treat the document as unverified.",
                "refs": ["TX-UNAVAILABLE"],
            }
        )
    return sentences


def template_case(
    payment_id: str,
    events: list[Any],
    *,
    llm: str = "off",
    text_signals: TextSignals | None = None,
) -> CaseFile:
    normalized = [event_dict(event) for event in events]
    risk_event = next((event for event in normalized if event.get("type") == "risk.scored"), {})
    risk_data = _data(risk_event)
    rules = [str(rule) for rule in risk_data.get("rulesFired", [])]
    reasons = [reason for reason in risk_data.get("reasons", []) if isinstance(reason, Mapping)]
    typology = _typology(normalized, risk_data)
    action = _recommended_action(normalized, risk_data, typology)

    sentences: list[dict[str, Any]] = []
    for reason in reasons:
        family = str(reason.get("ref", ""))
        refs = [family]
        refs.extend(rule for rule in rules if _family_for_rule(rule) == family)
        if risk_event.get("id"):
            refs.append(str(risk_event["id"]))
        sentences.append({"text": str(reason.get("text", "")), "refs": list(dict.fromkeys(refs))})

    for event in normalized:
        kind = str(event.get("type", ""))
        if kind in CASE_EVENT_TYPES or kind.startswith("escrow."):
            event_id = str(event.get("id", ""))
            if event_id:
                sentences.append({"text": _timeline_text(event), "refs": [event_id]})

    sentences.extend(_text_screen_sentences(text_signals, action))

    citations_by_ref: dict[str, dict[str, str]] = {}
    for sentence in sentences:
        for ref in sentence["refs"]:
            if ref in {str(event.get("id", "")) for event in normalized}:
                source = f"event:{ref}"
            elif ref in rules:
                source = f"rule:{ref}"
            else:
                source = f"reason:{ref}"
            citations_by_ref.setdefault(ref, {"ref": ref, "source": source})

    risk_tier = str(risk_data.get("tier", "unknown"))
    summary = f"Payment risk is {risk_tier}; recommended action: {action}."
    reason_texts = [str(reason.get("text", "")) for reason in reasons[:3] if reason.get("text")]
    explanation = " ".join(reason_texts)
    if not explanation:
        explanation = "No material risk reasons were recorded."
    if action == "RELEASE_AFTER_CONFIRMATION":
        explanation += " Keep funds held until out-of-band confirmation."
    elif action == "CONFIRM_REVOCATION":
        explanation += " Confirm the revocation and refund outcome."
    elif action == "ESCALATE_AML":
        explanation += " Escalate for sanctions or financial-crime review."
    else:
        explanation += " No additional action is recommended."

    timeline = [
        {
            "at": str(event.get("ts", _data(event).get("at", ""))),
            "event_id": str(event.get("id", "")),
            "text": _timeline_text(event),
        }
        for event in normalized
    ]
    return CaseFile.model_validate(
        {
            "paymentId": payment_id,
            "summary": summary,
            "sentences": sentences,
            "timeline": timeline,
            "typology": typology,
            "recommendedAction": action,
            "explanation": explanation,
            "citations": list(citations_by_ref.values()),
            "reportDraft": None,
            "llm": llm,
            "promptVersion": "none" if llm == "off" else "s2-v1",
            "model": "template-v1" if llm == "off" else "",
        }
    )
