"""OpenAI-compatible chat/completions client for text-model calls sent through a gateway.

When SEARCHPO_LLM_URL (a full chat/completions URL) is set, copy polish and
content scoring send OpenAI-format requests there with SEARCHPO_LLM_API_KEY and
SEARCHPO_LLM_MODEL (SEARCHPO_LLM_SCORER_MODEL overrides the scorer model). When
it is unset, each script keeps its provider-native client.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from scripts.env_utils import env_value
except ImportError:  # imported with scripts/ on sys.path
    from env_utils import env_value

GATEWAY_PROVIDER = "llm-gateway"
RETRYABLE_STATUS = (429, 500, 502, 503, 504)
# Request fields only DeepSeek understands; an OpenAI-compatible gateway may reject them.
PROVIDER_ONLY_FIELDS = ("thinking",)
FENCED_BLOCK_RE = re.compile(r"```[A-Za-z0-9_-]*[ \t]*\n?(.*?)```", re.S)
THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.S | re.I)


def gateway_config(env_file: Path | None, *, role: str = "polish") -> dict[str, str] | None:
    """Return the gateway settings, or None when SEARCHPO_LLM_URL is unset."""
    url = env_value("SEARCHPO_LLM_URL", env_file).strip()
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SystemExit("SEARCHPO_LLM_URL must be a full http(s) chat/completions URL")
    api_key = env_value("SEARCHPO_LLM_API_KEY", env_file).strip()
    if not api_key:
        raise SystemExit("SEARCHPO_LLM_API_KEY is required when SEARCHPO_LLM_URL is set")
    model = env_value("SEARCHPO_LLM_MODEL", env_file).strip()
    if role == "scorer":
        model = env_value("SEARCHPO_LLM_SCORER_MODEL", env_file).strip() or model
    if not model:
        raise SystemExit("SEARCHPO_LLM_MODEL is required when SEARCHPO_LLM_URL is set")
    return {"provider": GATEWAY_PROVIDER, "url": url, "api_key": api_key, "model": model}


def gateway_body(body: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in body.items() if key not in PROVIDER_ONLY_FIELDS}


def _redact(text: str, secret: str) -> str:
    return text.replace(secret, "[redacted]") if secret else text


def relax_unsupported_param(body: dict[str, Any], detail: str, adjusted: set[str]) -> dict[str, Any] | None:
    """Rewrite one parameter the gateway's model rejected, or return None.

    Reasoning models behind OpenAI-compatible gateways refuse a non-default
    temperature, want max_completion_tokens instead of max_tokens, or lack JSON
    mode. Each parameter is relaxed at most once per request.
    """
    lowered = detail.lower()
    for param in ("temperature", "max_tokens", "response_format"):
        if param in adjusted or param not in body or param not in lowered:
            continue
        relaxed = dict(body)
        value = relaxed.pop(param)
        if param == "max_tokens":
            relaxed["max_completion_tokens"] = value
        adjusted.add(param)
        return relaxed
    return None


def chat_completion(
    url: str,
    api_key: str,
    body: dict[str, Any],
    timeout: float,
    *,
    attempts: int = 2,
    label: str = "LLM gateway",
) -> dict[str, Any]:
    payload_body = gateway_body(body)
    adjusted: set[str] = set()
    attempts = max(1, attempts)
    attempt = 0
    last_exc: Exception | None = None
    while attempt < attempts:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload_body, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = _redact(exc.read().decode("utf-8", errors="replace")[-1000:], api_key)
            if exc.code == 400:
                relaxed = relax_unsupported_param(payload_body, detail, adjusted)
                if relaxed is not None:
                    print(f"{label} rejected a request parameter; retrying without it: {sorted(adjusted)}", file=sys.stderr)
                    payload_body = relaxed
                    continue
            if exc.code in RETRYABLE_STATUS and attempt < attempts - 1:
                delay = 3.0 * (2 ** attempt)
                print(f"{label} HTTP {exc.code}, retrying in {delay:.0f}s (attempt {attempt + 1}/{attempts})...", file=sys.stderr)
                time.sleep(delay)
                last_exc = RuntimeError(f"{label} HTTP {exc.code}: {detail}")
                attempt += 1
                continue
            raise RuntimeError(f"{label} HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt < attempts - 1:
                delay = 3.0 * (2 ** attempt)
                print(f"{label} network error, retrying in {delay:.0f}s (attempt {attempt + 1}/{attempts})...", file=sys.stderr)
                time.sleep(delay)
                last_exc = RuntimeError(f"{label} network error: {exc}")
                attempt += 1
                continue
            raise RuntimeError(f"{label} network error: {exc}") from exc
    raise last_exc or RuntimeError(f"{label} call exhausted retries")


def message_text(payload: dict[str, Any], *, label: str = "LLM gateway") -> str:
    choice = (payload.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        content = "".join(str(part.get("text") or "") for part in content if isinstance(part, dict))
    if not isinstance(content, str) or not content.strip():
        finish_reason = choice.get("finish_reason")
        message_keys = sorted(str(key) for key in message.keys())
        raise RuntimeError(f"{label} returned empty message content; finish_reason={finish_reason}; message_keys={message_keys}")
    return content.strip()


def strip_code_fences(text: str) -> str:
    """Return the body of a model reply that may be wrapped in ``` fences."""
    cleaned = THINK_BLOCK_RE.sub("", text or "").strip()
    if "```" not in cleaned:
        return cleaned
    match = FENCED_BLOCK_RE.search(cleaned)
    if match:
        return match.group(1).strip()
    # An opening fence whose closing fence was cut off.
    return re.sub(r"^```[A-Za-z0-9_-]*", "", cleaned).strip("`").strip()


def parse_json_text(text: str) -> Any:
    """Parse a JSON reply, tolerating code fences, reasoning blocks, and prose around it."""
    cleaned = THINK_BLOCK_RE.sub("", text or "").strip()
    # Unfenced JSON is tried first: string values (component code) may contain ``` themselves.
    for candidate in (cleaned, strip_code_fences(cleaned)):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    match = re.search(r"\{.*\}", cleaned, re.S)
    if not match:
        return json.loads(cleaned)
    return json.loads(match.group(0))
