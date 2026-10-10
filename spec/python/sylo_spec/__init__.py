"""Sylo.ai shared spec package (``sylo-spec``).

Every lane imports its models, ports, EIP-712 helpers and canonical scenarios from here.
Changes are additive only (see ``spec/README.md``).
"""

from pathlib import Path

SPEC_DIR = Path(__file__).resolve().parents[2]
"""The ``/spec`` directory (holds events.schema.json, eip712.json, geo/ and fixtures/)."""

__all__ = ["SPEC_DIR"]
