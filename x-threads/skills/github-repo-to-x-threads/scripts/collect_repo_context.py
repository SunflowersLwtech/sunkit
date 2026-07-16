#!/usr/bin/env python3
"""Collect local repo evidence and live GitHub metadata for repo-to-X analysis."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


GH_JSON_FIELDS = ",".join(
    [
        "name",
        "nameWithOwner",
        "description",
        "url",
        "homepageUrl",
        "stargazerCount",
        "forkCount",
        "watchers",
        "isArchived",
        "isFork",
        "createdAt",
        "updatedAt",
        "pushedAt",
        "defaultBranchRef",
        "licenseInfo",
        "primaryLanguage",
        "repositoryTopics",
        "latestRelease",
        "owner",
        "openGraphImageUrl",
    ]
)


def parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    key, value = stripped.split("=", 1)
    key = key.strip()
    if key.startswith("export "):
        key = key[len("export ") :].strip()
    if not key:
        return None
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return key, value


def load_dotenv(paths: list[Path]) -> dict[str, Any]:
    loaded_files: list[str] = []
    loaded_keys: list[str] = []
    seen_paths: set[Path] = set()
    for path in paths:
        path = path.expanduser().resolve()
        if path in seen_paths:
            continue
        seen_paths.add(path)
        if not path.exists() or not path.is_file():
            continue
        loaded_files.append(str(path))
        for line in path.read_text(errors="replace").splitlines():
            parsed = parse_env_line(line)
            if not parsed:
                continue
            key, value = parsed
            if key not in os.environ:
                os.environ[key] = value
                loaded_keys.append(key)

    if "GH_TOKEN" not in os.environ:
        for alias_key in ("GITHUB_TOKEN", "GITHUB_PERSONAL_ACCESS_TOKEN"):
            alias_value = os.environ.get(alias_key)
            if alias_value:
                os.environ["GH_TOKEN"] = alias_value
                loaded_keys.append("GH_TOKEN")
                break

    return {
        "loaded_files": loaded_files,
        "loaded_keys": sorted(set(loaded_keys)),
        "github_token_available": bool(
            os.environ.get("GH_TOKEN")
            or os.environ.get("GITHUB_TOKEN")
            or os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN")
        ),
    }


def run(cmd: list[str], cwd: Path | None = None, check: bool = False) -> tuple[int, str, str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed: {proc.stderr.strip()}")
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def parse_github_ref(value: str) -> str | None:
    value = value.strip()
    if re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", value):
        return value

    patterns = [
        r"github\.com[:/]([^/\s]+)/([^/\s#?]+?)(?:\.git)?(?:[#?].*)?$",
        r"^git@github\.com:([^/\s]+)/([^/\s]+?)(?:\.git)?$",
    ]
    for pattern in patterns:
        match = re.search(pattern, value)
        if match:
            return f"{match.group(1)}/{match.group(2)}"
    return None


def safe_slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "repo"


def ensure_repo(source: str, out: Path, refresh: bool) -> tuple[Path, str | None, str]:
    source_path = Path(source).expanduser()
    if source_path.exists():
        repo_path = source_path.resolve()
        code, origin, _ = run(["git", "-C", str(repo_path), "remote", "get-url", "origin"])
        owner_repo = parse_github_ref(origin) if code == 0 else None
        return repo_path, owner_repo, "local"

    owner_repo = parse_github_ref(source)
    if not owner_repo:
        raise SystemExit(f"Could not interpret source as local path or GitHub repo: {source}")

    repo_dir = out / "repo"
    if repo_dir.exists():
        if refresh:
            if out.resolve() == Path("/").resolve() or len(out.resolve().parts) < 3:
                raise SystemExit(f"Refusing to refresh unsafe output path: {out}")
            shutil.rmtree(repo_dir)
        else:
            return repo_dir.resolve(), owner_repo, "remote-cache"

    clone_url = f"https://github.com/{owner_repo}.git"
    run(["git", "clone", "--depth=1", clone_url, str(repo_dir)], check=True)
    return repo_dir.resolve(), owner_repo, "remote-clone"


def collect_git(repo_path: Path) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    commands = {
        "toplevel": ["git", "-C", str(repo_path), "rev-parse", "--show-toplevel"],
        "head": ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
        "branch": ["git", "-C", str(repo_path), "branch", "--show-current"],
        "origin": ["git", "-C", str(repo_path), "remote", "get-url", "origin"],
        "status": ["git", "-C", str(repo_path), "status", "--short"],
    }
    for key, cmd in commands.items():
        code, stdout, stderr = run(cmd)
        facts[key] = stdout if code == 0 else {"error": stderr}
    return facts


def collect_github(owner_repo: str | None) -> dict[str, Any] | None:
    if not owner_repo or not shutil.which("gh"):
        return None

    code, stdout, stderr = run(["gh", "repo", "view", owner_repo, "--json", GH_JSON_FIELDS])
    if code != 0:
        return {"error": stderr}
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return {"error": "gh returned non-JSON output", "raw": stdout[:1000]}


def write_manifest(repo_path: Path, out: Path) -> list[str]:
    if shutil.which("rg"):
        code, stdout, _ = run(["rg", "--files"], cwd=repo_path)
    else:
        code, stdout, _ = run(["git", "-C", str(repo_path), "ls-files"])
    files = stdout.splitlines() if code == 0 and stdout else []
    (out / "file_manifest.txt").write_text("\n".join(files) + ("\n" if files else ""), encoding="utf-8")
    return files


def detect_key_files(files: list[str]) -> dict[str, list[str]]:
    groups = {
        "readme": [],
        "license": [],
        "package_metadata": [],
        "docs": [],
        "examples": [],
        "images": [],
    }
    package_names = {
        "package.json",
        "pyproject.toml",
        "setup.py",
        "Cargo.toml",
        "go.mod",
        "pom.xml",
        "requirements.txt",
        "Dockerfile",
        "docker-compose.yml",
    }
    for file in files:
        lower = file.lower()
        name = Path(file).name
        if name.lower().startswith("readme"):
            groups["readme"].append(file)
        if "license" in name.lower() or name.lower() in {"copying", "notice"}:
            groups["license"].append(file)
        if name in package_names:
            groups["package_metadata"].append(file)
        if lower.startswith(("docs/", "doc/")) or "/docs/" in lower:
            groups["docs"].append(file)
        if lower.startswith(("examples/", "example/", "demo/", "demos/")) or "/examples/" in lower:
            groups["examples"].append(file)
        if lower.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg")):
            groups["images"].append(file)
    return groups


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="GitHub URL, owner/repo, or local path")
    parser.add_argument(
        "--out",
        default="repo-to-x-workspace/context/collect-repo-context",
        help="Governed output directory under the local workspace",
    )
    parser.add_argument("--refresh", action="store_true", help="Refresh cloned repo under output directory")
    args = parser.parse_args()

    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    skill_root = Path(__file__).resolve().parents[1]
    env_info = load_dotenv([skill_root / ".env", Path.cwd() / ".env"])

    repo_path, owner_repo, source_kind = ensure_repo(args.source, out, args.refresh)
    files = write_manifest(repo_path, out)
    context = {
        "source": args.source,
        "source_kind": source_kind,
        "repo_path": str(repo_path),
        "owner_repo": owner_repo,
        "git": collect_git(repo_path),
        "github": collect_github(owner_repo),
        "env": env_info,
        "key_files": detect_key_files(files),
        "file_count": len(files),
        "notes": [
            "Use this as a starting point only.",
            "Read the key files directly before drafting public claims.",
            "If GitHub metadata is null or contains an error, do not invent live metadata.",
        ],
    }
    context_path = out / "repo_context.json"
    context_path.write_text(json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Wrote {context_path}")
    print(f"Wrote {out / 'file_manifest.txt'}")
    if owner_repo:
        print(f"GitHub repo: {owner_repo}")
    print(f"Repo path: {repo_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
