#!/usr/bin/env python3
"""Static guard for safe-by-default command wiring."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    scripts = package.get("scripts") or {}
    e2e = scripts.get("e2e", "")
    if "SEARCHPO_DOUYIN_LIVE=1" in e2e:
        fail("package.json script `e2e` must not enable live publishing")
    if "SEARCHPO_REMOTION_RENDER_MODE=lambda" in e2e or "SEARCHPO_E2E_PROFILE=lambda" in e2e:
        fail("package.json script `e2e` must not use Lambda/S3 by default")
    if "SEARCHPO_E2E_PROFILE=contract" not in e2e:
        fail("package.json script `e2e` must declare SEARCHPO_E2E_PROFILE=contract")

    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    required_defaults = {
        "SEARCHPO_DOUYIN_LIVE=0": "live upload must default off",
        "SEARCHPO_E2E_PROFILE=contract": "E2E profile must default to contract",
        "SEARCHPO_REMOTION_RENDER_MODE=local": "Remotion render must default local",
    }
    for needle, reason in required_defaults.items():
        if needle not in env_example:
            fail(f".env.example missing `{needle}`: {reason}")

    workflow_dir = ROOT / ".github" / "workflows"
    if workflow_dir.exists():
        for path in workflow_dir.glob("*.yml"):
            text = path.read_text(encoding="utf-8")
            if "SEARCHPO_DOUYIN_LIVE=1" in text:
                fail(f"{path} must not enable live publishing in CI")
    print("no-live guard passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
