#!/usr/bin/env python3
"""Create a redacted local trace export and redaction report."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from scan_secrets import PATTERNS, scan


REPLACEMENTS = [
    (PATTERNS["openai_like_sk"], "[REDACTED_SK_TOKEN]"),
    (PATTERNS["google_api_key"], "[REDACTED_GOOGLE_API_KEY]"),
    (PATTERNS["bearer_token"], "Bearer [REDACTED_BEARER_TOKEN]"),
    (PATTERNS["cookie_token"], "[REDACTED_COOKIE_OR_SESSION_TOKEN]"),
]


TEXT_EXTS = {
    ".json",
    ".jsonl",
    ".md",
    ".txt",
    ".log",
    ".py",
    ".sh",
    ".ts",
    ".tsx",
    ".js",
    ".yaml",
    ".yml",
    ".toml",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def redact_text(text: str) -> tuple[str, int]:
    count = 0
    for pattern, replacement in REPLACEMENTS:
        text, n = pattern.subn(replacement, text)
        count += n
    return text, count


def copy_redacted(src: Path, dst: Path) -> int:
    replacements = 0
    for item in src.rglob("*"):
        target = dst / item.relative_to(src)
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if item.suffix.lower() in TEXT_EXTS:
            text = item.read_text(encoding="utf-8", errors="ignore")
            redacted, count = redact_text(text)
            replacements += count
            target.write_text(redacted, encoding="utf-8")
        else:
            shutil.copy2(item, target)
    return replacements


def make_archive(src: Path, output: Path) -> None:
    with tarfile.open(output, "w:gz") as archive:
        archive.add(src, arcname=src.name)


def requires_final_video(source: Path) -> bool:
    return (source / "run_final.json").exists() or (source / "artifact_manifest.json").exists()


def assert_final_video_included(source: Path) -> None:
    if not requires_final_video(source):
        return
    final_video = source / "video" / "final.mp4"
    if not final_video.is_file():
        raise SystemExit("video omitted => cannot claim production success")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_dir")
    parser.add_argument("output", help="Output directory or .tar.gz archive")
    args = parser.parse_args()

    source = Path(args.input_dir).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    if not source.is_dir():
        raise SystemExit(f"input_dir must be a directory: {source}")
    assert_final_video_included(source)

    with tempfile.TemporaryDirectory(prefix="searchpo-redacted-") as tmp:
        redacted_root = Path(tmp) / f"{source.name}-redacted"
        replacement_count = copy_redacted(source, redacted_root)
        report_path = redacted_root / "security" / "redaction_report.json"
        scan_report = scan(redacted_root)
        report = {
            "schema_version": 1,
            "created_at": utc_now(),
            "source": str(source),
            "redacted": True,
            "final_video_included": bool((source / "video" / "final.mp4").is_file()),
            "replacement_count": replacement_count,
            "scan_status": scan_report["status"],
            "scan_finding_count": scan_report["finding_count"],
            "scanner": scan_report,
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if output.suffixes[-2:] == [".tar", ".gz"]:
            output.parent.mkdir(parents=True, exist_ok=True)
            make_archive(redacted_root, output)
        else:
            if output.exists():
                shutil.rmtree(output)
            shutil.copytree(redacted_root, output)
    print(json.dumps({"redacted_export": str(output), "redacted": True}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
