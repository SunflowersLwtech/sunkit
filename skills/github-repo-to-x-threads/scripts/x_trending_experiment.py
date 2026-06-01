#!/usr/bin/env python3
"""Run multi-round posting experiments on current GitHub Trending repos."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from collect_repo_context import collect_github, load_dotenv, safe_slug  # noqa: E402
from run_repo_to_x_pack import (  # noqa: E402
    clean_macos_junk,
    collect_one,
    make_claims_ledger,
    make_images_manifest,
    repo_id,
    write_json,
    write_summary,
)


TRENDING_URL = "https://github.com/trending"

TRENDING_SCREENING_PROMPT = (
    "This repo came from current GitHub Trending. Generate a Chinese X thread for an independent sharer. "
    "This is metadata-only early screening unless the run says otherwise. "
    "Do not summarize the README mechanically. First produce materially different angles, then choose one. "
    "The chosen post needs a repeatable thesis, a concrete technical example, a visible caveat, and coherent voice. "
    "Attribution and repo URL must appear, but metadata cannot be the hook."
)
MIN_REWRITE_IMPROVEMENT = 0.001


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_run_id() -> str:
    return "trending_" + datetime.now().strftime("%Y%m%d_%H%M%S")


def run(cmd: list[str], cwd: Path) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, cwd=str(cwd), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def fetch_trending(limit: int, since: str = "daily", language: str = "") -> list[str]:
    query = f"?since={since}"
    if language:
        query = f"/{language}{query}"
    request = urllib.request.Request(
        TRENDING_URL + query,
        headers={
            "User-Agent": "Mozilla/5.0 repo-to-x-trending-experiment",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    html = urllib.request.urlopen(request, timeout=60).read().decode("utf-8", errors="replace")
    repos: list[str] = []
    seen: set[str] = set()
    blocked = {
        "about",
        "account",
        "apps",
        "collections",
        "customer-stories",
        "events",
        "explore",
        "features",
        "github",
        "login",
        "marketplace",
        "new",
        "notifications",
        "orgs",
        "pricing",
        "security",
        "settings",
        "sponsors",
        "topics",
        "trending",
    }
    for owner, name in re.findall(r'href="/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)"', html):
        if owner in blocked or name in blocked:
            continue
        full = f"{owner}/{name}"
        if full in seen:
            continue
        seen.add(full)
        repos.append(full)
        if len(repos) >= limit:
            break
    return repos


def copy_if_exists(src: Path, dst: Path) -> None:
    if src.exists():
        shutil.copy2(src, dst)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate(repo_dir: Path, cwd: Path, label: str, pack_file: str = "posting_pack.md") -> dict[str, Any]:
    cmd = [
        sys.executable,
        "-B",
        str(SCRIPT_DIR / "x_eval_post.py"),
        str(repo_dir),
        "--pack-file",
        pack_file,
        "--text-only-eval",
    ]
    code, stdout, stderr = run(cmd, cwd)
    eval_path = repo_dir / ("post_eval.json" if pack_file == "posting_pack.md" else f"post_eval.{Path(pack_file).stem}.json")
    data = read_json(eval_path)
    data["_command"] = " ".join(cmd)
    data["_returncode"] = code
    data["_stdout"] = stdout
    data["_stderr"] = stderr
    write_json(repo_dir / f"experiment_eval_{label}.json", data)
    copy_if_exists(repo_dir / pack_file, repo_dir / f"posting_pack_{label}.md")
    return data


def generate(repo_dir: Path, cwd: Path, prompt: str) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "-B",
        str(SCRIPT_DIR / "x_generate_posting_pack.py"),
        str(repo_dir),
        "--prompt",
        prompt,
    ]
    code, stdout, stderr = run(cmd, cwd)
    result = read_json(repo_dir / "generation_result.json")
    result["_returncode"] = code
    result["_stdout"] = stdout
    result["_stderr"] = stderr
    write_json(repo_dir / "experiment_generation.json", result)
    if code != 0:
        raise RuntimeError(stderr or stdout or "generation failed")
    return result


def tournament(repo_dir: Path, cwd: Path, prompt: str, label: str) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "-B",
        str(SCRIPT_DIR / "x_draft_tournament.py"),
        str(repo_dir),
        "--prompt",
        prompt,
        "--write-proposed-pack",
    ]
    code, stdout, stderr = run(cmd, cwd)
    result = read_json(repo_dir / "draft_tournament.json")
    result["_returncode"] = code
    result["_stdout"] = stdout
    result["_stderr"] = stderr
    write_json(repo_dir / f"experiment_tournament_{label}.json", result)
    copy_if_exists(repo_dir / "draft_tournament.md", repo_dir / f"draft_tournament_{label}.md")
    if code != 0:
        raise RuntimeError(stderr or stdout or "draft tournament failed")
    return result


def result_row(
    repo: dict[str, Any],
    repo_dir: Path,
    evals: list[dict[str, Any]],
    accepted_eval: dict[str, Any],
    rewrite_decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    best = max(evals, key=lambda item: float(item.get("final_score") or 0.0)) if evals else {}
    return {
        "repo_id": repo["repo_id"],
        "source": repo["source"],
        "owner_repo": repo.get("owner_repo"),
        "directory": str(repo_dir),
        "round_scores": [
            {
                "label": item.get("_label"),
                "decision": item.get("decision"),
                "final_score": item.get("final_score"),
                "scores": item.get("scores", {}),
                "top_fixes": item.get("top_fixes", []),
            }
            for item in evals
        ],
        "best_label": best.get("_label"),
        "best_score": best.get("final_score"),
        "best_decision": best.get("decision"),
        "accepted_label": accepted_eval.get("_label"),
        "final_score": accepted_eval.get("final_score"),
        "final_decision": accepted_eval.get("decision"),
        "rewrite_decisions": rewrite_decisions,
    }


def default_branch_name(github: dict[str, Any]) -> str:
    branch = github.get("defaultBranchRef")
    if isinstance(branch, dict) and branch.get("name"):
        return str(branch["name"])
    return "main"


def fetch_raw_text(url: str, limit: int = 60000) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 repo-to-x-trending-experiment"},
    )
    try:
        text = urllib.request.urlopen(request, timeout=60).read().decode("utf-8", errors="replace")
    except Exception:
        return ""
    return text[:limit]


def collect_metadata_only(source: str, repo_root: Path) -> dict[str, Any]:
    repo_root.mkdir(parents=True, exist_ok=True)
    github = collect_github(source) or {}
    branch = default_branch_name(github)
    owner, name = source.split("/", 1)
    raw_readme = ""
    readme_name = "README.md"
    for candidate in ("README.md", "readme.md", "README.zh-CN.md"):
        raw_readme = fetch_raw_text(f"https://raw.githubusercontent.com/{owner}/{name}/{branch}/{candidate}")
        if raw_readme:
            readme_name = candidate
            break
    files_root = repo_root / "metadata_files"
    files_root.mkdir(exist_ok=True)
    key_files = {"readme": [], "license": [], "package_metadata": [], "docs": [], "examples": [], "images": []}
    manifest_files = []
    if raw_readme:
        (files_root / readme_name).write_text(raw_readme, encoding="utf-8")
        key_files["readme"].append(readme_name)
        manifest_files.append(readme_name)
    context = {
        "source": source,
        "source_kind": "metadata-only",
        "repo_path": str(files_root),
        "owner_repo": source,
        "git": {},
        "github": github,
        "key_files": key_files,
        "file_count": len(manifest_files),
        "notes": [
            "Metadata-only trending experiment: README and GitHub metadata were fetched without cloning the full repo.",
            "Deep clone is required before live publishing or strong source-code claims.",
        ],
    }
    (repo_root / "file_manifest.txt").write_text("\n".join(manifest_files) + ("\n" if manifest_files else ""), encoding="utf-8")
    write_json(repo_root / "repo_context.json", context)
    write_json(repo_root / "claims_ledger.json", make_claims_ledger(source, source, context))
    write_json(repo_root / "images_manifest.json", make_images_manifest(source))
    (repo_root / "cross_check_review.md").write_text("# Cross-Check Review\n\nStatus: revise\n", encoding="utf-8")
    (repo_root / "posting_pack.md").write_text("# Posting Pack\n\n## Ready To Post\n\n```text\n\n```\n", encoding="utf-8")
    (repo_root / "images").mkdir(exist_ok=True)
    return context


def write_experiment_report(run_dir: Path, results: dict[str, Any]) -> None:
    rows = results["results"]
    lines = [
        f"# Trending Experiment {results['run_id']}",
        "",
        f"- Created at: {results['created_at']}",
        f"- Trending URL: {results['trending_url']}",
        f"- Requested limit: {results['limit']}",
        f"- Completed repos: {len(rows)}",
        "",
        "## Scoreboard",
        "",
        "| Repo | Best | Accepted | Decision | Accepted round |",
        "| --- | ---: | ---: | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| `{row.get('owner_repo') or row['source']}` | "
            f"{float(row.get('best_score') or 0):.3f} | "
            f"{float(row.get('final_score') or 0):.3f} | "
            f"{row.get('final_decision')} | {row.get('accepted_label')} |"
        )
    lines.extend(["", "## Common Fixes", ""])
    for fix, count in results.get("common_fixes", []):
        lines.append(f"- {count}x {fix}")
    lines.extend(["", "## Converged Rules", ""])
    for rule in results.get("converged_rules", []):
        lines.append(f"- {rule}")
    lines.extend(["", "## Repo Details", ""])
    for row in rows:
        lines.append(f"### {row.get('owner_repo') or row['source']}")
        for score in row.get("round_scores", []):
            lines.append(
                f"- {score.get('label')}: `{score.get('decision')}` "
                f"{float(score.get('final_score') or 0):.3f}"
            )
        decisions = row.get("rewrite_decisions", [])
        if decisions:
            lines.append("- Rewrite acceptance:")
            for decision in decisions:
                status = "accepted" if decision.get("accepted") else "rejected"
                min_improvement = float(decision.get("min_improvement") or 0)
                threshold_note = f"; min +{min_improvement:.3f}" if min_improvement else ""
                lines.append(
                    f"  - {decision.get('label')}: {status}; "
                    f"candidate {decision.get('candidate_decision', '?')} {float(decision.get('candidate_score') or 0):.3f} vs "
                    f"current {decision.get('previous_decision', '?')} {float(decision.get('previous_score') or 0):.3f} "
                    f"(delta {float(decision.get('delta') or 0):+.3f}{threshold_note})"
                )
        lines.append(f"- Directory: `{row['directory']}`")
        lines.append("")
    (run_dir / "trending_experiment_report.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def derive_rules(rows: list[dict[str, Any]]) -> list[str]:
    rules = [
        "Run text-only angle tournaments before image generation for trending repos; most quality failures are copy-angle failures, not asset failures.",
        "Use the first post to make one repeatable technical claim; move repo attribution and metadata into later posts or evidence.",
        "For thin trending repos, 4-6 dense posts can be enough; for rich repos, papers, or repo+vision angles, prefer 8-12 substantive posts and avoid README-summary completeness.",
    ]
    weak_hook_count = 0
    for row in rows:
        for score in row.get("round_scores", []):
            fixes = " ".join(score.get("top_fixes", []))
            if re.search(r"hook|opener|thesis", fixes, re.I):
                weak_hook_count += 1
    if weak_hook_count:
        rules.append("If eval mentions hook/opener/thesis twice, force a new angle rather than trimming the existing draft.")
    return rules


def copy_feedback_fixes(eval_result: dict[str, Any], text_only: bool) -> list[str]:
    fixes = [str(item) for item in eval_result.get("top_fixes", [])]
    if not text_only:
        return fixes
    return [
        fix
        for fix in fixes
        if not re.search(r"(image|images|GPT|screenshot|diagram|media|图片|截图)", fix, re.I)
    ]


def decision_rank(decision: str | None) -> int:
    return {"block": 0, "revise": 1, "ready": 2}.get(str(decision or "").lower(), 0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--since", default="daily", choices=["daily", "weekly", "monthly"])
    parser.add_argument("--language", default="")
    parser.add_argument("--run-id", default=default_run_id())
    parser.add_argument("--out-root", default=str(Path.cwd() / "repo-to-x-workspace" / "runs"))
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--metadata-only", action="store_true", help="Use GitHub metadata and README without cloning")
    args = parser.parse_args()

    cwd = Path.cwd()
    out_root = Path(args.out_root).expanduser().resolve()
    run_dir = out_root / safe_slug(args.run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    repos = fetch_trending(args.limit, args.since, args.language)
    if not repos:
        raise SystemExit("No trending repos parsed from GitHub.")
    (run_dir / "trending_sources.txt").write_text("\n".join(repos) + "\n", encoding="utf-8")
    env = load_dotenv([Path.cwd() / ".env", SCRIPT_DIR.parent / ".env"])

    manifest_repos: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    repos_dir = run_dir / "repos"
    repos_dir.mkdir(exist_ok=True)

    for source in repos:
        try:
            holder = repos_dir / safe_slug(source.replace("/", "__"))
            context = collect_metadata_only(source, holder) if args.metadata_only else collect_one(source, holder, args.refresh)
            rid = repo_id(source, context.get("owner_repo"), Path(context["repo_path"]))
            if holder.name != rid:
                target = repos_dir / rid
                if target.exists():
                    shutil.rmtree(target)
                holder.rename(target)
                holder = target
            repo_record = {
                "source": source,
                "repo_id": holder.name,
                "source_kind": context.get("source_kind"),
                "owner_repo": context.get("owner_repo"),
                "directory": str(holder),
                "context_path": str(holder / "repo_context.json"),
                "file_manifest_path": str(holder / "file_manifest.txt"),
                "claims_ledger_path": str(holder / "claims_ledger.json"),
                "cross_check_review_path": str(holder / "cross_check_review.md"),
                "posting_pack_path": str(holder / "posting_pack.md"),
                "images_manifest_path": str(holder / "images_manifest.json"),
            }
            manifest_repos.append(repo_record)
            generate(holder, cwd, TRENDING_SCREENING_PROMPT)
            evals = []
            first = evaluate(holder, cwd, "round1")
            first["_label"] = "round1"
            evals.append(first)
            accepted_eval = first
            rewrite_decisions: list[dict[str, Any]] = []
            for round_idx in range(2, max(2, args.rounds) + 1):
                feedback = copy_feedback_fixes(accepted_eval, text_only=True)
                tournament_prompt = (
                    "Improve this trending-repo post. User wants less rigid, higher taste, sharper thesis. "
                    f"Current copy eval fixes: {feedback}. This is text-only early screening; ignore image/media work. "
                    "Run a real angle tournament, not a paraphrase pass. "
                    "The winning draft must include a repeatable thesis, one concrete example, one caveat, and repo attribution/link. "
                    "Do not add unsupported claims."
                )
                tournament(holder, cwd, tournament_prompt, f"round{round_idx}")
                proposed_eval = evaluate(holder, cwd, f"round{round_idx}", "posting_pack.proposed.md")
                proposed_eval["_label"] = f"round{round_idx}"
                evals.append(proposed_eval)
                previous_score = float(accepted_eval.get("final_score") or 0.0)
                candidate_score = float(proposed_eval.get("final_score") or 0.0)
                previous_rank = decision_rank(accepted_eval.get("decision"))
                candidate_rank = decision_rank(proposed_eval.get("decision"))
                accepted = candidate_rank > previous_rank or (
                    candidate_rank == previous_rank and candidate_score > previous_score + MIN_REWRITE_IMPROVEMENT
                )
                rewrite_decisions.append(
                    {
                        "label": f"round{round_idx}",
                        "accepted": accepted,
                        "previous_label": accepted_eval.get("_label"),
                        "previous_decision": accepted_eval.get("decision"),
                        "previous_score": previous_score,
                        "candidate_decision": proposed_eval.get("decision"),
                        "candidate_score": candidate_score,
                        "delta": candidate_score - previous_score,
                        "min_improvement": MIN_REWRITE_IMPROVEMENT,
                    }
                )
                if accepted:
                    shutil.copy2(holder / "posting_pack.proposed.md", holder / "posting_pack.md")
                    accepted_eval = proposed_eval
            rows.append(result_row(repo_record, holder, evals, accepted_eval, rewrite_decisions))
        except Exception as exc:  # noqa: BLE001
            errors.append({"source": source, "error": str(exc)})

    manifest = {
        "schema_version": 1,
        "run_id": run_dir.name,
        "created_at": utc_now(),
        "run_dir": str(run_dir),
        "sources": repos,
        "env": env,
        "repos": manifest_repos,
    }
    write_json(run_dir / "run_manifest.json", manifest)
    write_summary(run_dir, manifest)
    fixes = Counter()
    for row in rows:
        for score in row.get("round_scores", []):
            fixes.update(score.get("top_fixes", []))
    results = {
        "schema_version": 1,
        "run_id": run_dir.name,
        "created_at": utc_now(),
        "trending_url": f"{TRENDING_URL}?since={args.since}",
        "limit": args.limit,
        "rounds": args.rounds,
        "sources": repos,
        "results": rows,
        "errors": errors,
        "common_fixes": fixes.most_common(12),
        "converged_rules": derive_rules(rows),
    }
    write_json(run_dir / "trending_experiment_results.json", results)
    write_experiment_report(run_dir, results)
    clean_macos_junk(run_dir)
    print(f"Wrote: {run_dir / 'trending_experiment_results.json'}")
    print(f"Wrote: {run_dir / 'trending_experiment_report.md'}")
    print(f"Completed repos: {len(rows)} / {len(repos)}")
    if errors:
        print(f"Errors: {len(errors)}", file=sys.stderr)
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
