from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from typing import Mapping


@dataclass(frozen=True)
class SideEffectTier:
    execution_profile: str
    agent_mode: str
    render_mode: str
    remotion_render_mode: str
    publish_mode: str
    douyin_check_level: str
    creates_media: bool
    uses_providers: bool
    uses_lambda: bool
    allows_live_upload: bool
    allowed_effects: tuple[str, ...]
    forbidden_effects: tuple[str, ...]
    required_env_groups: tuple[str, ...]
    success_criteria: tuple[str, ...]

    @property
    def side_effect_tier(self) -> str:
        return self.execution_profile

    def axes(self) -> dict[str, str]:
        return {
            "execution_profile": self.execution_profile,
            "side_effect_tier": self.side_effect_tier,
            "agent_mode": self.agent_mode,
            "render_mode": self.render_mode,
            "publish_mode": self.publish_mode,
        }

    def to_dict(self) -> dict[str, object]:
        return asdict(self) | {"side_effect_tier": self.side_effect_tier}


SIDE_EFFECT_TIERS: dict[str, SideEffectTier] = {
    "contract": SideEffectTier(
        execution_profile="contract",
        agent_mode="contract",
        render_mode="none",
        remotion_render_mode="local",
        publish_mode="none",
        douyin_check_level="manifest",
        creates_media=False,
        uses_providers=False,
        uses_lambda=False,
        allows_live_upload=False,
        allowed_effects=("public_source_fetch", "ignored_runtime_artifacts", "text_preflight"),
        forbidden_effects=("provider_api", "media_render", "aws_lambda_s3", "douyin_upload"),
        required_env_groups=(),
        success_criteria=("cross_check_pass", "content_preflight_pass", "no_media_or_final_release_artifacts"),
    ),
    "provider": SideEffectTier(
        execution_profile="provider",
        agent_mode="provider",
        render_mode="local",
        remotion_render_mode="local",
        publish_mode="contract-check",
        douyin_check_level="adapter",
        creates_media=True,
        uses_providers=True,
        uses_lambda=False,
        allows_live_upload=False,
        allowed_effects=("provider_api", "local_remotion_render", "ignored_runtime_artifacts", "douyin_adapter_preflight"),
        forbidden_effects=("aws_lambda_s3", "douyin_upload"),
        required_env_groups=("script_agents_required", "research_required"),
        success_criteria=("artifact_manifest_bound", "deterministic_visual_audit_pass", "gemini_visual_audit_pass", "douyin_contract_gate_pass"),
    ),
    "lambda": SideEffectTier(
        execution_profile="lambda",
        agent_mode="provider",
        render_mode="lambda",
        remotion_render_mode="lambda",
        publish_mode="contract-check",
        douyin_check_level="adapter",
        creates_media=True,
        uses_providers=True,
        uses_lambda=True,
        allows_live_upload=False,
        allowed_effects=("provider_api", "aws_lambda_s3_render", "ignored_runtime_artifacts", "douyin_adapter_preflight"),
        forbidden_effects=("douyin_upload",),
        required_env_groups=("script_agents_required", "research_required", "remotion_lambda_required"),
        success_criteria=("lambda_site_redeployed", "artifact_manifest_bound", "deterministic_visual_audit_pass", "gemini_visual_audit_pass", "douyin_contract_gate_pass"),
    ),
    "live": SideEffectTier(
        execution_profile="live",
        agent_mode="provider",
        render_mode="lambda",
        remotion_render_mode="lambda",
        publish_mode="live",
        douyin_check_level="adapter",
        creates_media=True,
        uses_providers=True,
        uses_lambda=True,
        allows_live_upload=True,
        allowed_effects=("provider_api", "aws_lambda_s3_render", "ignored_runtime_artifacts", "douyin_live_upload"),
        forbidden_effects=(),
        required_env_groups=("script_agents_required", "research_required", "remotion_lambda_required", "douyin_account_required"),
        success_criteria=("artifact_manifest_bound", "deterministic_visual_audit_pass", "gemini_visual_audit_pass", "remote_identity_verified"),
    ),
}


def normalize_execution_profile(value: str | None) -> str:
    profile = (value or "contract").strip().lower()
    if profile not in SIDE_EFFECT_TIERS:
        expected = ", ".join(SIDE_EFFECT_TIERS)
        raise ValueError(f"Unsupported SEARCHPO_E2E_PROFILE: {profile} (expected {expected})")
    return profile


def resolve_side_effect_tier(profile: str | None = None, env: Mapping[str, str] | None = None) -> SideEffectTier:
    values = env if env is not None else os.environ
    selected = profile or values.get("SEARCHPO_EXECUTION_PROFILE") or values.get("SEARCHPO_E2E_PROFILE")
    return SIDE_EFFECT_TIERS[normalize_execution_profile(selected)]


def side_effect_axes(profile: str | None = None, env: Mapping[str, str] | None = None) -> dict[str, str]:
    return resolve_side_effect_tier(profile, env).axes()
