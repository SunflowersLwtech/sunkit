"""Three independent privacy switches: video, audio, ai.

The state file is the only source of truth across restarts. Anything we cannot
read with certainty counts as "off" (fail closed).
"""
from __future__ import annotations

import json
import os
import threading
import time

KEYS = ("video", "audio", "ai")
LABELS = {"video": "视频", "audio": "声音", "ai": "AI"}


class SwitchWriteError(RuntimeError):
    pass


class Switches:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self._listeners = []
        self.load_error: str | None = None
        self._state = self._load()

    def _load(self) -> dict:
        state = {k: False for k in KEYS}
        state["updated_at"] = None
        state["source"] = None
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            self.load_error = "no state file yet"
            return state
        except (OSError, ValueError) as e:
            self.load_error = f"unreadable state file: {e}"
            return state
        if not isinstance(data, dict):
            self.load_error = "state file is not an object"
            return state
        for k in KEYS:
            # Only a literal true turns a switch on.
            state[k] = data.get(k) is True
        state["updated_at"] = data.get("updated_at")
        state["source"] = data.get("source")
        self.load_error = None
        return state

    def get(self, key: str) -> bool:
        with self._lock:
            return self._state.get(key) is True

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._state)

    def on_change(self, fn):
        self._listeners.append(fn)

    def set(self, changes: dict, source: str) -> dict:
        """Apply changes like {"video": False}. Returns {key: (old, new)} for keys that changed.

        Turning something off always takes effect in memory even if the state file
        cannot be written; turning something on requires a successful write.
        """
        clean = {}
        for k, v in changes.items():
            if k not in KEYS:
                raise ValueError(f"unknown switch: {k}")
            if not isinstance(v, bool):
                raise ValueError(f"switch {k} needs true/false")
            clean[k] = v
        with self._lock:
            new_state = dict(self._state)
            diff = {k: (self._state[k], v) for k, v in clean.items() if self._state[k] != v}
            if not diff:
                return {}
            new_state.update(clean)
            new_state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            new_state["source"] = source
            try:
                self._write(new_state)
            except OSError as e:
                if any(new for _, new in diff.values()):
                    raise SwitchWriteError(f"cannot persist switch state: {e}") from e
                # Only offs: apply anyway, the file will be retried on next change.
                self.load_error = f"state write failed: {e}"
            self._state = new_state
        for fn in list(self._listeners):
            try:
                fn(diff, source)
            except Exception:  # listeners must not break switching
                pass
        return diff

    def _write(self, state: dict):
        d = os.path.dirname(self.path) or "."
        os.makedirs(d, exist_ok=True)
        tmp = f"{self.path}.tmp.{os.getpid()}"
        body = {k: state[k] for k in KEYS}
        body["updated_at"] = state.get("updated_at")
        body["source"] = state.get("source")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(body, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)
        dfd = os.open(d, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)


def describe(state: dict) -> str:
    return " / ".join(f"{LABELS[k]} {'开' if state.get(k) is True else '关'}" for k in KEYS)
