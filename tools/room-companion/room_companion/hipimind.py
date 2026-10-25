"""Connect room-companion to HipiMind Room over one outgoing WebSocket.

Two ways to run it, same protocol (HipiMind's "connect your own room device" contract,
https://hipimind.com/room/connect):
- in-process (recommended): add a "hipimind" section to room-companion's config; the app starts
  the connector itself, with direct access to the switches, frames, reminders and the models layer
  (so the HipiMind page can also choose each model and run "Test connection");
- sidecar: `python -m room_companion.hipimind run --config …` next to any room-companion (or an
  older build with the same local HTTP API); switches, state, events and live video only.

What leaves this machine, and only to the owner's HipiMind account:
- the three switches and what the capture/model processes are doing;
- the current scene label and its one-line note ("what the AI sees", text only);
- reminder categories, switch changes, scene changes and a few notices;
- JPEG frames, only while the owner has the HipiMind page open and asked for live video.
Never sent: transcripts, audio, the local event log as such, process ids, device
names, logs. The device token and any model key are never logged.

    python -m room_companion pair --code K7QM-2WXH --name Bedroom      # in-process: uses the app's config
    python -m room_companion.hipimind pair --server https://api.hipimind.com --code K7QM-2WXH --name Bedroom
    python -m room_companion.hipimind run --config ~/.config/room-companion/hipimind.json   # sidecar
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import logging
import os
import random
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime

log = logging.getLogger("room_companion.hipimind")

PROTOCOL_VERSION = 1
SOFTWARE = "room-companion-hipimind/0.1.0"
KEYS = ("video", "audio", "ai")
CAPTURE_STATES = ("off", "starting", "running", "waiting_device", "error")
MODEL_STATES = ("off", "starting", "ready", "error")
# local policy mode -> HipiMind reminder level, and back
LEVEL_OF_MODE = {"quiet": "quiet", "balanced": "balanced", "active": "proactive"}
MODE_COMMAND = {"quiet": "安静模式", "balanced": "平衡模式", "proactive": "主动模式"}
PERMANENT_CLOSE = {4401: "the device token is unknown or revoked; pair the device again",
                   4403: "HipiMind Room is not enabled for this account",
                   4409: "another connection for this device replaced this one"}
EVENT_NAMESPACE = uuid.UUID("6f2b1c1e-7a0d-4f43-9a51-2d2f1b0c9e11")
SCENE_LABELS = {"laundry": "洗衣服", "cooking": "做饭", "coding": "写代码", "router": "配置路由器", "yoga": "瑜伽",
                "sofa_phone": "沙发上玩手机", "sleeping": "睡觉", "other": "其他", "empty": "没人"}
CATEGORY_LABELS = {"久坐": "久坐提醒", "路由器": "改路由器前备份", "手机": "沙发上看手机", "晾衣服": "晾衣服",
                   "厨房": "做完饭关火通风", "运动后": "运动后补水拉伸"}
NOTICE_TEXT = {"camera_missing_reminder": "Video is on but the camera has been missing for a few minutes",
               "gpu_too_hot": "The local model is paused for 30 minutes to cool down"}

DEFAULTS = {
    "server": "https://api.hipimind.com",
    "ws_url": None,
    "token_file": "~/.config/room-companion/hipimind.token",
    "local_api": "http://127.0.0.1:8790",
    "local_api_key_file": None,
    "poll_seconds": 1.0,
    "platform": None,
    "live": {"max_fps": 2, "max_width": 960, "jpeg_quality": 70},
    "events": {"reminders": True, "switches": True, "scene": True, "notices": True},
    "scene_event_min_minutes": 10,
}


# ---------------------------------------------------------------- config / files

def load_config(path: str) -> dict:
    with open(os.path.expanduser(path), "r", encoding="utf-8") as f:
        return load_config_dict(json.load(f))


def load_config_dict(data: dict) -> dict:
    """The bridge config with defaults filled in (one level deep for the nested sections)."""
    if not isinstance(data, dict):
        raise ValueError("config must be a JSON object")
    cfg = json.loads(json.dumps(DEFAULTS))
    for k, v in data.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    return cfg


def ws_url_for(cfg: dict) -> str:
    if cfg.get("ws_url"):
        return cfg["ws_url"]
    u = urllib.parse.urlsplit(cfg["server"].rstrip("/"))
    scheme = {"https": "wss", "http": "ws"}.get(u.scheme, u.scheme)
    return urllib.parse.urlunsplit((scheme, u.netloc, u.path + "/ws/room/device", "", ""))


def write_secret(path: str, value: str):
    """Write a secret readable only by this user (file 600, new parent dirs 700)."""
    path = os.path.expanduser(path)
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, mode=0o700, exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, value.encode("utf-8"))
    finally:
        os.close(fd)
    os.replace(tmp, path)


def read_secret(path: str | None) -> str | None:
    if not path:
        return None
    try:
        with open(os.path.expanduser(path), "r", encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def default_platform() -> str:
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/version", "r", encoding="utf-8") as f:
                if "microsoft" in f.read().lower():
                    return "windows-wsl"
        except OSError:
            pass
        return "linux"
    return {"darwin": "macos", "win32": "windows"}.get(sys.platform, sys.platform)


# ---------------------------------------------------------------- pairing

def pair(server: str, code: str, name: str, token_file: str, platform: str | None = None,
         urlopen=urllib.request.urlopen) -> dict:
    body = json.dumps({"code": code, "name": name, "software": SOFTWARE,
                       "platform": platform or default_platform()}).encode()
    req = urllib.request.Request(server.rstrip("/") + "/api/room/pair", data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode("utf-8"))
        except ValueError:
            err = {}
        raise PairError(e.code, err.get("error") or "error", err.get("message") or str(e)) from None
    token = data.get("device_token")
    if not isinstance(token, str) or not token:
        raise PairError(0, "bad_response", "the server did not return a device token")
    write_secret(token_file, token)
    return {"device_id": data.get("device_id"), "ws_url": data.get("ws_url"),
            "token_file": os.path.expanduser(token_file)}


class PairError(RuntimeError):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(f"{status} {code}: {message}")
        self.status, self.code, self.message = status, code, message


# ---------------------------------------------------------------- local API

class LocalAPI:
    """room-companion's own HTTP API. Loopback needs no key; anything else sends the web key."""

    def __init__(self, base: str, key: str | None = None, timeout: float = 15.0, urlopen=urllib.request.urlopen):
        self.base = base.rstrip("/")
        self.key = key
        self.timeout = timeout
        self.urlopen = urlopen

    def _req(self, method: str, path: str, body: dict | None = None):
        headers = {"X-Room-AI": "1"} if method == "POST" else {}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if self.key:
            headers["Authorization"] = "Bearer " + self.key
        data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with self.urlopen(req, timeout=self.timeout) as r:
                return r.status, r.headers.get("Content-Type", ""), r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers.get("Content-Type", "") if e.headers else "", e.read()

    def status(self) -> dict:
        code, _, raw = self._req("GET", "/api/status")
        if code != 200:
            raise RuntimeError(f"local status answered {code}")
        return json.loads(raw.decode("utf-8"))

    def snapshot(self) -> bytes | None:
        code, ctype, raw = self._req("GET", "/snapshot.jpg")
        return raw if code == 200 and ctype.startswith("image/jpeg") else None

    def switch(self, changes: dict, source: str) -> tuple[int, dict]:
        code, _, raw = self._req("POST", "/api/switch", dict(changes, source=source))
        try:
            return code, json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            return code, {}

    def command(self, text: str, source: str) -> tuple[int, dict]:
        code, _, raw = self._req("POST", "/api/command", {"text": text, "source": source})
        try:
            return code, json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            return code, {}


class AppDevice:
    """The same calls as LocalAPI, straight into a running App (in-process connector), plus models."""

    models_capable = True

    def __init__(self, app):
        self.app = app

    def status(self) -> dict:
        st = self.app.status()
        st["events"] = self.app.events.latest(30)
        pol = st.get("policy")
        if isinstance(pol, dict):
            pol["quiet_hours"] = self.app.quiet_hours()
        return st

    def snapshot(self) -> bytes | None:
        if not self.app.switches.get("video"):
            return None
        frame, _ = self.app.video.latest()
        return frame

    def switch(self, changes: dict, source: str) -> tuple[int, dict]:
        from .switches import SwitchWriteError
        try:
            self.app.set_switches(changes, source)
        except (ValueError, SwitchWriteError) as e:
            return 500, {"ok": False, "message": str(e)[:200]}
        self.app.wait_settled()
        return 200, {"ok": True}

    def command(self, text: str, source: str) -> tuple[int, dict]:
        r = self.app.run_command(text, source)
        return (200 if r.get("ok") else 400), r

    def set_quiet_hours(self, qh) -> None:
        if qh is None:
            self.app.set_quiet_hours(None, None)
        else:
            self.app.set_quiet_hours(str(qh.get("start")), str(qh.get("end")))

    def apply_models(self, models: dict, keys: dict | None) -> list[str]:
        return self.app.apply_models(models, keys)

    def test_model(self, slot: str, model: dict, key: str | None) -> dict:
        return self.app.test_model(slot, model, key)

    def set_cloud(self, cloud) -> None:
        self.app.cloud = cloud


LocalAPI.models_capable = False


# ---------------------------------------------------------------- mapping (pure)

def _iso(ts) -> str | None:
    if isinstance(ts, (int, float)) and ts > 0:
        return datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")
    if isinstance(ts, str):
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
            try:
                return datetime.strptime(ts, fmt).isoformat(timespec="seconds")
            except ValueError:
                continue
    return None


def _models_state(st: dict) -> dict:
    models = st.get("models") if isinstance(st.get("models"), dict) else None
    if models is not None:
        out = {}
        for slot in ("vision", "stt", "tts"):
            m = models.get(slot) if isinstance(models.get(slot), dict) else None
            if not m:
                continue
            e = {"source": m.get("source") if m.get("source") in ("engine", "openai", "cloud", "off") else "engine"}
            if m.get("state") in MODEL_STATES:
                e["state"] = m["state"]
            if isinstance(m.get("name"), str):
                e["name"] = m["name"][:80]
            if e["source"] == "openai":
                if isinstance(m.get("base_url"), str):
                    e["base_url"] = m["base_url"][:200]
                e["has_key"] = m.get("has_key") is True
            out[slot] = e
        return out
    # an older room-companion without the models layer: only the vision engine is known
    model = st.get("model") if isinstance(st.get("model"), dict) else None
    ai = st.get("ai") if isinstance(st.get("ai"), dict) else {}
    if model is not None:
        v = {"source": "engine"}
        if model.get("state") in MODEL_STATES:
            v["state"] = "off" if model.get("paused_hot") else model["state"]
        return {"vision": v}
    return {"vision": {"source": "engine"} if ai.get("client") else {"source": "off", "state": "off"}}


def map_state(st: dict) -> dict:
    """room-companion's /api/status -> HipiMind State. Only whitelisted fields are read."""
    sw = st.get("switches") if isinstance(st.get("switches"), dict) else {}
    out: dict = {"switches": {k: sw.get(k) is True for k in KEYS}}
    capture = {}
    for k in ("video", "audio"):
        part = st.get(k) if isinstance(st.get(k), dict) else {}
        s = part.get("state")
        if s in CAPTURE_STATES:
            capture[k] = s
        elif isinstance(s, str):
            capture[k] = "error"
    if capture:
        out["capture"] = capture
    out["models"] = _models_state(st)
    pol = st.get("policy") if isinstance(st.get("policy"), dict) else {}
    if pol:
        rem = {}
        if pol.get("mode") in LEVEL_OF_MODE:
            rem["level"] = LEVEL_OF_MODE[pol["mode"]]
        if isinstance(pol.get("delivered_today"), int):
            rem["today"] = pol["delivered_today"]
        qh = pol.get("quiet_hours", "absent")
        if qh is None or (isinstance(qh, dict) and isinstance(qh.get("start"), str) and isinstance(qh.get("end"), str)):
            rem["quiet_hours"] = qh
        if rem:
            out["reminders"] = rem
        scene = pol.get("scene")
        if isinstance(scene, str) and scene:
            note = pol.get("note") if isinstance(pol.get("note"), str) else ""
            text = (note or pol.get("scene_text") or SCENE_LABELS.get(scene, scene))[:200]
            entry = {"label": scene, "text": text}
            at = _iso(pol.get("observed_at"))
            if at:
                entry["at"] = at
            out["scene"] = entry
    if isinstance(st.get("summary"), str):
        out["summary"] = st["summary"][:300]
    return out


def _switch_text(changes: dict, source) -> str:
    names = {"video": "Video", "audio": "Audio", "ai": "AI"}
    parts = [f"{names[k]} {'on' if v else 'off'}" for k, v in changes.items() if k in names]
    text = ", ".join(parts) or "Switches unchanged"
    if isinstance(source, str) and source:
        text += f" ({source[:60]})"
    return text


class EventDiffer:
    """Turns new entries of the local event list into HipiMind events (only a few kinds)."""

    def __init__(self, enabled: dict | None = None, scene_min_minutes: float = 10, clock=time.time):
        self.enabled = dict(DEFAULTS["events"], **(enabled or {}))
        self.scene_gap = scene_min_minutes * 60
        self.clock = clock
        self.seen: dict[str, None] = {}
        self.baselined = False
        self.last_scene_sent = 0.0

    @staticmethod
    def _key(ev: dict) -> str:
        return json.dumps(ev, sort_keys=True, ensure_ascii=False)

    def new_events(self, local: list, device_id: str | None) -> list[dict]:
        local = [e for e in local if isinstance(e, dict)]
        if not self.baselined:
            # what was already in the list when the bridge started is history, not news
            for e in local:
                self.seen[self._key(e)] = None
            self.baselined = True
            return []
        out = []
        for e in local:
            k = self._key(e)
            if k in self.seen:
                continue
            self.seen[k] = None
            m = self.map_event(e)
            if m is None:
                continue
            m["id"] = str(uuid.uuid5(EVENT_NAMESPACE, f"{device_id}|{e.get('ts')}|{m['kind']}|{m['text']}"))
            out.append(m)
        while len(self.seen) > 1000:
            self.seen.pop(next(iter(self.seen)))
        return out

    def map_event(self, e: dict) -> dict | None:
        kind = e.get("kind")
        at = _iso(e.get("ts")) or datetime.now().astimezone().isoformat(timespec="seconds")
        if kind == "reminder" and self.enabled.get("reminders"):
            cat = str(e.get("category") or "")
            return {"type": "event", "kind": "reminder", "text": CATEGORY_LABELS.get(cat, cat or "reminder")[:1000],
                    "at": at, "data": {"category": cat[:40]}}
        if kind == "summary" and self.enabled.get("reminders"):
            return {"type": "event", "kind": "reminder", "text": "早报", "at": at, "data": {"category": "summary"}}
        if kind == "switch" and self.enabled.get("switches"):
            changes = e.get("changes") if isinstance(e.get("changes"), dict) else {}
            changes = {k: v is True for k, v in changes.items() if k in KEYS}
            return {"type": "event", "kind": "switch", "text": _switch_text(changes, e.get("source")), "at": at,
                    "data": {"changes": changes}}
        if kind == "scene" and self.enabled.get("scene"):
            now = self.clock()
            if now - self.last_scene_sent < self.scene_gap:
                return None
            self.last_scene_sent = now
            scene = str(e.get("scene") or "")
            return {"type": "event", "kind": "scene", "text": SCENE_LABELS.get(scene, scene)[:200], "at": at,
                    "data": {"label": scene[:40]}}
        if kind in NOTICE_TEXT and self.enabled.get("notices"):
            return {"type": "event", "kind": "notice", "text": NOTICE_TEXT[kind], "at": at, "data": {}}
        return None


# ---------------------------------------------------------------- frames

def fit_frame(jpeg: bytes, max_width: int, quality: int, max_bytes: int) -> bytes | None:
    """Downscale to max_width (Pillow, if installed) and keep under max_bytes; None if it cannot fit."""
    try:
        from PIL import Image
    except ImportError:
        return jpeg if len(jpeg) <= max_bytes else None
    try:
        im = Image.open(io.BytesIO(jpeg))
        if im.width > max_width:
            im = im.resize((max_width, max(1, round(im.height * max_width / im.width))))
        im = im.convert("RGB")
        q = quality
        while q >= 30:
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=q)
            data = buf.getvalue()
            if len(data) <= max_bytes:
                return data
            q -= 15
    except Exception:  # a broken frame is skipped, never fatal
        return None
    return None


# ---------------------------------------------------------------- the bridge

CLOUD_KINDS = ("infer", "transcribe", "speak")


class Bridge:
    def __init__(self, cfg: dict, device=None, connect=None, clock=time.time):
        self.cfg = cfg
        self.device = device or LocalAPI(cfg["local_api"], read_secret(cfg.get("local_api_key_file")))
        self.clock = clock
        self._connect = connect
        self.ws_url = ws_url_for(cfg)
        self.events = EventDiffer(cfg.get("events"), cfg.get("scene_event_min_minutes", 10), clock)
        self.state: dict | None = None
        self.state_changed = asyncio.Event()
        self.unacked: dict[str, dict] = {}
        self.device_id: str | None = None
        self.limits: dict = {}
        self.ws = None
        self.ready = False  # True between this connection's welcome and its end
        self.loop: asyncio.AbstractEventLoop | None = None
        self.live_task: asyncio.Task | None = None
        self.live_params = {"on": False}
        self.cloud_waiters: dict[str, asyncio.Future] = {}
        self.cloud_times: dict[str, list[float]] = {k: [] for k in CLOUD_KINDS}
        self.stopped = asyncio.Event()
        self.stop_reason: str | None = None
        self._last_status_error = None

    # ---- local side ----
    @property
    def models_capable(self) -> bool:
        return bool(getattr(self.device, "models_capable", False))

    def capabilities(self) -> list[str]:
        caps = ["video", "audio", "ai", "live", "reminder_config"]
        if self.models_capable:
            caps += ["model_config", "model_test"]
        return caps

    async def poll_once(self):
        try:
            st = await asyncio.to_thread(self.device.status)
        except Exception as e:
            if self._last_status_error != type(e).__name__:
                log.warning("room-companion status not available (%s)", type(e).__name__)
                self._last_status_error = type(e).__name__
            return
        self._last_status_error = None
        new = map_state(st)
        if new != self.state:
            self.state = new
            self.state_changed.set()
        local_events = st.get("events") if isinstance(st.get("events"), list) else []
        if self.events.baselined and self.device_id is None:
            return  # event ids include the device id; wait for the first welcome
        for ev in self.events.new_events(local_events, self.device_id):
            self.unacked[ev["id"]] = ev
            while len(self.unacked) > 200:
                self.unacked.pop(next(iter(self.unacked)))
            if self.ready:
                await self._send_json(ev)

    async def poll_forever(self):
        while not self.stopped.is_set():
            await self.poll_once()
            try:
                await asyncio.wait_for(self.stopped.wait(), self.cfg.get("poll_seconds", 1.0))
            except asyncio.TimeoutError:
                pass

    # ---- connection ----
    async def _send_json(self, obj: dict):
        ws = self.ws
        if ws is None:
            return
        try:
            await ws.send(json.dumps(obj, ensure_ascii=False))
        except Exception:
            pass

    def _open(self, token: str):
        if self._connect is not None:
            return self._connect(self.ws_url, token)
        from websockets.asyncio.client import connect
        return connect(self.ws_url, additional_headers={"Authorization": "Bearer " + token},
                       max_size=2 ** 20, open_timeout=20, ping_interval=30, ping_timeout=30)

    async def run_forever(self) -> str | None:
        """Keep a connection up until a permanent refusal or stop(); returns why it stopped for good."""
        self.loop = asyncio.get_running_loop()
        if hasattr(self.device, "set_cloud"):
            self.device.set_cloud(self.cloud_threadsafe)
        poller = asyncio.create_task(self.poll_forever())
        backoff = 1.0
        try:
            while not self.stopped.is_set():
                token = read_secret(self.cfg["token_file"])
                if not token:
                    self.stop_reason = "no device token; run the pair command first"
                    log.error(self.stop_reason)
                    break
                started = self.clock()
                code = await self.session(token)
                if code in PERMANENT_CLOSE:
                    self.stop_reason = f"{code}: {PERMANENT_CLOSE[code]}"
                    log.error("HipiMind closed the connection for good (%s)", self.stop_reason)
                    break
                if self.stopped.is_set():
                    break
                if self.clock() - started >= 60:
                    backoff = 1.0
                delay = backoff * random.uniform(0.8, 1.2)
                log.info("reconnecting in %.1f s (last close %s)", delay, code)
                try:
                    await asyncio.wait_for(self.stopped.wait(), delay)
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, 60.0)
        finally:
            self.stopped.set()
            poller.cancel()
            await self._stop_live()
            if hasattr(self.device, "set_cloud"):
                self.device.set_cloud(None)
        return self.stop_reason

    def stop(self):
        """Stop from the bridge's own loop (tests) or from any other thread."""
        loop = self.loop
        if loop is not None and loop.is_running():
            try:
                if asyncio.get_running_loop() is loop:
                    self.stopped.set()
                    return
            except RuntimeError:
                pass
            loop.call_soon_threadsafe(self.stopped.set)
        else:
            self.stopped.set()

    async def session(self, token: str) -> int | None:
        try:
            ws = await self._open(token)
        except Exception as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (401, 403):
                return 4401 if status == 401 else 4403
            log.warning("could not connect to HipiMind (%s)", type(e).__name__)
            return None
        self.ws, self.ready = ws, False
        sender = watcher = None
        try:
            if self.state is None:
                await self.poll_once()
            await ws.send(json.dumps({"type": "hello", "v": PROTOCOL_VERSION,
                                      "device": {"software": SOFTWARE,
                                                 "platform": self.cfg.get("platform") or default_platform(),
                                                 "capabilities": self.capabilities()},
                                      "state": self.state or {"switches": {k: False for k in KEYS}}},
                                     ensure_ascii=False))
            watcher = asyncio.create_task(self._close_when_stopped(ws))
            first = json.loads(await asyncio.wait_for(ws.recv(), 20))
            if not isinstance(first, dict) or first.get("type") != "welcome":
                log.warning("HipiMind did not welcome the device (%s)",
                            str(first.get("code") if isinstance(first, dict) else "")[:60])
                await ws.close()
            else:
                await self.handle(first)
            sender = asyncio.create_task(self._state_sender())
            async for raw in ws:
                if isinstance(raw, (bytes, bytearray)):
                    continue
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(msg, dict):
                    await self.handle(msg)
        except Exception as e:
            if not hasattr(e, "rcvd") and not hasattr(e, "code"):
                log.warning("connection error (%s)", type(e).__name__)
        finally:
            for task in (sender, watcher):
                if task is not None:
                    task.cancel()
            self.ws, self.ready = None, False
            await self._stop_live()
            for fut in self.cloud_waiters.values():
                if not fut.done():
                    fut.set_result({"ok": False, "error": {"code": "unavailable", "message": "disconnected"}})
            self.cloud_waiters.clear()
        code = getattr(ws, "close_code", None)
        if code is None:
            code = getattr(getattr(ws, "close_rcvd", None), "code", None)
        return code

    async def _close_when_stopped(self, ws):
        await self.stopped.wait()
        await ws.close(1001, "device stopping")

    async def _state_sender(self):
        sent = None
        while True:
            await self.state_changed.wait()
            self.state_changed.clear()
            if self.state is not None and self.state != sent:
                sent = self.state
                await self._send_json({"type": "state", "state": self.state})
            await asyncio.sleep(1.0)

    # ---- messages ----
    async def handle(self, msg: dict):
        t = msg.get("type")
        if t == "welcome":
            self.device_id = msg.get("device_id")
            self.limits = msg.get("limits") if isinstance(msg.get("limits"), dict) else {}
            self.ready = True
            log.info("connected to HipiMind as device %s", self.device_id)
            self.state_changed.set()
            for ev in list(self.unacked.values()):
                await self._send_json(ev)
        elif t == "ping":
            await self._send_json({"type": "pong", "t": msg.get("t")})
        elif t == "event_ack":
            self.unacked.pop(msg.get("id"), None)
        elif t == "set":
            await self.on_set(msg)
        elif t == "config":
            await self.on_config(msg)
        elif t == "test_model":
            await self.on_test_model(msg)
        elif t == "live":
            await self.on_live(msg)
        elif isinstance(t, str) and t.endswith("_result") and t[:-7] in CLOUD_KINDS:
            fut = self.cloud_waiters.pop(msg.get("req"), None)
            if fut is not None and not fut.done():
                fut.set_result(msg)
        elif t == "error":
            log.warning("HipiMind reported an error: %s", str(msg.get("code"))[:60])

    async def _ack(self, req, ok: bool, error: dict | None = None, **extra):
        await self.poll_once()
        body = {"type": "ack", "req": req, "ok": ok}
        if ok:
            body["state"] = self.state
        else:
            body["error"] = error
        body.update(extra)
        await self._send_json(body)

    async def on_set(self, msg: dict):
        sw = msg.get("switches") if isinstance(msg.get("switches"), dict) else {}
        changes = {k: v for k, v in sw.items() if k in KEYS and isinstance(v, bool)}
        if not changes:
            return await self._ack(msg.get("req"), False, {"code": "bad_request", "message": "no switch to change"})
        source = f"HipiMind ({str(msg.get('source') or 'web')[:20]})"
        try:
            code, body = await asyncio.to_thread(self.device.switch, changes, source)
        except Exception as e:
            return await self._ack(msg.get("req"), False, {"code": "local_unreachable", "message": type(e).__name__})
        if code != 200:
            return await self._ack(msg.get("req"), False,
                                   {"code": "local_error", "message": str(body.get("message") or code)[:200]})
        await self._ack(msg.get("req"), True)

    async def on_config(self, msg: dict):
        cfg = msg.get("config") if isinstance(msg.get("config"), dict) else {}
        ignored = []
        rem = cfg.get("reminders") if isinstance(cfg.get("reminders"), dict) else {}
        level = rem.get("level")
        if level is not None:
            if level not in MODE_COMMAND:
                return await self._ack(msg.get("req"), False, {"code": "bad_request", "message": "unknown level"})
            current = ((self.state or {}).get("reminders") or {}).get("level")
            if level != current:
                code, body = await asyncio.to_thread(self.device.command, MODE_COMMAND[level], "HipiMind")
                if code != 200:
                    return await self._ack(msg.get("req"), False,
                                           {"code": "local_error", "message": str(body.get("message") or code)[:200]})
        if "quiet_hours" in rem:
            if hasattr(self.device, "set_quiet_hours"):
                try:
                    await asyncio.to_thread(self.device.set_quiet_hours, rem["quiet_hours"])
                except (ValueError, TypeError, AttributeError):
                    return await self._ack(msg.get("req"), False,
                                           {"code": "bad_request", "message": "quiet hours must be HH:MM"})
            else:
                ignored.append("reminders.quiet_hours")
        models = cfg.get("models") if isinstance(cfg.get("models"), dict) else None
        keys = msg.get("model_keys") if isinstance(msg.get("model_keys"), dict) else None
        if models is not None or keys:
            if self.models_capable:
                changed = await asyncio.to_thread(self.device.apply_models, models or {}, keys)
                log.info("models changed for %s", ",".join(changed) or "nothing")
            else:
                ignored.append("models")
        await self._ack(msg.get("req"), True, ignored=ignored)

    async def on_test_model(self, msg: dict):
        if not self.models_capable:
            return await self._ack(msg.get("req"), False, {"code": "unsupported",
                                                           "message": "this device cannot test models"})
        slot, model, key = msg.get("slot"), msg.get("model"), msg.get("key")
        if slot not in ("vision", "stt", "tts") or not isinstance(model, dict):
            return await self._ack(msg.get("req"), False, {"code": "bad_request", "message": "slot and model needed"})
        res = await asyncio.to_thread(self.device.test_model, slot, model, key if isinstance(key, str) else None)
        if res.get("ok"):
            await self._send_json({"type": "ack", "req": msg.get("req"), "ok": True, "result": res.get("result")})
        else:
            await self._send_json({"type": "ack", "req": msg.get("req"), "ok": False, "error": res.get("error")})

    async def on_live(self, msg: dict):
        await self._stop_live()
        if msg.get("on") is True:
            conf = self.cfg.get("live") or {}
            fps = min(float(msg.get("fps") or 1), float(conf.get("max_fps", 2)),
                      float(self.limits.get("live_max_fps", 5)))
            width = int(min(int(msg.get("max_width") or 960), int(conf.get("max_width", 960))))
            self.live_params = {"on": True, "fps": max(0.1, fps), "width": width,
                                "quality": int(conf.get("jpeg_quality", 70)),
                                "max_bytes": int(self.limits.get("frame_max_bytes", 300_000))}
            self.live_task = asyncio.create_task(self._live_loop())
        await self._ack(msg.get("req"), True)

    async def _stop_live(self):
        self.live_params = {"on": False}
        task, self.live_task = self.live_task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    async def _live_loop(self):
        p = self.live_params
        interval = 1.0 / p["fps"]
        while True:
            t0 = time.monotonic()
            try:
                jpeg = await asyncio.to_thread(self.device.snapshot)
            except Exception:
                jpeg = None
            if jpeg:
                frame = await asyncio.to_thread(fit_frame, jpeg, p["width"], p["quality"], p["max_bytes"])
                if frame and self.ws is not None:
                    try:
                        await self.ws.send(frame)
                    except Exception:
                        return
            await asyncio.sleep(max(0.0, interval - (time.monotonic() - t0)))

    # ---- HipiMind cloud models (for slots set to "cloud") ----
    async def cloud(self, kind: str, payload: dict, timeout: float = 60) -> dict:
        if kind not in CLOUD_KINDS:
            return {"ok": False, "error": {"code": "bad_request", "message": "unknown cloud request"}}
        if self.ws is None or not self.ready:
            return {"ok": False, "error": {"code": "unavailable", "message": "not connected to HipiMind"}}
        now = time.monotonic()
        times = self.cloud_times[kind] = [t for t in self.cloud_times[kind] if now - t < 60]
        if len(times) >= int(self.limits.get("infer_per_minute", 6)):
            return {"ok": False, "error": {"code": "rate_limited", "message": "too many cloud requests this minute"}}
        times.append(now)
        req = "r-" + uuid.uuid4().hex[:12]
        fut = asyncio.get_running_loop().create_future()
        self.cloud_waiters[req] = fut
        body = {k: v for k, v in (payload or {}).items() if v is not None}
        await self._send_json({"type": kind, "req": req, **body})
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            self.cloud_waiters.pop(req, None)
            return {"ok": False, "error": {"code": "unavailable", "message": "no answer in time"}}

    def cloud_threadsafe(self, kind: str, payload: dict) -> dict:
        """For the models layer, which runs on the app's threads."""
        loop = self.loop
        if loop is None or not loop.is_running():
            return {"ok": False, "error": {"code": "unavailable", "message": "not connected to HipiMind"}}
        try:
            return asyncio.run_coroutine_threadsafe(self.cloud(kind, payload), loop).result(90)
        except Exception as e:
            return {"ok": False, "error": {"code": "unavailable", "message": type(e).__name__}}


class InProcess:
    """The connector running inside room-companion, on its own thread and event loop."""

    def __init__(self, app, hcfg: dict):
        self.bridge = Bridge(load_config_dict(dict(hcfg)), device=AppDevice(app))
        self.thread = threading.Thread(target=self._run, name="hipimind", daemon=True)
        self.reason = None

    def _run(self):
        try:
            self.reason = asyncio.run(self.bridge.run_forever())
        except Exception as e:  # the connector must never take the room companion down
            log.error("HipiMind connector stopped (%s)", type(e).__name__)

    def start(self):
        self.thread.start()
        return self

    def stop(self, timeout=5):
        self.bridge.stop()
        self.thread.join(timeout)


def start_in_process(app, hcfg: dict) -> InProcess:
    return InProcess(app, hcfg).start()


# ---------------------------------------------------------------- CLI

def pair_from_app_config(argv, app_cfg: dict) -> int:
    """`python -m room_companion pair`: server and token file come from the app config's "hipimind" section."""
    ap = argparse.ArgumentParser(prog="room-companion pair")
    ap.add_argument("--code", required=True)
    ap.add_argument("--name", default="Room")
    args = ap.parse_args(argv)
    h = load_config_dict(dict(app_cfg.get("hipimind") or {}))
    try:
        res = pair(h["server"], args.code, args.name, h["token_file"], h.get("platform"))
    except PairError as e:
        print(f"pairing failed: {e.code}: {e.message}", file=sys.stderr)
        return 2
    print(f"paired: device {res['device_id']}; token saved to {res['token_file']} (readable only by you)")
    if not app_cfg.get("hipimind"):
        print('add a "hipimind" section to the config so the app connects (see docs/hipimind.md)', file=sys.stderr)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="room-companion-hipimind", description="Connect room-companion to HipiMind Room")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pair", help="exchange a pairing code from the HipiMind page for a device token")
    p.add_argument("--server", default=DEFAULTS["server"])
    p.add_argument("--code", required=True)
    p.add_argument("--name", default="Room")
    p.add_argument("--token-file", default=DEFAULTS["token_file"])
    p.add_argument("--config", help="read server and token_file from this config file")
    r = sub.add_parser("run", help="keep the device connected (sidecar, through the local HTTP API)")
    r.add_argument("--config", required=True)
    r.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if getattr(args, "verbose", False) else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    if args.cmd == "pair":
        server, token_file = args.server, args.token_file
        if args.config:
            cfg = load_config(args.config)
            server, token_file = cfg["server"], cfg["token_file"]
        try:
            res = pair(server, args.code, args.name, token_file)
        except PairError as e:
            print(f"pairing failed: {e.code}: {e.message}", file=sys.stderr)
            return 2
        print(f"paired: device {res['device_id']}; token saved to {res['token_file']} (readable only by you)")
        return 0
    cfg = load_config(args.config)
    bridge = Bridge(cfg)
    reason = asyncio.run(bridge.run_forever())
    if reason:
        print(f"stopped: {reason}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
