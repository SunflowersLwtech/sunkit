#!/usr/bin/env python3
"""Create a governed Agent-engineering X workspace for arbitrary inputs."""

from __future__ import annotations

import argparse
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

from collect_repo_context import load_dotenv, safe_slug  # noqa: E402
from brand_profile import BRAND_PROFILE  # noqa: E402
from run_repo_to_x_pack import make_claims_ledger, make_images_manifest, write_json  # noqa: E402
from x_strategy_router import build_decision  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def read_sources(positional: list[str], source_file: str | None) -> list[str]:
    sources = list(positional)
    if source_file:
        for line in Path(source_file).expanduser().read_text(encoding="utf-8").splitlines():
            value = line.strip()
            if value and not value.startswith("#"):
                sources.append(value)
    return list(dict.fromkeys(sources))


def clean_macos_junk(root: Path) -> None:
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


def template(name: str) -> str:
    return (SKILL_ROOT / "references" / name).read_text(encoding="utf-8")


def source_context(item: dict[str, Any], workspace_dir: Path) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source": item["source"],
        "source_kind": item["kind"],
        "owner_repo": item.get("owner_repo"),
        "paper_id": item.get("paper_id"),
        "host": item.get("host"),
        "evidence_mode": item["evidence_mode"],
        "workspace_repo_dir": str(workspace_dir),
        "created_at": utc_now(),
        "key_files": {},
        "github": {},
        "notes": [
            "This is an arbitrary-input run. Collect source-specific evidence before drafting public claims.",
            "For GitHub/local repos, prefer run_repo_to_x_pack.py when deeper repo evidence is required.",
            "Apply the Agent engineering brand gate before publishing on the main account.",
            "KYC/support/life/media inputs must become cold bug reports, Agent failure-mode notes, or off-main-account drafts.",
            "Fill claims_ledger.json before publishing.",
        ]
        + list(item.get("notes") or []),
    }


def init_source_dir(parent: Path, item: dict[str, Any]) -> dict[str, Any]:
    source_id = safe_slug(item.get("source_id") or item["source"][:48])
    source_dir = parent / source_id
    if source_dir.exists():
        shutil.rmtree(source_dir)
    source_dir.mkdir(parents=True)
    context = source_context(item, source_dir)
    write_json(source_dir / "repo_context.json", context)
    write_json(source_dir / "source_context.json", context)
    write_json(source_dir / "claims_ledger.json", make_claims_ledger(item["source"], item.get("owner_repo"), context))
    write_json(source_dir / "images_manifest.json", make_images_manifest(item.get("owner_repo")))
    (source_dir / "cross_check_review.md").write_text(template("cross-check-review-template.md"), encoding="utf-8")
    (source_dir / "posting_pack.md").write_text(template("posting-pack-template.md"), encoding="utf-8")
    (source_dir / "images").mkdir(exist_ok=True)
    (source_dir / "file_manifest.txt").write_text(
        "\n".join(
            [
                "repo_context.json",
                "source_context.json",
                "claims_ledger.json",
                "cross_check_review.md",
                "posting_pack.md",
                "images_manifest.json",
                "images/",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "source": item["source"],
        "repo_id": source_id,
        "source_kind": item["kind"],
        "owner_repo": item.get("owner_repo"),
        "directory": str(source_dir),
        "context_path": str(source_dir / "repo_context.json"),
        "file_manifest_path": str(source_dir / "file_manifest.txt"),
        "claims_ledger_path": str(source_dir / "claims_ledger.json"),
        "cross_check_review_path": str(source_dir / "cross_check_review.md"),
        "posting_pack_path": str(source_dir / "posting_pack.md"),
        "images_manifest_path": str(source_dir / "images_manifest.json"),
    }


def write_summary(run_dir: Path, manifest: dict[str, Any], strategy: dict[str, Any]) -> None:
    lines = [
        f"# Any Input To X Run {manifest['run_id']}",
        "",
        f"- Created at: {manifest['created_at']}",
        f"- Strategy: `{strategy['recommended_strategy']['strategy_id']}`",
        f"- Run directory: `{run_dir}`",
        f"- Source count: {len(manifest['repos'])}",
        "",
        "## Sources",
        "",
    ]
    for repo in manifest["repos"]:
        lines.extend(
            [
                f"### {repo['repo_id']}",
                "",
                f"- Source: `{repo['source']}`",
                f"- Kind: `{repo['source_kind']}`",
                f"- Directory: `{repo['directory']}`",
                f"- Posting pack: `{repo['posting_pack_path']}`",
                f"- Claims ledger: `{repo['claims_ledger_path']}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Strategy Gate",
            "",
            "- Read `strategy_decision.json` before drafting.",
            "- Apply the Agent engineering Brand Fit gate: pillar, account fit, reusable asset, discussion question.",
            "- Collect source-specific evidence before making public claims.",
            "- Do not publish until `cross_check_review.md` is `pass` and image gates pass.",
            "- After review or publish, run `record_post_outcome.py` so the local strategy memory improves.",
            "",
        ]
    )
    (run_dir / "SUMMARY.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", nargs="*", help="Any input source: repo, paper, URL, local path, posting pack, profile prompt, support complaint, or idea")
    parser.add_argument("--prompt", default="", help="Full user request or angle")
    parser.add_argument("--source-file")
    parser.add_argument("--out-root", default=str(Path.cwd() / "repo-to-x-workspace" / "runs"))
    parser.add_argument("--run-id", default=default_run_id())
    parser.add_argument("--memory-root", default=str(Path.cwd() / "repo-to-x-workspace" / "strategy-memory"))
    args = parser.parse_args()

    sources = read_sources(args.sources, args.source_file)
    if not sources:
        sources = [args.prompt or "raw idea"]

    out_root = Path(args.out_root).expanduser().resolve()
    run_dir = out_root / safe_slug(args.run_id)
    source_parent = run_dir / "repos"
    source_parent.mkdir(parents=True, exist_ok=True)
    memory_root = Path(args.memory_root).expanduser().resolve()
    strategy = build_decision(sources, args.prompt, memory_root)

    repos = [init_source_dir(source_parent, item) for item in strategy["classifications"]]
    manifest = {
        "schema_version": 1,
        "run_id": run_dir.name,
        "created_at": utc_now(),
        "run_dir": str(run_dir),
        "sources": sources,
        "prompt": args.prompt,
        "env": load_dotenv([SKILL_ROOT / ".env", Path.cwd() / ".env"]),
        "strategy_decision_path": str(run_dir / "strategy_decision.json"),
        "strategy_memory_root": str(memory_root),
        "workspace_contract": str(SKILL_ROOT / "references" / "run-workspace-contract.md"),
        "brand_profile": {
            "positioning": BRAND_PROFILE["positioning"],
            "tagline": BRAND_PROFILE["tagline"],
            "pillars": BRAND_PROFILE["pillars"],
        },
        "repos": repos,
    }
    write_json(run_dir / "strategy_decision.json", strategy)
    write_json(run_dir / "run_manifest.json", manifest)
    write_summary(run_dir, manifest, strategy)
    clean_macos_junk(run_dir)

    print(f"Wrote arbitrary-input run workspace: {run_dir}")
    print(f"Wrote strategy decision: {run_dir / 'strategy_decision.json'}")
    print(f"Wrote manifest: {run_dir / 'run_manifest.json'}")
    for repo in repos:
        print(f"- {repo['repo_id']}: {repo['directory']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
