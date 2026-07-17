from __future__ import annotations

import urllib.parse
from pathlib import Path

from env_utils import env_value


def default_gemini_mode(env_file: Path) -> str:
    configured = env_value("SEARCHPO_GEMINI_API_MODE", env_file)
    if configured:
        return configured
    if env_value("GOOGLE_API_KEY", env_file) and not env_value("GOOGLE_AGENT_PLATFORM_API", env_file):
        return "developer"
    return "vertex_express"


def generate_content_url(model: str, api_key: str, env_file: Path) -> str:
    mode = default_gemini_mode(env_file)
    quoted_key = urllib.parse.quote(api_key)
    quoted_model = urllib.parse.quote(model)
    if mode == "developer":
        return f"https://generativelanguage.googleapis.com/v1beta/models/{quoted_model}:generateContent?key={quoted_key}"
    if mode == "vertex_express":
        model_path = model if "/" in model else f"publishers/google/models/{model}"
        return f"https://aiplatform.googleapis.com/v1/{model_path}:generateContent?key={quoted_key}"
    if mode == "vertex_standard":
        project = (
            env_value("SEARCHPO_GEMINI_VERTEX_PROJECT", env_file)
            or env_value("GOOGLE_CLOUD_PROJECT", env_file)
            or env_value("GOOGLE_PROJECT_ID", env_file)
        )
        location = (
            env_value("SEARCHPO_GEMINI_VERTEX_LOCATION", env_file)
            or env_value("GOOGLE_CLOUD_LOCATION", env_file)
            or env_value("GOOGLE_VERTEX_LOCATION", env_file)
            or "global"
        )
        if not project:
            raise RuntimeError("SEARCHPO_GEMINI_VERTEX_PROJECT or GOOGLE_CLOUD_PROJECT is required for vertex_standard mode")
        host = "aiplatform.googleapis.com" if location == "global" else f"{location}-aiplatform.googleapis.com"
        model_path = model if model.startswith("projects/") else f"projects/{project}/locations/{location}/publishers/google/models/{model}"
        return f"https://{host}/v1/{model_path}:generateContent?key={quoted_key}"
    raise RuntimeError(f"Unsupported SEARCHPO_GEMINI_API_MODE: {mode}")
