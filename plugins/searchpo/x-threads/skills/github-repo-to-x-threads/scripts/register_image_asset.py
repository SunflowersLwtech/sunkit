#!/usr/bin/env python3
"""Register a generated or sourced image in a repo-to-X run workspace."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def safe_id(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in value.strip())
    return cleaned.strip("-._") or "image"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_text_or_value(value: str, file_path: str | None) -> str:
    if file_path:
        return Path(file_path).expanduser().read_text(encoding="utf-8").strip()
    return value


def load_manifest(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    now = utc_now()
    return {
        "schema_version": 1,
        "created_at": now,
        "updated_at": now,
        "image_policy": {
            "default_model": "gpt-image-2",
            "default_source_type": "gpt_image_2_generated",
            "allowed_statuses": ["planned", "prompt_only", "generated", "approved", "rejected"],
            "allowed_source_types": [
                "gpt_image_2_generated",
                "official_repo_asset",
                "user_asset",
                "prompt_only",
            ],
        },
        "images": [],
        "rules": [
            "Generated visuals must be labeled as conceptual.",
            "Do not create fake screenshots, fake GitHub metrics, or fake benchmark charts.",
            "Use official repo assets only when actually present and attributed.",
            "Do not reference an image in posting_pack.md unless it exists in images_manifest.json.",
            "Actual image files must be copied into images/ and include sha256.",
            "Prompt-only entries are allowed only for explicit user-requested prompt-only/text-only/manual-image mode.",
            "Prompt-only entries are never a fallback for failed actual image generation.",
        ],
    }


def write_manifest(path: Path, data: dict) -> None:
    data["updated_at"] = utc_now()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_entry(args: argparse.Namespace, copied_path: Path | None, repo_run_dir: Path) -> dict:
    now = utc_now()
    prompt = read_text_or_value(args.prompt, args.prompt_file)
    relative_path = ""
    checksum = ""
    mime_type = ""
    if copied_path:
        relative_path = str(copied_path.relative_to(repo_run_dir))
        checksum = sha256_file(copied_path)
        mime_type = mimetypes.guess_type(copied_path.name)[0] or "application/octet-stream"

    status = "prompt_only" if args.prompt_only else args.status
    source_type = "prompt_only" if args.prompt_only else args.source_type
    return {
        "id": args.id,
        "post": args.post,
        "purpose": args.purpose,
        "status": status,
        "source_type": source_type,
        "model": args.model,
        "path": relative_path,
        "sha256": checksum,
        "mime_type": mime_type,
        "prompt": prompt,
        "prompt_path": args.prompt_file or "",
        "prompt_only_reason": args.prompt_only_reason if args.prompt_only else "",
        "alt_text": args.alt_text,
        "disclosure": args.disclosure,
        "review_status": args.review_status,
        "review_notes": args.review_notes,
        "created_at": now,
        "updated_at": now,
    }


def copy_asset(args: argparse.Namespace, repo_run_dir: Path) -> Path | None:
    if args.prompt_only:
        if args.prompt_only_reason not in {
            "user_requested_prompt_only",
            "user_requested_text_only",
            "user_requested_manual_images",
        }:
            raise SystemExit(
                "--prompt-only requires --prompt-only-reason "
                "user_requested_prompt_only|user_requested_text_only|user_requested_manual_images"
            )
        return None
    if not args.asset_path:
        raise SystemExit("asset_path is required unless --prompt-only is set")
    source = Path(args.asset_path).expanduser().resolve()
    if not source.exists() or not source.is_file():
        raise SystemExit(f"image asset does not exist: {source}")

    images_dir = repo_run_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    suffix = source.suffix.lower() or ".bin"
    target = images_dir / f"{safe_id(args.id)}{suffix}"
    if target.exists() and not args.replace:
        raise SystemExit(f"target already exists, use --replace: {target}")
    shutil.copy2(source, target)
    return target


def upsert_image(manifest: dict, entry: dict, replace: bool) -> None:
    images = manifest.setdefault("images", [])
    for index, existing in enumerate(images):
        if existing.get("id") == entry["id"]:
            if not replace:
                raise SystemExit(f"image id already exists, use --replace: {entry['id']}")
            entry["created_at"] = existing.get("created_at") or entry["created_at"]
            images[index] = entry
            return
    images.append(entry)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo_run_dir", help="Repo directory under repo-to-x-workspace/runs/<run-id>/repos/<repo-id>")
    parser.add_argument("asset_path", nargs="?", help="Generated or sourced image file to copy into images/")
    parser.add_argument("--id", default="image-1", help="Stable image id used by posting_pack.md")
    parser.add_argument("--post", default="1/N", help="Thread post where the image is used")
    parser.add_argument("--purpose", default="hook visual", help="Image purpose in the posting pack")
    parser.add_argument("--status", default="generated", choices=["generated", "approved", "rejected"])
    parser.add_argument(
        "--source-type",
        default="gpt_image_2_generated",
        choices=["gpt_image_2_generated", "official_repo_asset", "user_asset"],
    )
    parser.add_argument("--model", default="gpt-image-2")
    parser.add_argument("--prompt", default="")
    parser.add_argument("--prompt-file")
    parser.add_argument("--alt-text", default="")
    parser.add_argument(
        "--disclosure",
        default="Generated conceptual visual, not an official project screenshot.",
    )
    parser.add_argument("--review-status", default="needs_review", choices=["needs_review", "approved", "rejected"])
    parser.add_argument("--review-notes", default="")
    parser.add_argument(
        "--prompt-only",
        action="store_true",
        help="Register a prompt without an image file only when the user explicitly requested prompt-only/text-only/manual-image output",
    )
    parser.add_argument(
        "--prompt-only-reason",
        choices=["user_requested_prompt_only", "user_requested_text_only", "user_requested_manual_images"],
        default="",
        help="Required with --prompt-only; prompt-only is never a fallback for failed image generation",
    )
    parser.add_argument("--replace", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()

    repo_run_dir = Path(args.repo_run_dir).expanduser().resolve()
    if not repo_run_dir.exists() or not repo_run_dir.is_dir():
        raise SystemExit(f"repo_run_dir does not exist: {repo_run_dir}")

    copied_path = copy_asset(args, repo_run_dir)
    entry = build_entry(args, copied_path, repo_run_dir)
    manifest_path = repo_run_dir / "images_manifest.json"
    manifest = load_manifest(manifest_path)
    upsert_image(manifest, entry, args.replace)
    write_manifest(manifest_path, manifest)

    print(f"Registered image: {entry['id']}")
    print(f"Manifest: {manifest_path}")
    if entry["path"]:
        print(f"Path: {repo_run_dir / entry['path']}")
        print(f"SHA256: {entry['sha256']}")
    else:
        print("Path: prompt-only")
    return 0


if __name__ == "__main__":
    sys.exit(main())
