#!/usr/bin/env python3
"""Validate governed image assets before presenting a repo-to-X pack as ready."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(repo_run_dir: Path) -> dict[str, Any]:
    manifest_path = repo_run_dir / "images_manifest.json"
    if not manifest_path.exists():
        raise SystemExit(f"missing images_manifest.json: {manifest_path}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo_run_dir", help="Repo directory under repo-to-x-workspace/runs/<run-id>/repos/<repo-id>")
    parser.add_argument("--min-actual", type=int, default=1, help="Minimum actual image files required")
    parser.add_argument(
        "--allow-prompt-only",
        action="store_true",
        help="Allow prompt-only entries only for explicit prompt-only/text-only/manual-image user requests",
    )
    args = parser.parse_args()

    repo_run_dir = Path(args.repo_run_dir).expanduser().resolve()
    manifest = load_manifest(repo_run_dir)
    images = manifest.get("images") or []

    errors: list[str] = []
    warnings: list[str] = []
    actual_count = 0

    if not images:
        errors.append("images_manifest.json has no image entries")

    for image in images:
        image_id = image.get("id") or "<missing-id>"
        status = image.get("status") or ""
        path_value = image.get("path") or ""
        required = image.get("required", True)
        prompt_only = status == "prompt_only" or image.get("source_type") == "prompt_only"

        if prompt_only and not args.allow_prompt_only:
            if required:
                errors.append(f"{image_id}: prompt_only is not allowed for default ready-to-post packs")
            else:
                warnings.append(f"{image_id}: optional prompt_only image was not used")
            continue
        if prompt_only and args.allow_prompt_only:
            reason = str(image.get("prompt_only_reason") or "")
            if reason not in {"user_requested_prompt_only", "user_requested_text_only", "user_requested_manual_images"}:
                errors.append(
                    f"{image_id}: prompt_only requires explicit user-request reason; got {reason or '<missing>'}"
                )
                continue

        if status == "planned":
            if required:
                errors.append(f"{image_id}: still planned; generate or remove it before ready-to-post")
            else:
                warnings.append(f"{image_id}: optional image remains planned")
            continue

        if not path_value:
            if required and not args.allow_prompt_only:
                errors.append(f"{image_id}: missing governed image file path")
            continue

        image_path = (repo_run_dir / path_value).resolve()
        try:
            image_path.relative_to(repo_run_dir)
        except ValueError:
            errors.append(f"{image_id}: image path escapes repo run dir: {image_path}")
            continue

        if not image_path.exists() or not image_path.is_file():
            errors.append(f"{image_id}: image file does not exist: {image_path}")
            continue

        actual_count += 1
        expected_sha = image.get("sha256") or ""
        if not expected_sha:
            errors.append(f"{image_id}: missing sha256")
        else:
            actual_sha = sha256_file(image_path)
            if actual_sha != expected_sha:
                errors.append(f"{image_id}: sha256 mismatch")

        if not image.get("mime_type"):
            errors.append(f"{image_id}: missing mime_type")
        if not image.get("alt_text"):
            errors.append(f"{image_id}: missing alt_text")
        if not image.get("disclosure"):
            errors.append(f"{image_id}: missing disclosure")
        if image.get("review_status") != "approved":
            warnings.append(f"{image_id}: review_status is {image.get('review_status') or '<missing>'}, not approved")

    if actual_count < args.min_actual and not args.allow_prompt_only:
        errors.append(f"only {actual_count} actual image file(s); expected at least {args.min_actual}")

    if warnings:
        print("Image asset warnings:", file=sys.stderr)
        for warning in warnings:
            print(f"- {warning}", file=sys.stderr)

    if errors:
        print("Image asset gate failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"Image asset gate passed: {actual_count} actual image file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
