#!/usr/bin/env python3
"""Scan files or archives for high-confidence secret-shaped strings."""

from __future__ import annotations

import argparse
import json
import re
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


PATTERNS = {
    "openai_like_sk": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    "bearer_token": re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{20,}"),
    "cookie_token": re.compile(
        r"\b(?:cookie|session|sid|csrf|oauth)(?:[_-]?(?:token|secret|id))?\s*[:=]\s*[A-Za-z0-9._~+/=-]{20,}",
        re.I,
    ),
}

SKIP_DIRS = {".git", "node_modules", "runtime", "out", "public/generated", "__pycache__"}


def should_skip_path(path: Path) -> bool:
    if any(part in SKIP_DIRS for part in path.parts):
        return True
    name = path.name
    return name.startswith(".env") and name != ".env.example"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def iter_files(path: Path) -> Iterable[tuple[str, bytes]]:
    if path.is_dir():
        for item in path.rglob("*"):
            if should_skip_path(item):
                continue
            if item.is_file():
                yield str(item), item.read_bytes()
    elif tarfile.is_tarfile(path):
        with tarfile.open(path, "r:*") as archive:
            for member in archive.getmembers():
                if member.isfile():
                    handle = archive.extractfile(member)
                    if handle:
                        yield member.name, handle.read()
    else:
        yield str(path), path.read_bytes()


def scan(path: Path) -> dict[str, object]:
    findings = []
    for name, payload in iter_files(path):
        text = payload.decode("utf-8", "ignore")
        for pattern_name, pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                findings.append(
                    {
                        "file": name,
                        "line": line,
                        "pattern": pattern_name,
                        "match_preview": match.group(0)[:8] + "...",
                    }
                )
    return {
        "schema_version": 1,
        "created_at": utc_now(),
        "path": str(path),
        "status": "pass" if not findings else "fail",
        "finding_count": len(findings),
        "findings": findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path")
    parser.add_argument("--output")
    parser.add_argument("--allow-findings", action="store_true")
    args = parser.parse_args()

    report = scan(Path(args.path).expanduser().resolve())
    if args.output:
        output = Path(args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if args.allow_findings or report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
