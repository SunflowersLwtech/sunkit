#!/usr/bin/env python3
"""Probe source_registry.json endpoints without extra dependencies."""

from __future__ import annotations

import argparse
import json
import socket
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


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
        url = source.get("probe_url") or source["primary_endpoint"]
        result = probe(url, args.timeout)
        results.append(
            {
                "source": source["id"],
                "priority": source["priority"],
                "url": url,
                **result,
            }
        )

    ok_count = sum(1 for item in results if item["ok"])
    p0_ok_count = sum(1 for item in results if item["ok"] and item["priority"] == "P0")
    failures = [item for item in results if not item["ok"]]
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
