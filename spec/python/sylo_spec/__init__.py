"""sylo-spec: the shared interfaces of Sylo.ai (models, ports, EIP-712, scenarios, conformance).

The data files of the spec (event schema, EIP-712 vector, geography, fixtures) live two
folders up, in `/spec`. This package is installed in editable mode from the repository.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

SPEC_DIR = Path(__file__).resolve().parents[2]
EVENTS_SCHEMA_PATH = SPEC_DIR / "events.schema.json"
EIP712_VECTOR_PATH = SPEC_DIR / "eip712.json"
INSTITUTIONS_PATH = SPEC_DIR / "geo" / "institutions.json"
FIXTURES_DIR = SPEC_DIR / "fixtures"

FIXTURE_FILES = (
    "scene1-legit.jsonl",
    "scene2-diverted.jsonl",
    "scene2-deny.jsonl",
    "scene2-confirm.jsonl",
    "scene2b-release-revoked.jsonl",
)

__version__ = "0.1.0"


@lru_cache(maxsize=1)
def load_event_schema() -> dict[str, Any]:
    return json.loads(EVENTS_SCHEMA_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def event_validator():
    """A jsonschema validator for one event envelope (draft 2020-12, formats checked)."""
    from jsonschema import Draft202012Validator, FormatChecker

    schema = load_event_schema()
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_event(event: dict[str, Any]) -> None:
    """Raise jsonschema.ValidationError if `event` does not match `events.schema.json`."""
    event_validator().validate(event)


@lru_cache(maxsize=1)
def load_geo() -> dict[str, Any]:
    return json.loads(INSTITUTIONS_PATH.read_text(encoding="utf-8"))


def institution_ids() -> set[str]:
    return {i["id"] for i in load_geo()["institutions"]}


def read_fixture(name: str) -> list[dict[str, Any]]:
    path = FIXTURES_DIR / name
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
