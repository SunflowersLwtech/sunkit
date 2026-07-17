#!/usr/bin/env python3
"""Probe source_registry.json endpoints without extra dependencies."""

from __future__ import annotations

import argparse
import json
import sys
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.env_utils import env_value, first_env

ENV_FILE = ROOT / ".env"
SECRET_QUERY_KEYS = {"api_key", "key", "token", "access_token"}

DEFAULT_HEADERS = {
    "User-Agent": "oss-radar-source-probe/0.1 (+https://local)",
    "Accept": "application/json, application/atom+xml, application/rss+xml, text/html;q=0.8, */*;q=0.5",
}


def probe(url: str, timeout: float) -> dict[str, Any]:
    started = time.time()
    request = urllib.request.Request(url, headers=DEFAULT_HEADERS, method="GET")

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(512)
            elapsed_ms = round((time.time() - started) * 1000)
            return {
                "ok": 200 <= response.status < 400,
                "status": response.status,
                "elapsed_ms": elapsed_ms,
                "content_type": response.headers.get("content-type"),
                "content_length": response.headers.get("content-length"),
                "sample_bytes": len(body),
            }
    except urllib.error.HTTPError as exc:
        elapsed_ms = round((time.time() - started) * 1000)
        return {
            "ok": False,
            "status": exc.code,
            "elapsed_ms": elapsed_ms,
            "error": str(exc),
        }
    except (urllib.error.URLError, TimeoutError, socket.timeout, ssl.SSLError) as exc:
        elapsed_ms = round((time.time() - started) * 1000)
        return {
            "ok": False,
            "status": None,
            "elapsed_ms": elapsed_ms,
            "error": str(exc),
        }


def probe_exa(url: str, timeout: float) -> dict[str, Any]:
    api_key = env_value("EXA_API_KEY", ENV_FILE)
    payload = json.dumps({"query": "AI agent developer tool", "numResults": 1, "type": "auto"}).encode("utf-8")
    started = time.time()
    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            **DEFAULT_HEADERS,
            "Content-Type": "application/json",
            "x-api-key": api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(512)
            elapsed_ms = round((time.time() - started) * 1000)
            return {
                "ok": 200 <= response.status < 400,
                "status": response.status,
                "elapsed_ms": elapsed_ms,
                "content_type": response.headers.get("content-type"),
                "content_length": response.headers.get("content-length"),
                "sample_bytes": len(body),
            }
    except urllib.error.HTTPError as exc:
        elapsed_ms = round((time.time() - started) * 1000)
        return {"ok": False, "status": exc.code, "elapsed_ms": elapsed_ms, "error": str(exc)}
    except (urllib.error.URLError, TimeoutError, socket.timeout, ssl.SSLError) as exc:
        elapsed_ms = round((time.time() - started) * 1000)
        return {"ok": False, "status": None, "elapsed_ms": elapsed_ms, "error": str(exc)}


def with_query_params(base_url: str, params: dict[str, Any]) -> str:
    parsed = urllib.parse.urlparse(base_url)
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    for key, value in params.items():
        if value is not None and value != "":
            query[key] = str(value)
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))


def redact_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    pairs = []
    for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        pairs.append((key, "REDACTED" if key.lower() in SECRET_QUERY_KEYS else value))
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(pairs)))


def missing_required_env(source: dict[str, Any]) -> list[str]:
    required_any = [str(item) for item in source.get("requires_env_any") or []]
    if required_any and not first_env(required_any, ENV_FILE):
        return required_any
    return []


def probe_url_for(source: dict[str, Any]) -> str:
    source_id = source["id"]
    url = source.get("probe_url") or source["primary_endpoint"]
    if source_id == "libraries_io_search":
        return with_query_params(url, {"api_key": env_value("LIBRARIES_IO_API_KEY", ENV_FILE)})
    return url


def parse_statuses(raw: str) -> set[int]:
    statuses: set[int] = set()
    for item in raw.split(","):
        stripped = item.strip()
        if not stripped:
            continue
        statuses.add(int(stripped))
    return statuses


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe OSS Radar source endpoints.")
    parser.add_argument(
        "--registry",
        default=str(Path(__file__).resolve().parents[1] / "source_registry.json"),
        help="Path to source_registry.json.",
    )
    parser.add_argument("--timeout", type=float, default=12.0, help="Per-source timeout in seconds.")
    parser.add_argument("--min-ok-sources", type=int, default=0, help="Allow transient failures when at least this many sources pass.")
    parser.add_argument("--min-ok-p0", type=int, default=0, help="Allow transient failures when at least this many P0 sources pass.")
    parser.add_argument(
        "--allow-transient-statuses",
        default="",
        help="Comma-separated HTTP statuses allowed as transient failures with min-ok gates.",
    )
    parser.add_argument(
        "--allow-transient-timeouts",
        action="store_true",
        help="Allow read timeouts as transient failures with min-ok gates.",
    )
    args = parser.parse_args()

    registry_path = Path(args.registry)
    registry = json.loads(registry_path.read_text())

    results = []
    for source in registry["sources"]:
        missing_env = missing_required_env(source)
        if missing_env:
            results.append(
                {
                    "source": source["id"],
                    "priority": source["priority"],
                    "url": source.get("probe_url") or source["primary_endpoint"],
                    "ok": True,
                    "skipped": True,
                    "missing_required_env": missing_env,
                }
            )
            continue
        url = probe_url_for(source)
        source_timeout = float(source.get("timeout_seconds") or args.timeout)
        if source["id"] == "exa_web_search":
            result = probe_exa(url, min(args.timeout, source_timeout))
        else:
            result = probe(url, min(args.timeout, source_timeout))
        results.append(
            {
                "source": source["id"],
                "priority": source["priority"],
                "url": redact_url(url),
                **result,
            }
        )

    ok_count = sum(1 for item in results if item["ok"] and not item.get("skipped"))
    p0_ok_count = sum(1 for item in results if item["ok"] and item["priority"] == "P0" and not item.get("skipped"))
    failures = [item for item in results if not item["ok"] and not item.get("skipped")]
    transient_statuses = parse_statuses(args.allow_transient_statuses)
    hard_failures = []
    for item in failures:
        status = item.get("status")
        error = str(item.get("error") or "").lower()
        is_transient_status = isinstance(status, int) and status in transient_statuses
        is_transient_timeout = args.allow_transient_timeouts and status is None and "timed out" in error
        if not is_transient_status and not is_transient_timeout:
            hard_failures.append(item)
    policy = {
        "ok_count": ok_count,
        "p0_ok_count": p0_ok_count,
        "min_ok_sources": args.min_ok_sources,
        "min_ok_p0": args.min_ok_p0,
        "transient_statuses": sorted(transient_statuses),
        "allow_transient_timeouts": args.allow_transient_timeouts,
        "hard_failure_count": len(hard_failures),
    }

    print(json.dumps({"registry": str(registry_path), "policy": policy, "results": results}, ensure_ascii=False, indent=2))
    if not failures:
        return 0
    if args.min_ok_sources or args.min_ok_p0:
        enough_sources = ok_count >= args.min_ok_sources and p0_ok_count >= args.min_ok_p0
        return 0 if enough_sources and not hard_failures else 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
