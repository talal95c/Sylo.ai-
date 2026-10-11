from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from sylo_spec import SPEC_DIR
from sylo_spec.models import CaseFile
from sylo_spec.ports import CasePort

from sylo_risk.case import (
    CaseWriter,
    TemplateCaseWriter,
    TextScreen,
    TextSignals,
    explain_invalid_case,
    validate_case,
)
from sylo_risk.case.writer import SYSTEM_PROMPT, _allowed_refs

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


def _mocked_case(monkeypatch, action: str, *, text_screen: TextScreen | None = None):
    events = scene2_events()
    base = TemplateCaseWriter(text_screen=text_screen).write("PAY-2026-0002", events)
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
    events, observed = _mocked_case(monkeypatch, "ESCALATE_AML", text_screen=TextScreen(mode="off"))
    invoice = (Path(__file__).parents[1] / "sylo_risk/case/fixtures/scene2_invoice.txt").read_text()
    case = CaseWriter(
        mode="live",
        api_key="test-key",
        documents={"PAY-2026-0002": invoice},
        text_screen=TextScreen(mode="off"),
    ).write("PAY-2026-0002", events)

    assert case.llm == "live"
    assert case.recommended_action == "ESCALATE_AML"
    request = observed["kwargs"]["json"]
    assert "tools" not in request
    assert request["messages"][0]["content"] == SYSTEM_PROMPT
    assert "ˆ" in request["messages"][1]["content"]
    assert "<untrusted_document>" in request["messages"][1]["content"]
    assert "Account holder" not in request["messages"][1]["content"]
    assert request["response_format"]["type"] == "json_schema"
    assert request["temperature"] == 0
    assert request["max_tokens"] == 900


def _install_responses(monkeypatch, responses):
    requests = []

    def post(url, **kwargs):
        requests.append(kwargs)
        response = responses[len(requests) - 1]
        if isinstance(response, BaseException):
            raise response
        if isinstance(response, dict):
            return _Response(response)
        return response

    monkeypatch.setattr("sylo_risk.case.writer.httpx.post", post)
    return requests


class _ContentResponse(_Response):
    def __init__(self, content):
        self.content = content

    def json(self):
        return {"choices": [{"message": {"content": self.content}}]}


def test_strict_schema_contains_only_generated_fields_and_request_ref_enums(monkeypatch):
    events = scene2_events()
    template = TemplateCaseWriter().write("PAY-2026-0002", events)
    body = template.model_dump(by_alias=True, mode="json")
    body["recommendedAction"] = "ESCALATE_AML"
    requests = _install_responses(monkeypatch, [body])

    case = CaseWriter(mode="live", api_key="test-key").write("PAY-2026-0002", events)

    assert case.llm == "live"
    assert set(requests[0]["json"]["response_format"]) == {"type", "json_schema"}
    structured = requests[0]["json"]["response_format"]["json_schema"]
    assert structured["name"] == "sylo_case_file"
    assert structured["strict"] is True
    schema = structured["schema"]
    assert set(schema["properties"]) == {
        "summary",
        "sentences",
        "typology",
        "recommendedAction",
        "explanation",
        "citations",
    }
    assert schema["required"] == list(schema["properties"])
    assert schema["additionalProperties"] is False
    allowed_refs = _allowed_refs(events, template)
    sentence_refs = schema["properties"]["sentences"]["items"]["properties"]["refs"]["items"]
    citation_ref = schema["properties"]["citations"]["items"]["properties"]["ref"]
    assert sentence_refs["enum"] == allowed_refs
    assert citation_ref["enum"] == allowed_refs
    assert schema["properties"]["recommendedAction"]["enum"] == [
        "NO_ACTION",
        "RELEASE_AFTER_CONFIRMATION",
        "CONFIRM_REVOCATION",
        "ESCALATE_AML",
    ]


def test_invalid_first_response_is_repaired_once_without_repeating_document(monkeypatch):
    events = scene2_events()
    screen = TextScreen(mode="off")
    template = TemplateCaseWriter(
        documents={"PAY-2026-0002": "PRIVATE-INVOICE-TEXT"},
        text_screen=screen,
    ).write("PAY-2026-0002", events)
    rejected = template.model_dump(by_alias=True, mode="json")
    rejected["recommendedAction"] = "NO_ACTION"
    repaired = template.model_dump(by_alias=True, mode="json")
    repaired["recommendedAction"] = "ESCALATE_AML"
    requests = _install_responses(monkeypatch, [rejected, repaired])
    writer = CaseWriter(
        mode="live",
        api_key="test-key",
        documents={"PAY-2026-0002": "PRIVATE-INVOICE-TEXT"},
        text_screen=screen,
    )

    case = writer.write("PAY-2026-0002", events)

    assert case.llm == "live"
    assert writer.last_fallback_reason is None
    assert writer.last_repair is True
    assert len(requests) == 2
    retry_messages = requests[1]["json"]["messages"]
    assert retry_messages[-2] == {
        "role": "assistant",
        "content": json.dumps(rejected),
    }
    assert retry_messages[-1] == {
        "role": "user",
        "content": (
            "Your previous JSON was rejected: invalid:less_strict_action. "
            "Return corrected JSON only."
        ),
    }
    assert "PRIVATE-INVOICE-TEXT" not in retry_messages[-1]["content"]
    assert "untrusted_document" not in retry_messages[-1]["content"]
    assert all(request["timeout"] <= writer.timeout for request in requests)


def test_invalid_twice_falls_back_with_final_reason(monkeypatch):
    events = scene2_events()
    template = TemplateCaseWriter().write("PAY-2026-0002", events)
    rejected = template.model_dump(by_alias=True, mode="json")
    rejected["recommendedAction"] = "NO_ACTION"
    requests = _install_responses(monkeypatch, [rejected, rejected])
    writer = CaseWriter(mode="live", api_key="test-key")

    case = writer.write("PAY-2026-0002", events)

    assert case.llm == "off"
    assert writer.last_fallback_reason == "invalid:less_strict_action"
    assert writer.last_repair is False
    assert len(requests) == 2


def test_parse_error_is_retried_once(monkeypatch):
    events = scene2_events()
    template = TemplateCaseWriter().write("PAY-2026-0002", events)
    valid = template.model_dump(by_alias=True, mode="json")
    valid["recommendedAction"] = "ESCALATE_AML"
    requests = _install_responses(
        monkeypatch,
        [_ContentResponse("not-json"), valid],
    )
    writer = CaseWriter(mode="live", api_key="test-key")

    case = writer.write("PAY-2026-0002", events)

    assert case.llm == "live"
    assert writer.last_repair is True
    assert len(requests) == 2
    assert requests[1]["json"]["messages"][-1]["content"] == (
        "Your previous JSON was rejected: parse_error. Return corrected JSON only."
    )


def test_repaired_answer_less_strict_than_template_is_rejected(monkeypatch):
    events = scene2_events()
    template = TemplateCaseWriter().write("PAY-2026-0002", events)
    unknown = template.model_dump(by_alias=True, mode="json")
    unknown["sentences"][0]["refs"] = ["evt-unknown"]
    unknown["citations"][0].update({"ref": "evt-unknown", "source": "event:evt-unknown"})
    less_strict = template.model_dump(by_alias=True, mode="json")
    less_strict["recommendedAction"] = "NO_ACTION"
    requests = _install_responses(monkeypatch, [unknown, less_strict])
    writer = CaseWriter(mode="live", api_key="test-key")

    case = writer.write("PAY-2026-0002", events)

    assert case.llm == "off"
    assert writer.last_fallback_reason == "invalid:less_strict_action"
    assert writer.last_repair is False
    assert len(requests) == 2


def test_timeout_falls_back_without_retry(monkeypatch):
    events = scene2_events()
    requests = _install_responses(monkeypatch, [httpx.TimeoutException("timed out")])
    writer = CaseWriter(mode="live", api_key="test-key")

    case = writer.write("PAY-2026-0002", events)

    assert case.llm == "off"
    assert writer.last_fallback_reason == "timeout"
    assert writer.last_repair is False
    assert len(requests) == 1


def test_http_error_falls_back_without_retry_and_records_status(monkeypatch):
    events = scene2_events()
    response = httpx.Response(
        400,
        text="schema rejected",
        request=httpx.Request("POST", "https://api.mistral.ai/v1/chat/completions"),
    )
    error = httpx.HTTPStatusError(
        "bad request",
        request=response.request,
        response=response,
    )
    requests = _install_responses(monkeypatch, [error])
    writer = CaseWriter(mode="live", api_key="test-key")

    case = writer.write("PAY-2026-0002", events)

    assert case.llm == "off"
    assert writer.last_fallback_reason == "http_400"
    assert writer.last_http_error_body == "schema rejected"
    assert len(requests) == 1


def test_live_missing_api_key_records_template_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    writer = CaseWriter(mode="live", cache_dir=tmp_path)

    case = writer.write("PAY-2026-0002", scene2_events())

    assert case.llm == "off"
    assert writer.last_fallback_reason == "no_api_key"
    assert writer.last_repair is False


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda value: value.pop("summary"), "missing_field:summary"),
        (lambda value: value.update({"summary": []}), "invalid_case"),
        (lambda value: value["sentences"][0].update({"refs": []}), "missing_refs"),
        (
            lambda value: value["sentences"][0].update({"refs": ["evt-unknown"]}),
            "unknown_ref",
        ),
        (
            lambda value: value["citations"].append(value["citations"][0]),
            "duplicate_citation",
        ),
        (lambda value: value["citations"].pop(), "citation_mismatch"),
        (
            lambda value: value["citations"][0].update({"source": "unknown"}),
            "invalid_citation_source",
        ),
        (
            lambda value: value.update({"summary": "Payment amount 987654321."}),
            "unsupported_claim",
        ),
        (
            lambda value: value.update({"recommendedAction": "NO_ACTION"}),
            "less_strict_action",
        ),
        (
            lambda value: value.update({"explanation": "word " * 121}),
            "explanation_too_long",
        ),
    ],
)
def test_explain_invalid_case_returns_a_reason_code(mutation, reason):
    events = scene2_events()
    template = TemplateCaseWriter().write("PAY-2026-0002", events)
    value = template.model_dump(by_alias=True, mode="json")
    mutation(value)

    assert explain_invalid_case(value, events, template) == reason


def test_explain_invalid_case_returns_none_for_valid_output():
    events = scene2_events()
    template = TemplateCaseWriter().write("PAY-2026-0002", events)

    assert explain_invalid_case(template, events, template) is None


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


def _renumbered(events: list[dict], offset: int) -> list[dict]:
    return [{**event, "id": f"evt-{int(event['id'][4:]) + offset:06d}", "seq": event["seq"] + offset} for event in events]


def test_scene2_cache_survives_earlier_scenes_in_the_session():
    events = _renumbered([event for event in scene2_events() if event["type"] != "case.ready"], 45)
    case = CaseWriter(mode="cached").write("PAY-2026-0002", events)

    assert case.llm == "cached"
    ids = {event["id"] for event in events}
    cited_events = {ref for sentence in case.sentences for ref in sentence.refs if ref.startswith("evt-")}
    assert cited_events and cited_events <= ids
    assert [entry.event_id for entry in case.timeline] == [event["id"] for event in events]


def test_scene2_cache_falls_back_when_a_cited_event_is_missing():
    events = [event for event in scene2_events() if event["type"] not in {"case.ready", "payment.held"}]
    assert CaseWriter(mode="cached").write("PAY-2026-0002", events).llm == "off"


def test_recorded_mistral_tx_citation_source_is_normalized(monkeypatch):
    events = scene2_events()
    payment_id = "PAY-2026-0002"
    document = "Synthetic invoice text"

    class FixedTextScreen:
        mode = "off"

        def screen(self, _document):
            return TextSignals(1.0, 1.0, 1.0, "jev-live", "jev-text-v1")

    screen = FixedTextScreen()
    template = TemplateCaseWriter(
        documents={payment_id: document},
        text_screen=screen,
    ).write(payment_id, events)
    response = template.model_dump(by_alias=True, mode="json")
    citation = next(citation for citation in response["citations"] if citation["ref"] == "TX-CHANGE")
    citation["source"] = "text:TX-CHANGE"
    requests = _install_responses(monkeypatch, [response])

    case = CaseWriter(
        mode="live",
        api_key="test-key",
        documents={payment_id: document},
        text_screen=screen,
    ).write(payment_id, events)

    assert case.llm == "live"
    assert next(c.source for c in case.citations if c.ref == "TX-CHANGE") == "reason:TX-CHANGE"
    assert len(requests) == 1


def test_unexpected_live_writer_warning_redacts_document_and_key(monkeypatch, caplog):
    payment_id = "PAY-2026-0002"
    document = "PRIVATE-INVOICE-CONTENT"
    api_key = "PRIVATE-MISTRAL-KEY"

    def fail(_url, **_kwargs):
        raise RuntimeError(f"request failed for {document} with {api_key}")

    monkeypatch.setattr("sylo_risk.case.writer.httpx.post", fail)
    CaseWriter(
        mode="live",
        api_key=api_key,
        documents={payment_id: document},
        text_screen=TextScreen(mode="off"),
    ).write(payment_id, scene2_events())

    assert document not in caplog.text
    assert api_key not in caplog.text
    assert "[redacted]" in caplog.text
