"""Hash-chained decision log (roadmap A1.6, PRD module M8).

Every event of the engine becomes one line ``{ seq, prevHash, type, payload, hash }`` where
``hash = keccak256(canonical_json({ seq, prevHash, type, payload }))`` and ``prevHash`` is the hash
of the line before. Changing or removing any line breaks every hash after it:

    python -m sylo.journal verify            # check engine/data/log.jsonl
    python -m sylo.journal verify <file>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sylo_spec.canonical import hash_record

from . import ENGINE_DIR

GENESIS = "0x" + "00" * 32
DEFAULT_PATH = ENGINE_DIR / "data" / "log.jsonl"


def entry_hash(seq: int, prev_hash: str, type_: str, payload: dict[str, Any]) -> str:
    return hash_record({"seq": seq, "prevHash": prev_hash, "type": type_, "payload": payload})


def read(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def verify(entries: list[dict[str, Any]]) -> tuple[bool, str]:
    """Recompute the chain. Returns (ok, message); the message names the first line that does not fit."""
    previous = GENESIS
    for index, entry in enumerate(entries, start=1):
        try:
            seq, prev_hash, type_, payload, stored = (
                entry["seq"],
                entry["prevHash"],
                entry["type"],
                entry["payload"],
                entry["hash"],
            )
        except (KeyError, TypeError):
            return False, f"line {index}: not a log entry"
        if seq != index:
            return False, f"line {index}: seq is {seq}, expected {index} (a line was removed or inserted)"
        if prev_hash != previous:
            return False, f"line {index} (seq {seq}): prevHash does not match the line before"
        if entry_hash(seq, prev_hash, type_, payload) != stored:
            return False, f"line {index} (seq {seq}, {type_}): the content does not match its hash"
        previous = stored
    return True, f"{len(entries)} entries, chain intact, head {previous}"


class Journal:
    """Append-only log, in memory and (when ``path`` is given) on disk. An existing file is continued."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else None
        self._entries: list[dict[str, Any]] = []
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists():
                try:
                    self._entries = read(self.path)
                except json.JSONDecodeError:
                    # Fail safe: keep the damaged file as evidence and start a new chain.
                    self.path.replace(self.path.with_suffix(self.path.suffix + ".damaged"))

    @property
    def head(self) -> str:
        return self._entries[-1]["hash"] if self._entries else GENESIS

    @property
    def entries(self) -> list[dict[str, Any]]:
        return list(self._entries)

    def append(self, type_: str, payload: dict[str, Any]) -> dict[str, Any]:
        seq = len(self._entries) + 1
        prev_hash = self.head
        entry = {
            "seq": seq,
            "prevHash": prev_hash,
            "type": type_,
            "payload": payload,
            "hash": entry_hash(seq, prev_hash, type_, payload),
        }
        self._entries.append(entry)
        if self.path is not None:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def record_event(self, event: dict[str, Any]) -> None:
        """Bus listener: one log line per event."""
        self.append(
            event["type"],
            {
                "eventId": event["id"],
                "paymentId": event["paymentId"],
                "ts": event["ts"],
                "simulated": event["simulated"],
                "data": event["data"],
            },
        )

    def for_payment(self, payment_id: str) -> list[dict[str, Any]]:
        return [entry for entry in self._entries if entry["payload"].get("paymentId") == payment_id]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["verify"])
    parser.add_argument("path", nargs="?", default=str(DEFAULT_PATH))
    args = parser.parse_args(argv)

    path = Path(args.path)
    if not path.exists():
        print(f"no decision log at {path} (run a scenario first)", file=sys.stderr)
        return 1
    try:
        entries = read(path)
    except json.JSONDecodeError as err:
        print(f"decision log TAMPERED: {path} is not valid JSON lines ({err})", file=sys.stderr)
        return 1
    ok, message = verify(entries)
    if ok:
        print(f"decision log OK: {message}")
        return 0
    print(f"decision log TAMPERED: {message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
