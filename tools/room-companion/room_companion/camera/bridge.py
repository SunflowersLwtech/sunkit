"""Talks to ble_helper.py: starts it (Windows Python from WSL, or local Python), sends one request at a
time, and hands its unasked events (status, battery, need_tap, disconnected) to a callback."""
from __future__ import annotations

import hashlib
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HELPER_FILES = ("ble_helper.py", "rsdk.py", "duml.py")


class BridgeError(RuntimeError):
    pass


def _sha(path: str) -> str | None:
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def win_path(wsl_path: str) -> str:
    """/mnt/c/Users/x -> C:\\Users\\x (what wslpath -w prints for drive mounts)."""
    parts = wsl_path.split("/")
    if len(parts) > 2 and parts[1] == "mnt" and len(parts[2]) == 1:
        return parts[2].upper() + ":\\" + "\\".join(parts[3:])
    raise BridgeError(f"not a Windows drive path: {wsl_path}")


class BleBridge:
    def __init__(self, python: str | None = None, helper_dir: str | None = None, on_event=None,
                 extra_args=(), popen=subprocess.Popen, interop=None):
        self.python = python or sys.executable
        self.windows = self.python.lower().endswith(".exe")
        self.helper_dir = helper_dir
        self.on_event = on_event or (lambda ev: None)
        self.extra_args = list(extra_args)
        self.popen = popen
        self.interop = interop  # windows.Interop: a WSL channel that can start Windows programs
        self.proc = None
        self.ready = None
        self._ids = 0
        self._replies: dict[int, queue.Queue] = {}
        self._lock = threading.Lock()  # one request in flight
        self.last_error = None

    # ---- process ----
    def _script(self) -> str:
        if not self.windows and not self.helper_dir:
            return os.path.join(HERE, "ble_helper.py")
        if not self.helper_dir:
            raise BridgeError("helper_dir is required when the helper runs with Windows Python")
        os.makedirs(self.helper_dir, exist_ok=True)
        for name in HELPER_FILES:
            src, dst = os.path.join(HERE, name), os.path.join(self.helper_dir, name)
            if _sha(src) != _sha(dst):
                shutil.copyfile(src, dst)
        dst = os.path.join(self.helper_dir, "ble_helper.py")
        return win_path(dst) if self.windows else dst

    def start(self, timeout: float = 20.0) -> dict:
        if self.proc is not None and self.proc.poll() is None:
            return self.ready or {}
        if not (self.windows and self.interop is not None):
            return self._start(timeout)
        self.interop.ensure()
        try:
            return self._start(timeout)
        except BridgeError:
            # Windows Python may not start because the WSL interop channel broke: pick another, retry once
            if not self.interop.ensure(force=True):
                raise
            return self._start(timeout)

    def _start(self, timeout: float) -> dict:
        self.ready = None
        ready_q: queue.Queue = queue.Queue()
        cmd = [self.python, "-u", self._script(), *self.extra_args]
        try:
            self.proc = self.popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as e:
            raise BridgeError(f"cannot start the Bluetooth helper: {e}") from e
        proc = self.proc
        threading.Thread(target=self._read, args=(proc, ready_q), daemon=True).start()
        threading.Thread(target=self._drain_stderr, args=(proc,), daemon=True).start()
        try:
            ev = ready_q.get(timeout=timeout)
        except queue.Empty:
            self.stop()
            raise BridgeError("the Bluetooth helper did not start in time")
        if ev.get("error"):
            self.stop()
            raise BridgeError(ev["error"])
        self.ready = ev
        return ev

    def _read(self, proc, ready_q):
        for raw in proc.stdout:
            try:
                msg = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue
            if msg.get("ev") == "ready":
                ready_q.put(msg)
            elif "id" in msg and msg["id"] in self._replies:
                self._replies[msg["id"]].put(msg)
            elif "ev" in msg:
                try:
                    self.on_event(msg)
                except Exception:
                    pass
        for q in list(self._replies.values()):
            q.put({"ok": False, "error": "helper_exited"})

    def _drain_stderr(self, proc):
        for line in proc.stderr:
            self.last_error = line.decode("utf-8", "replace").strip()[:300] or self.last_error

    def stop(self):
        proc, self.proc = self.proc, None
        if proc is None:
            return
        try:
            if proc.poll() is None:
                try:
                    proc.stdin.write(b'{"cmd": "quit"}\n')
                    proc.stdin.flush()
                    proc.wait(5)
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    pass
            if proc.poll() is None:
                proc.terminate()
                proc.wait(5)
        except (OSError, subprocess.TimeoutExpired):
            try:
                proc.kill()
            except OSError:
                pass
        for pipe in (proc.stdin, proc.stdout, proc.stderr):
            try:
                pipe.close()
            except (OSError, AttributeError):
                pass

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    # ---- requests ----
    def call(self, cmd: str, timeout: float = 30.0, **kw) -> dict:
        with self._lock:
            if not self.running:
                self.start()
            self._ids += 1
            rid = self._ids
            q: queue.Queue = queue.Queue()
            self._replies[rid] = q
            try:
                self.proc.stdin.write((json.dumps({"id": rid, "cmd": cmd, **kw}) + "\n").encode())
                self.proc.stdin.flush()
                return q.get(timeout=timeout)
            except (OSError, ValueError) as e:
                return {"ok": False, "error": "helper_io", "detail": str(e)[:200]}
            except queue.Empty:
                # the helper is stuck (a Bluetooth stack that hangs): restart it next time
                self.stop()
                return {"ok": False, "error": "timeout"}
            finally:
                self._replies.pop(rid, None)


def wait_until(pred, timeout: float, step: float = 0.5, sleep=time.sleep, clock=time.monotonic) -> bool:
    end = clock() + timeout
    while True:
        if pred():
            return True
        if clock() >= end:
            return False
        sleep(step)
