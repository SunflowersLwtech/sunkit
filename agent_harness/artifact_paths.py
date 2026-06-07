from __future__ import annotations

import re
from pathlib import Path


RUN_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def run_date(run_dir: Path) -> str:
    """Return the artifact date folder for a run directory."""
    date = run_dir.resolve().parent.name
    return date if RUN_DATE_RE.match(date) else "undated"


def preview_dir(
    root: Path,
    run_dir: Path,
    *,
    backend: str,
    attempt: int | None = None,
    purpose: str | None = None,
) -> Path:
    """Run-scoped preview directory under out/previews.

    Preview files are readable scratch outputs. Publishable media is still copied
    and hash-bound under the run directory by finalize_artifacts.py.
    """
    if attempt is not None:
        segment = f"attempt-{attempt:02d}"
    else:
        segment = purpose or "manual"
    return root / "out" / "previews" / run_date(run_dir) / run_dir.name / segment / backend


def preview_output_paths(
    root: Path,
    run_dir: Path,
    *,
    backend: str,
    attempt: int | None = None,
    purpose: str | None = None,
) -> tuple[Path, Path]:
    directory = preview_dir(root, run_dir, backend=backend, attempt=attempt, purpose=purpose)
    return directory / "searchpo-radar.mp4", directory / "searchpo-cover.jpg"


def legacy_preview_globs(run_dir: Path, *, media: str) -> list[str]:
    if media == "video":
        return [
            f"previews/*/{run_dir.name}/**/searchpo-radar*.mp4",
            f"{run_dir.name}-searchpo-radar*.mp4",
        ]
    if media == "cover":
        return [
            f"previews/*/{run_dir.name}/**/searchpo-cover*.jpg",
            f"{run_dir.name}-searchpo-cover*.jpg",
        ]
    raise ValueError(f"unsupported media kind: {media}")
