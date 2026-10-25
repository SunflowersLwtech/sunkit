"""The single door between captured data and any AI model.

Everything that would go to a model (frames, transcripts, event context) must
go through AIGate, which checks the AI switch at the moment of sending.
With no client configured, submissions are counted and dropped.
"""
from __future__ import annotations

import threading


class AIGate:
    def __init__(self, switches, client=None):
        self.switches = switches
        self.client = client
        self._lock = threading.Lock()
        self.sent = 0
        self.dropped_off = 0
        self.dropped_no_client = 0

    def _open(self) -> bool:
        if not self.switches.get("ai"):
            with self._lock:
                self.dropped_off += 1
            return False
        if self.client is None:
            with self._lock:
                self.dropped_no_client += 1
            return False
        # Re-check right before the call: a switch-off between the two checks wins.
        if not self.switches.get("ai"):
            with self._lock:
                self.dropped_off += 1
            return False
        return True

    def submit(self, kind: str, payload) -> bool:
        if not self._open():
            return False
        self.client.send(kind, payload)
        with self._lock:
            self.sent += 1
        return True

    def ask(self, kind: str, payload):
        """Like submit, but returns the model's answer (or None when nothing was sent or it failed)."""
        if not self._open():
            return None
        with self._lock:
            self.sent += 1
        return self.client.ask(kind, payload)

    def status(self):
        return {"client": type(self.client).__name__ if self.client else None, "sent": self.sent,
                "dropped_off": self.dropped_off, "dropped_no_client": self.dropped_no_client}
