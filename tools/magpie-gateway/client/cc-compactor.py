#!/usr/bin/env python3
"""
cc-compactor.py — Multi-Dimensional Weighted Context Compaction & Handoff Engine

Client-side companion to the Magpie `context-budget` gateway middleware plugin.
Evaluates live session state (tokens, cache TTL age, tool/edit ratios) alongside
real-time Magpie multi-seat pool quotas (`/v1/magpie/quotas`) to minimize a
5-dimensional weighted objective across five candidate actions:

  1. STAY_NOOP            — Continue on active primary seat (preserve 100% cache)
  2. WAIT_KEEP_WARM       — Hold for imminent 5h quota reset + keep cache warm
  3. WARM_PRECOMPACT      — Proactively compact while active seat cache is still warm
  4. BYOK_JSONL_SPLICE    — Distill via BYOK (zcode/GLM-5.3 / always-up) + splice
                            native Claude Code `compact_boundary` into `.jsonl`
  5. CROSS_HARNESS_HANDOFF— Emit `.claude/handoff/current.md` for subagent/fresh start
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

DEFAULT_CONFIG: dict[str, Any] = {
    "general": {
        "default_profile": "balanced",
        "magpie_settings_path": "~/.claude/magpie-settings.json",
        "state_dir": "~/.cache/cc-compactor",
        "handoff_relpath": ".claude/handoff/current.md",
    },
    "limits": {
        "max_byok_input_chars": 32000,
        "max_byok_output_tokens": 3200,
        "byok_timeout_sec": 60,
        "min_compaction_cooldown_sec": 180,
        "max_compactions_per_hour": 6,
        "preserve_tail_messages": 10,
        "preserve_head_messages": 2,
        "auto_trigger_min_tokens": 155000,
    },
    "profiles": {
        "balanced": {
            "w_quota": 0.30,
            "w_cache": 0.25,
            "w_wait": 0.20,
            "w_loss": 0.15,
            "w_stampede": 0.10,
            "theta_5h": 0.85,
            "theta_7d": 0.90,
            "tau_wait_max_min": 15.0,
            "target_post_compact_tokens": 38000,
        },
        "cache_first": {
            "w_quota": 0.20,
            "w_cache": 0.42,
            "w_wait": 0.13,
            "w_loss": 0.15,
            "w_stampede": 0.10,
            "theta_5h": 0.92,
            "theta_7d": 0.94,
            "tau_wait_max_min": 25.0,
            "target_post_compact_tokens": 48000,
        },
        "zero_claude_burn": {
            "w_quota": 0.50,
            "w_cache": 0.15,
            "w_wait": 0.10,
            "w_loss": 0.15,
            "w_stampede": 0.10,
            "theta_5h": 0.72,
            "theta_7d": 0.80,
            "tau_wait_max_min": 10.0,
            "target_post_compact_tokens": 32000,
        },
        "speed_first": {
            "w_quota": 0.20,
            "w_cache": 0.18,
            "w_wait": 0.40,
            "w_loss": 0.14,
            "w_stampede": 0.08,
            "theta_5h": 0.88,
            "theta_7d": 0.92,
            "tau_wait_max_min": 4.0,
            "target_post_compact_tokens": 36000,
        },
    },
    "pools": {
        "claude_primary": {
            "provider": "claude",
            "window_tokens": 1000000,
            "safe_window_ratio": 0.90,
            "reserve_output_tokens": 16384,
            "cache_ttl_sec": 3600,
            "quota_scarcity": 1.00,
        },
        "zcode_glm": {
            "provider": "zcode",
            "model": "GLM-5.3",
            "window_tokens": 200000,
            "safe_window_ratio": 0.90,
            "reserve_output_tokens": 16384,
            "quota_scarcity": 0.12,
        },
        "bedrock_glm5": {
            "provider": "bedrock-glm5",
            "model": "glm-5.1",
            "window_tokens": 202752,
            "safe_window_ratio": 0.90,
            "reserve_output_tokens": 16384,
            "quota_scarcity": 0.15,
        },
        "devin_fallback": {
            "provider": "devin",
            "model": "claude-opus-4-6",
            "window_tokens": 262144,
            "safe_window_ratio": 0.90,
            "reserve_output_tokens": 16384,
            "quota_scarcity": 0.22,
        },
    },
    "compactors": {
        "surgical_hybrid": {
            "mode": "hybrid",
            "byok_chain": ["claude-haiku-5-5", "zcode/GLM-5.3", "always-up"],
            "preserve_buckets": [
                "file_paths_and_line_ranges",
                "git_diff_stat",
                "failing_assertions_and_tracebacks",
                "architectural_decisions",
                "todo_state_machine",
            ],
            "evict_buckets": [
                "stale_read_buffers",
                "passing_test_logs",
                "superseded_reasoning",
                "old_base64_images",
            ],
        }
    },
    "keep_warm": {
        "enabled": True,
        "ttl_seconds": 3600,
        "ping_after_idle_seconds": 3120,
        "min_cached_tokens": 90000,
        "min_remaining_5h_pct": 12,
    },
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    candidates: list[Path] = []
    if config_path:
        candidates.append(Path(config_path).expanduser())
    env_cfg = os.environ.get("CC_COMPACTOR_CONFIG")
    if env_cfg:
        candidates.append(Path(env_cfg).expanduser())
    candidates.append(Path("~/.config/cc-compactor/config.toml").expanduser())
    candidates.append(Path(__file__).resolve().parent / "cc-compactor.toml")

    for path in candidates:
        if path.is_file():
            with path.open("rb") as f:
                user_cfg = tomllib.load(f)
            merged = deep_merge(DEFAULT_CONFIG, user_cfg)
            merged["_config_path"] = str(path)
            return merged

    merged = copy.deepcopy(DEFAULT_CONFIG)
    merged["_config_path"] = "<builtin-defaults>"
    return merged


def load_magpie_connection(cfg: dict[str, Any]) -> dict[str, Any]:
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "").strip()
    custom_headers_raw = os.environ.get("ANTHROPIC_CUSTOM_HEADERS", "").strip()
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()

    settings_path = Path(
        cfg.get("general", {}).get("magpie_settings_path", "~/.claude/magpie-settings.json")
    ).expanduser()
    if settings_path.is_file():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            env = data.get("env", {}) if isinstance(data, dict) else {}
            if not base_url:
                base_url = str(env.get("ANTHROPIC_BASE_URL", "")).strip()
            if not custom_headers_raw:
                custom_headers_raw = str(env.get("ANTHROPIC_CUSTOM_HEADERS", "")).strip()
            if not api_key:
                api_key = str(env.get("ANTHROPIC_API_KEY", "")).strip()
        except Exception:
            pass

    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
    }
    if custom_headers_raw:
        for line in custom_headers_raw.replace(";", "\n").splitlines():
            if ":" in line:
                hk, hv = line.split(":", 1)
                headers[hk.strip()] = hv.strip()
    if api_key:
        headers.setdefault("x-api-key", api_key)

    return {
        "base_url": base_url.rstrip("/"),
        "headers": headers,
    }


def parse_iso_ts(val: str | None) -> float | None:
    if not val or not isinstance(val, str):
        return None
    try:
        s = val.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return dt.datetime.fromisoformat(s).timestamp()
    except Exception:
        return None


def fetch_magpie_quotas(
    cfg: dict[str, Any],
    now_ts: float | None = None,
    mock_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = now_ts if now_ts is not None else time.time()
    if mock_payload is not None:
        raw_list = mock_payload.get("data", []) if isinstance(mock_payload, dict) else mock_payload
    else:
        conn = load_magpie_connection(cfg)
        if not conn["base_url"]:
            return default_quota_snapshot(now, reachable=False, error="missing_base_url")
        url = f"{conn['base_url']}/v1/magpie/quotas"
        req = urllib.request.Request(url, headers=conn["headers"], method="GET")
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            raw_list = payload.get("data", []) if isinstance(payload, dict) else payload
        except Exception as exc:
            return default_quota_snapshot(now, reachable=False, error=str(exc))

    claude_seats: list[dict[str, Any]] = []
    other_pools: dict[str, list[dict[str, Any]]] = {}

    for item in raw_list if isinstance(raw_list, list) else []:
        if not isinstance(item, dict):
            continue
        provider = str(item.get("provider", ""))
        user = str(item.get("user") or item.get("account") or item.get("plan") or "default")
        last_served_ts = parse_iso_ts(item.get("lastServedAt")) or 0.0
        windows = item.get("windows") if isinstance(item.get("windows"), list) else []

        w5: dict[str, Any] = {}
        w7: dict[str, Any] = {}
        for w in windows:
            if not isinstance(w, dict):
                continue
            wname = str(w.get("name", "")).lower()
            if "5 hour" in wname or "5h" in wname:
                w5 = w
            elif "7 day" in wname or "7d" in wname or "week" in wname:
                w7 = w
            elif not w5:
                w5 = w

        used_5h = float(w5.get("used", 0.0)) if w5 else 0.0
        rem_5h = float(w5.get("remaining", max(0.0, 100.0 - used_5h))) if w5 else 100.0
        reset_5h_ts = parse_iso_ts(w5.get("resetsAt")) if w5 else None

        used_7d = float(w7.get("used", 0.0)) if w7 else 0.0
        rem_7d = float(w7.get("remaining", max(0.0, 100.0 - used_7d))) if w7 else 100.0
        reset_7d_ts = parse_iso_ts(w7.get("resetsAt")) if w7 else None

        routed5 = (w5.get("holds") or {}).get("routed") or {}
        cache_read = int(routed5.get("cacheRead", 0) or 0)
        cache_write = int(routed5.get("cacheWrite", 0) or 0)

        seat_info = {
            "provider": provider,
            "user": user,
            "plan": str(item.get("plan", "")),
            "used_5h": used_5h,
            "remaining_5h": rem_5h,
            "reset_5h_ts": reset_5h_ts,
            "minutes_to_reset_5h": (
                max(0.0, (reset_5h_ts - now) / 60.0) if reset_5h_ts else None
            ),
            "used_7d": used_7d,
            "remaining_7d": rem_7d,
            "reset_7d_ts": reset_7d_ts,
            "cache_read": cache_read,
            "cache_write": cache_write,
            "last_served_ts": last_served_ts,
            "exhausted": (used_5h >= 99.0) or (used_7d >= 99.5),
            "healthy": (used_5h < 96.0) and (used_7d < 98.0),
        }

        if provider == "claude":
            claude_seats.append(seat_info)
        else:
            other_pools.setdefault(provider, []).append(seat_info)

    if not claude_seats:
        return default_quota_snapshot(now, reachable=True, error=None)

    # Identify active seat (most recently served, or lowest 5h usage among non-7d-exhausted)
    claude_By_recent = sorted(claude_seats, key=lambda s: s["last_served_ts"], reverse=True)
    active_seat = claude_By_recent[0]

    healthy_seats = [s for s in claude_seats if s["healthy"]]
    usable_7d_seats = [s for s in claude_seats if s["used_7d"] < 99.5]

    min_used_5h = (
        min(s["used_5h"] for s in usable_7d_seats) if usable_7d_seats else 100.0
    )

    reset_candidates = [
        s["minutes_to_reset_5h"]
        for s in usable_7d_seats
        if s["minutes_to_reset_5h"] is not None
    ]
    minutes_to_earliest_reset = min(reset_candidates) if reset_candidates else 120.0

    total_cr = sum(s["cache_read"] for s in claude_seats)
    total_cw = sum(s["cache_write"] for s in claude_seats)
    cw_ratio = total_cw / max(1, total_cr + total_cw)

    return {
        "reachable": True,
        "error": None,
        "claude_seats": claude_seats,
        "other_pools": other_pools,
        "healthy_claude_seat_count": len(healthy_seats),
        "total_claude_seat_count": len(claude_seats),
        "active_seat": active_seat["user"],
        "active_used_5h": active_seat["used_5h"],
        "active_used_7d": active_seat["used_7d"],
        "min_used_5h": min_used_5h,
        "minutes_to_earliest_reset": round(minutes_to_earliest_reset, 2),
        "cache_write_ratio": round(cw_ratio, 4),
    }


def default_quota_snapshot(now: float, reachable: bool, error: str | None) -> dict[str, Any]:
    return {
        "reachable": reachable,
        "error": error,
        "claude_seats": [],
        "other_pools": {},
        "healthy_claude_seat_count": 1,
        "total_claude_seat_count": 1,
        "active_seat": "unknown",
        "active_used_5h": 50.0,
        "active_used_7d": 50.0,
        "min_used_5h": 50.0,
        "minutes_to_earliest_reset": 60.0,
        "cache_write_ratio": 0.05,
    }


def estimate_chars_to_tokens(chars: int) -> int:
    if chars <= 0:
        return 0
    return max(1, int(round(chars / 3.5)))


def find_session_jsonl(session_arg: str | None = None, cwd: str | None = None) -> Path:
    if session_arg:
        candidate = Path(session_arg).expanduser()
        if candidate.is_file():
            return candidate
        # Search by UUID prefix across ~/.claude/projects
        projects_root = Path("~/.claude/projects").expanduser()
        if projects_root.is_dir():
            matches = sorted(
                projects_root.glob(f"*/*{session_arg}*.jsonl"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if matches:
                return matches[0]
        raise FileNotFoundError(f"Could not find session JSONL matching '{session_arg}'")

    projects_root = Path("~/.claude/projects").expanduser()
    if not projects_root.is_dir():
        raise FileNotFoundError(f"Claude projects directory not found: {projects_root}")

    if cwd:
        slug_dir = "-" + str(Path(cwd).resolve()).strip("/").replace("/", "-")
        proj_dir = projects_root / slug_dir
        if proj_dir.is_dir():
            files = sorted(
                proj_dir.glob("*.jsonl"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if files:
                return files[0]

    all_files = sorted(
        projects_root.glob("*/*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not all_files:
        raise FileNotFoundError(f"No .jsonl transcripts found in {projects_root}")
    return all_files[0]


def analyze_transcript(jsonl_path: Path, now_ts: float | None = None) -> dict[str, Any]:
    now = now_ts if now_ts is not None else time.time()
    raw_lines = jsonl_path.read_text(encoding="utf-8", errors="replace").splitlines()

    records: list[dict[str, Any]] = []
    last_boundary_idx = -1

    for line in raw_lines:
        line_str = line.strip()
        if not line_str:
            continue
        try:
            obj = json.loads(line_str)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        idx = len(records)
        records.append(obj)
        if obj.get("type") == "system" and obj.get("subtype") == "compact_boundary":
            last_boundary_idx = idx

    active_records = records[last_boundary_idx + 1 :] if last_boundary_idx >= 0 else records

    last_usage_tokens = 0
    chars_since_last_usage = 0
    last_cache_touch_ts: float | None = None

    total_chars = 0
    tool_result_chars = 0
    assistant_turns = 0
    edit_turns = 0

    initial_task = ""
    recent_user_prompts: list[str] = []
    touched_files: dict[str, str] = {}
    commands_run: list[str] = []
    errors_and_failures: list[str] = []
    discovered_tools: set[str] = set()
    conversation_records: list[dict[str, Any]] = []
    all_uuids: list[str] = []

    meta = {
        "sessionId": jsonl_path.stem,
        "cwd": str(Path.cwd()),
        "version": "2.1.310",
        "gitBranch": "main",
        "slug": "session",
        "entrypoint": "cli",
    }

    for rec in records[-15:]:
        for k in ("sessionId", "cwd", "version", "gitBranch", "slug", "entrypoint"):
            if rec.get(k):
                meta[k] = str(rec[k])

    edit_tool_names = {"Edit", "MultiEdit", "Write", "NotebookEdit", "apply_patch"}
    file_param_keys = ("file_path", "path", "Path", "target_file", "notebook_path")

    for rec in active_records:
        rec_uuid = rec.get("uuid")
        if isinstance(rec_uuid, str) and rec_uuid:
            all_uuids.append(rec_uuid)

        rec_type = rec.get("type")
        if rec_type not in ("user", "assistant"):
            continue

        conversation_records.append(rec)
        msg = rec.get("message") if isinstance(rec.get("message"), dict) else {}
        role = msg.get("role") or rec_type
        content = msg.get("content")
        rec_ts = parse_iso_ts(rec.get("timestamp"))

        usage = msg.get("usage") if isinstance(msg.get("usage"), dict) else None
        if usage and role == "assistant":
            in_tok = int(usage.get("input_tokens", 0) or 0)
            cw_tok = int(usage.get("cache_creation_input_tokens", 0) or 0)
            cr_tok = int(usage.get("cache_read_input_tokens", 0) or 0)
            out_tok = int(usage.get("output_tokens", 0) or 0)
            combined = in_tok + cw_tok + cr_tok + out_tok
            if combined > 0:
                last_usage_tokens = combined
                chars_since_last_usage = 0
            if (cw_tok > 0 or cr_tok > 0) and rec_ts:
                last_cache_touch_ts = rec_ts

        msg_chars = 0
        has_edit_in_turn = False

        if isinstance(content, str):
            msg_chars += len(content)
            if (
                role == "user"
                and not rec.get("isCompactSummary")
                and not content.startswith("<local-command")
                and not content.startswith("<command-name>")
            ):
                clean = " ".join(content.strip().split())
                if clean:
                    if not initial_task:
                        initial_task = clean[:600]
                    recent_user_prompts.append(clean[:320])
        elif isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text":
                    txt = str(block.get("text", ""))
                    msg_chars += len(txt)
                    if (
                        role == "user"
                        and not rec.get("isCompactSummary")
                        and not txt.startswith("<system-reminder>")
                        and not txt.startswith("<local-command")
                    ):
                        clean = " ".join(txt.strip().split())
                        if clean:
                            if not initial_task:
                                initial_task = clean[:600]
                            recent_user_prompts.append(clean[:320])
                elif btype == "thinking":
                    msg_chars += len(str(block.get("thinking", "")))
                elif btype == "tool_use":
                    tname = str(block.get("name", "tool"))
                    discovered_tools.add(tname)
                    inp = block.get("input") if isinstance(block.get("input"), dict) else {}
                    msg_chars += len(json.dumps(inp, ensure_ascii=False))
                    if tname in edit_tool_names:
                        has_edit_in_turn = True
                    for fk in file_param_keys:
                        fval = inp.get(fk)
                        if isinstance(fval, str) and fval.strip():
                            tag = "MODIFIED" if tname in edit_tool_names else "READ"
                            prev = touched_files.get(fval)
                            if prev != "MODIFIED":
                                touched_files[fval] = tag
                    if tname == "Bash" and isinstance(inp.get("command"), str):
                        cmd_str = " ".join(inp["command"].strip().split())[:220]
                        if cmd_str:
                            commands_run.append(cmd_str)
                elif btype == "tool_result":
                    tcontent = block.get("content")
                    if isinstance(tcontent, str):
                        blen = len(tcontent)
                        msg_chars += blen
                        tool_result_chars += blen
                        t_snippet = tcontent.strip()
                    elif isinstance(tcontent, list):
                        parts = []
                        for sub in tcontent:
                            if isinstance(sub, dict) and sub.get("type") == "text":
                                parts.append(str(sub.get("text", "")))
                        joined = "\n".join(parts)
                        blen = len(joined)
                        msg_chars += blen
                        tool_result_chars += blen
                        t_snippet = joined.strip()
                    else:
                        t_snippet = ""

                    is_err = bool(block.get("is_error"))
                    if is_err or any(
                        marker in t_snippet
                        for marker in ("Traceback (most recent", "AssertionError", "FAILED ", "Error: ", "exit code 1")
                    ):
                        tail_err = " ".join(t_snippet[-360:].split())
                        if tail_err:
                            errors_and_failures.append(tail_err)

        total_chars += msg_chars
        if not (usage and role == "assistant"):
            chars_since_last_usage += msg_chars

        if role == "assistant":
            assistant_turns += 1
            if has_edit_in_turn:
                edit_turns += 1

    estimated_active_tokens = (
        last_usage_tokens + estimate_chars_to_tokens(chars_since_last_usage)
        if last_usage_tokens > 0
        else estimate_chars_to_tokens(total_chars)
    )

    cache_age_sec = (
        max(0.0, now - last_cache_touch_ts) if last_cache_touch_ts is not None else 3600.0
    )
    r_tool = round(tool_result_chars / max(1, total_chars), 4)
    r_edit = round(edit_turns / max(1, assistant_turns), 4)

    head_uuid = conversation_records[0].get("uuid") if conversation_records else None
    tail_uuid = conversation_records[-1].get("uuid") if conversation_records else None

    return {
        "jsonl_path": str(jsonl_path),
        "total_records": len(records),
        "active_records_count": len(active_records),
        "conversation_records": conversation_records,
        "last_boundary_idx": last_boundary_idx,
        "context_tokens": estimated_active_tokens,
        "cache_age_sec": round(cache_age_sec, 1),
        "cache_ttl_remaining_min": round(max(0.0, (3600.0 - cache_age_sec) / 60.0), 1),
        "r_tool": r_tool,
        "r_edit": r_edit,
        "initial_task": initial_task,
        "recent_user_prompts": recent_user_prompts[-6:],
        "touched_files": touched_files,
        "commands_run": commands_run[-12:],
        "errors_and_failures": errors_and_failures[-8:],
        "discovered_tools": sorted(discovered_tools),
        "meta": meta,
        "head_uuid": head_uuid,
        "tail_uuid": tail_uuid,
        "all_uuids": all_uuids,
    }


def evaluate_actions(
    transcript_state: dict[str, Any],
    quota_state: dict[str, Any],
    cfg: dict[str, Any],
    profile_name: str | None = None,
) -> dict[str, Any]:
    prof_key = profile_name or cfg.get("general", {}).get("default_profile", "balanced")
    profiles = cfg.get("profiles", {})
    prof = profiles.get(prof_key) or profiles.get("balanced") or DEFAULT_CONFIG["profiles"]["balanced"]

    w_q = float(prof.get("w_quota", 0.30))
    w_c = float(prof.get("w_cache", 0.25))
    w_w = float(prof.get("w_wait", 0.20))
    w_l = float(prof.get("w_loss", 0.15))
    w_s = float(prof.get("w_stampede", 0.10))

    theta_5h = float(prof.get("theta_5h", 0.85)) * 100.0
    theta_7d = float(prof.get("theta_7d", 0.90)) * 100.0
    tau_wait_max = float(prof.get("tau_wait_max_min", 15.0))

    c_raw = int(transcript_state["context_tokens"])
    cache_age_sec = float(transcript_state["cache_age_sec"])
    r_tool = float(transcript_state["r_tool"])
    r_edit = float(transcript_state["r_edit"])

    u5 = float(quota_state["active_used_5h"])
    u7 = float(quota_state["active_used_7d"])
    healthy_seats = int(quota_state["healthy_claude_seat_count"])
    min_u5 = float(quota_state["min_used_5h"])
    t_reset_min = float(quota_state["minutes_to_earliest_reset"])
    cw_ratio = float(quota_state["cache_write_ratio"])

    zcode_safe_budget = int(200000 * 0.90) - 16384  # 163,616 tokens
    overflows_zcode = c_raw > zcode_safe_budget
    cache_is_warm = (cache_age_sec < 3300.0) and (c_raw >= 40000)
    near_ttl_cliff = 2900.0 <= cache_age_sec <= 3540.0

    # Loss penalty factor: high tool-output density means large logs can be stripped with very low semantic loss
    compaction_loss_base = max(0.12, min(0.85, 0.52 * (1.0 - 0.62 * r_tool) + 0.18 * r_edit))

    actions: dict[str, dict[str, float]] = {}

    # 1. STAY_NOOP
    if healthy_seats == 0:
        # All Claude seats exhausted; staying uncompacted forces raw payload onto fallback (zcode 200K / devin 262K)
        q_stay = 0.92
        c_stay = 0.88 if overflows_zcode else 0.45
        w_stay = 0.10
        l_stay = 0.00
        s_stay = 1.25 if overflows_zcode else 0.55
    else:
        over_5h = max(0.0, (u5 - theta_5h) / max(1.0, 100.0 - theta_5h))
        over_7d = max(0.0, (u7 - theta_7d) / max(1.0, 100.0 - theta_7d))
        size_pressure = min(1.0, c_raw / 350000.0)
        q_stay = min(1.2, (0.22 + 0.65 * over_5h + 0.35 * over_7d) * (0.4 + 0.6 * size_pressure))
        # If active seat is >=95% used, staying uncompacted risks an imminent mid-task seat switch -> massive cold cacheWrite
        imminent_switch_risk = 0.85 if u5 >= 95.0 and c_raw > 120000 else (0.10 if cache_is_warm else 0.48)
        c_stay = imminent_switch_risk
        w_stay = 0.02
        l_stay = 0.00
        s_stay = min(1.0, cw_ratio * 2.5 + (0.45 if u5 >= 94.0 else 0.05))

    actions["STAY_NOOP"] = {
        "Phi_quota": q_stay,
        "Phi_cache": c_stay,
        "Phi_wait": w_stay,
        "Phi_loss": l_stay,
        "Phi_stampede": s_stay,
    }

    # 2. WAIT_KEEP_WARM
    wait_ratio = min(1.5, t_reset_min / max(1.0, tau_wait_max))
    q_wait = 0.08 if cache_is_warm else 0.25
    # If reset is after TTL expires and we don't have budget to ping, cache expires; if near_ttl_cliff, keep-warm saves it!
    c_wait = 0.12 if (cache_is_warm and t_reset_min <= 45.0) else 0.72
    if near_ttl_cliff and healthy_seats > 0:
        c_wait = 0.05
    w_wait_pen = wait_ratio if healthy_seats == 0 else (0.18 if near_ttl_cliff else 0.78)
    actions["WAIT_KEEP_WARM"] = {
        "Phi_quota": q_wait,
        "Phi_cache": c_wait,
        "Phi_wait": w_wait_pen,
        "Phi_loss": 0.00,
        "Phi_stampede": 0.08,
    }

    # 3. WARM_PRECOMPACT (Proactive in-seat compaction while a Claude seat still has warm cache & headroom)
    if healthy_seats > 0 and c_raw >= 130000 and theta_5h - 12.0 <= u5 <= 96.0 and cache_is_warm:
        q_warm = 0.24
        c_warm = 0.22
        w_warm = 0.18
        l_warm = compaction_loss_base
        s_warm = 0.12
    else:
        # Either too small to need compaction, or all Claude seats are already exhausted
        q_warm = 0.78 if healthy_seats == 0 else 0.52
        c_warm = 0.65 if not cache_is_warm else 0.45
        w_warm = 0.28
        l_warm = compaction_loss_base + (0.30 if c_raw < 90000 else 0.0)
        s_warm = 0.40

    actions["WARM_PRECOMPACT"] = {
        "Phi_quota": q_warm,
        "Phi_cache": c_warm,
        "Phi_wait": w_warm,
        "Phi_loss": l_warm,
        "Phi_stampede": s_warm,
    }

    # 4. BYOK_JSONL_SPLICE (External BYOK distillation via zcode/GLM-5.3 + native JSONL compact_boundary splice)
    # Zero primary Claude quota burn (`Phi_quota = 0.05`), shrinks context to ~38K so both zcode (200K)
    # and rotating Claude seats incur minimal cold cacheWrite!
    need_compaction = (c_raw >= 140000) or (healthy_seats == 0 and c_raw >= 90000) or overflows_zcode
    q_byok = 0.05
    c_byok = 0.16 if need_compaction else 0.58
    w_byok = 0.15
    l_byok = compaction_loss_base if need_compaction else compaction_loss_base + 0.35
    s_byok = 0.06 if need_compaction else 0.30

    actions["BYOK_JSONL_SPLICE"] = {
        "Phi_quota": q_byok,
        "Phi_cache": c_byok,
        "Phi_wait": w_byok,
        "Phi_loss": l_byok,
        "Phi_stampede": s_byok,
    }

    # 5. CROSS_HARNESS_HANDOFF (Emit .claude/handoff/current.md for fresh session / opencode-go / gemini)
    severe_exhaustion = (healthy_seats == 0 and t_reset_min > tau_wait_max and c_raw >= 260000)
    q_handoff = 0.04
    c_handoff = 0.25 if severe_exhaustion else 0.55
    w_handoff = 0.22
    l_handoff = min(0.95, compaction_loss_base + 0.18)
    s_handoff = 0.05

    actions["CROSS_HARNESS_HANDOFF"] = {
        "Phi_quota": q_handoff,
        "Phi_cache": c_handoff,
        "Phi_wait": w_handoff,
        "Phi_loss": l_handoff,
        "Phi_stampede": s_handoff,
    }

    ranked: list[dict[str, Any]] = []
    for act_name, dims in actions.items():
        total_j = (
            w_q * dims["Phi_quota"]
            + w_c * dims["Phi_cache"]
            + w_w * dims["Phi_wait"]
            + w_l * dims["Phi_loss"]
            + w_s * dims["Phi_stampede"]
        )
        ranked.append(
            {
                "action": act_name,
                "score": round(total_j, 4),
                "components": {k: round(v, 4) for k, v in dims.items()},
                "weighted_contributions": {
                    "quota": round(w_q * dims["Phi_quota"], 4),
                    "cache": round(w_c * dims["Phi_cache"], 4),
                    "wait": round(w_w * dims["Phi_wait"], 4),
                    "loss": round(w_l * dims["Phi_loss"], 4),
                    "stampede": round(w_s * dims["Phi_stampede"], 4),
                },
            }
        )

    ranked.sort(key=lambda item: item["score"])
    winner = ranked[0]

    return {
        "profile": prof_key,
        "weights": {
            "w_quota": w_q,
            "w_cache": w_c,
            "w_wait": w_w,
            "w_loss": w_l,
            "w_stampede": w_s,
        },
        "recommended_action": winner["action"],
        "recommended_score": winner["score"],
        "overflows_zcode_200k": overflows_zcode,
        "ranked_actions": ranked,
    }


def collect_git_context(cwd: str) -> dict[str, str]:
    result = {"status_short": "", "diff_stat": "", "branch": ""}
    cwd_path = Path(cwd)
    if not cwd_path.is_dir():
        return result
    try:
        proc_b = subprocess.run(
            ["git", "-C", str(cwd_path), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if proc_b.returncode == 0:
            result["branch"] = proc_b.stdout.strip()

        proc_s = subprocess.run(
            ["git", "-C", str(cwd_path), "status", "-sb"],
            capture_output=True,
            text=True,
            timeout=4,
        )
        if proc_s.returncode == 0:
            result["status_short"] = "\n".join(proc_s.stdout.strip().splitlines()[:25])

        proc_d = subprocess.run(
            ["git", "-C", str(cwd_path), "diff", "--stat"],
            capture_output=True,
            text=True,
            timeout=4,
        )
        if proc_d.returncode == 0:
            result["diff_stat"] = "\n".join(proc_d.stdout.strip().splitlines()[:25])
    except Exception:
        pass
    return result


def build_deterministic_digest(
    transcript_state: dict[str, Any],
    git_ctx: dict[str, str],
) -> str:
    lines: list[str] = []
    lines.append("### 1. Primary User Request & Intent")
    lines.append(transcript_state.get("initial_task") or "(See recent prompt history below)")
    lines.append("")

    if transcript_state.get("recent_user_prompts"):
        lines.append("### 2. Chronological User Steering Prompts")
        for idx, p in enumerate(transcript_state["recent_user_prompts"], 1):
            lines.append(f"{idx}. {p}")
        lines.append("")

    touched: dict[str, str] = transcript_state.get("touched_files") or {}
    if touched:
        lines.append("### 3. Touched Files & Mutation State")
        for fpath, tag in list(touched.items())[:30]:
            lines.append(f"- `[{tag}]` `{fpath}`")
        lines.append("")

    if git_ctx.get("status_short") or git_ctx.get("diff_stat"):
        lines.append("### 4. Live Git Working Tree State")
        if git_ctx.get("status_short"):
            lines.append("```text")
            lines.append(git_ctx["status_short"])
            lines.append("```")
        if git_ctx.get("diff_stat"):
            lines.append("```text")
            lines.append(git_ctx["diff_stat"])
            lines.append("```")
        lines.append("")

    if transcript_state.get("commands_run"):
        lines.append("### 5. Recent Commands Executed")
        for cmd in transcript_state["commands_run"]:
            lines.append(f"- `{cmd}`")
        lines.append("")

    if transcript_state.get("errors_and_failures"):
        lines.append("### 6. Diagnostic Errors & Failing Assertions Retained")
        for err in transcript_state["errors_and_failures"]:
            lines.append(f"- {err}")
        lines.append("")

    return "\n".join(lines).strip()


def check_and_record_rate_limit(cfg: dict[str, Any], dry_run: bool = False) -> tuple[bool, str]:
    state_dir = Path(cfg.get("general", {}).get("state_dir", "~/.cache/cc-compactor")).expanduser()
    state_dir.mkdir(parents=True, exist_ok=True)
    rate_file = state_dir / "rate_guard.json"

    limits = cfg.get("limits", {})
    cooldown_sec = int(limits.get("min_compaction_cooldown_sec", 180))
    max_per_hour = int(limits.get("max_compactions_per_hour", 6))
    now = time.time()

    history: list[float] = []
    if rate_file.is_file():
        try:
            data = json.loads(rate_file.read_text(encoding="utf-8"))
            history = [float(ts) for ts in data.get("timestamps", []) if now - float(ts) < 3600.0]
        except Exception:
            history = []

    if history and (now - history[-1]) < cooldown_sec:
        rem = int(cooldown_sec - (now - history[-1]))
        return False, f"cooldown_active ({rem}s remaining)"

    if len(history) >= max_per_hour:
        return False, f"hourly_cap_reached ({len(history)}/{max_per_hour} per hour)"

    if not dry_run:
        history.append(now)
        rate_file.write_text(json.dumps({"timestamps": history}, indent=2), encoding="utf-8")

    return True, "ok"


def distill_with_byok_llm(
    deterministic_digest: str,
    transcript_state: dict[str, Any],
    cfg: dict[str, Any],
) -> tuple[str | None, str]:
    conn = load_magpie_connection(cfg)
    if not conn["base_url"]:
        return None, "missing_gateway_url"

    limits = cfg.get("limits", {})
    max_chars = int(limits.get("max_byok_input_chars", 140000))
    max_out_tokens = int(limits.get("max_byok_output_tokens", 3200))
    timeout_sec = float(limits.get("byok_timeout_sec", 35.0))

    compactor_cfg = cfg.get("compactors", {}).get("surgical_hybrid", {})
    byok_chain = compactor_cfg.get("byok_chain") or ["claude-haiku-5-5", "zcode/GLM-5.3", "always-up"]

    # Build bounded excerpt from middle conversation turns
    conv = transcript_state.get("conversation_records") or []
    preserve_tail = int(limits.get("preserve_tail_messages", 10))
    middle_records = conv[:-preserve_tail] if len(conv) > preserve_tail else conv

    snippets: list[str] = []
    budget_left = max(4000, max_chars - len(deterministic_digest) - 2000)
    for rec in middle_records[-60:]:
        msg = rec.get("message") if isinstance(rec.get("message"), dict) else {}
        role = msg.get("role", "user")
        content = msg.get("content")
        text_chunk = ""
        if isinstance(content, str):
            text_chunk = content[:1200]
        elif isinstance(content, list):
            parts = []
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text":
                    parts.append(str(b.get("text", ""))[:1000])
                elif b.get("type") == "tool_use":
                    parts.append(f"[tool_use: {b.get('name')}]")
                elif b.get("type") == "tool_result":
                    t_str = str(b.get("content", ""))
                    if len(t_str) > 500:
                        t_str = t_str[:250] + " ... " + t_str[-200:]
                    parts.append(f"[tool_result: {t_str}]")
            text_chunk = " ".join(parts)
        if text_chunk:
            line = f"[{role.upper()}] {text_chunk.strip()}"
            if len(line) <= budget_left:
                snippets.append(line)
                budget_left -= len(line)

    prompt = (
        "You are a surgical context compaction engine for an active software engineering session.\n"
        "Combine the deterministic ground-truth facts below with the middle-turn excerpts into a dense, "
        "high-signal technical continuation summary (<1800 words).\n"
        "Strictly preserve: exact file paths, function/symbol names, architectural constraints, "
        "commands executed, failing assertions/errors, and the exact next pending steps.\n\n"
        "=== DETERMINISTIC GROUND TRUTH ===\n"
        f"{deterministic_digest}\n\n"
        "=== MIDDLE TURN EXCERPTS ===\n"
        + "\n".join(snippets)
    )

    for model_name in byok_chain:
        req_body = {
            "model": model_name,
            "max_tokens": max_out_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        data_bytes = json.dumps(req_body).encode("utf-8")
        req = urllib.request.Request(
            f"{conn['base_url']}/v1/messages",
            data=data_bytes,
            headers=conn["headers"],
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                resp_obj = json.loads(resp.read().decode("utf-8"))
            blocks = resp_obj.get("content") if isinstance(resp_obj, dict) else []
            texts = [
                str(b.get("text", ""))
                for b in (blocks or [])
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            combined = "\n".join(t for t in texts if t.strip()).strip()
            if len(combined) >= 120:
                return combined, f"byok:{model_name}"
        except Exception:
            continue

    return None, "deterministic_fallback"


def select_safe_tail_records(
    conversation_records: list[dict[str, Any]],
    preserve_tail_count: int,
) -> list[dict[str, Any]]:
    if not conversation_records:
        return []
    count = min(len(conversation_records), max(2, preserve_tail_count))
    start_idx = len(conversation_records) - count

    # Never start the preserved tail on a `tool_result` user message without its preceding `tool_use` assistant message
    if start_idx > 0:
        first_msg = conversation_records[start_idx].get("message") or {}
        first_content = first_msg.get("content")
        if isinstance(first_content, list) and any(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in first_content
        ):
            start_idx -= 1

    return conversation_records[start_idx:]


def splice_compact_boundary(
    jsonl_path: Path,
    transcript_state: dict[str, Any],
    summary_markdown: str,
    compactor_source: str,
    cfg: dict[str, Any],
    duration_ms: int,
) -> dict[str, Any]:
    state_dir = Path(cfg.get("general", {}).get("state_dir", "~/.cache/cc-compactor")).expanduser()
    backup_dir = state_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    ts_slug = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"{jsonl_path.stem}.{ts_slug}.jsonl.bak"
    shutil.copy2(jsonl_path, backup_path)

    preserve_tail = int(cfg.get("limits", {}).get("preserve_tail_messages", 10))
    conv_records = transcript_state.get("conversation_records") or []
    tail_records = select_safe_tail_records(conv_records, preserve_tail)
    tail_uuids = [str(r.get("uuid")) for r in tail_records if r.get("uuid")]

    boundary_uuid = str(uuid.uuid4())
    summary_uuid = str(uuid.uuid4())
    prompt_uuid = str(uuid.uuid4())
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    head_uuid = transcript_state.get("head_uuid") or boundary_uuid
    tail_uuid = transcript_state.get("tail_uuid") or boundary_uuid
    all_uuids = transcript_state.get("all_uuids") or tail_uuids
    meta = transcript_state.get("meta") or {}
    discovered_tools = transcript_state.get("discovered_tools") or []

    pre_tokens = int(transcript_state.get("context_tokens", 0))
    summary_tokens = estimate_chars_to_tokens(len(summary_markdown))
    tail_chars = sum(len(json.dumps(r.get("message", {}))) for r in tail_records)
    post_tokens = summary_tokens + estimate_chars_to_tokens(tail_chars)

    tools_tag = (
        f"<tools-used-before-summary>{json.dumps(discovered_tools)}</tools-used-before-summary>\n"
        if discovered_tools
        else ""
    )
    summary_content = (
        "This session is being continued from a previous conversation that ran out of context. "
        "The summary below covers the earlier portion of the conversation.\n\n"
        f"{tools_tag}"
        f"Summary ({compactor_source}):\n"
        f"{summary_markdown}\n\n"
        "If you need specific details from before compaction (like exact code chunks, error tracebacks, "
        "or old command outputs) that are not in this summary, inspect the git working tree or re-read "
        "the relevant files listed above. Continue the conversation smoothly without repeating completed work."
    )

    boundary_record = {
        "parentUuid": None,
        "logicalParentUuid": tail_uuid,
        "isSidechain": False,
        "type": "system",
        "subtype": "compact_boundary",
        "content": "Conversation compacted",
        "isMeta": False,
        "timestamp": now_iso,
        "uuid": boundary_uuid,
        "level": "info",
        "compactMetadata": {
            "trigger": "auto",
            "preTokens": pre_tokens,
            "durationMs": duration_ms,
            "preCompactDiscoveredTools": discovered_tools,
            "preservedSegment": {
                "headUuid": head_uuid,
                "anchorUuid": summary_uuid,
                "tailUuid": tail_uuid,
            },
            "preservedMessages": {
                "anchorUuid": summary_uuid,
                "uuids": tail_uuids,
                "allUuids": all_uuids[-200:],
            },
            "postTokens": post_tokens,
            "cumulativeDroppedTokens": max(0, pre_tokens - post_tokens),
        },
        "userType": "external",
        "entrypoint": meta.get("entrypoint", "cli"),
        "cwd": meta.get("cwd", str(Path.cwd())),
        "sessionId": meta.get("sessionId", jsonl_path.stem),
        "version": meta.get("version", "2.1.310"),
        "gitBranch": meta.get("gitBranch", "main"),
        "slug": meta.get("slug", "session"),
    }

    summary_record = {
        "parentUuid": boundary_uuid,
        "isSidechain": False,
        "promptId": prompt_uuid,
        "type": "user",
        "message": {
            "role": "user",
            "content": summary_content,
        },
        "isVisibleInTranscriptOnly": True,
        "isCompactSummary": True,
        "uuid": summary_uuid,
        "timestamp": now_iso,
        "userType": "external",
        "entrypoint": meta.get("entrypoint", "cli"),
        "cwd": meta.get("cwd", str(Path.cwd())),
        "sessionId": meta.get("sessionId", jsonl_path.stem),
        "version": meta.get("version", "2.1.310"),
        "gitBranch": meta.get("gitBranch", "main"),
        "slug": meta.get("slug", "session"),
    }

    with jsonl_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(boundary_record, ensure_ascii=False) + "\n")
        f.write(json.dumps(summary_record, ensure_ascii=False) + "\n")

    return {
        "session_path": str(jsonl_path),
        "backup_path": str(backup_path),
        "boundary_uuid": boundary_uuid,
        "summary_uuid": summary_uuid,
        "compactor_source": compactor_source,
        "pre_tokens": pre_tokens,
        "post_tokens": post_tokens,
        "dropped_tokens": max(0, pre_tokens - post_tokens),
        "preserved_tail_messages": len(tail_uuids),
    }


def write_handoff_document(
    transcript_state: dict[str, Any],
    quota_state: dict[str, Any],
    decision: dict[str, Any],
    cfg: dict[str, Any],
    output_path: str | Path | None = None,
) -> Path:
    meta = transcript_state.get("meta") or {}
    cwd = meta.get("cwd") or str(Path.cwd())
    git_ctx = collect_git_context(cwd)
    digest = build_deterministic_digest(transcript_state, git_ctx)

    if output_path:
        target = Path(output_path).expanduser().resolve()
    else:
        rel = cfg.get("general", {}).get("handoff_relpath", ".claude/handoff/current.md")
        target = Path(cwd) / rel

    target.parent.mkdir(parents=True, exist_ok=True)
    now_iso = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    doc = "\n".join(
        [
            f"# Cross-Harness Session Handoff (`{meta.get('sessionId', 'session')}`)",
            "",
            f"- **Generated At**: {now_iso}",
            f"- **Working Directory**: `{cwd}`",
            f"- **Git Branch**: `{git_ctx.get('branch') or meta.get('gitBranch', 'main')}`",
            f"- **Pre-Handoff Context Size**: `{transcript_state['context_tokens']:,}` tokens "
            f"(`r_tool={transcript_state['r_tool']}`, `r_edit={transcript_state['r_edit']}`)",
            f"- **Magpie Pool State**: `{quota_state['healthy_claude_seat_count']}/{quota_state['total_claude_seat_count']}` "
            f"healthy Claude seats (earliest 5h reset in `{quota_state['minutes_to_earliest_reset']}` min)",
            f"- **Engine Recommendation**: `{decision['recommended_action']}` (`J = {decision['recommended_score']}`)",
            "",
            digest,
            "",
            "### 7. Continuation Instructions for Receiving Agent",
            "1. Review the touched files and `git diff --stat` above before reading any large files from scratch.",
            "2. Continue directly from the latest user steering prompt without repeating completed verification steps.",
            "",
        ]
    )
    target.write_text(doc, encoding="utf-8")
    return target


def format_explain_table(
    transcript_state: dict[str, Any],
    quota_state: dict[str, Any],
    decision: dict[str, Any],
) -> str:
    lines: list[str] = []
    lines.append("╭──────────────────────────────────────────────────────────────────────────────╮")
    lines.append("│ cc-compactor: Multi-Dimensional Weighted Context & Pool Decision Engine      │")
    lines.append("╰──────────────────────────────────────────────────────────────────────────────╯")
    lines.append(f"  Session JSONL : {transcript_state['jsonl_path']}")
    lines.append(
        f"  Context State : C_raw = {transcript_state['context_tokens']:,} tokens | "
        f"cache_age = {transcript_state['cache_age_sec']}s (TTL rem: {transcript_state['cache_ttl_remaining_min']}m)"
    )
    lines.append(
        f"  Signal Ratios : r_tool = {transcript_state['r_tool']:.2f} | "
        f"r_edit = {transcript_state['r_edit']:.2f} | "
        f"overflows_zcode_200k = {decision['overflows_zcode_200k']}"
    )
    lines.append(
        f"  Magpie Pool   : healthy_claude_seats = {quota_state['healthy_claude_seat_count']}/{quota_state['total_claude_seat_count']} | "
        f"active_seat = {quota_state['active_seat']} (5h: {quota_state['active_used_5h']:.0f}%, 7d: {quota_state['active_used_7d']:.0f}%)"
    )
    lines.append(
        f"  Reset Horizon : earliest_5h_reset = {quota_state['minutes_to_earliest_reset']:.1f}m | "
        f"cache_write_ratio = {quota_state['cache_write_ratio']:.3f}"
    )
    lines.append("")
    w = decision["weights"]
    lines.append(
        f"  Active Profile: [{decision['profile']}] "
        f"(w_quota={w['w_quota']}, w_cache={w['w_cache']}, w_wait={w['w_wait']}, "
        f"w_loss={w['w_loss']}, w_stampede={w['w_stampede']})"
    )
    lines.append("  ──────────────────────────────────────────────────────────────────────────────")
    lines.append(
        "  Rank  Candidate Action         Total J   Phi_q   Phi_c   Phi_w   Phi_l   Phi_s"
    )
    lines.append("  ──────────────────────────────────────────────────────────────────────────────")
    for idx, item in enumerate(decision["ranked_actions"], 1):
        c = item["components"]
        marker = "★" if idx == 1 else " "
        lines.append(
            f"  {marker} #{idx}  {item['action']:<23}  {item['score']:>7.4f}  "
            f"{c['Phi_quota']:>6.3f}  {c['Phi_cache']:>6.3f}  {c['Phi_wait']:>6.3f}  "
            f"{c['Phi_loss']:>6.3f}  {c['Phi_stampede']:>6.3f}"
        )
    lines.append("  ──────────────────────────────────────────────────────────────────────────────")
    lines.append(
        f"  Optimal Action a* = {decision['recommended_action']} (J* = {decision['recommended_score']:.4f})"
    )
    return "\n".join(lines)


def cmd_explain(args: argparse.Namespace, cfg: dict[str, Any]) -> int:
    jsonl_path = find_session_jsonl(args.session, args.cwd)
    t_state = analyze_transcript(jsonl_path)
    q_state = fetch_magpie_quotas(cfg)
    decision = evaluate_actions(t_state, q_state, cfg, profile_name=args.profile)

    if args.json:
        out = {
            "transcript": {k: v for k, v in t_state.items() if k != "conversation_records"},
            "quotas": q_state,
            "decision": decision,
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        print(format_explain_table(t_state, q_state, decision))
    return 0


def cmd_compact(args: argparse.Namespace, cfg: dict[str, Any]) -> int:
    t0 = time.time()
    jsonl_path = find_session_jsonl(args.session, args.cwd)
    t_state = analyze_transcript(jsonl_path)
    q_state = fetch_magpie_quotas(cfg)
    decision = evaluate_actions(t_state, q_state, cfg, profile_name=args.profile)

    allowed, reason = check_and_record_rate_limit(cfg, dry_run=args.dry_run or args.force)
    if not allowed and not args.force:
        print(json.dumps({"status": "skipped", "reason": reason}, indent=2))
        return 0

    meta = t_state.get("meta") or {}
    git_ctx = collect_git_context(meta.get("cwd", str(Path.cwd())))
    deterministic_digest = build_deterministic_digest(t_state, git_ctx)

    if args.deterministic_only:
        summary_md = deterministic_digest
        source = "deterministic_ast_git"
    else:
        byok_md, source = distill_with_byok_llm(deterministic_digest, t_state, cfg)
        summary_md = byok_md if byok_md else deterministic_digest

    duration_ms = int((time.time() - t0) * 1000)

    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "dry_run",
                    "session_path": str(jsonl_path),
                    "pre_tokens": t_state["context_tokens"],
                    "compactor_source": source,
                    "recommended_action": decision["recommended_action"],
                    "summary_preview": summary_md[:1200],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    result = splice_compact_boundary(
        jsonl_path=jsonl_path,
        transcript_state=t_state,
        summary_markdown=summary_md,
        compactor_source=source,
        cfg=cfg,
        duration_ms=duration_ms,
    )
    result["status"] = "compacted"
    result["recommended_action"] = decision["recommended_action"]
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def cmd_handoff(args: argparse.Namespace, cfg: dict[str, Any]) -> int:
    jsonl_path = find_session_jsonl(args.session, args.cwd)
    t_state = analyze_transcript(jsonl_path)
    q_state = fetch_magpie_quotas(cfg)
    decision = evaluate_actions(t_state, q_state, cfg, profile_name=args.profile)
    path = write_handoff_document(t_state, q_state, decision, cfg, output_path=args.output)
    print(
        json.dumps(
            {
                "status": "handoff_written",
                "handoff_path": str(path),
                "context_tokens": t_state["context_tokens"],
                "recommended_action": decision["recommended_action"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def cmd_keep_warm(args: argparse.Namespace, cfg: dict[str, Any]) -> int:
    jsonl_path = find_session_jsonl(args.session, args.cwd)
    t_state = analyze_transcript(jsonl_path)
    q_state = fetch_magpie_quotas(cfg)

    kw_cfg = cfg.get("keep_warm", {})
    ping_after = float(kw_cfg.get("ping_after_idle_seconds", 3120))
    ttl_sec = float(kw_cfg.get("ttl_seconds", 3600))
    min_tokens = int(kw_cfg.get("min_cached_tokens", 90000))

    age = float(t_state["cache_age_sec"])
    tokens = int(t_state["context_tokens"])

    should_ping = (
        args.force
        or (
            bool(kw_cfg.get("enabled", True))
            and ping_after <= age < ttl_sec
            and tokens >= min_tokens
            and q_state["healthy_claude_seat_count"] > 0
        )
    )

    out = {
        "session_path": str(jsonl_path),
        "context_tokens": tokens,
        "cache_age_sec": age,
        "healthy_claude_seats": q_state["healthy_claude_seat_count"],
        "should_ping": should_ping,
    }
    print(json.dumps(out, indent=2))
    return 0


def cmd_hook(args: argparse.Namespace, cfg: dict[str, Any]) -> int:
    # Non-blocking hook entrypoint for Claude Code PreCompact / Stop / PostToolUse
    try:
        jsonl_path = find_session_jsonl(args.session, args.cwd)
        t_state = analyze_transcript(jsonl_path)
        min_tokens = int(cfg.get("limits", {}).get("auto_trigger_min_tokens", 155000))
        if t_state["context_tokens"] < min_tokens and not args.force:
            return 0

        q_state = fetch_magpie_quotas(cfg)
        decision = evaluate_actions(t_state, q_state, cfg, profile_name=args.profile)
        rec = decision["recommended_action"]

        if rec in ("BYOK_JSONL_SPLICE", "WARM_PRECOMPACT") and args.apply:
            allowed, _ = check_and_record_rate_limit(cfg, dry_run=False)
            if allowed:
                meta = t_state.get("meta") or {}
                git_ctx = collect_git_context(meta.get("cwd", str(Path.cwd())))
                digest = build_deterministic_digest(t_state, git_ctx)
                byok_md, source = distill_with_byok_llm(digest, t_state, cfg)
                splice_compact_boundary(
                    jsonl_path=jsonl_path,
                    transcript_state=t_state,
                    summary_markdown=byok_md or digest,
                    compactor_source=source,
                    cfg=cfg,
                    duration_ms=250,
                )
        elif rec == "CROSS_HARNESS_HANDOFF" and args.apply:
            write_handoff_document(t_state, q_state, decision, cfg)
    except Exception:
        return 0
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cc-compactor",
        description="Multi-dimensional weighted context compaction & handoff engine for Claude Code + Magpie",
    )
    parser.add_argument("--config", help="Path to cc-compactor.toml configuration file")
    parser.add_argument(
        "--profile",
        choices=["balanced", "cache_first", "zero_claude_burn", "speed_first"],
        help="Override 5D weight profile",
    )
    parser.add_argument("--session", help="Session JSONL file path or UUID substring")
    parser.add_argument("--cwd", help="Project working directory to resolve latest session")

    sub = parser.add_subparsers(dest="subcommand", required=True)

    p_exp = sub.add_parser("explain", help="Evaluate 5D cost table and print recommended action")
    p_exp.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    p_cmp = sub.add_parser("compact", help="Run surgical hybrid compaction and splice compact_boundary")
    p_cmp.add_argument("--dry-run", action="store_true", help="Preview summary without writing to JSONL")
    p_cmp.add_argument(
        "--deterministic-only",
        action="store_true",
        help="Use deterministic AST/git/log extraction only without calling BYOK LLM",
    )
    p_cmp.add_argument("--force", action="store_true", help="Bypass cooldown guard")

    p_ho = sub.add_parser("handoff", help="Generate cross-harness .claude/handoff/current.md")
    p_ho.add_argument("--output", help="Custom output path for HANDOFF.md")

    p_kw = sub.add_parser("keep-warm", help="Evaluate cache TTL cliff status for keep-warm ping")
    p_kw.add_argument("--force", action="store_true", help="Force ping evaluation")

    p_hk = sub.add_parser("hook", help="Claude Code hook entrypoint (PreCompact / Stop / PostToolUse)")
    p_hk.add_argument("--apply", action="store_true", help="Automatically execute recommended compaction/handoff")
    p_hk.add_argument("--force", action="store_true", help="Bypass minimum token gate")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    cfg = load_config(args.config)

    if args.subcommand == "explain":
        return cmd_explain(args, cfg)
    if args.subcommand == "compact":
        return cmd_compact(args, cfg)
    if args.subcommand == "handoff":
        return cmd_handoff(args, cfg)
    if args.subcommand == "keep-warm":
        return cmd_keep_warm(args, cfg)
    if args.subcommand == "hook":
        return cmd_hook(args, cfg)
    return 1


if __name__ == "__main__":
    sys.exit(main())
