"""Local vision model: llama.cpp's llama-server on this PC's GPU, never a cloud model.

The server process exists only while the AI switch is on and the camera is running;
switching AI off ends the process (and frees the GPU). Frames reach it only through
AIGate.ask, which re-checks the AI switch at the moment of sending.
"""
from __future__ import annotations

import base64
import collections
import json
import subprocess
import threading
import time
import urllib.error
import urllib.request

SCENES = {
    "laundry": "洗衣服", "cooking": "做饭", "coding": "写代码", "router": "配置路由器", "yoga": "瑜伽",
    "sofa_phone": "沙发上玩手机", "sleeping": "睡觉", "other": "其他", "empty": "没人",
}

SCHEMA = {
    "type": "object",
    "properties": {
        "person": {"type": "boolean"},
        "scene": {"enum": list(SCENES)},
        "hot_oil": {"type": "boolean"},
        "on_phone_call": {"type": "boolean"},
        "note": {"type": "string"},
    },
    "required": ["person", "scene", "hot_oil", "on_phone_call", "note"],
}

PROMPT = (
    "这是一个人家里房间的摄像头画面。只根据画面判断，输出 JSON。"
    "person：画面里有没有人。scene 取值：laundry=洗衣服或晾衣服，cooking=做饭，coding=在电脑前写代码或办公，"
    "router=在摆弄路由器或网线，yoga=在瑜伽垫上锻炼，sofa_phone=在沙发上玩手机，sleeping=在床上睡觉，"
    "other=其他活动，empty=房间里没有人。hot_oil：是否正在用热油或明火炒菜。on_phone_call：是否在打电话。"
    "note：不超过 20 个字的中文描述。"
)


def parse_observation(content: str) -> dict | None:
    try:
        d = json.loads(content)
    except (TypeError, ValueError):
        return None
    if not isinstance(d, dict) or d.get("scene") not in SCENES:
        return None
    obs = {
        "person": d.get("person") is True,
        "scene": d["scene"],
        "hot_oil": d.get("hot_oil") is True,
        "on_phone_call": d.get("on_phone_call") is True,
        "note": str(d.get("note", ""))[:40],
    }
    if not obs["person"]:
        obs["scene"] = "empty"
    if obs["scene"] == "empty":
        obs["person"] = False
    return obs


class LlamaServer:
    """Starts and stops llama-server.exe (Windows, CUDA) through WSL interop."""

    def __init__(self, cfg: dict, events, popen=subprocess.Popen, urlopen=urllib.request.urlopen):
        self.cfg = cfg
        self.events = events
        self.popen = popen
        self.urlopen = urlopen
        self.proc = None
        self.state = "off"
        self.detail = ""
        self.started_at = None
        self._retry_at = 0.0
        self._backoff = 30.0
        self._lock = threading.Lock()
        self._log = collections.deque(maxlen=30)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.cfg.get('port', 8791)}"

    def cmd(self) -> list[str]:
        c = self.cfg
        return [c["exe"], "-m", c["model"], "--mmproj", c["mmproj"], "-ngl", "99",
                "-c", str(c.get("ctx", 4096)), "-np", "1", "--host", "127.0.0.1", "--port", str(c.get("port", 8791)),
                "--api-key-file", c["key_file_win"], "--no-webui", *c.get("extra_args", [])]

    def ensure(self, want: bool):
        with self._lock:
            if want and self.proc is None:
                if time.time() >= self._retry_at:
                    self._start()
            elif not want and self.proc is not None:
                self._stop("not needed")
            elif want and self.proc is not None and self.proc.poll() is not None:
                rc = self.proc.returncode
                self._stop(f"exited {rc}")
                self.state, self.detail = "error", f"模型进程退出（{rc}）：" + " | ".join(list(self._log)[-2:])
                self._retry_at = time.time() + self._backoff  # don't restart a crashing model every few seconds
                self._backoff = min(self._backoff * 2, 600.0)
            if not want and self.proc is None and self.state == "error":
                self.state, self._retry_at, self._backoff = "off", 0.0, 30.0

    def _start(self):
        try:
            self.proc = self.popen(self.cmd(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.PIPE)
        except OSError as e:
            self.state, self.detail = "error", f"启动不了模型：{e}"
            return
        self.state, self.detail, self.started_at = "starting", "", time.time()
        threading.Thread(target=self._read_log, args=(self.proc,), daemon=True).start()
        self.events.add("model_on")

    def _read_log(self, proc):
        try:
            for line in proc.stderr:
                self._log.append(line.decode("utf-8", "replace").strip()[:200])
        except (OSError, ValueError, AttributeError):
            pass

    def _stop(self, why):
        proc, self.proc = self.proc, None
        if proc is None:
            return
        try:
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(10)
        except OSError:
            pass
        self.state, self.detail, self.started_at = "off", "", None
        self.events.add("model_off", reason=why)

    def stop(self, why="shutdown"):
        with self._lock:
            self._stop(why)

    def ready(self) -> bool:
        if self.proc is None:
            return False
        if self.state == "ready":
            return True
        try:
            with self.urlopen(self.base + "/health", timeout=2) as r:
                ok = r.status == 200
        except (urllib.error.URLError, OSError, ValueError):
            ok = False
        if ok:
            self.state, self._backoff = "ready", 30.0
            self.events.add("model_ready", seconds=round(time.time() - (self.started_at or time.time()), 1))
        return ok

    def status(self):
        return {"state": self.state, "detail": self.detail, "pid": self.proc.pid if self.proc else None}


class LocalVision:
    """The AI gate's client: one frame in, one scene observation out."""

    def __init__(self, server: LlamaServer, key_file: str, urlopen=urllib.request.urlopen, timeout=90):
        self.server = server
        self.key_file = key_file
        self.urlopen = urlopen
        self.timeout = timeout
        self.last_seconds = None
        self.errors = 0
        self.last_error = None

    def _key(self) -> str:
        with open(self.key_file, "r", encoding="utf-8") as f:
            return f.read().strip()

    def send(self, kind, payload):
        """Transcripts are not forwarded to the model in this version."""
        return False

    def ask(self, kind, payload):
        if kind != "frame" or not self.server.ready():
            return None
        body = {
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(payload["jpeg"]).decode()}},
                {"type": "text", "text": PROMPT}]}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "observation", "schema": SCHEMA}},
            "temperature": 0.1,
        }
        req = urllib.request.Request(self.server.base + "/v1/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": "Bearer " + self._key()})
        t = time.time()
        try:
            with self.urlopen(req, timeout=self.timeout) as r:
                resp = json.load(r)
            content = resp["choices"][0]["message"]["content"]
        except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError) as e:
            self.errors += 1
            self.last_error = str(e)[:200]
            return None
        self.last_seconds = round(time.time() - t, 2)
        obs = parse_observation(content)
        if obs is None:
            self.errors += 1
            self.last_error = "unparseable: " + str(content)[:120]
        return obs
