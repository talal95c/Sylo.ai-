import json

from jsonschema import Draft202012Validator

from sylo_spec import SPEC_DIR
from sylo_spec.models import CaseFile, RiskResult, Tier
from sylo_spec.ports import CasePort

EVENTS = Draft202012Validator(json.loads((SPEC_DIR / "events.schema.json").read_text(encoding="utf-8")))
METRICS = Draft202012Validator(json.loads((SPEC_DIR / "metrics.schema.json").read_text(encoding="utf-8")))

CASE = {
    "paymentId": "0x" + "ab" * 32,
    "summary": "New account opened 9 days ago, announced by an invoice e-mail from a lookalike domain.",
    "sentences": [{"text": "The account is 9 days old and has never been paid.", "refs": ["R-FL-01"]}],
    "timeline": [{"at": "2026-10-11T09:00:01.000Z", "eventId": "evt-000004", "text": "Risk scored MEDIUM."}],
    "typology": "T1",
    "recommendedAction": "CONFIRM_REVOCATION",
    "explanation": "Held because the beneficiary changed through an untrusted channel.",
    "citations": [{"ref": "R-FL-01", "source": "rule"}],
    "reportDraft": None,
    "llm": "off",
    "promptVersion": "template-v1",
    "model": "template",
}


def event(kind: str, data: dict) -> dict:
    return {"v": 1, "seq": 1, "id": "evt-000001", "ts": "2026-10-11T09:00:00.000Z", "type": kind,
            "paymentId": CASE["paymentId"], "simulated": True, "data": data}


def test_case_file_round_trips_and_validates_as_case_ready():
    case = CaseFile.model_validate(CASE)
    data = case.model_dump(by_alias=True, mode="json")
    assert data == CASE
    assert not list(EVENTS.iter_errors(event("case.ready", data)))


def test_case_ready_rejects_unknown_action_and_uncited_sentence():
    bad = dict(CASE, recommendedAction="APPROVE")
    assert list(EVENTS.iter_errors(event("case.ready", bad)))
    uncited = dict(CASE, sentences=[{"text": "Trust me.", "refs": []}])
    assert list(EVENTS.iter_errors(event("case.ready", uncited)))


def test_oob_resolvable_is_optional_and_false_by_default():
    base = {"score": 64, "tier": Tier.MEDIUM, "floorTier": Tier.MEDIUM, "rulesFired": [], "reasons": [], "model": "rules-v1"}
    assert RiskResult.model_validate(base).oob_resolvable is False
    assert RiskResult.model_validate(dict(base, oobResolvable=True)).oob_resolvable is True
    scored = {k: v for k, v in base.items() if k != "floorTier"}
    assert not list(EVENTS.iter_errors(event("risk.scored", dict(scored, tier="MEDIUM", oobResolvable=True))))


def test_case_port_is_a_runtime_protocol():
    class Writer:
        name = "template"

        def write(self, payment_id, events):
            return CaseFile.model_validate(CASE)

    assert isinstance(Writer(), CasePort)


def test_metrics_sample_validates_and_is_labelled_sample():
    sample = json.loads((SPEC_DIR / "metrics.sample.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(METRICS.schema)
    assert not list(METRICS.iter_errors(sample))
    assert sample["sample"] is True
    assert list(METRICS.iter_errors(dict(sample, metrics=dict(sample["metrics"], recallAll=1.5))))
