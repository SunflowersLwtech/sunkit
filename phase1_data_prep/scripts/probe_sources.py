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


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe OSS Radar source endpoints.")
    parser.add_argument(
        "--registry",
        default=str(Path(__file__).resolve().parents[1] / "source_registry.json"),
        help="Path to source_registry.json.",
    )
    parser.add_argument("--timeout", type=float, default=12.0, help="Per-source timeout in seconds.")
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

    print(json.dumps({"registry": str(registry_path), "results": results}, ensure_ascii=False, indent=2))
    return 0 if all(item["ok"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
