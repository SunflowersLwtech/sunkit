#!/usr/bin/env python3
"""Create a governed multi-repo workspace for Agent-engineering X content."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from collect_repo_context import (  # noqa: E402
    collect_git,
    collect_github,
    detect_key_files,
    ensure_repo,
    load_dotenv,
    safe_slug,
    write_manifest,
)
from brand_profile import BRAND_PROFILE  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def read_sources(positional: list[str], source_file: str | None) -> list[str]:
    sources: list[str] = []
    sources.extend(positional)
    if source_file:
        path = Path(source_file).expanduser()
        for line in path.read_text(encoding="utf-8").splitlines():
            value = line.strip()
            if value and not value.startswith("#"):
                sources.append(value)
    deduped: list[str] = []
    seen: set[str] = set()
    for source in sources:
        if source not in seen:
            deduped.append(source)
            seen.add(source)
    return deduped


def repo_id(source: str, owner_repo: str | None, repo_path: Path) -> str:
    if owner_repo:
        return safe_slug(owner_repo.replace("/", "__"))
    digest = hashlib.sha1(str(repo_path).encode("utf-8")).hexdigest()[:8]
    return safe_slug(f"local__{repo_path.name}__{digest}")


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def clean_macos_junk(root: Path) -> None:
    """Remove macOS sidecar/cache files from generated workspaces."""
    if not root.exists():
        return
    for pattern in (".DS_Store", "._*"):
        for path in root.rglob(pattern):
            if path.is_file():
                path.unlink(missing_ok=True)
    for path in root.rglob("__pycache__"):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
    for command in (["xattr", "-rc", str(root)], ["dot_clean", "-m", str(root)]):
        try:
            subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        except FileNotFoundError:
            continue
    for path in root.rglob("._*"):
        if path.is_file():
            path.unlink(missing_ok=True)


def template_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def make_claims_ledger(source: str, owner_repo: str | None, context: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source": source,
        "owner_repo": owner_repo,
        "created_at": utc_now(),
        "review_status": "draft",
        "claim_types": [
            "verified_repo_fact",
            "github_metadata",
            "reasonable_inference",
            "user_vision",
            "unknown_or_unsafe",
        ],
        "claim_statuses": ["keep", "revise", "remove", "needs_source"],
        "claims": [
            {
                "id": "C001",
                "claim": "",
                "type": "verified_repo_fact",
                "source": "",
                "status": "needs_source",
                "public_wording": "",
                "notes": "Add one row per public claim before publishing.",
            }
        ],
        "source_handles": {
            "repo_context": "repo_context.json",
            "file_manifest": "file_manifest.txt",
            "key_files": context.get("key_files", {}),
            "github_metadata_available": bool(context.get("github")) and not context.get("github", {}).get("error"),
        },
        "rules": [
            "Do not publish a factual claim unless it maps to a source.",
            "Label personal vision as personal vision.",
            "Downgrade unsupported superlatives.",
            "Do not imply official roadmap or affiliation unless verified.",
            "Map the post to the Agent engineering brand before publishing.",
            "Include one reusable asset and one concrete discussion question.",
        ],
    }


def make_images_manifest(owner_repo: str | None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "owner_repo": owner_repo,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "image_policy": {
            "default_model": "gpt-image-2",
            "default_source_type": "gpt_image_2_generated",
            "default_requirement": "actual generated images are required for ready-to-post packs unless the user explicitly opts out",
            "default_image_count": "adaptive 1-3",
            "prompt_only_allowed_when": [
                "the user explicitly requests text-only, no images, prompts-only, or manual images",
            ],
            "allowed_statuses": ["planned", "prompt_only", "generated", "approved", "rejected"],
            "allowed_source_types": [
                "gpt_image_2_generated",
                "official_repo_asset",
                "user_asset",
                "prompt_only",
            ],
            "storage": "Store generated files under images/ and register them with scripts/register_image_asset.py.",
            "review_gate": "Before Ready To Post, run scripts/check_image_assets.py. Prompt-only is only for explicit user-requested prompt/text/manual-image mode.",
        },
        "images": [
            {
                "id": "image-1",
                "required": True,
                "post": "1/N",
                "purpose": "hook visual",
                "status": "planned",
                "source_type": "gpt_image_2_generated",
                "model": "gpt-image-2",
                "path": "",
                "sha256": "",
                "mime_type": "",
                "prompt": "",
                "prompt_path": "",
                "alt_text": "",
                "disclosure": "Generated conceptual visual, not an official project screenshot.",
                "review_status": "needs_review",
                "review_notes": "",
                "created_at": utc_now(),
                "updated_at": utc_now(),
            },
            {
                "id": "image-2",
                "required": False,
                "post": "adaptive middle post",
                "purpose": "architecture or workflow visual",
                "status": "planned",
                "source_type": "gpt_image_2_generated",
                "model": "gpt-image-2",
                "path": "",
                "sha256": "",
                "mime_type": "",
                "prompt": "",
                "prompt_path": "",
                "alt_text": "",
                "disclosure": "Generated conceptual visual, not an official project screenshot.",
                "review_status": "needs_review",
                "review_notes": "Use this only if the repo needs a second visual.",
                "created_at": utc_now(),
                "updated_at": utc_now(),
            },
            {
                "id": "image-3",
                "required": False,
                "post": "adaptive later post",
                "purpose": "vision, caveat, or deployment-path visual",
                "status": "planned",
                "source_type": "gpt_image_2_generated",
                "model": "gpt-image-2",
                "path": "",
                "sha256": "",
                "mime_type": "",
                "prompt": "",
                "prompt_path": "",
                "alt_text": "",
                "disclosure": "Generated conceptual visual, not an official project screenshot.",
                "review_status": "needs_review",
                "review_notes": "Use this only if the user's angle or repo complexity justifies it.",
                "created_at": utc_now(),
                "updated_at": utc_now(),
            }
        ],
        "rules": [
            "Generate 1-3 actual images by default for final posting packs.",
            "Do not downgrade to prompt-only when actual image generation fails; block the image gate instead.",
            "Generated visuals must be labeled as conceptual.",
            "Do not create fake screenshots, fake GitHub metrics, or fake benchmark charts.",
            "Use official repo assets only when actually present and attributed.",
            "Do not reference an image in posting_pack.md unless it exists in images_manifest.json.",
            "Actual image files must be copied into images/ and include sha256.",
        ],
    }


def collect_one(source: str, repo_root: Path, refresh: bool) -> dict[str, Any]:
    repo_root.mkdir(parents=True, exist_ok=True)
    repo_path, owner_repo, source_kind = ensure_repo(source, repo_root, refresh)
    files = write_manifest(repo_path, repo_root)
    context = {
        "source": source,
        "source_kind": source_kind,
        "repo_path": str(repo_path),
        "owner_repo": owner_repo,
        "git": collect_git(repo_path),
        "github": collect_github(owner_repo),
        "key_files": detect_key_files(files),
        "file_count": len(files),
        "notes": [
            "Use this context as evidence input, not as the final public copy.",
            "Fill claims_ledger.json before publishing.",
            "Run cross_check_review.md before publishing.",
        ],
    }
    write_json(repo_root / "repo_context.json", context)
    write_json(repo_root / "claims_ledger.json", make_claims_ledger(source, owner_repo, context))
    write_json(repo_root / "images_manifest.json", make_images_manifest(owner_repo))
    (repo_root / "cross_check_review.md").write_text(
        template_text(SKILL_ROOT / "references" / "cross-check-review-template.md"),
        encoding="utf-8",
    )
    (repo_root / "posting_pack.md").write_text(
        template_text(SKILL_ROOT / "references" / "posting-pack-template.md"),
        encoding="utf-8",
    )
    (repo_root / "images").mkdir(exist_ok=True)
    return context


def write_summary(run_dir: Path, manifest: dict[str, Any]) -> None:
    lines = [
        f"# Repo To X Run {manifest['run_id']}",
        "",
        f"- Created at: {manifest['created_at']}",
        f"- Run directory: `{run_dir}`",
        f"- Repo count: {len(manifest['repos'])}",
        "",
        "## Repos",
        "",
    ]
    for repo in manifest["repos"]:
        lines.extend(
            [
                f"### {repo['repo_id']}",
                "",
                f"- Source: `{repo['source']}`",
                f"- Owner/repo: `{repo.get('owner_repo') or 'unresolved local repo'}`",
                f"- Directory: `{repo['directory']}`",
                f"- Context: `{repo['context_path']}`",
                f"- Claims ledger: `{repo['claims_ledger_path']}`",
                f"- Cross-check review: `{repo['cross_check_review_path']}`",
                f"- Posting pack: `{repo['posting_pack_path']}`",
                f"- Images manifest: `{repo['images_manifest_path']}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Publish Gate",
            "",
            "Do not publish until each target repo has:",
            "",
            "- `claims_ledger.json` filled for public claims.",
            "- `cross_check_review.md` marked `pass`.",
            "- `posting_pack.md` updated with final copy and image map.",
            "- Agent engineering Brand Fit, reusable asset, and discussion question filled.",
            "- `scripts/check_image_assets.py <repo-dir>` passes, unless the user explicitly opted out of actual images.",
            "",
            "This run directory is local workspace output and should stay out of git.",
            "",
        ]
    )
    (run_dir / "SUMMARY.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", nargs="*", help="GitHub URLs, owner/repo strings, or local repo paths")
    parser.add_argument("--source-file", help="Text file containing one source per line")
    parser.add_argument("--out-root", default=str(Path.cwd() / "repo-to-x-workspace" / "runs"))
    parser.add_argument("--run-id", default=default_run_id())
    parser.add_argument("--refresh", action="store_true", help="Refresh cloned remote repos")
    args = parser.parse_args()

    sources = read_sources(args.sources, args.source_file)
    if not sources:
        parser.error("provide at least one repo source or --source-file")

    env_info = load_dotenv([SKILL_ROOT / ".env", Path.cwd() / ".env"])
    out_root = Path(args.out_root).expanduser().resolve()
    run_dir = out_root / safe_slug(args.run_id)
    repos_dir = run_dir / "repos"
    repos_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_dir.name,
        "created_at": utc_now(),
        "run_dir": str(run_dir),
        "sources": sources,
        "env": env_info,
        "workspace_contract": str(SKILL_ROOT / "references" / "run-workspace-contract.md"),
        "brand_profile": {
            "positioning": BRAND_PROFILE["positioning"],
            "tagline": BRAND_PROFILE["tagline"],
            "pillars": BRAND_PROFILE["pillars"],
            "main_account_rule": "Publish only content tied to Agent reliability, build-in-public, paper-to-system, or embodied AI watch.",
        },
        "git_hygiene": {
            "ignored_workspace": "repo-to-x-workspace/",
            "do_not_commit": [
                ".env",
                "repo-to-x-workspace/",
                "cloned repos",
                "generated images",
                "repo-specific posting packs",
                "repo-specific claims ledgers",
            ],
        },
        "repos": [],
    }

    used_ids: set[str] = set()
    for index, source in enumerate(sources, start=1):
        provisional = repos_dir / f"source-{index:03d}"
        context = collect_one(source, provisional, args.refresh)
        rid = repo_id(source, context.get("owner_repo"), Path(context["repo_path"]))
        if rid in used_ids:
            rid = f"{rid}-{index:03d}"
        used_ids.add(rid)
        final_dir = repos_dir / rid
        if final_dir != provisional:
            if final_dir.exists():
                shutil.rmtree(final_dir)
            provisional.rename(final_dir)
            context["workspace_repo_dir"] = str(final_dir)
            write_json(final_dir / "repo_context.json", context)
        manifest["repos"].append(
            {
                "source": source,
                "repo_id": rid,
                "owner_repo": context.get("owner_repo"),
                "directory": str(final_dir),
                "context_path": str(final_dir / "repo_context.json"),
                "file_manifest_path": str(final_dir / "file_manifest.txt"),
                "claims_ledger_path": str(final_dir / "claims_ledger.json"),
                "cross_check_review_path": str(final_dir / "cross_check_review.md"),
                "posting_pack_path": str(final_dir / "posting_pack.md"),
                "images_manifest_path": str(final_dir / "images_manifest.json"),
            }
        )

    write_json(run_dir / "run_manifest.json", manifest)
    write_summary(run_dir, manifest)
    clean_macos_junk(run_dir)

    print(f"Wrote run workspace: {run_dir}")
    print(f"Wrote manifest: {run_dir / 'run_manifest.json'}")
    print(f"Wrote summary: {run_dir / 'SUMMARY.md'}")
    for repo in manifest["repos"]:
        print(f"- {repo['repo_id']}: {repo['directory']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
