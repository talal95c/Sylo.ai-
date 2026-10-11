"""Reads the repository's ``.env`` for the command-line tools (guardian, scene scripts)."""

from __future__ import annotations

import os
import re
from pathlib import Path

ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"
_COMMENT = re.compile(r"\s+#.*$")


def load_env_file(path: Path = ROOT_ENV) -> None:
    """Sets the variables of ``path`` that the environment does not set already. A missing file is fine."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.removeprefix("export ").strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = _COMMENT.sub("", value)
        os.environ.setdefault(key, value)
