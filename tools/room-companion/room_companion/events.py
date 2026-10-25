"""Event summaries on disk: one JSON line per event, one file per day.

Only summaries go here (switch changes, motion start/end, how long someone
spoke). No frames, no audio, no transcript text.
"""
from __future__ import annotations

import collections
import json
import os
import threading
import time


class EventLog:
    def __init__(self, directory: str, retention_days: int = 30):
        self.dir = directory
        self.retention_days = retention_days
        self._lock = threading.Lock()
        self.recent = collections.deque(maxlen=200)
        os.makedirs(self.dir, exist_ok=True)
        self._last_purge = 0.0

    def add(self, kind: str, **fields):
        ev = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "kind": kind, **fields}
        line = json.dumps(ev, ensure_ascii=False)
        with self._lock:
            self.recent.append(ev)
            path = os.path.join(self.dir, time.strftime("%Y-%m-%d") + ".jsonl")
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                pass
        if time.time() - self._last_purge > 3600:
            self.purge()
        return ev

    def purge(self, now: float | None = None):
        now = now or time.time()
        self._last_purge = now
        cutoff = now - self.retention_days * 86400
        try:
            names = os.listdir(self.dir)
        except OSError:
            return
        for n in names:
            if not n.endswith(".jsonl"):
                continue
            try:
                day = time.mktime(time.strptime(n[:-6], "%Y-%m-%d"))
            except ValueError:
                continue
            if day + 86400 < cutoff:
                try:
                    os.unlink(os.path.join(self.dir, n))
                except OSError:
                    pass

    def latest(self, n: int = 30):
        with self._lock:
            return list(self.recent)[-n:]
