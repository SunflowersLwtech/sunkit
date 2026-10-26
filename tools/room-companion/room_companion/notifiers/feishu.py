"""Optional notifier plugin: short text messages to one Feishu (Lark) user through a custom app bot.

Enabled with config {"notifier": {"type": "feishu"}} and the env vars FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_OPEN_ID."""
from __future__ import annotations

import json
import queue
import threading
import time
import urllib.request


class FeishuNotifier:
    def __init__(self, app_id: str | None, app_secret: str | None, open_id: str | None,
                 base: str = "https://open.feishu.cn", post=None):
        self.app_id, self.app_secret, self.open_id = app_id, app_secret, open_id
        self.base = base.rstrip("/")
        self._post = post or _post_json
        self._token = None
        self._token_exp = 0.0
        self._q: queue.Queue = queue.Queue(maxsize=100)
        self.sent = 0
        self.last_error = None
        self.history = []

    @property
    def configured(self) -> bool:
        return bool(self.app_id and self.app_secret and self.open_id)

    def start(self):
        threading.Thread(target=self._worker, name="notify", daemon=True).start()

    def send(self, text: str):
        """Queue a message; never blocks the caller."""
        try:
            self._q.put_nowait(text)
        except queue.Full:
            self.last_error = "queue full"

    def send_now(self, text: str) -> bool:
        self.history = (self.history + [{"t": time.time(), "text": text}])[-20:]
        if not self.configured:
            self.last_error = "飞书凭据未配置"
            return False
        try:
            tok = self._tenant_token()
            body = {"receive_id": self.open_id, "msg_type": "text",
                    "content": json.dumps({"text": text}, ensure_ascii=False)}
            r = self._post(f"{self.base}/open-apis/im/v1/messages?receive_id_type=open_id", body,
                           {"Authorization": f"Bearer {tok}"})
            if r.get("code") != 0:
                self.last_error = f"send failed: code={r.get('code')} msg={r.get('msg')}"
                if r.get("code") in (99991663, 99991661, 99991668):  # token invalid/expired
                    self._token = None
                return False
            self.sent += 1
            self.last_error = None
            return True
        except Exception as e:
            self.last_error = f"send failed: {e}"[:200]
            return False

    def _tenant_token(self) -> str:
        if self._token and time.time() < self._token_exp:
            return self._token
        r = self._post(f"{self.base}/open-apis/auth/v3/tenant_access_token/internal",
                       {"app_id": self.app_id, "app_secret": self.app_secret}, {})
        if r.get("code") != 0 or not r.get("tenant_access_token"):
            raise RuntimeError(f"token error code={r.get('code')} msg={r.get('msg')}")
        self._token = r["tenant_access_token"]
        self._token_exp = time.time() + max(60, int(r.get("expire", 7200)) - 300)
        return self._token

    def _worker(self):
        while True:
            text = self._q.get()
            for attempt in range(3):
                if self.send_now(text):
                    break
                time.sleep(2 * (attempt + 1))


def _post_json(url, body, headers):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8", **headers})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))
