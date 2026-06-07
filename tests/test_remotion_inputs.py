from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.verify_remotion_inputs import verify_render_inputs


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class RemotionInputVerifierTests(unittest.TestCase):
    def test_verify_render_inputs_accepts_prepared_props_and_generated_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            props = run_dir / "remotion_input_props.json"
            tsx = run_dir / "AgentVisual.generated.tsx"
            css = run_dir / "agent-visual.generated.css"
            props.write_text('{"title":"Demo"}\n', encoding="utf-8")
            tsx.write_text("export const AgentVisualGenerated = () => null;\n", encoding="utf-8")
            css.write_text(".agent { color: white; }\n", encoding="utf-8")
            write_json(
                run_dir / "render_input_manifest.json",
                {
                    "props": str(props),
                    "props_sha256": sha256_file(props),
                    "agent_visual_source": str(tsx),
                    "agent_visual_source_sha256": sha256_file(tsx),
                    "agent_visual_css": str(css),
                    "agent_visual_css_sha256": sha256_file(css),
                },
            )

            self.assertEqual(verify_render_inputs(run_dir, props), [])

    def test_verify_render_inputs_rejects_missing_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            props = run_dir / "remotion_input_props.json"
            props.write_text("{}\n", encoding="utf-8")

            errors = verify_render_inputs(run_dir, props)

            self.assertIn("Missing render input manifest", "; ".join(errors))

    def test_verify_render_inputs_rejects_stale_generated_css(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            props = run_dir / "remotion_input_props.json"
            tsx = run_dir / "AgentVisual.generated.tsx"
            css = run_dir / "agent-visual.generated.css"
            props.write_text('{"title":"Demo"}\n', encoding="utf-8")
            tsx.write_text("export const AgentVisualGenerated = () => null;\n", encoding="utf-8")
            css.write_text(".agent { color: white; }\n", encoding="utf-8")
            expected_css_sha = sha256_file(css)
            css.write_text(".agent { color: red; }\n", encoding="utf-8")
            write_json(
                run_dir / "render_input_manifest.json",
                {
                    "props": str(props),
                    "props_sha256": sha256_file(props),
                    "agent_visual_source": str(tsx),
                    "agent_visual_source_sha256": sha256_file(tsx),
                    "agent_visual_css": str(css),
                    "agent_visual_css_sha256": expected_css_sha,
                },
            )

            errors = verify_render_inputs(run_dir, props)

            self.assertIn("Prepared agent visual CSS is stale", "; ".join(errors))
