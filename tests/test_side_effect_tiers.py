from __future__ import annotations

import unittest
from pathlib import Path

from agent_harness.side_effect_tiers import SIDE_EFFECT_TIERS, side_effect_axes


ROOT = Path(__file__).resolve().parents[1]


class SideEffectTierTests(unittest.TestCase):
    def test_profile_matrix_defines_three_runtime_axes(self) -> None:
        self.assertEqual(
            {name: tier.axes() for name, tier in SIDE_EFFECT_TIERS.items()},
            {
                "contract": {
                    "execution_profile": "contract",
                    "side_effect_tier": "contract",
                    "agent_mode": "contract",
                    "render_mode": "none",
                    "publish_mode": "none",
                },
                "provider": {
                    "execution_profile": "provider",
                    "side_effect_tier": "provider",
                    "agent_mode": "provider",
                    "render_mode": "local",
                    "publish_mode": "contract-check",
                },
                "lambda": {
                    "execution_profile": "lambda",
                    "side_effect_tier": "lambda",
                    "agent_mode": "provider",
                    "render_mode": "lambda",
                    "publish_mode": "contract-check",
                },
                "live": {
                    "execution_profile": "live",
                    "side_effect_tier": "live",
                    "agent_mode": "provider",
                    "render_mode": "lambda",
                    "publish_mode": "live",
                },
            },
        )

    def test_lambda_wrapper_uses_delete_after_and_default_concurrency(self) -> None:
        text = (ROOT / "scripts" / "lambda_render.sh").read_text(encoding="utf-8")
        self.assertIn('FRAMES_PER_LAMBDA="${SEARCHPO_LAMBDA_FRAMES_PER_LAMBDA:-}"', text)
        self.assertIn('CONCURRENCY="${SEARCHPO_LAMBDA_CONCURRENCY:-${REMOTION_LAMBDA_CONCURRENCY:-4}}"', text)
        self.assertIn('RENDER_CMD+=(--delete-after "$DELETE_AFTER")', text)
        self.assertIn('STILL_CMD+=(--delete-after "$DELETE_AFTER")', text)
        self.assertIn('RENDER_CMD+=(--concurrency "$CONCURRENCY")', text)
        self.assertIn('RENDER_CMD+=(--frames-per-lambda "$FRAMES_PER_LAMBDA")', text)

    def test_side_effect_axes_ignore_legacy_remotion_render_mode_for_contract(self) -> None:
        axes = side_effect_axes("contract", {"SEARCHPO_REMOTION_RENDER_MODE": "local"})
        self.assertEqual(axes["render_mode"], "none")
        self.assertEqual(axes["publish_mode"], "none")


if __name__ == "__main__":
    unittest.main()
