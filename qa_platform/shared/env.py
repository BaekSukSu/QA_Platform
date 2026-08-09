from __future__ import annotations

import os
from pathlib import Path


def load_key_value_env_file(
    env_path: Path,
    *,
    override: bool = False,
) -> None:
    if not env_path.is_file():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue

        if not override and os.environ.get(key):
            continue

        os.environ[key] = _strip_matching_quotes(value.strip())


def _strip_matching_quotes(value: str) -> str:
    if len(value) < 2:
        return value
    if value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
