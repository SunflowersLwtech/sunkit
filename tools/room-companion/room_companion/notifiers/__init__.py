"""Where confirmations and reminders go. Pick one in config: {"notifier": {"type": "log" | "feishu"}}.

A notifier needs `send(text)` (non-blocking) and may have `start()`, `configured`, `sent`, `last_error`.
The default only records messages in memory and prints them; nothing leaves the machine.
"""
from __future__ import annotations

import os
import sys


class LogNotifier:
    configured = True

    def __init__(self, stream=sys.stdout):
        self.stream = stream
        self.sent = 0
        self.last_error = None
        self.history = []

    def send(self, text: str) -> bool:
        self.sent += 1
        self.history.append(text)
        del self.history[:-50]
        print("[notify] " + text.replace("\n", " / "), file=self.stream, flush=True)
        return True


def make_notifier(cfg: dict):
    kind = (cfg.get("notifier") or {}).get("type", "log")
    if kind == "feishu":
        from .feishu import FeishuNotifier
        return FeishuNotifier(os.environ.get("FEISHU_APP_ID"), os.environ.get("FEISHU_APP_SECRET"),
                              os.environ.get("FEISHU_OPEN_ID"))
    if kind == "log":
        return LogNotifier()
    raise ValueError(f"unknown notifier type: {kind}")
