from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger("searchpo.harness")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def retry_call(fn, *, max_retries: int = 3, base_delay: float = 2.0, retryable: tuple[type[Exception], ...] = ()):
    """Retry fn() with exponential backoff on retryable exceptions."""
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except retryable as exc:
            last_exc = exc
            if attempt == max_retries:
                break
            delay = base_delay * (2 ** attempt)
            logger.warning(f"Retry {attempt+1}/{max_retries} after {delay:.1f}s: {exc}")
            time.sleep(delay)
    raise last_exc  # type: ignore[misc]


@dataclass(frozen=True)
class Artifact:
    kind: str
    path: Path
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Gate:
    name: str
    status: str
    summary: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class StageResult:
    step: str
    status: str
    details: str
    artifacts: list[Artifact] = field(default_factory=list)
    gates: list[Gate] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class HarnessContext:
    root_dir: Path
    run_dir: Path
    board: "TaskBoard"
    state: dict[str, Any] = field(default_factory=dict)


@dataclass
class HarnessRunResult:
    root_task_id: str
    stage_results: list[StageResult]


class Stage(Protocol):
    name: str
    title: str
    owner: str

    def run(self, context: HarnessContext) -> StageResult:
        ...


class TaskBoard:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        self.conn.close()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            create table if not exists tasks (
              id text primary key,
              parent_id text,
              kind text not null,
              title text not null,
              owner text not null,
              status text not null,
              created_at text not null,
              updated_at text not null
            );
            create table if not exists events (
              id text primary key,
              task_id text not null,
              actor text not null,
              event_type text not null,
              payload_json text not null,
              created_at text not null
            );
            create table if not exists artifacts (
              id text primary key,
              task_id text not null,
              kind text not null,
              path text not null,
              meta_json text not null,
              created_at text not null
            );
            create table if not exists gates (
              id text primary key,
              task_id text not null,
              name text not null,
              status text not null,
              summary text not null,
              meta_json text not null,
              created_at text not null
            );
            """
        )
        self.conn.commit()

    def create_task(self, kind: str, title: str, owner: str, parent_id: str | None = None) -> str:
        task_id = str(uuid.uuid4())
        now = utc_now()
        self.conn.execute(
            """
            insert into tasks (id, parent_id, kind, title, owner, status, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (task_id, parent_id, kind, title, owner, "queued", now, now),
        )
        self.conn.commit()
        self.event(task_id, owner, "task.created", {"kind": kind, "title": title})
        return task_id

    def set_status(self, task_id: str, status: str, actor: str, payload: dict[str, Any] | None = None) -> None:
        now = utc_now()
        self.conn.execute("update tasks set status = ?, updated_at = ? where id = ?", (status, now, task_id))
        self.conn.commit()
        self.event(task_id, actor, f"task.{status}", payload or {})

    def event(self, task_id: str, actor: str, event_type: str, payload: dict[str, Any]) -> None:
        self.conn.execute(
            """
            insert into events (id, task_id, actor, event_type, payload_json, created_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), task_id, actor, event_type, json.dumps(payload, ensure_ascii=False), utc_now()),
        )
        self.conn.commit()

    def artifact(self, task_id: str, artifact: Artifact) -> None:
        self.conn.execute(
            """
            insert into artifacts (id, task_id, kind, path, meta_json, created_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                task_id,
                artifact.kind,
                str(artifact.path),
                json.dumps(artifact.meta, ensure_ascii=False),
                utc_now(),
            ),
        )
        self.conn.commit()

    def gate(self, task_id: str, gate: Gate) -> None:
        self.conn.execute(
            """
            insert into gates (id, task_id, name, status, summary, meta_json, created_at)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                task_id,
                gate.name,
                gate.status,
                gate.summary,
                json.dumps(gate.meta, ensure_ascii=False),
                utc_now(),
            ),
        )
        self.conn.commit()

    def snapshot(self, root_task_id: str) -> dict[str, Any]:
        tasks = [
            dict(row)
            for row in self.conn.execute(
                "select * from tasks where id = ? or parent_id = ? order by rowid",
                (root_task_id, root_task_id),
            )
        ]
        task_ids = [task["id"] for task in tasks]
        if not task_ids:
            return {"tasks": [], "events": [], "artifacts": [], "gates": []}
        marks = ",".join("?" for _ in task_ids)
        events = [
            dict(row)
            for row in self.conn.execute(
                f"select * from events where task_id in ({marks}) order by rowid",
                task_ids,
            )
        ]
        artifacts = [
            dict(row)
            for row in self.conn.execute(
                f"select * from artifacts where task_id in ({marks}) order by rowid",
                task_ids,
            )
        ]
        gates = [
            dict(row)
            for row in self.conn.execute(
                f"select * from gates where task_id in ({marks}) order by rowid",
                task_ids,
            )
        ]
        return {"tasks": tasks, "events": events, "artifacts": artifacts, "gates": gates}


def _setup_logging(run_dir: Path) -> None:
    handler = logging.FileHandler(run_dir / "harness.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger("searchpo")
    if not root.handlers:
        root.addHandler(handler)
        root.setLevel(logging.INFO)


def _save_state(context: HarnessContext, completed_stages: list[str]) -> None:
    write_json(context.run_dir / "harness_state.json", {
        "completed_stages": completed_stages,
        "state": {k: str(v) if isinstance(v, Path) else v for k, v in context.state.items()
                  if not isinstance(v, (bytes,))},
        "saved_at": utc_now(),
    })


def _load_state(context: HarnessContext) -> list[str]:
    state_path = context.run_dir / "harness_state.json"
    if not state_path.exists():
        return []
    data = read_json(state_path)
    # Restore context.state from persisted data on resume
    saved_state = data.get("state")
    if saved_state and isinstance(saved_state, dict):
        for key, value in saved_state.items():
            if key not in context.state:
                # Convert post_dir back to Path
                if key == "post_dir" and isinstance(value, str):
                    context.state[key] = Path(value)
                else:
                    context.state[key] = value
    return data.get("completed_stages") or []


def _quarantine_partial_artifacts(run_dir: Path, stage_name: str) -> Path | None:
    stage_files = {
        "deepseek_polish": ["deepseek_polish.json"],
        "content_scoring": ["content_score.json"],
        "gemini_tts": ["voiceover.wav", "voiceover_manifest.json"],
        "build_captions": ["captions.json"],
        "content_improvement_loop": ["script.json", "scene_plan.json"],
        "render_payload": ["video_spec.json", "render_payload.json"],
        "publish_package": ["post_manifest.json"],
    }
    files = stage_files.get(stage_name, [])
    existing = [run_dir / name for name in files if (run_dir / name).exists()]
    if not existing:
        return None
    quarantine_dir = run_dir / "quarantine" / stage_name / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    moved: list[dict[str, str]] = []
    for path in existing:
        target = quarantine_dir / path.name
        shutil.move(str(path), str(target))
        moved.append({"from": str(path), "to": str(target)})
    write_json(
        quarantine_dir / "quarantine_manifest.json",
        {
            "created_at": utc_now(),
            "stage": stage_name,
            "reason": "stage failed before producing a trustworthy artifact chain",
            "moved": moved,
        },
    )
    return quarantine_dir


class SyncHarness:
    def __init__(self, stages: list[Stage]) -> None:
        self.stages = stages

    def run(self, context: HarnessContext, resume_from: int = 0) -> HarnessRunResult:
        _setup_logging(context.run_dir)
        board = context.board
        root_task = board.create_task("searchpo_agent_run", "Searchpo tracked agent harness run", "harness")
        board.set_status(root_task, "running", "harness", {"run_dir": str(context.run_dir)})
        stage_results: list[StageResult] = []
        completed_stages: list[str] = []

        if resume_from > 0:
            completed_stages = _load_state(context)
            logger.info(f"Resuming from stage {resume_from}, previously completed: {completed_stages}")

        try:
            for idx, stage in enumerate(self.stages):
                if idx < resume_from and stage.name in completed_stages:
                    logger.info(f"Skipping completed stage: {stage.name}")
                    continue

                task = board.create_task(stage.name, stage.title, stage.owner, root_task)
                board.set_status(task, "running", stage.owner)
                board.event(task, stage.owner, "stage.started", {"stage": stage.name})
                logger.info(f"Stage started: {stage.name}")
                t0 = time.time()
                result = stage.run(context)
                elapsed = time.time() - t0
                logger.info(f"Stage completed: {stage.name} ({elapsed:.1f}s) status={result.status}")
                stage_results.append(result)
                for artifact in result.artifacts:
                    board.artifact(task, artifact)
                for gate in result.gates:
                    board.gate(task, gate)
                board.set_status(task, result.status, stage.owner, result.metadata)
                completed_stages.append(stage.name)
                _save_state(context, completed_stages)
                if result.status != "completed":
                    raise RuntimeError(f"Stage {stage.name} ended with status {result.status}: {result.details}")
        except Exception as exc:
            quarantine_dir = _quarantine_partial_artifacts(context.run_dir, stage.name)
            failure_path = context.run_dir / "failure.json"
            failure_payload = {
                "created_at": utc_now(),
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(limit=20),
                "failed_stage_index": idx,
                "failed_stage_name": stage.name,
                "quarantine_dir": str(quarantine_dir) if quarantine_dir else None,
            }
            write_json(failure_path, failure_payload)
            board.artifact(root_task, Artifact("failure", failure_path))
            board.gate(root_task, Gate("harness_result", "fail", str(exc)[:500], failure_payload))
            board.set_status(root_task, "failed", "harness", failure_payload)
            logger.error(f"Harness failed at stage {stage.name}: {exc}")
            raise

        board.gate(root_task, Gate("harness_result", "pass", f"{len(stage_results)} stages completed"))
        board.set_status(root_task, "completed", "harness", {"stage_count": len(stage_results)})
        logger.info(f"Harness completed: {len(stage_results)} stages")
        return HarnessRunResult(root_task, stage_results)
