from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _env_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip().removeprefix("export ").strip()
        if key:
            keys.add(key)
    return keys


class AgentCapabilitiesTest(unittest.TestCase):
    def test_agent_capability_catalog_covers_env_example(self) -> None:
        catalog = json.loads((ROOT / "config" / "agent_capabilities.json").read_text(encoding="utf-8"))
        declared = set(catalog["declared_env"])
        self.assertLessEqual(_env_keys(ROOT / ".env.example"), declared)

    def test_agent_capability_reporter_is_redacted_and_checkable(self) -> None:
        result = subprocess.run(
            [
                "python3",
                "scripts/agent_capabilities.py",
                "--env-file",
                ".env.example",
                "--profile",
                "repo",
                "--format",
                "json",
                "--check",
            ],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        report = json.loads(result.stdout)
        self.assertTrue(report["secrets_omitted"])
        self.assertTrue(report["mcp"]["deepwiki_configured"])
        self.assertIn("deepwiki-repo-context", {item["id"] for item in report["capabilities"]})
        self.assertTrue(all("value" not in item for item in report["capabilities"]))


if __name__ == "__main__":
    unittest.main()
