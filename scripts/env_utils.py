from __future__ import annotations

import os
from pathlib import Path


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def env_value(key: str, env_file: Path | None = None, default: str = "") -> str:
    value = os.environ.get(key)
    if value:
        return value
    if env_file is not None:
        return load_env_file(env_file).get(key, default)
    return default


def first_env(keys: list[str], env_file: Path | None = None, default: str = "") -> str:
    for key in keys:
        value = env_value(key, env_file)
        if value:
            return value
    return default
