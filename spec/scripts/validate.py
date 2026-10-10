"""Validate every recorded fixture against events.schema.json.

    cd spec/python && uv run python ../scripts/validate.py

Checks, per file: one JSON event per line, schema-valid, `seq` increasing by one,
`id` matching `seq`, institution ids that exist in geo/institutions.json.
Exit code 1 on the first problem.
"""

import json
import sys

from jsonschema import ValidationError

from sylo_spec import FIXTURE_FILES, FIXTURES_DIR, event_validator, institution_ids

# The file each branch fixture continues (its first seq = last seq of the parent + 1).
CONTINUES = {
    "scene2-deny.jsonl": "scene2-diverted.jsonl",
    "scene2-confirm.jsonl": "scene2-diverted.jsonl",
    "scene2b-release-revoked.jsonl": "scene2-deny.jsonl",
}


def _load(name: str) -> list[dict]:
    path = FIXTURES_DIR / name
    if not path.exists():
        raise SystemExit(f"missing fixture: {path} (run `make fixtures`)")
    events = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            raise SystemExit(f"{name}:{number}: empty line")
        events.append(json.loads(line))
    if not events:
        raise SystemExit(f"{name}: no events")
    return events


def _institutions_in(value) -> list[str]:
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ("from", "to", "institutionId") and isinstance(item, str):
                found.append(item)
            else:
                found.extend(_institutions_in(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_institutions_in(item))
    return found


def main() -> int:
    validator = event_validator()
    known = institution_ids()
    loaded = {name: _load(name) for name in FIXTURE_FILES}
    total = 0
    for name, events in loaded.items():
        parent = CONTINUES.get(name)
        expected = loaded[parent][-1]["seq"] + 1 if parent else 1
        for index, event in enumerate(events, start=1):
            try:
                validator.validate(event)
            except ValidationError as err:
                print(f"{name}:{index}: {event.get('type')}: {err.message}", file=sys.stderr)
                return 1
            if event["seq"] != expected:
                print(f"{name}:{index}: seq {event['seq']}, expected {expected}", file=sys.stderr)
                return 1
            if event["id"] != f"evt-{event['seq']:06d}":
                print(f"{name}:{index}: id {event['id']} does not match seq {event['seq']}", file=sys.stderr)
                return 1
            unknown = [i for i in _institutions_in(event["data"]) if i not in known]
            if unknown:
                print(f"{name}:{index}: unknown institution ids {unknown}", file=sys.stderr)
                return 1
            expected += 1
        total += len(events)
        print(f"ok  {name}: {len(events)} events (seq {events[0]['seq']}–{events[-1]['seq']})")
    print(f"{total} events valid in {len(loaded)} fixtures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
