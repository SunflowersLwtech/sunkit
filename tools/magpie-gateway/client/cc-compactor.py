#!/usr/bin/env python3
"""
cc-compactor — what to do with a Claude Code session that stopped on a usage limit.

Three actions are scored for a stopped session:

  wait     等额度          leave it; say "continue" in it when a seat (or a usable pool) has room again
  compact  压缩后 --resume  splice a summary into its transcript as Claude Code's own compact_boundary,
                           then resume it (smaller context: cheaper first turn and every turn after)
  handoff  写交接换人      write a handoff document and give the work to another session or executor

on four dimensions, each a penalty in [0, 1] built from weighted parts (every weight is in the config):

  timing   how long until the action can go on (seat/pool reset times, the live guard) against how long
           the task can wait (urgency), plus how sure that wait is
  session  what the session loses: context dropped by a summary, a raw context near the window, a warm
           cache thrown away (how long it has been stopped decides whether the cache is still warm)
  cost     seat allowance the action spends: the resume turn, the turns after it, the summary call
  account  that spend against the room left on the seats (5-hour and weekly) when the action goes on

J(action) = sum(weight[d] * penalty[d]) / sum(weight); the lowest J is the recommendation.

Subcommands: explain (score and print), compact (splice a summary into a stopped session), handoff
(write the handoff document). Nothing here runs inside a live session: compact refuses a transcript
written to within limits.live_guard_sec.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import os
import re
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
from zoneinfo import ZoneInfo

ACTIONS = {"wait": "等额度", "compact": "压缩后 --resume", "handoff": "写交接换人"}
DIMENSIONS = ("timing", "session", "cost", "account")
DIMENSION_LABELS = {"timing": "时机", "session": "会话", "cost": "成本", "account": "账号"}

# Digest sections and summary instructions a compaction keeps; evictable excerpt kinds.
PRESERVE_BUCKETS = ("user_requests", "todos", "files_touched", "git_state", "commands", "errors", "decisions")
EVICT_BUCKETS = ("read_results", "passing_test_logs")

DEFAULT_CONFIG: dict[str, Any] = {
    "general": {
        "default_profile": "balanced",
        "default_urgency": "normal",
        "magpie_settings_path": "~/.claude/magpie-settings.json",
        # For --route seat: the seat this machine's Claude Code is signed in to (oauthAccount.emailAddress).
        "claude_json_path": "~/.claude.json",
        "state_dir": "~/.cache/cc-compactor",
        "handoff_relpath": ".claude/handoff/current.md",
    },
    "limits": {
        "max_byok_input_chars": 18000,
        # The reply is bounded by the prompt (<1200 words), the input cap above and
        # the rate limits below, not by cutting the model's output short.
        "max_byok_output_tokens": 32000,
        "byok_timeout_sec": 90,
        # A transcript written to within this many seconds belongs to a running
        # session: Claude Code keeps that conversation in memory, so a splice
        # would only take effect on --resume and could race its next write.
        "live_guard_sec": 120,
        "min_compaction_cooldown_sec": 180,
        "max_compactions_per_hour": 6,
    },
    "compaction": {
        # Gateway models tried in order for the summary; with none answering the digest is used alone.
        # LiteLLM's Claude API first (its own cc-compactor key: Haiku only, $25 / 30 days, 30 rpm), so a
        # compaction spends no seat; seat Haiku next, "always-up" last.
        "byok_chain": ["litellm-claude-api/hipimind/claude-haiku-5-5", "litellm-claude-api/anthropic/claude-haiku-4-5", "claude-haiku-5-5", "always-up"],
        "preserve_tail_messages": 10,
        # The summary plus the kept tail; tail records are dropped from the front past this.
        "target_post_compact_tokens": 40000,
        # Expected size of the summary (also used by the cost estimate).
        "summary_tokens": 3000,
        "preserve_buckets": list(PRESERVE_BUCKETS),
        "evict_buckets": list(EVICT_BUCKETS),
    },
    "seats": {
        # Only these plans count as seats the gateway serves (the personal Max card is plan "max").
        "plans": ["team"],
        # A seat is full at its cap: the gateway stops sending it work there (providers.json accountCaps).
        "caps": {"5 hours": 95, "7 days": 100},
        # Per-seat overrides, keyed like the gateway's accountWindowCaps (lower-case card user). They go in each
        # machine's own config: the shipped defaults name no account.
        "seat_caps": {},
        "window_tokens": 1000000,
        "safe_window_ratio": 0.90,
    },
    # Other gateway pools. usable = the gateway's group falls back to it for a resumed session and that
    # model is acceptable for the work; only then does it count as room. seat_pct_factor converts the
    # pool's spend into seat-percent (how scarce it is next to a Claude seat).
    "pools": {
        "zcode": {"window_tokens": 1000000, "usable": False, "min_remaining_pct": 5, "seat_pct_factor": 0.12},
        "devin": {"window_tokens": 1000000, "usable": False, "min_remaining_pct": 5, "seat_pct_factor": 0.22},
        "grok": {"window_tokens": 256000, "usable": False, "min_remaining_pct": 5, "seat_pct_factor": 0.15},
    },
    "weights": {"timing": 0.30, "session": 0.25, "cost": 0.25, "account": 0.20},
    "timing": {
        # The wait (minutes) at which the timing penalty is one half: penalty = minutes / (minutes + this).
        # The secretary's rule (limit-migration-judgment): back within half an hour -> wait; an hour or
        # more and the work is urgent or long -> hand it to another executor.
        "tolerable_wait_min": {"high": 10, "normal": 30, "low": 120},
        # Wait assumed when neither seat readings nor the stop message give one.
        "unknown_wait_min": 60,
        "compact_min": 2,
        "handoff_min": 10,
        "w_wait": 0.8,
        "w_uncertain": 0.2,
    },
    "session": {
        "cache_ttl_sec": 3600,
        # Below this a summary saves too little to be worth what it drops.
        "compact_min_tokens": 100000,
        "compact_loss": 0.6,
        # Share of the loss tool output takes away (logs and file contents are cheap to get back).
        "tool_relief": 0.5,
        "handoff_loss": 0.8,
        "w_loss": 0.6,
        "w_size": 0.25,
        "w_cache": 0.15,
    },
    "cost": {
        # Input-equivalent tokens per percent of a seat's 5-hour window.
        "tokens_per_seat_pct": 300000,
        "cache_write_mult": 2.0,
        "cache_read_mult": 0.1,
        "output_mult": 5.0,
        # Price of the summary model next to the session's model (Haiku against Opus).
        "compactor_price_factor": 0.2,
        "turns_after_resume": 15,
        "handoff_reread_tokens": 80000,
        # Seat-percent at which the cost penalty reaches 1.
        "norm_pct": 20,
    },
    "account": {
        "w_5h": 0.7,
        "w_7d": 0.3,
        # Weekly percent one 5-hour percent of a seat uses up (estimate).
        "pct_7d_per_pct_5h": 0.15,
        "min_headroom_pct": 1,
        # Room a handoff lands on (another executor or session); 100 = a whole fresh seat.
        "handoff_headroom_pct": 100,
    },
    # A profile is deep-merged over the sections above before scoring.
    "profiles": {
        "balanced": {},
        "speed_first": {"weights": {"timing": 0.50, "session": 0.20, "cost": 0.15, "account": 0.15}},
        "quality_first": {"weights": {"timing": 0.20, "session": 0.50, "cost": 0.15, "account": 0.15}},
        "seat_saver": {"weights": {"timing": 0.15, "session": 0.20, "cost": 0.35, "account": 0.30}},
    },
}

# Tables whose keys are names chosen in the config (any key is fine below them).
FREE_KEY_TABLES = {("seats", "seat_caps"), ("pools",), ("profiles",), ("timing", "tolerable_wait_min")}
# Fields of one [pools.<provider>] table; a pool named only in the config gets these defaults.
POOL_DEFAULT = {"window_tokens": 200000, "usable": False, "min_remaining_pct": 5, "seat_pct_factor": 0.2}
SEAT_WINDOWS = ("5 hours", "7 days")
# What a profile may override: the sections scoring reads. Compaction itself never reads a profile.
SCORING_SECTIONS = ("weights", "timing", "session", "cost", "account", "seats", "pools")


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
            merged["pools"] = {name: deep_merge(POOL_DEFAULT, pool or {}) for name, pool in merged["pools"].items()}
            merged["_config_path"] = str(path)
            merged["_problems"] = config_problems(user_cfg)
            return merged

    merged = copy.deepcopy(DEFAULT_CONFIG)
    merged["_config_path"] = "<builtin-defaults>"
    merged["_problems"] = []
    return merged


def config_problems(user_cfg: dict[str, Any], schema: dict[str, Any] | None = None, path: tuple = ()) -> list[str]:
    """Keys the code doesn't know (a typo or a leftover is a setting that silently does nothing),
    and bucket names outside the vocabulary."""
    schema = DEFAULT_CONFIG if schema is None else schema
    out: list[str] = []
    for k, v in user_cfg.items():
        here = path + (k,)
        if path and path in FREE_KEY_TABLES:
            continue
        if k not in schema:
            out.append("unknown key " + ".".join(here))
            continue
        if isinstance(v, dict) and isinstance(schema[k], dict) and here not in FREE_KEY_TABLES:
            out.extend(config_problems(v, schema[k], here))
    if path:
        return out
    for name, pool in (user_cfg.get("pools") or {}).items():
        for k in pool or {}:
            if k not in POOL_DEFAULT:
                out.append(f"unknown key pools.{name}.{k} (a pool has {', '.join(POOL_DEFAULT)})")
    for user, caps in ((user_cfg.get("seats") or {}).get("seat_caps") or {}).items():
        for k in caps or {}:
            if k not in SEAT_WINDOWS:
                out.append(f"unknown window seats.seat_caps.{user!r}.{k!r} (windows: {', '.join(SEAT_WINDOWS)})")
    comp = user_cfg.get("compaction") or {}
    for key, vocab in (("preserve_buckets", PRESERVE_BUCKETS), ("evict_buckets", EVICT_BUCKETS)):
        for name in comp.get(key) or []:
            if name not in vocab:
                out.append(f"compaction.{key}: unknown bucket {name!r} (known: {', '.join(vocab)})")
    for name, prof in (user_cfg.get("profiles") or {}).items():
        for k, v in (prof or {}).items():
            if k not in SCORING_SECTIONS:
                out.append(f"unknown key profiles.{name}.{k} (a profile sets only {', '.join(SCORING_SECTIONS)})")
            elif isinstance(v, dict):
                out.extend(p.replace("unknown key ", f"unknown key profiles.{name}.", 1)
                           for p in config_problems({k: v}) if p.startswith("unknown key"))
    return out


def scoring_config(cfg: dict[str, Any], profile_name: str | None) -> tuple[str, dict[str, Any]]:
    name = profile_name or cfg["general"]["default_profile"]
    profiles = cfg.get("profiles") or {}
    if name not in profiles:
        raise SystemExit(f"cc-compactor: no profile {name!r} (have: {', '.join(sorted(profiles))})")
    base = {k: v for k, v in cfg.items() if k != "profiles"}
    out = deep_merge(base, {k: v for k, v in (profiles[name] or {}).items() if k in SCORING_SECTIONS})
    out["pools"] = {p: deep_merge(POOL_DEFAULT, pool or {}) for p, pool in out["pools"].items()}
    return name, out


def load_magpie_connection(cfg: dict[str, Any]) -> dict[str, Any]:
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "").strip()
    custom_headers_raw = os.environ.get("ANTHROPIC_CUSTOM_HEADERS", "").strip()
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()

    settings_path = Path(cfg["general"]["magpie_settings_path"]).expanduser()
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


def iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ── seat and pool readings ────────────────────────────────────────────────────


def fetch_quota_cards(cfg: dict[str, Any]) -> tuple[list[dict[str, Any]] | None, str | None]:
    conn = load_magpie_connection(cfg)
    if not conn["base_url"]:
        return None, "missing_base_url"
    req = urllib.request.Request(f"{conn['base_url']}/v1/magpie/quotas", headers=conn["headers"], method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"[:200]
    raw = payload.get("data", []) if isinstance(payload, dict) else payload
    return (raw if isinstance(raw, list) else []), None


def general_window(windows: list[Any], name: str) -> dict[str, Any] | None:
    """The card's window called exactly `name`. "7 days · Fable" is a window for one model:
    reading it as the seat's week shows 0% while the seat's own week is a third used."""
    for w in windows:
        if isinstance(w, dict) and str(w.get("name", "")).strip().lower() == name:
            return w
    return None


def seat_cap(user: str, window: str, seats_cfg: dict[str, Any]) -> float:
    own = (seats_cfg.get("seat_caps") or {}).get(user.lower()) or {}
    if own.get(window) is not None:
        return float(own[window])
    return float((seats_cfg.get("caps") or {}).get(window, 100))


def read_seat(item: dict[str, Any], seats_cfg: dict[str, Any], now: float) -> dict[str, Any]:
    user = str(item.get("user") or "")
    windows = item.get("windows") if isinstance(item.get("windows"), list) else []
    w5, w7 = general_window(windows, "5 hours"), general_window(windows, "7 days")
    cap5, cap7 = seat_cap(user, "5 hours", seats_cfg), seat_cap(user, "7 days", seats_cfg)

    used5 = float(w5.get("used") or 0) if w5 else None
    reset5 = parse_iso_ts(w5.get("resetsAt")) if w5 else None
    if reset5 is not None and reset5 <= now:  # rolled over since the reading
        used5, reset5 = 0.0, None
    used7 = float(w7.get("used") or 0) if w7 else 0.0
    reset7 = parse_iso_ts(w7.get("resetsAt")) if w7 else None
    if reset7 is not None and reset7 <= now:
        used7, reset7 = 0.0, None

    unread = w5 is None
    full5 = used5 is not None and used5 >= cap5
    full7 = used7 >= cap7
    healthy = not (unread or full5 or full7)
    usable_at = reset7 if full7 else (reset5 if full5 else None)
    return {
        "user": user,
        "plan": str(item.get("plan") or ""),
        "used_5h": used5,
        "cap_5h": cap5,
        "reset_5h_ts": reset5,
        "used_7d": used7,
        "cap_7d": cap7,
        "reset_7d_ts": reset7,
        "unread": unread,
        "healthy": healthy,
        "usable_at_ts": None if healthy else usable_at,
        "headroom_5h": max(0.0, cap5 - used5) if healthy else 0.0,
        "headroom_7d": max(0.0, cap7 - used7),
        "last": bool(item.get("last")),
        "last_served_ts": parse_iso_ts(item.get("lastServedAt")) or 0.0,
    }


def read_pool(items: list[dict[str, Any]], now: float) -> dict[str, Any]:
    """A non-Claude provider: room is what its fullest window leaves, on its best account."""
    best: dict[str, Any] | None = None
    for item in items:
        used, reset = 0.0, None
        for w in item.get("windows") or []:
            if not isinstance(w, dict) or w.get("used") is None:
                continue
            u = float(w.get("used") or 0)
            r = parse_iso_ts(w.get("resetsAt"))
            if r is not None and r <= now:
                continue
            if u >= used:
                used, reset = u, r
        cand = {"remaining_pct": max(0.0, 100.0 - used), "reset_ts": reset if used >= 100 else None}
        if best is None or cand["remaining_pct"] > best["remaining_pct"]:
            best = cand
    return best or {"remaining_pct": 0.0, "reset_ts": None}


def read_quotas(cfg: dict[str, Any], now: float, cards: list[dict[str, Any]] | None, error: str | None = None) -> dict[str, Any]:
    if cards is None:
        return {"reachable": False, "error": error, "seats": [], "skipped": [], "pools": {}, "healthy": 0, "counted": 0}
    seats_cfg = cfg["seats"]
    plans = {str(p).lower() for p in seats_cfg.get("plans") or []}
    seats, skipped = [], []
    pools: dict[str, list[dict[str, Any]]] = {}
    for item in cards:
        if not isinstance(item, dict):
            continue
        prov = str(item.get("provider", ""))
        if prov == "claude":
            if str(item.get("plan") or "").lower() not in plans:
                skipped.append({"user": item.get("user"), "plan": item.get("plan"), "why": "plan not in seats.plans"})
                continue
            seats.append(read_seat(item, seats_cfg, now))
        elif prov:
            pools.setdefault(prov, []).append(item)
    return {
        "reachable": True,
        "error": None,
        "seats": seats,
        "skipped": skipped,
        "pools": {p: read_pool(items, now) for p, items in pools.items()},
        "healthy": sum(1 for s in seats if s["healthy"]),
        "counted": len(seats),
    }


def fetch_magpie_quotas(cfg: dict[str, Any], now_ts: float | None = None, mock_payload: Any = None) -> dict[str, Any]:
    now = now_ts if now_ts is not None else time.time()
    if mock_payload is not None:
        cards = mock_payload.get("data", []) if isinstance(mock_payload, dict) else mock_payload
        return read_quotas(cfg, now, cards)
    cards, err = fetch_quota_cards(cfg)
    return read_quotas(cfg, now, cards, err)


def signed_in_seat(cfg: dict[str, Any]) -> str | None:
    path = Path(cfg["general"]["claude_json_path"]).expanduser()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        email = ((data.get("oauthAccount") or {}) if isinstance(data, dict) else {}).get("emailAddress")
        return str(email).lower() if email else None
    except Exception:
        return None


# ── transcript ────────────────────────────────────────────────────────────────


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


RESET_RE = re.compile(
    r"resets\s+(?:(?P<mon>[A-Z][a-z]{2})\s+(?P<day>\d{1,2}),?\s+(?:at\s+)?)?"
    r"(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ap>am|pm)(?:\s+\((?P<tz>[^)]+)\))?",
    re.I,
)
ZH_RESET_RE = re.compile(r"将在\s*(\d{4}-\d{2}-\d{2})\s+(\d{1,2}:\d{2}(?::\d{2})?)\s*重置")
# The gateway names the provider it tried last ("Request rejected (429) · Claude Code: ...",
# "API Error: 402 Grok (SuperGrok): ..."); a session signed in to Anthropic directly gets no name.
GATEWAY_RE = re.compile(r"Request rejected \((\d+)\)\s*·\s*([A-Za-z][^:{]*):")
PROVIDER_RE = re.compile(r"API Error:\s*(\d{3})\s+([A-Za-z][^:{]*):")
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_reset_text(text: str, ref_ts: float) -> float | None:
    """When a limit message says the limit lifts: Claude Code's "resets 6:20am (Asia/Shanghai)" /
    "resets Oct 29, 3pm (Asia/Kuala_Lumpur)", ZCode's "将在 2026-11-01 12:00:00 重置" (Beijing time)."""
    m = RESET_RE.search(text or "")
    if m:
        try:
            tz = ZoneInfo(m["tz"].strip()) if m["tz"] else dt.timezone.utc
        except Exception:
            tz = dt.timezone.utc
        ref = dt.datetime.fromtimestamp(ref_ts, tz)
        hour = int(m["h"]) % 12 + (12 if m["ap"].lower() == "pm" else 0)
        minute = int(m["m"] or 0)
        if m["mon"] and m["mon"].lower() in MONTHS:
            cand = dt.datetime(ref.year, MONTHS[m["mon"].lower()], int(m["day"]), hour, minute, tzinfo=tz)
            if cand < ref - dt.timedelta(days=1):
                cand = cand.replace(year=ref.year + 1)
        else:
            cand = ref.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if cand <= ref:
                cand += dt.timedelta(days=1)
        return cand.timestamp()
    z = ZH_RESET_RE.search(text or "")
    if z:
        clock = z.group(2) if z.group(2).count(":") == 2 else z.group(2) + ":00"
        try:
            return dt.datetime.fromisoformat(f"{z.group(1)}T{clock}").replace(tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
        except Exception:
            return None
    return None


def read_stop(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The API error the session stopped on: its last assistant record, when that is one."""
    for rec in reversed(records):
        if rec.get("type") != "assistant":
            continue
        if not rec.get("isApiErrorMessage"):
            return None
        msg = rec.get("message") if isinstance(rec.get("message"), dict) else {}
        content = msg.get("content")
        text = content if isinstance(content, str) else " ".join(
            str(b.get("text", "")) for b in content or [] if isinstance(b, dict) and b.get("type") == "text"
        )
        at = parse_iso_ts(rec.get("timestamp"))
        gw = GATEWAY_RE.search(text)
        prov = gw or PROVIDER_RE.search(text)
        low = text.lower()
        if "hit your session limit" in low:
            kind = "session_limit"
        elif "hit your weekly limit" in low:
            kind = "weekly_limit"
        elif rec.get("error") == "rate_limit" or rec.get("apiErrorStatus") == 429 or any(
            w in low for w in ("quota", "usage limit", "balance exhausted", "budget has been exceeded", "credits consumed", "使用上限")
        ):
            kind = "usage_limit"
        else:
            kind = "other"
        return {
            "kind": kind,
            "limit": kind != "other",
            "provider": prov.group(2).strip() if prov else None,
            "via_gateway": bool(prov),
            "at_ts": at,
            "reset_ts": parse_reset_text(text, at or time.time()),
            "text": text[:300],
        }
    return None


def analyze_transcript(jsonl_path: Path, now_ts: float | None = None, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    now = now_ts if now_ts is not None else time.time()
    ttl = float((cfg or DEFAULT_CONFIG)["session"]["cache_ttl_sec"])
    raw_lines = jsonl_path.read_text(encoding="utf-8", errors="replace").splitlines()

    records: list[dict[str, Any]] = []
    last_boundary_idx = -1
    compactions = 0
    last_ts: float | None = None

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
            compactions += 1
        ts = parse_iso_ts(obj.get("timestamp"))
        if ts is not None and (last_ts is None or ts > last_ts):
            last_ts = ts

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
    tool_names: dict[str, str] = {}
    latest_todos: list[dict[str, Any]] = []

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
                    if block.get("id"):
                        tool_names[str(block["id"])] = tname
                    inp = block.get("input") if isinstance(block.get("input"), dict) else {}
                    msg_chars += len(json.dumps(inp, ensure_ascii=False))
                    if tname in edit_tool_names:
                        has_edit_in_turn = True
                    if tname == "TodoWrite" and isinstance(inp.get("todos"), list):
                        latest_todos = [t for t in inp["todos"] if isinstance(t, dict)]
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
                    t_snippet = tool_result_text(block)
                    blen = len(t_snippet)
                    msg_chars += blen
                    tool_result_chars += blen
                    t_snippet = t_snippet.strip()

                    is_err = bool(block.get("is_error"))
                    if is_err or any(marker in t_snippet for marker in ERROR_MARKERS):
                        tail_err = " ".join(t_snippet[-360:].split())
                        if tail_err:
                            errors_and_failures.append(tail_err)

        total_chars += msg_chars
        if not (usage and role == "assistant"):
            chars_since_last_usage += msg_chars

        if role == "assistant" and not rec.get("isApiErrorMessage"):
            assistant_turns += 1
            if has_edit_in_turn:
                edit_turns += 1

    estimated_active_tokens = (
        last_usage_tokens + estimate_chars_to_tokens(chars_since_last_usage)
        if last_usage_tokens > 0
        else estimate_chars_to_tokens(total_chars)
    )

    cache_age_sec = max(0.0, now - last_cache_touch_ts) if last_cache_touch_ts is not None else ttl
    r_tool = round(tool_result_chars / max(1, total_chars), 4)
    r_edit = round(edit_turns / max(1, assistant_turns), 4)

    head_uuid = conversation_records[0].get("uuid") if conversation_records else None
    tail_uuid = conversation_records[-1].get("uuid") if conversation_records else None
    mtime = jsonl_path.stat().st_mtime

    return {
        "jsonl_path": str(jsonl_path),
        "total_records": len(records),
        "active_records_count": len(active_records),
        "conversation_records": conversation_records,
        "last_boundary_idx": last_boundary_idx,
        "compactions": compactions,
        "context_tokens": estimated_active_tokens,
        "cache_age_sec": round(cache_age_sec, 1),
        "cache_ttl_remaining_min": round(max(0.0, (ttl - cache_age_sec) / 60.0), 1),
        "last_record_ts": last_ts,
        "stopped_min": round(max(0.0, now - (last_ts if last_ts is not None else mtime)) / 60.0, 1),
        "quiet_sec": round(max(0.0, now - mtime), 1),
        "stop": read_stop(records),
        "r_tool": r_tool,
        "r_edit": r_edit,
        "initial_task": initial_task,
        "recent_user_prompts": recent_user_prompts[-6:],
        "touched_files": touched_files,
        "commands_run": commands_run[-12:],
        "errors_and_failures": errors_and_failures[-8:],
        "latest_todos": latest_todos,
        "tool_names": tool_names,
        "discovered_tools": sorted(discovered_tools),
        "meta": meta,
        "head_uuid": head_uuid,
        "tail_uuid": tail_uuid,
        "all_uuids": all_uuids,
    }


ERROR_MARKERS = ("Traceback (most recent", "AssertionError", "FAILED ", "Error: ", "exit code 1")
PASSING_RE = re.compile(r"\b\d+ passed\b|\bRan \d+ tests? in [\d.]+s\s+OK\b|\bAll tests passed\b|\btests? \d+ pass\b|^ok\s", re.I | re.M)


def tool_result_text(block: dict[str, Any]) -> str:
    tcontent = block.get("content")
    if isinstance(tcontent, str):
        return tcontent
    if isinstance(tcontent, list):
        return "\n".join(str(sub.get("text", "")) for sub in tcontent if isinstance(sub, dict) and sub.get("type") == "text")
    return ""


def activity_after(jsonl_path: Path, since_ts: float) -> dict[str, Any]:
    """What the session did after since_ts: its first answered turn (when, and what it read and wrote
    to the cache) and how many answered turns. Used to see how a stopped session was taken up."""
    first: dict[str, Any] | None = None
    turns = 0
    for line in jsonl_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if not isinstance(rec, dict) or rec.get("type") != "assistant" or rec.get("isApiErrorMessage"):
            continue
        ts = parse_iso_ts(rec.get("timestamp"))
        if ts is None or ts <= since_ts:
            continue
        msg = rec.get("message") if isinstance(rec.get("message"), dict) else {}
        u = msg.get("usage") if isinstance(msg.get("usage"), dict) else {}
        total = sum(int(u.get(k, 0) or 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens"))
        if total <= 0:
            continue
        turns += 1
        if first is None:
            first = {
                "at": iso(ts),
                "after_min": round((ts - since_ts) / 60.0, 1),
                "model": msg.get("model"),
                "cache_write": int(u.get("cache_creation_input_tokens", 0) or 0),
                "cache_read": int(u.get("cache_read_input_tokens", 0) or 0),
                "input": int(u.get("input_tokens", 0) or 0),
            }
    return {"turns": turns, "first": first}


# ── scoring ───────────────────────────────────────────────────────────────────


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def blend(parts: dict[str, tuple[float, float]]) -> float:
    """Weighted mean of (weight, penalty) pairs."""
    total = sum(w for w, _ in parts.values())
    return clamp01(sum(w * p for w, p in parts.values()) / total) if total > 0 else 0.0


def detect_route(t_state: dict[str, Any], cfg: dict[str, Any], route: str) -> str:
    if route in ("gateway", "seat"):
        return route
    stop = t_state.get("stop") or {}
    if stop.get("via_gateway"):
        return "gateway"
    if stop.get("limit") and stop.get("provider") is None:
        return "seat"
    return "gateway" if Path(cfg["general"]["magpie_settings_path"]).expanduser().is_file() else "seat"


def route_seats(q: dict[str, Any], route: str, login: str | None) -> list[dict[str, Any]]:
    seats = q.get("seats") or []
    if route == "seat":
        return [s for s in seats if login and s["user"].lower().startswith(login)]
    return seats


def capacity_wait(
    q: dict[str, Any], route: str, login: str | None, tokens: int, t_state: dict[str, Any], cfg: dict[str, Any], now: float
) -> dict[str, Any]:
    """How long until something can serve `tokens` of context on this route: minutes, what it is,
    the pool when it is one, and whether the minutes are only a guess."""
    best: dict[str, Any] | None = None
    if q.get("reachable") and q.get("seats"):
        for s in route_seats(q, route, login):
            if s["healthy"]:
                return {"minutes": 0.0, "source": f"seat {s['user']}", "pool": None, "guess": False}
            if s["usable_at_ts"]:
                m = max(0.0, (s["usable_at_ts"] - now) / 60.0)
                if best is None or m < best["minutes"]:
                    best = {"minutes": m, "source": f"seat {s['user']} resets", "pool": None, "guess": False}
    if q.get("reachable") and route == "gateway":
        for name, pc in (cfg.get("pools") or {}).items():
            pool = (q.get("pools") or {}).get(name)
            if not pool or not pc.get("usable") or tokens > float(pc["window_tokens"]) * float(cfg["seats"]["safe_window_ratio"]):
                continue
            if pool["remaining_pct"] >= float(pc["min_remaining_pct"]):
                return {"minutes": 0.0, "source": f"pool {name}", "pool": name, "guess": False}
            if pool["reset_ts"]:
                m = max(0.0, (pool["reset_ts"] - now) / 60.0)
                if best is None or m < best["minutes"]:
                    best = {"minutes": m, "source": f"pool {name} resets", "pool": name, "guess": False}
    if best is not None:
        best["minutes"] = round(best["minutes"], 1)
        return best
    stop = t_state.get("stop") or {}
    if stop.get("reset_ts"):
        return {"minutes": round(max(0.0, (stop["reset_ts"] - now) / 60.0), 1), "source": "stop message", "pool": None, "guess": False}
    return {"minutes": float(cfg["timing"]["unknown_wait_min"]), "source": "unknown", "pool": None, "guess": True}


def headroom_at(q: dict[str, Any], route: str, login: str | None, at_ts: float) -> tuple[float, float]:
    """Seat-percent of 5-hour and weekly room on the route's seats once at_ts has come: a seat that
    has room by then counts what its cap leaves (all of it when its window started over meanwhile)."""
    h5 = h7 = 0.0
    for s in route_seats(q, route, login):
        if s["unread"]:
            continue
        week_over = s["reset_7d_ts"] is not None and s["reset_7d_ts"] <= at_ts
        h7 += s["cap_7d"] if week_over else s["headroom_7d"]
        if not (s["healthy"] or (s["usable_at_ts"] is not None and s["usable_at_ts"] <= at_ts)):
            continue
        five_over = s["reset_5h_ts"] is not None and s["reset_5h_ts"] <= at_ts
        h5 += max(0.0, s["cap_5h"] - (0.0 if five_over else (s["used_5h"] or 0.0)))
    return h5, h7


def pool_room(q: dict[str, Any], cfg: dict[str, Any], name: str) -> tuple[float, float]:
    """(seat-percent factor of a pool's spend, its room in percent)."""
    return float(cfg["pools"][name]["seat_pct_factor"]), float(((q.get("pools") or {}).get(name) or {}).get("remaining_pct", 0.0))


def post_compact_tokens(t_state: dict[str, Any], cfg: dict[str, Any]) -> int:
    comp = cfg["compaction"]
    tail = select_safe_tail_records(t_state.get("conversation_records") or [], int(comp["preserve_tail_messages"]), tail_token_cap(cfg))
    return int(comp["summary_tokens"]) + sum(record_tokens(r) for r in tail)


def evaluate_actions(
    transcript_state: dict[str, Any],
    quota_state: dict[str, Any],
    cfg: dict[str, Any],
    profile_name: str | None = None,
    urgency: str | None = None,
    route: str = "auto",
    login: str | None = None,
    now_ts: float | None = None,
) -> dict[str, Any]:
    now = now_ts if now_ts is not None else time.time()
    prof_name, c = scoring_config(cfg, profile_name)
    tm, ss, co, ac, lim = c["timing"], c["session"], c["cost"], c["account"], c["limits"]
    W = {d: float(c["weights"][d]) for d in DIMENSIONS}
    urgency = urgency or c["general"]["default_urgency"]
    tolerable = tm["tolerable_wait_min"]
    if urgency not in tolerable:
        raise SystemExit(f"cc-compactor: no urgency {urgency!r} in timing.tolerable_wait_min (have: {', '.join(tolerable)})")
    tol = max(1.0, float(tolerable[urgency]))

    t = transcript_state
    C = int(t["context_tokens"])
    route = detect_route(t, c, route)
    ttl_min = float(ss["cache_ttl_sec"]) / 60.0
    cache_left = max(0.0, ttl_min - float(t["cache_age_sec"]) / 60.0)
    post = min(C, post_compact_tokens(t, c))
    window = float(c["seats"]["window_tokens"]) * float(c["seats"]["safe_window_ratio"])
    min_c = float(ss["compact_min_tokens"])

    per_pct = float(co["tokens_per_seat_pct"])
    write, read, out_mult = float(co["cache_write_mult"]), float(co["cache_read_mult"]), float(co["output_mult"])
    turns = float(co["turns_after_resume"])
    summary = int(c["compaction"]["summary_tokens"])

    def size_pressure(tokens: float) -> float:
        return clamp01((tokens - min_c) / max(1.0, window - min_c))

    def timing_pen(minutes: float, guess: bool) -> float:
        late = max(0.0, minutes) / (max(0.0, minutes) + tol)
        return blend({"wait": (float(tm["w_wait"]), late), "uncertain": (float(tm["w_uncertain"]), 1.0 if guess else 0.0)})

    def account_pen(spend_pct: float, h5: float, h7: float) -> float:
        floor = float(ac["min_headroom_pct"])
        return blend({
            "5h": (float(ac["w_5h"]), clamp01(spend_pct / max(floor, h5))),
            "7d": (float(ac["w_7d"]), clamp01(spend_pct * float(ac["pct_7d_per_pct_5h"]) / max(floor, h7))),
        })

    def spend_and_room(cap: dict[str, Any], tokens_spent: float, at_min: float) -> tuple[float, float, float]:
        """Seat-percent spent and the 5-hour / weekly room it is spent from (a pool's own room,
        its spend scaled by how scarce it is next to a seat)."""
        if cap["pool"]:
            factor, room = pool_room(quota_state, c, cap["pool"])
            return tokens_spent / per_pct * factor, room, room
        h5, h7 = headroom_at(quota_state, route, login, now + at_min * 60)
        return tokens_spent / per_pct, h5, h7

    raw = capacity_wait(quota_state, route, login, C, t, c, now)
    raw_warm = cache_left > raw["minutes"]  # the cache would still be there when a plain wait resumes
    actions: dict[str, dict[str, Any]] = {}

    # wait: resume the session as it is once there is room
    spend, h5, h7 = spend_and_room(raw, C * (read if raw_warm else write) + turns * C * read, raw["minutes"])
    actions["wait"] = {
        "minutes": raw["minutes"],
        "source": raw["source"],
        "spend_pct": spend,
        "dims": {
            "timing": timing_pen(raw["minutes"], raw["guess"]),
            "session": blend({"loss": (float(ss["w_loss"]), 0.0), "size": (float(ss["w_size"]), size_pressure(C)), "cache": (float(ss["w_cache"]), 0.0)}),
            "cost": clamp01(spend / float(co["norm_pct"])),
            "account": account_pen(spend, h5, h7),
        },
    }

    # compact: summary + kept tail, resumed once there is room (and the transcript has been quiet long enough)
    cw = capacity_wait(quota_state, route, login, post, t, c, now)
    guard_left = max(0.0, float(lim["live_guard_sec"]) - float(t.get("quiet_sec", 1e9))) / 60.0
    c_minutes = max(cw["minutes"], guard_left) + float(tm["compact_min"])
    dropped = clamp01(1.0 - post / max(1, C))
    loss = 1.0 if C < min_c else clamp01(float(ss["compact_loss"]) * dropped * (1.0 - float(ss["tool_relief"]) * float(t["r_tool"])))
    call = (min(C, int(lim["max_byok_input_chars"]) / 3.5) + summary * out_mult) * float(co["compactor_price_factor"])
    spend, h5, h7 = spend_and_room(cw, call + post * write + turns * post * read, c_minutes)
    c_guess = cw["guess"]
    actions["compact"] = {
        "minutes": round(c_minutes, 1),
        "source": cw["source"] if guard_left <= 0 else f"{cw['source']}; live guard {guard_left:.1f} min",
        "spend_pct": spend,
        "dims": {
            "timing": timing_pen(c_minutes, c_guess),
            "session": blend({"loss": (float(ss["w_loss"]), loss), "size": (float(ss["w_size"]), size_pressure(post)), "cache": (float(ss["w_cache"]), 1.0 if raw_warm else 0.0)}),
            "cost": clamp01(spend / float(co["norm_pct"])),
            "account": account_pen(spend, h5, h7),
        },
    }

    # handoff: a fresh session elsewhere reads the handoff document and re-reads what it needs
    fresh = summary + float(co["handoff_reread_tokens"])
    spend = (fresh * write + turns * fresh * read) / per_pct
    room = float(ac["handoff_headroom_pct"])
    h_minutes = float(tm["handoff_min"])
    actions["handoff"] = {
        "minutes": h_minutes,
        "source": "another executor",
        "spend_pct": spend,
        "dims": {
            "timing": timing_pen(h_minutes, False),
            "session": blend({"loss": (float(ss["w_loss"]), float(ss["handoff_loss"])), "size": (float(ss["w_size"]), 0.0), "cache": (float(ss["w_cache"]), 1.0 if raw_warm else 0.0)}),
            "cost": clamp01(spend / float(co["norm_pct"])),
            "account": account_pen(spend, room, room),
        },
    }

    wsum = sum(W.values()) or 1.0
    ranked = []
    for name, a in actions.items():
        score = sum(W[d] * a["dims"][d] for d in DIMENSIONS) / wsum
        ranked.append({
            "action": name,
            "label": ACTIONS[name],
            "score": round(score, 4),
            "dims": {d: round(a["dims"][d], 4) for d in DIMENSIONS},
            "minutes": round(a["minutes"], 1),
            "source": a["source"],
            "spend_pct": round(a["spend_pct"], 3),
        })
    ranked.sort(key=lambda r: r["score"])
    best = ranked[0]
    signals = {
        "route": route,
        "urgency": urgency,
        "context_tokens": C,
        "post_compact_tokens": post,
        "stopped_min": t.get("stopped_min"),
        "cache_left_min": round(cache_left, 1),
        "cache_warm_at_wait": raw_warm,
        "healthy_seats": quota_state.get("healthy", 0),
        "counted_seats": quota_state.get("counted", 0),
        "readings": "ok" if quota_state.get("reachable") else f"unreachable ({quota_state.get('error')})",
    }
    return {
        "profile": prof_name,
        "weights": W,
        "recommended_action": best["action"],
        "recommended_label": best["label"],
        "recommended_score": best["score"],
        "ranked_actions": ranked,
        "signals": signals,
        "summary_zh": summary_line(ranked, signals),
    }


def summary_line(ranked: list[dict[str, Any]], s: dict[str, Any]) -> str:
    best = ranked[0]
    others = "，".join(f"{r['label']} {r['score']:.2f}" for r in ranked[1:])
    cache = f"缓存还热 {s['cache_left_min']:.0f} 分钟" if s["cache_left_min"] > 0 else "缓存已冷"
    wait = next(r for r in ranked if r["action"] == "wait")
    when = "现在就有余量" if wait["minutes"] <= 0 else f"{wait['minutes']:.0f} 分钟后有余量（{wait['source']}）"
    dims = "；".join(
        f"{r['label']} " + "/".join(f"{r['dims'][d]:.2f}" for d in DIMENSIONS) for r in ranked
    )
    return (
        f"建议{best['label']}（J={best['score']:.2f}；{others}）。上下文 {s['context_tokens'] // 1000}K，停了 {s['stopped_min']:.0f} 分钟，{cache}，"
        f"{when}，健康座位 {s['healthy_seats']}/{s['counted_seats']}。四维得分（时机/会话/成本/账号，越低越好）：{dims}"
    )


# ── compaction ────────────────────────────────────────────────────────────────


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
    buckets: list[str] | tuple[str, ...] = PRESERVE_BUCKETS,
) -> str:
    keep = set(buckets)
    lines: list[str] = []
    if "user_requests" in keep:
        lines.append("### Primary User Request & Intent")
        lines.append(transcript_state.get("initial_task") or "(See recent prompt history below)")
        lines.append("")
        if transcript_state.get("recent_user_prompts"):
            lines.append("### Chronological User Steering Prompts")
            for idx, p in enumerate(transcript_state["recent_user_prompts"], 1):
                lines.append(f"{idx}. {p}")
            lines.append("")

    todos = transcript_state.get("latest_todos") or []
    if "todos" in keep and todos:
        lines.append("### Todo List (latest)")
        for td in todos[:40]:
            lines.append(f"- [{td.get('status', '?')}] {str(td.get('content') or td.get('activeForm') or '')[:200]}")
        lines.append("")

    touched: dict[str, str] = transcript_state.get("touched_files") or {}
    if "files_touched" in keep and touched:
        lines.append("### Touched Files & Mutation State")
        for fpath, tag in list(touched.items())[:30]:
            lines.append(f"- `[{tag}]` `{fpath}`")
        lines.append("")

    if "git_state" in keep and (git_ctx.get("status_short") or git_ctx.get("diff_stat")):
        lines.append("### Live Git Working Tree State")
        if git_ctx.get("status_short"):
            lines.append("```text")
            lines.append(git_ctx["status_short"])
            lines.append("```")
        if git_ctx.get("diff_stat"):
            lines.append("```text")
            lines.append(git_ctx["diff_stat"])
            lines.append("```")
        lines.append("")

    if "commands" in keep and transcript_state.get("commands_run"):
        lines.append("### Recent Commands Executed")
        for cmd in transcript_state["commands_run"]:
            lines.append(f"- `{cmd}`")
        lines.append("")

    if "errors" in keep and transcript_state.get("errors_and_failures"):
        lines.append("### Diagnostic Errors & Failing Assertions Retained")
        for err in transcript_state["errors_and_failures"]:
            lines.append(f"- {err}")
        lines.append("")

    return "\n".join(lines).strip()


def session_is_live(jsonl_path: Path, cfg: dict[str, Any], now_ts: float | None = None) -> bool:
    guard = float(cfg["limits"]["live_guard_sec"])
    now = now_ts if now_ts is not None else time.time()
    return guard > 0 and (now - jsonl_path.stat().st_mtime) < guard


def check_and_record_rate_limit(
    cfg: dict[str, Any], dry_run: bool = False, force: bool = False
) -> tuple[bool, str]:
    state_dir = Path(cfg["general"]["state_dir"]).expanduser()
    state_dir.mkdir(parents=True, exist_ok=True)
    rate_file = state_dir / "rate_guard.json"

    limits = cfg["limits"]
    cooldown_sec = int(limits["min_compaction_cooldown_sec"])
    max_per_hour = int(limits["max_compactions_per_hour"])
    now = time.time()

    history: list[float] = []
    if rate_file.is_file():
        try:
            data = json.loads(rate_file.read_text(encoding="utf-8"))
            history = [float(ts) for ts in data.get("timestamps", []) if now - float(ts) < 3600.0]
        except Exception:
            history = []

    if not force:
        if history and (now - history[-1]) < cooldown_sec:
            rem = int(cooldown_sec - (now - history[-1]))
            return False, f"cooldown_active ({rem}s remaining)"

        if len(history) >= max_per_hour:
            return False, f"hourly_cap_reached ({len(history)}/{max_per_hour} per hour)"

    if not dry_run:
        history.append(now)
        rate_file.write_text(json.dumps({"timestamps": history}, indent=2), encoding="utf-8")

    return True, "ok"


PRESERVE_PROMPT = {
    "user_requests": "the user's requests and steering in their own words",
    "todos": "the todo list and the exact next pending steps",
    "files_touched": "exact file paths and function/symbol names",
    "git_state": "the git branch and uncommitted changes",
    "commands": "commands executed and what they showed",
    "errors": "failing assertions and errors, verbatim",
    "decisions": "architectural decisions, constraints and choices already made (and why)",
}


def middle_excerpts(transcript_state: dict[str, Any], cfg: dict[str, Any], budget: int) -> list[str]:
    evict = set(cfg["compaction"]["evict_buckets"])
    names: dict[str, str] = transcript_state.get("tool_names") or {}
    conv = transcript_state.get("conversation_records") or []
    preserve_tail = int(cfg["compaction"]["preserve_tail_messages"])
    middle_records = conv[:-preserve_tail] if len(conv) > preserve_tail else conv

    snippets: list[str] = []
    for rec in middle_records[-30:]:
        if rec.get("isApiErrorMessage"):
            continue
        msg = rec.get("message") if isinstance(rec.get("message"), dict) else {}
        role = msg.get("role", "user")
        content = msg.get("content")
        text_chunk = ""
        if isinstance(content, str):
            text_chunk = content[:800]
        elif isinstance(content, list):
            parts = []
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text":
                    parts.append(str(b.get("text", ""))[:600])
                elif b.get("type") == "tool_use":
                    parts.append(f"[tool_use: {b.get('name')}]")
                elif b.get("type") == "tool_result":
                    t_str = tool_result_text(b)
                    tool = names.get(str(b.get("tool_use_id")), "")
                    if "read_results" in evict and tool == "Read" and not b.get("is_error"):
                        parts.append("[tool_result: file contents omitted]")
                        continue
                    if (
                        "passing_test_logs" in evict
                        and not b.get("is_error")
                        and PASSING_RE.search(t_str)
                        and not any(m in t_str for m in ERROR_MARKERS)
                    ):
                        parts.append("[tool_result: passing test log omitted]")
                        continue
                    if len(t_str) > 360:
                        t_str = t_str[:180] + " ... " + t_str[-140:]
                    parts.append(f"[tool_result: {t_str}]")
            text_chunk = " ".join(parts)
        if text_chunk:
            line = f"[{role.upper()}] {text_chunk.strip()}"
            if len(line) <= budget:
                snippets.append(line)
                budget -= len(line)
    return snippets


def distill_with_byok_llm(
    deterministic_digest: str,
    transcript_state: dict[str, Any],
    cfg: dict[str, Any],
    tried: list[str] | None = None,
) -> tuple[str | None, str]:
    # tried, when given, gets one line per model that didn't answer, and why.
    tried = tried if tried is not None else []
    conn = load_magpie_connection(cfg)
    if not conn["base_url"]:
        return None, "missing_gateway_url"

    limits = cfg["limits"]
    max_chars = int(limits["max_byok_input_chars"])
    max_out_tokens = int(limits["max_byok_output_tokens"])
    timeout_sec = float(limits["byok_timeout_sec"])
    comp = cfg["compaction"]
    byok_chain = comp["byok_chain"]

    snippets = middle_excerpts(transcript_state, cfg, max(3000, max_chars - len(deterministic_digest) - 1200))
    keep = [PRESERVE_PROMPT[b] for b in comp["preserve_buckets"] if b in PRESERVE_PROMPT]
    prompt = (
        "You are a surgical context compaction engine for an active software engineering session.\n"
        "Combine the deterministic ground-truth facts below with the middle-turn excerpts into a dense, "
        "high-signal technical continuation summary (<1200 words).\n"
        + (f"Strictly preserve: {'; '.join(keep)}.\n\n" if keep else "\n")
        + "=== DETERMINISTIC GROUND TRUTH ===\n"
        f"{deterministic_digest}\n\n"
        "=== MIDDLE TURN EXCERPTS ===\n"
        + "\n".join(snippets)
    )

    for model_name in byok_chain:
        req_body = {
            "model": model_name,
            "max_tokens": max_out_tokens,
            "thinking": {"type": "disabled"},
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
            tried.append(f"{model_name}: reply of {len(combined)} chars")
        except urllib.error.HTTPError as exc:
            tried.append(f"{model_name}: HTTP {exc.code}")
        except Exception as exc:
            tried.append(f"{model_name}: {type(exc).__name__}")

    return None, "deterministic_fallback"


def record_tokens(rec: dict[str, Any]) -> int:
    return estimate_chars_to_tokens(len(json.dumps(rec.get("message", {}))))


def tail_token_cap(cfg: dict[str, Any]) -> int:
    comp = cfg["compaction"]
    return max(0, int(comp["target_post_compact_tokens"]) - int(comp["summary_tokens"]))


def starts_with_tool_result(rec: dict[str, Any]) -> bool:
    content = (rec.get("message") or {}).get("content")
    return isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)


def select_safe_tail_records(
    conversation_records: list[dict[str, Any]],
    preserve_tail_count: int,
    max_tokens: int | None = None,
) -> list[dict[str, Any]]:
    if not conversation_records:
        return []
    n = len(conversation_records)
    count = min(n, max(2, preserve_tail_count))
    start_idx = n - count

    # Past the token cap, drop records from the front of the tail (always keeping the last two).
    if max_tokens:
        sizes = [record_tokens(r) for r in conversation_records[start_idx:]]
        while start_idx < n - 2 and sum(sizes) > max_tokens:
            sizes.pop(0)
            start_idx += 1

    # Never start the preserved tail on a `tool_result` user message without its preceding `tool_use` assistant message
    if start_idx > 0 and starts_with_tool_result(conversation_records[start_idx]):
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
    state_dir = Path(cfg["general"]["state_dir"]).expanduser()
    backup_dir = state_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    ts_slug = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"{jsonl_path.stem}.{ts_slug}.jsonl.bak"
    shutil.copy2(jsonl_path, backup_path)

    preserve_tail = int(cfg["compaction"]["preserve_tail_messages"])
    conv_records = transcript_state.get("conversation_records") or []
    tail_records = select_safe_tail_records(conv_records, preserve_tail, tail_token_cap(cfg))
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
    digest = build_deterministic_digest(transcript_state, git_ctx, cfg["compaction"]["preserve_buckets"])

    if output_path:
        target = Path(output_path).expanduser().resolve()
    else:
        target = Path(cwd) / cfg["general"]["handoff_relpath"]

    target.parent.mkdir(parents=True, exist_ok=True)
    now_iso = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    doc = "\n".join(
        [
            f"# Session Handoff (`{meta.get('sessionId', 'session')}`)",
            "",
            f"- **Generated At**: {now_iso}",
            f"- **Working Directory**: `{cwd}`",
            f"- **Git Branch**: `{git_ctx.get('branch') or meta.get('gitBranch', 'main')}`",
            f"- **Pre-Handoff Context Size**: `{transcript_state['context_tokens']:,}` tokens "
            f"(`r_tool={transcript_state['r_tool']}`, `r_edit={transcript_state['r_edit']}`)",
            f"- **Seats**: `{quota_state.get('healthy', 0)}/{quota_state.get('counted', 0)}` with room",
            f"- **Recommendation**: `{decision['recommended_action']}` (`J = {decision['recommended_score']}`)",
            "",
            digest,
            "",
            "### Continuation Instructions for Receiving Agent",
            "1. Review the touched files and `git diff --stat` above before reading any large files from scratch.",
            "2. Continue directly from the latest user steering prompt without repeating completed verification steps.",
            "",
        ]
    )
    target.write_text(doc, encoding="utf-8")
    return target


# ── commands ──────────────────────────────────────────────────────────────────


def format_explain_table(t: dict[str, Any], q: dict[str, Any], d: dict[str, Any]) -> str:
    s = d["signals"]
    lines = [
        f"  Session       : {t['jsonl_path']}",
        f"  Context       : {s['context_tokens']:,} tokens (after a compaction ~{s['post_compact_tokens']:,}) | "
        f"stopped {s['stopped_min']} min | cache warm {s['cache_left_min']} min more",
    ]
    stop = t.get("stop")
    if stop:
        lines.append(f"  Stopped on    : {stop['kind']} ({stop.get('provider') or 'seat'}) reset {iso(stop.get('reset_ts')) or '?'}")
    lines.append(f"  Route         : {s['route']} | urgency {s['urgency']} | readings {s['readings']}")
    for seat in q.get("seats") or []:
        u5 = "unread" if seat["used_5h"] is None else f"{seat['used_5h']:5.1f}%"
        lines.append(
            f"  seat {seat['user'][:44]:<44} 5h {u5} / cap {seat['cap_5h']:.0f}  7d {seat['used_7d']:5.1f}% / {seat['cap_7d']:.0f}"
            f"  {'room' if seat['healthy'] else 'full'}"
            + ("" if seat["healthy"] or not seat["usable_at_ts"] else f" until {iso(seat['usable_at_ts'])}")
        )
    for sk in q.get("skipped") or []:
        lines.append(f"  (not counted: {sk['user']} plan={sk['plan']})")
    for name, pool in (q.get("pools") or {}).items():
        lines.append(f"  pool {name:<10} {pool['remaining_pct']:5.1f}% left")
    w = d["weights"]
    lines.append("")
    lines.append(
        f"  Profile [{d['profile']}]  weights: " + ", ".join(f"{DIMENSION_LABELS[k]} {k}={w[k]}" for k in DIMENSIONS)
    )
    lines.append("  Rank  Action    J        timing  session  cost    account  minutes  seat-%  ")
    for i, r in enumerate(d["ranked_actions"], 1):
        dm = r["dims"]
        lines.append(
            f"  {'★' if i == 1 else ' '}#{i}  {r['action']:<8}  {r['score']:.4f}   {dm['timing']:.3f}   {dm['session']:.3f}    "
            f"{dm['cost']:.3f}   {dm['account']:.3f}    {r['minutes']:>6.1f}   {r['spend_pct']:.2f}   ({r['source']})"
        )
    lines.append("")
    lines.append("  " + d["summary_zh"])
    for p in d.get("config_problems") or []:
        lines.append(f"  config: {p}")
    return "\n".join(lines)


def explain_payload(args: argparse.Namespace, cfg: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    jsonl_path = find_session_jsonl(args.session, args.cwd)
    t_state = analyze_transcript(jsonl_path, cfg=cfg)
    q_state = fetch_magpie_quotas(cfg)
    login = signed_in_seat(cfg)
    decision = evaluate_actions(
        t_state, q_state, cfg, profile_name=args.profile, urgency=args.urgency, route=args.route, login=login
    )
    decision["config_problems"] = cfg.get("_problems") or []
    return t_state, q_state, decision


SESSION_STATS = (
    "jsonl_path", "total_records", "active_records_count", "compactions", "context_tokens", "cache_age_sec",
    "cache_ttl_remaining_min", "stopped_min", "quiet_sec", "r_tool", "r_edit",
)


def cmd_explain(args: argparse.Namespace, cfg: dict[str, Any]) -> int:
    t_state, q_state, decision = explain_payload(args, cfg)
    if args.json:
        stop = dict(t_state["stop"]) if t_state.get("stop") else None
        if stop:
            stop["at"], stop["reset_at"] = iso(stop.pop("at_ts")), iso(stop.pop("reset_ts"))
        out: dict[str, Any] = {
            "session": {**{k: t_state[k] for k in SESSION_STATS}, "last_record_at": iso(t_state["last_record_ts"]), "stop": stop},
            "quotas": q_state,
            "decision": decision,
        }
        if args.after:
            since = parse_iso_ts(args.after)
            if since is None:
                raise SystemExit(f"cc-compactor: --after wants an ISO time, got {args.after!r}")
            out["after"] = activity_after(Path(t_state["jsonl_path"]), since)
        if args.full:
            out["transcript"] = {k: v for k, v in t_state.items() if k not in ("conversation_records", "tool_names")}
        print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    else:
        print(format_explain_table(t_state, q_state, decision))
    return 0


def cmd_compact(args: argparse.Namespace, cfg: dict[str, Any]) -> int:
    t0 = time.time()
    problems = [p for p in cfg.get("_problems") or [] if p.startswith("compaction.")]
    if problems:
        print(json.dumps({"status": "config_error", "problems": problems}, indent=2, ensure_ascii=False))
        return 2
    jsonl_path = find_session_jsonl(args.session, args.cwd)
    t_state = analyze_transcript(jsonl_path, cfg=cfg)

    if not args.dry_run and not args.allow_live and session_is_live(jsonl_path, cfg):
        print(json.dumps({"status": "skipped", "reason": "session_live", "session_path": str(jsonl_path)}, indent=2))
        return 0

    allowed, reason = check_and_record_rate_limit(cfg, dry_run=args.dry_run, force=args.force)
    if not allowed:
        print(json.dumps({"status": "skipped", "reason": reason}, indent=2))
        return 0

    meta = t_state.get("meta") or {}
    git_ctx = collect_git_context(meta.get("cwd", str(Path.cwd())))
    deterministic_digest = build_deterministic_digest(t_state, git_ctx, cfg["compaction"]["preserve_buckets"])

    tried: list[str] = []
    if args.deterministic_only:
        summary_md = deterministic_digest
        source = "deterministic_ast_git"
    else:
        byok_md, source = distill_with_byok_llm(deterministic_digest, t_state, cfg, tried)
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
                    "failed_models": tried,
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
    result["failed_models"] = tried
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def cmd_handoff(args: argparse.Namespace, cfg: dict[str, Any]) -> int:
    t_state, q_state, decision = explain_payload(args, cfg)
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


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cc-compactor",
        description="Wait, compact or hand off a Claude Code session stopped on a usage limit (scored on timing, session, cost and account)",
    )
    parser.add_argument("--config", help="Path to cc-compactor.toml configuration file")
    parser.add_argument("--profile", help="Weight profile from [profiles.*] (default: general.default_profile)")
    parser.add_argument("--urgency", help="Key of timing.tolerable_wait_min (default: general.default_urgency)")
    parser.add_argument(
        "--route",
        choices=["auto", "gateway", "seat"],
        default="auto",
        help="How the session reaches Claude: the gateway's seats, or this machine's own sign-in (auto: from the stop message)",
    )
    parser.add_argument("--session", help="Session JSONL file path or UUID substring")
    parser.add_argument("--cwd", help="Project working directory to resolve latest session")

    sub = parser.add_subparsers(dest="subcommand", required=True)

    p_exp = sub.add_parser("explain", help="Score wait / compact / handoff and print the recommendation")
    p_exp.add_argument("--json", action="store_true", help="Machine-readable: numbers and decision, no transcript text")
    p_exp.add_argument("--full", action="store_true", help="With --json: include the transcript digest fields")
    p_exp.add_argument("--after", help="With --json: what the session did after this ISO time (first answered turn, cache)")

    p_cmp = sub.add_parser("compact", help="Splice a summary into a stopped session's transcript as a compact_boundary")
    p_cmp.add_argument("--dry-run", action="store_true", help="Preview summary without writing to JSONL")
    p_cmp.add_argument(
        "--deterministic-only",
        action="store_true",
        help="Use deterministic AST/git/log extraction only without calling BYOK LLM",
    )
    p_cmp.add_argument("--force", action="store_true", help="Bypass cooldown and hourly cap (still counted)")
    p_cmp.add_argument(
        "--allow-live",
        action="store_true",
        help="Splice a transcript written to within live_guard_sec (only for a session you will --resume)",
    )

    p_ho = sub.add_parser("handoff", help="Write a handoff document (.claude/handoff/current.md)")
    p_ho.add_argument("--output", help="Custom output path for HANDOFF.md")

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
    return 1


if __name__ == "__main__":
    sys.exit(main())
