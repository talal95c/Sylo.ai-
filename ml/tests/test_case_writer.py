from __future__ import annotations

import json
from pathlib import Path

import pytest
from sylo_spec import SPEC_DIR
from sylo_spec.models import CaseFile
from sylo_spec.ports import CasePort

from sylo_risk.case import CaseWriter, TemplateCaseWriter, validate_case
from sylo_risk.case.writer import SYSTEM_PROMPT

REPO = SPEC_DIR.parent


def scene2_events() -> list[dict]:
    path = SPEC_DIR / "fixtures" / "scene2-diverted.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def denied_events() -> list[dict]:
    prefix = scene2_events()
    path = SPEC_DIR / "fixtures" / "scene2-deny.jsonl"
    return prefix + [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_template_case_is_deterministic_and_schema_valid():
    events = scene2_events()
    writer = TemplateCaseWriter()
    first = writer.write("PAY-2026-0002", events)
    second = writer.write("PAY-2026-0002", events)

    assert isinstance(writer, CasePort)
    assert first == second
    assert first.typology == "T1 supplier impersonation"
    assert first.recommended_action == "RELEASE_AFTER_CONFIRMATION"
    assert first.timeline[0].event_id == events[0]["id"]
    assert all(sentence.refs for sentence in first.sentences)
    assert first.model == "template-v1"
    assert first.prompt_version == "none"


def test_template_recommends_revocation_after_denial():
    case = TemplateCaseWriter().write("PAY-2026-0002", denied_events())
    assert case.recommended_action == "CONFIRM_REVOCATION"


def test_validator_replaces_out_of_set_typology_but_accepts_a_known_typology():
    events = scene2_events()
    template = TemplateCaseWriter().write("PAY-2026-0002", events)
    valid = template.model_copy(update={"typology": "T2 account takeover"})
    invalid = template.model_copy(update={"typology": "T9 fabricated"})

    assert validate_case(valid, events, template).typology == "T2 account takeover"
    assert validate_case(invalid, events, template).typology == template.typology


@pytest.mark.parametrize(
    "mutation",
    [
        lambda case: case.model_copy(
            update={"sentences": [case.sentences[0].model_copy(update={"refs": []}), *case.sentences[1:]]}
        ),
        lambda case: case.model_copy(
            update={
                "sentences": [case.sentences[0].model_copy(update={"refs": ["evt-unknown"]}), *case.sentences[1:]],
                "citations": [case.citations[0].model_copy(update={"ref": "evt-unknown", "source": "event:evt-unknown"}), *case.citations[1:]],
            }
        ),
        lambda case: case.model_copy(update={"summary": "The payment amount was EUR 987654321."}),
        lambda case: case.model_copy(update={"recommended_action": "NO_ACTION"}),
        lambda case: case.model_copy(update={"explanation": "word " * 121}),
    ],
)
def test_validator_rejects_uncited_unknown_fabricated_looser_and_long_output(mutation):
    events = scene2_events()
    template = TemplateCaseWriter().write("PAY-2026-0002", events)
    assert validate_case(mutation(template), events, template) is None


class _Response:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": json.dumps(self.body)}}]}


def _mocked_case(monkeypatch, action: str):
    events = scene2_events()
    base = TemplateCaseWriter().write("PAY-2026-0002", events)
    body = base.model_dump(by_alias=True, mode="json")
    body["recommendedAction"] = action
    observed = {}

    def post(url, **kwargs):
        observed["url"] = url
        observed["kwargs"] = kwargs
        return _Response(body)

    monkeypatch.setattr("sylo_risk.case.writer.httpx.post", post)
    return events, observed


def test_injected_less_strict_action_is_rejected(monkeypatch):
    events, _ = _mocked_case(monkeypatch, "NO_ACTION")
    case = CaseWriter(mode="live", api_key="test-key").write("PAY-2026-0002", events)
    assert case.llm == "off"
    assert case.recommended_action == "RELEASE_AFTER_CONFIRMATION"


def test_stricter_action_is_accepted_and_prompt_is_spotlighted(monkeypatch):
    events, observed = _mocked_case(monkeypatch, "ESCALATE_AML")
    invoice = (Path(__file__).parents[1] / "sylo_risk/case/fixtures/scene2_invoice.txt").read_text()
    case = CaseWriter(
        mode="live",
        api_key="test-key",
        documents={"PAY-2026-0002": invoice},
    ).write("PAY-2026-0002", events)

    assert case.llm == "live"
    assert case.recommended_action == "ESCALATE_AML"
    request = observed["kwargs"]["json"]
    assert "tools" not in request
    assert request["messages"][0]["content"] == SYSTEM_PROMPT
    assert "ˆ" in request["messages"][1]["content"]
    assert "<untrusted_document>" in request["messages"][1]["content"]
    assert "Account holder" not in request["messages"][1]["content"]


def test_cache_hit_is_revalidated_and_invalid_cache_falls_back(tmp_path):
    events = scene2_events()
    writer = TemplateCaseWriter()
    template = writer.write("PAY-2026-0002", events)
    path = tmp_path / "PAY-2026-0002.json"
    path.write_text(template.model_dump_json(by_alias=True), encoding="utf-8")

    cached = CaseWriter(mode="cached", cache_dir=tmp_path).write("PAY-2026-0002", events)
    assert cached.llm == "cached"

    body = template.model_dump(by_alias=True, mode="json")
    body["summary"] = "Fabricated payment amount 987654321."
    path.write_text(json.dumps(body), encoding="utf-8")
    fallback = CaseWriter(mode="cached", cache_dir=tmp_path).write("PAY-2026-0002", events)
    assert fallback.llm == "off"
