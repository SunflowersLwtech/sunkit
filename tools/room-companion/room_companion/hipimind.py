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
Never sent: transcripts, audio, the local event log as such, process ids, device or speaker
names, client addresses, capture error output, logs. The summary is written here from the
switch/capture/model facts, never copied from the local status text. The device token and any
model key are never logged.

    python -m room_companion pair --code K7QM-2WXH --name Bedroom      # in-process: uses the app's config
    python -m room_companion.hipimind pair --server https://api.hipimind.com --code K7QM-2WXH --name Bedroom
    python -m room_companion.hipimind run --config ~/.config/room-companion/hipimind.json   # sidecar
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import ipaddress
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

from .models import clean_base_url

log = logging.getLogger("room_companion.hipimind")
# The websockets library logs the handshake headers at DEBUG, the device token among them: the connection
# gets its own logger, held at INFO whatever level the host application (or -v) sets.
_WS_LOG = logging.getLogger("room_companion.hipimind.websocket")
_WS_LOG.setLevel(logging.INFO)

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
LANGUAGES = ("zh", "en")
# Event text in the owner's language (config.language); the page renders switch events from `data` and
# falls back to this text.
SCENE_LABELS = {
    "zh": {"laundry": "洗衣服", "cooking": "做饭", "coding": "写代码", "router": "配置路由器", "yoga": "瑜伽",
           "sofa_phone": "沙发上玩手机", "sleeping": "睡觉", "other": "其他", "empty": "没人"},
    "en": {"laundry": "Laundry", "cooking": "Cooking", "coding": "Coding", "router": "Router setup", "yoga": "Yoga",
           "sofa_phone": "Phone on the sofa", "sleeping": "Sleeping", "other": "Something else", "empty": "Nobody"},
}
CATEGORY_LABELS = {
    "zh": {"久坐": "久坐提醒", "路由器": "改路由器前备份", "手机": "沙发上看手机", "晾衣服": "晾衣服",
           "厨房": "做完饭关火通风", "运动后": "运动后补水拉伸", "summary": "早报"},
    "en": {"久坐": "Time to move", "路由器": "Back up the router first", "手机": "A break from the phone",
           "晾衣服": "Hang up the laundry", "厨房": "Stove off, air the kitchen", "运动后": "Water and a stretch",
           "summary": "Morning summary"},
}
SWITCH_NAMES = {"zh": {"video": "视频", "audio": "声音", "ai": "AI"}, "en": {"video": "Video", "audio": "Sound", "ai": "AI"}}
SOURCE_NAMES = {"zh": {"web": "网页", "local": "本机网页", "voice": "语音", "feishu": "飞书", "device": "设备"},
                "en": {"web": "website", "local": "local page", "voice": "voice", "feishu": "Feishu", "device": "device"}}
# Spec defaults (HipiMind docs §2) for when a server sends no limits.
DEFAULT_FRAME_MAX_BYTES = 150_000
DEFAULT_LIVE_MAX_FPS = 3
DEFAULT_MESSAGE_MAX_BYTES = 65_536
#: "Test connection" runs at most this many times a minute: each one makes this device call an address
#: the page chose, so a stolen session must not be able to sweep the local network with it.
TESTS_PER_MINUTE = 10
#: An output that has no short name (a configured label, or the built-in one for the PC's own speakers) is
#: reported as this word: output names are hardware names, and often carry the owner's name.
GENERIC_OUTPUT = {"zh": "音箱", "en": "speaker"}
ANNOUNCE_ERROR_CODES = ("no_output", "ai_off", "tts_failed", "playback_failed", "no_result")
ANNOUNCE_REFUSALS = {
    "empty": "nothing to read out",
    "too_long": "more than 300 characters",
    "rate_limited": "more than 6 a minute or 200 a day",
    "busy": "earlier sentences are still waiting",
    "no_output": "nothing that can make a sound",
    "ai_off": "the voice is a remote model and AI is off",
}


def announce_error_code(error) -> str | None:
    """The fixed code HipiMind gets for a failed announcement; the local text (paths, PowerShell output,
    host names) stays on the device."""
    if not error:
        return None
    text = str(error)
    if text in ANNOUNCE_ERROR_CODES:  # the speaker already reports a code
        return text
    if "没有能出声" in text or "no output" in text.lower():
        return "no_output"
    if "AI is off" in text:
        return "ai_off"
    if "no result" in text:
        return "no_result"
    # The player's own failures say so ("playback failed: …"), and writing the sound file fails with an
    # OSError; anything else came from making the voice (a remote voice server, a missing voice model).
    if text.startswith("playback failed") or "[Errno" in text:
        return "playback_failed"
    return "tts_failed"


NOTICE_TEXT = {
    "en": {"camera_missing_reminder": "Video is on but the camera has been missing for a few minutes",
           "gpu_too_hot": "The local model is paused for 30 minutes to cool down"},
    "zh": {"camera_missing_reminder": "视频开着，但相机已经几分钟没接上了",
           "gpu_too_hot": "本地模型太热，暂停 30 分钟降温"},
}

DEFAULTS = {
    "server": "https://api.hipimind.com",
    "ws_url": None,
    "token_file": "~/.config/room-companion/hipimind.token",
    "local_api": "http://127.0.0.1:8790",
    "local_api_key_file": None,
    "poll_seconds": 1.0,
    "platform": None,
    "live": {"max_fps": 2, "max_width": 960, "jpeg_quality": 70},
    "events": {"reminders": True, "switches": True, "scene": True, "notices": True, "announce": True},
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


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def plain_text_refused(url: str) -> str | None:
    """Why the device token must not be sent to this URL, or None. The token goes only over TLS
    (https://, wss://); plain http:// or ws:// is allowed to this machine itself (tests, a local tunnel)."""
    try:
        u = urllib.parse.urlsplit(str(url))
        host = u.hostname
    except ValueError:
        return "the HipiMind address is not a valid URL"
    if u.scheme in ("https", "wss") and host:
        return None
    if u.scheme in ("http", "ws") and _is_loopback(host):
        return None
    return (f"{u.scheme or '(no scheme)'}://{host or ''} would carry the device token without encryption; "
            f"use an https:// (wss://) address")


def token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


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
    why = plain_text_refused(server)
    if why:
        raise PairError(0, "insecure", why)
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
    account = data.get("account") if isinstance(data.get("account"), str) else None
    return {"device_id": data.get("device_id"), "ws_url": data.get("ws_url"), "account": account,
            "token_file": os.path.expanduser(token_file)}


def paired_message(res: dict) -> str:
    """What `pair` prints: which account the camera joined (so a person can see they paired to their own)."""
    who = f"Paired to {res['account']}" if res.get("account") else "Paired"
    return f"{who}: device {res['device_id']}; token saved to {res['token_file']} (readable only by you)"


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

    announce_capable = True

    def announce_labels(self) -> set[str]:
        from .speaker import DEFAULT_LABELS
        return {label for labels in DEFAULT_LABELS.values() for label in labels.values()}

    #: How long a sidecar follows one announcement before reporting it failed: as long as HipiMind waits,
    #: since the speaker queues up to ten sentences and 300 characters take about a minute and a half.
    ANNOUNCE_FOLLOW_SECONDS = 900.0

    def announce(self, text: str, source: str, req: str, on_done) -> dict:
        """Hand `text` to the room-companion to read out; on_done(result) once it was played or failed."""
        code, _, raw = self._req("POST", "/api/broadcast", {"text": text, "id": req, "source": source})
        try:
            res = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            res = {}
        if code == 404:
            return {"ok": False, "code": "no_output", "message": "this room-companion cannot read text out"}
        if not isinstance(res, dict) or "ok" not in res:
            return {"ok": False, "code": "busy", "message": f"local answer {code}"}
        if res.get("ok"):
            threading.Thread(target=self._follow_announcement, args=(str(res.get("id") or req), on_done),
                             name="announce-follow", daemon=True).start()
        return res

    def _follow_announcement(self, bid: str, on_done):
        deadline = time.monotonic() + self.ANNOUNCE_FOLLOW_SECONDS
        while time.monotonic() < deadline:
            time.sleep(1.0)
            try:
                code, _, raw = self._req("GET", "/api/broadcast/" + urllib.parse.quote(bid, safe=""))
                r = json.loads(raw.decode("utf-8") or "{}") if code == 200 else {}
            except Exception:
                continue
            if isinstance(r, dict) and r.get("state") in ("done", "failed"):
                on_done({"id": bid, **{k: r.get(k) for k in ("ok", "output", "seconds", "peak", "error")}})
                return
        on_done({"id": bid, "ok": False, "output": None, "seconds": None, "peak": None,
                 "error": "no result from the room-companion in time"})


class AppDevice:
    """The same calls as LocalAPI, straight into a running App (in-process connector), plus models."""

    models_capable = True

    def __init__(self, app):
        self.app = app

    def status(self) -> dict:
        try:
            st = self.app.status(evidence=False)  # no Windows helper processes every second
        except TypeError:
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
        # HipiMind waits 8 s for the ack: answer with what is true after at most 5 s of settling
        self.app.wait_settled(timeout=5.0)
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

    def reset_remote_models(self) -> list[str]:
        return self.app.reset_remote_models()

    def bind_token(self, fingerprint: str) -> list[str]:
        return self.app.bind_token(fingerprint)

    def unbind_token(self) -> list[str]:
        return self.app.unbind_token()

    @property
    def announce_capable(self) -> bool:
        return hasattr(self.app, "broadcast")

    def announce(self, text: str, source: str, req: str, on_done) -> dict:
        models = getattr(self.app, "models", None)
        if (models is not None and models.slot("tts")["source"] in ("openai", "cloud")
                and not self.app.switches.get("ai")):
            # a remote voice is a remote model: nothing goes to one while AI is off
            return {"ok": False, "code": "ai_off", "message": "the voice is a remote model and AI is off"}
        return self.app.broadcast(text, source, request_id=req, on_done=on_done)

    def announce_labels(self) -> set[str]:
        from .speaker import DEFAULT_LABELS
        sp = getattr(self.app, "speaker", None)
        cfg = getattr(sp, "cfg", {}) or {}
        own = cfg.get("output_labels") if isinstance(cfg.get("output_labels"), dict) else {}
        return {str(v) for v in own.values()} | {label for labels in DEFAULT_LABELS.values()
                                                  for label in labels.values()}

    def set_cloud(self, cloud) -> None:
        self.app.cloud = cloud

    @property
    def language(self):
        return getattr(self.app, "language", None)

    def set_language(self, lang: str) -> None:
        self.app.set_language(lang)

    # camera drivers (when the app has them): config.camera and camera_action
    @property
    def camera_capable(self) -> bool:
        return hasattr(self.app, "set_camera_config")

    def set_camera_config(self, cfg: dict):
        return self.app.set_camera_config(cfg)

    def camera_action(self, action: str):
        return self.app.camera_action(action)


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
                base = clean_base_url(m.get("base_url"))
                if base:
                    e["base_url"] = base[:200]  # never a user name or password, never a non-http address
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


def map_state(st: dict, lang: str = "en") -> dict:
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
    # Built here from the facts above, never copied from the local status text: that names hardware
    # (speaker and microphone names) and carries capture error output.
    out["summary"] = summarize(out, lang)
    return out


def summarize(state: dict, lang: str = "en") -> str:
    """One plain sentence from the allow-listed state: switches, capture and model readiness only."""
    sw = state.get("switches") or {}
    cap = state.get("capture") or {}
    vision = (state.get("models") or {}).get("vision") or {}
    ready = vision.get("state")
    if lang == "zh":
        words = {"running": "使用中", "off": "已释放", "starting": "启动中", "waiting_device": "没接设备", "error": "出错"}
        parts = []
        for key, name in (("video", "视频"), ("audio", "声音")):
            c = cap.get(key)
            parts.append(f"{name}{'开' if sw.get(key) else '关'}" + (f"（{words[c]}）" if c in words else ""))
        if not sw.get("ai"):
            parts.append("AI 关（不发给任何模型）")
        else:
            where = {"engine": "设备本地", "openai": "自选服务", "cloud": "HipiMind 云"}.get(vision.get("source"), "")
            states = {"ready": "就绪", "starting": "启动中", "off": "待命", "error": "出错"}
            parts.append("AI 开" + (f"（看图：{where}" + (f"，{states[ready]}" if ready in states else "") + "）"
                                    if where else ""))
        return "；".join(parts)[:300]
    words = {"running": "in use", "off": "released", "starting": "starting", "waiting_device": "no device",
             "error": "problem"}
    parts = []
    for key, name in (("video", "Video"), ("audio", "Sound")):
        c = cap.get(key)
        parts.append(f"{name} {'on' if sw.get(key) else 'off'}" + (f" ({words[c]})" if c in words else ""))
    if not sw.get("ai"):
        parts.append("AI off (nothing goes to any model)")
    else:
        where = {"engine": "on this device", "openai": "on your server", "cloud": "HipiMind cloud"}.get(
            vision.get("source"), "")
        parts.append("AI on" + (f", vision {where}" if where else "") + (f" ({ready})" if ready in MODEL_STATES else ""))
    return "; ".join(parts)[:300]


def _source_code(source) -> str:
    """Where a switch change came from, as a fixed code — "web" (the HipiMind website), "local" (the
    device's own page), "voice", "feishu" or "device" — never a client address or a host name."""
    s = str(source or "")
    low = s.lower()
    if low.startswith("hipimind"):
        return "web"
    if "网页" in s or "web" in low or "browser" in low:
        return "local"
    if "语音" in s or "voice" in low:
        return "voice"
    if "飞书" in s or "feishu" in low or "lark" in low:
        return "feishu"
    return "device"


def _switch_text(changes: dict, source, lang: str = "en") -> str:
    lang = lang if lang in LANGUAGES else "en"
    names, code = SWITCH_NAMES[lang], _source_code(source) if source else None
    if lang == "zh":
        text = "，".join(f"{'开' if v else '关'}{names[k]}" for k, v in changes.items() if k in names) or "开关没有变化"
        return text + (f"（{SOURCE_NAMES['zh'][code]}）" if code else "")
    text = ", ".join(f"{names[k]} {'on' if v else 'off'}" for k, v in changes.items() if k in names) or "Switches unchanged"
    return text + (f" ({SOURCE_NAMES['en'][code]})" if code else "")


class EventDiffer:
    """Turns new entries of the local event list into HipiMind events (only a few kinds)."""

    def __init__(self, enabled: dict | None = None, scene_min_minutes: float = 10, clock=time.time,
                 language=lambda: "zh"):
        self.enabled = dict(DEFAULTS["events"], **(enabled or {}))
        self.language = language  # callable: the language event text is written in
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
        lang = self.language()
        lang = lang if lang in LANGUAGES else "zh"
        at = _iso(e.get("ts")) or datetime.now().astimezone().isoformat(timespec="seconds")
        if kind == "reminder" and self.enabled.get("reminders"):
            cat = str(e.get("category") or "")
            text = CATEGORY_LABELS[lang].get(cat, cat or ("提醒" if lang == "zh" else "Reminder"))
            return {"type": "event", "kind": "reminder", "text": text[:1000], "at": at, "data": {"category": cat[:40]}}
        if kind == "summary" and self.enabled.get("reminders"):
            return {"type": "event", "kind": "reminder", "text": CATEGORY_LABELS[lang]["summary"], "at": at,
                    "data": {"category": "summary"}}
        if kind == "switch" and self.enabled.get("switches"):
            changes = e.get("changes") if isinstance(e.get("changes"), dict) else {}
            changes = {k: v is True for k, v in changes.items() if k in KEYS}
            return {"type": "event", "kind": "switch", "text": _switch_text(changes, e.get("source"), lang), "at": at,
                    "data": {"changes": changes, "source": _source_code(e.get("source"))}}
        if kind == "scene" and self.enabled.get("scene"):
            now = self.clock()
            if now - self.last_scene_sent < self.scene_gap:
                return None
            self.last_scene_sent = now
            scene = str(e.get("scene") or "")
            return {"type": "event", "kind": "scene", "text": SCENE_LABELS[lang].get(scene, scene)[:200], "at": at,
                    "data": {"label": scene[:40]}}
        if kind == "broadcast" and self.enabled.get("announce"):
            chars = e.get("chars") if isinstance(e.get("chars"), int) else 0
            text = f"播报了一句（{chars} 字）" if lang == "zh" else f"Announced a message ({chars} characters)"
            return {"type": "event", "kind": "announce", "text": text, "at": at,
                    "data": {"chars": chars, "source": _source_code(e.get("source"))}}
        if kind in NOTICE_TEXT["en"] and self.enabled.get("notices"):
            return {"type": "event", "kind": "notice", "text": NOTICE_TEXT[lang][kind], "at": at, "data": {}}
        return None


# ---------------------------------------------------------------- frames

def jpeg_size(data: bytes) -> tuple[int, int] | None:
    """(width, height) from a JPEG's frame header, without an image library; None if not found."""
    if not data.startswith(b"\xff\xd8"):
        return None
    i, n = 2, len(data)
    while i + 9 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        length = int.from_bytes(data[i + 2:i + 4], "big")
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
        i += 2 + length
    return None


def fit_frame(jpeg: bytes, max_width: int, quality: int, max_bytes: int) -> bytes | None:
    """Downscale to max_width (Pillow, if installed) and keep under max_bytes; None if it cannot fit.

    Without Pillow nothing can be scaled: a frame goes only if it is already within both limits.
    """
    try:
        from PIL import Image
    except ImportError:
        size = jpeg_size(jpeg)
        if size is None or size[0] > max_width or len(jpeg) > max_bytes:
            return None
        return jpeg
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
        # The language event text and the summary are written in: config.language from HipiMind once it
        # arrives, else the device's own (the app's "language", or this bridge's config), else Chinese.
        self.language: str | None = None
        self.events = EventDiffer(cfg.get("events"), cfg.get("scene_event_min_minutes", 10), clock,
                                  language=self.lang)
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
        # Commands run off the receive loop, so pings and cloud answers keep flowing while one works:
        # set/config/live/camera_action in order on one lane, Test connection on its own (at most 2).
        self.control_q: asyncio.Queue | None = None
        self.side_tasks: set[asyncio.Task] = set()
        self.test_slots: asyncio.Semaphore | None = None
        self.test_times: list[float] = []
        self._tests_refused = 0
        # The token of the last session, and the close code HipiMind announced in-band in this one
        # ({"type": "close", "code": …} before closing: on the way, every close frame may arrive as 1005).
        self._session_token: str | None = None
        self._closed_for_token: str | None = None
        self._inband_close: int | None = None

    def lang(self) -> str:
        if self.language in LANGUAGES:
            return self.language
        own = getattr(self.device, "language", None)
        if own in LANGUAGES:
            return own
        return self.cfg.get("language") if self.cfg.get("language") in LANGUAGES else "zh"

    # ---- local side ----
    @property
    def models_capable(self) -> bool:
        return bool(getattr(self.device, "models_capable", False))

    def capabilities(self) -> list[str]:
        caps = ["video", "audio", "ai", "live", "reminder_config"]
        if self.models_capable:
            caps += ["model_config", "model_test"]
        if getattr(self.device, "camera_capable", False):
            caps += ["camera_config", "camera_action"]
        if getattr(self.device, "announce_capable", False):
            caps += ["announce"]
        return caps

    def _limit(self, name: str, default: int) -> int:
        try:
            v = int(self.limits.get(name))
            return v if v > 0 else default
        except (TypeError, ValueError):
            return default

    async def poll_once(self):
        try:
            st = await asyncio.to_thread(self.device.status)
        except Exception as e:
            if self._last_status_error != type(e).__name__:
                log.warning("room-companion status not available (%s)", type(e).__name__)
                self._last_status_error = type(e).__name__
            return
        self._last_status_error = None
        new = map_state(st, self.lang())
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
            await self._close_if_token_replaced()
            try:
                await asyncio.wait_for(self.stopped.wait(), self.cfg.get("poll_seconds", 1.0))
            except asyncio.TimeoutError:
                pass

    # ---- connection ----
    async def _send_json(self, obj: dict) -> bool:
        ws = self.ws
        if ws is None:
            return False
        raw = json.dumps(obj, ensure_ascii=False)
        cap = (self._limit("cloud_message_max_bytes", self._limit("message_max_bytes", DEFAULT_MESSAGE_MAX_BYTES))
               if obj.get("type") in CLOUD_KINDS else self._limit("message_max_bytes", DEFAULT_MESSAGE_MAX_BYTES))
        if len(raw) > cap:  # the server would close the socket (4413); refuse here instead
            log.warning("not sending a %s message of %d characters (limit %d)", obj.get("type"), len(raw), cap)
            return False
        try:
            await ws.send(raw)
            return True
        except Exception:
            return False

    def _open(self, token: str):
        if self._connect is not None:
            return self._connect(self.ws_url, token)
        from websockets.asyncio.client import connect
        return connect(self.ws_url, additional_headers={"Authorization": "Bearer " + token},
                       max_size=2 ** 20, open_timeout=20, ping_interval=30, ping_timeout=30, logger=_WS_LOG)

    async def _pause(self, seconds: float):
        """The wait before reconnecting; stop() ends it early."""
        try:
            await asyncio.wait_for(self.stopped.wait(), seconds)
        except asyncio.TimeoutError:
            pass

    async def _forget_account(self, why: str, reset_models: bool = True):
        """The account this device was connected to refused it, or another token takes over: nothing of
        the old account goes to the next one — not its unsent events, not the device id their ids are
        made from, and (reset_models) not the remote models and keys its page chose."""
        log.warning("%s: unsent events, the device id and models chosen on the page are dropped", why)
        self.unacked.clear()
        self.device_id = None
        self.limits = {}
        self.events.seen.clear()
        self.events.baselined = False  # what is in the local list now is history for the next account
        if reset_models and hasattr(self.device, "reset_remote_models"):
            await asyncio.to_thread(self.device.reset_remote_models)

    async def _close_if_token_replaced(self):
        """`pair` wrote a new token while connected with the old one: end this session, so the next one
        uses the new token (and leaves the old account behind)."""
        ws, current = self.ws, self._session_token
        if ws is None or current is None:
            return
        token = read_secret(self.cfg["token_file"])
        if token and token != current and token != self._closed_for_token:
            log.info("the device token was replaced; reconnecting with the new one")
            self._closed_for_token = token
            try:
                await ws.close(1000, "device token replaced")
            except Exception:
                pass

    async def run_forever(self) -> str | None:
        """Keep a connection up until a permanent refusal or stop(); returns why it stopped for good."""
        why = plain_text_refused(self.ws_url)
        if why:
            self.stop_reason = why
            log.error("not connecting to HipiMind: %s", why)
            self.stopped.set()
            return self.stop_reason
        self.loop = asyncio.get_running_loop()
        if hasattr(self.device, "set_cloud"):
            self.device.set_cloud(self.cloud_threadsafe)
        poller = asyncio.create_task(self.poll_forever())
        backoff = 1.0
        try:
            refused = None  # a token HipiMind refused (4401); waiting for `pair` to write a new one
            waiting_logged = False
            while not self.stopped.is_set():
                token = read_secret(self.cfg["token_file"])
                if not token or token == refused:
                    if not self.cfg.get("wait_for_token"):
                        self.stop_reason = "no device token; run the pair command first"
                        log.error(self.stop_reason)
                        break
                    if not waiting_logged:
                        log.warning("waiting for a device token (run the pair command; no restart needed)")
                        waiting_logged = True
                        if not token and hasattr(self.device, "unbind_token"):
                            # the token file is gone: the page's choices lost their account
                            await asyncio.to_thread(self.device.unbind_token)
                    try:
                        await asyncio.wait_for(self.stopped.wait(), self.cfg.get("token_poll_seconds", 30))
                    except asyncio.TimeoutError:
                        pass
                    continue
                waiting_logged = False
                if self._session_token is not None and token != self._session_token:
                    await self._forget_account("the device token changed", reset_models=False)
                self._session_token = token
                if hasattr(self.device, "bind_token"):
                    # models chosen under another token (also before a restart) are dropped here
                    await asyncio.to_thread(self.device.bind_token, token_fingerprint(token))
                started = self.clock()
                code = await self.session(token)
                if code == 4401:
                    await self._forget_account("HipiMind refused the device token")
                if code == 4401 and self.cfg.get("wait_for_token"):
                    refused = token
                    log.error("HipiMind refused the device token (%s)", PERMANENT_CLOSE[4401])
                    continue
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
                await self._pause(delay)
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
        self._inband_close = None
        sender = watcher = None
        self.control_q = asyncio.Queue()
        self.test_slots = asyncio.Semaphore(2)
        worker = asyncio.create_task(self._control_worker(self.control_q))
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
            if isinstance(first, dict) and first.get("type") == "close":
                await self.handle(first)  # refused right after hello (an unknown token, say)
                await ws.close()
            elif not isinstance(first, dict) or first.get("type") != "welcome":
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
                    try:
                        await self.handle(msg)
                    except Exception as e:  # one odd message never ends the connection
                        log.warning("ignored a %s message (%s)", str(msg.get("type"))[:30], type(e).__name__)
        except Exception as e:
            if not hasattr(e, "rcvd") and not hasattr(e, "code"):
                log.warning("connection error (%s)", type(e).__name__)
        finally:
            for task in (sender, watcher, worker, *self.side_tasks):
                if task is not None:
                    task.cancel()
            self.side_tasks.clear()
            try:  # a session that ended on an error must not leave the socket open behind it
                await asyncio.wait_for(ws.close(), 5)
            except Exception:
                pass
            self.ws, self.ready = None, False
            await self._stop_live()
            for fut in self.cloud_waiters.values():
                if not fut.done():
                    fut.set_result({"ok": False, "error": {"code": "unavailable", "message": "disconnected"}})
            self.cloud_waiters.clear()
        if self._inband_close is not None:
            return self._inband_close
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
        """Called from the receive loop: anything that can take time is handed to a lane, so this
        returns at once and pings and cloud answers are never stuck behind a command.

        Ids from the server (`req`, an event's `id`) are strings; a message with another kind of id is
        ignored, never allowed to end the connection."""
        t = msg.get("type")
        if msg.get("req") is not None and not isinstance(msg.get("req"), str):
            log.debug("ignored a %s message with a malformed req", str(t)[:30])
            return
        if t == "welcome":
            self.device_id = msg.get("device_id") if isinstance(msg.get("device_id"), str) else None
            self.limits = msg.get("limits") if isinstance(msg.get("limits"), dict) else {}
            self.ready = True
            log.info("connected to HipiMind as device %s", self.device_id)
            self.state_changed.set()
            for ev in list(self.unacked.values()):
                await self._send_json(ev)
            if isinstance(msg.get("config"), dict) and self.control_q is not None:
                # what the owner changed while this device was offline
                self.control_q.put_nowait({"type": "_welcome_config", "config": msg["config"]})
        elif t == "ping":
            await self._send_json({"type": "pong", "t": msg.get("t")})
        elif t == "event_ack":
            if isinstance(msg.get("id"), str):
                self.unacked.pop(msg["id"], None)
        elif t == "close":
            code = msg.get("code")
            if isinstance(code, int) and not isinstance(code, bool) and 1000 <= code <= 4999:
                self._inband_close = code
                log.info("HipiMind is closing the connection (%s: %s)", code, str(msg.get("reason") or "")[:120])
        elif t in ("set", "config", "live", "camera_action"):
            if self.control_q is not None:
                self.control_q.put_nowait(msg)
            else:
                await self._run_command(msg)
        elif t == "test_model":
            now = time.monotonic()
            self.test_times = [x for x in self.test_times if now - x < 60]
            if len(self.test_times) >= TESTS_PER_MINUTE:
                if not self._tests_refused:
                    log.warning("Test connection refused: more than %d this minute", TESTS_PER_MINUTE)
                self._tests_refused += 1
                await self._send_json({"type": "ack", "req": msg.get("req"), "ok": False, "error": {
                    "code": "rate_limited",
                    "message": f"at most {TESTS_PER_MINUTE} connection tests a minute; try again in a minute"}})
                return
            self._tests_refused = 0
            self.test_times.append(now)
            task = asyncio.create_task(self._run_test(msg))
            self.side_tasks.add(task)
            task.add_done_callback(self.side_tasks.discard)
        elif t == "announce":
            task = asyncio.create_task(self._run_announce(msg))
            self.side_tasks.add(task)
            task.add_done_callback(self.side_tasks.discard)
        elif isinstance(t, str) and t.endswith("_result") and t[:-7] in CLOUD_KINDS:
            fut = self.cloud_waiters.pop(msg.get("req"), None)
            if fut is not None and not fut.done():
                fut.set_result(msg)
        elif t == "error":
            log.warning("HipiMind reported an error: %s", str(msg.get("code"))[:60])

    async def _control_worker(self, q: asyncio.Queue):
        while True:
            msg = await q.get()
            await self._run_command(msg)

    async def _run_command(self, msg: dict):
        """One command; any failure is answered with ack ok:false, never by dropping the connection."""
        t = msg.get("type")
        try:
            if t == "set":
                await self.on_set(msg)
            elif t == "config":
                await self.on_config(msg)
            elif t == "live":
                await self.on_live(msg)
            elif t == "camera_action":
                await self.on_camera_action(msg)
            elif t == "_welcome_config":
                ok, err, ignored = await self._apply_config(msg["config"], None, from_welcome=True)
                if not ok:
                    log.warning("could not apply the saved settings from HipiMind (%s)", (err or {}).get("code"))
        except Exception as e:
            log.warning("a %s command failed (%s)", t, type(e).__name__)
            if t != "_welcome_config":
                await self._send_json({"type": "ack", "req": msg.get("req"), "ok": False,
                                       "error": {"code": "bad_request", "message": f"could not apply ({type(e).__name__})"}})

    async def _run_announce(self, msg: dict):
        """Read the owner's typed text out in the room: ack at once (taken, or why not), then an
        announce_result once it has been played or has failed. The text itself is never logged."""
        req = msg.get("req")
        text = msg.get("text")

        async def refuse(code: str, message: str):
            await self._send_json({"type": "ack", "req": req, "ok": False, "error": {"code": code, "message": message}})

        if not getattr(self.device, "announce_capable", False):
            return await refuse("no_output", "this device cannot read text out")
        if not isinstance(text, str) or not text.strip():
            return await refuse("empty", "nothing to read out")
        loop = asyncio.get_running_loop()

        safe = getattr(self.device, "announce_labels", lambda: set())()
        lang = self.lang()

        def on_done(r: dict):  # from the speaker's thread
            output = r.get("output")
            if output:  # a short name the owner gave, or a plain word: never the hardware name
                output = output if output in safe else GENERIC_OUTPUT[lang]
            body = {"type": "announce_result", "req": req, "ok": bool(r.get("ok")),
                    "output": str(output)[:80] if output else None,
                    "seconds": r.get("seconds") if isinstance(r.get("seconds"), (int, float)) else None,
                    "peak": r.get("peak") if isinstance(r.get("peak"), (int, float)) else None,
                    "error": None if r.get("ok") else (announce_error_code(r.get("error")) or "playback_failed")}
            asyncio.run_coroutine_threadsafe(self._send_json(body), loop)

        source = f"HipiMind ({str(msg.get('source') or 'web')[:20]})"
        try:
            res = await asyncio.to_thread(self.device.announce, text, source, req, on_done)
        except Exception as e:
            log.warning("an announcement could not be handed over (%s)", type(e).__name__)
            return await refuse("busy", f"could not start ({type(e).__name__})")
        if not isinstance(res, dict) or not res.get("ok"):
            res = res if isinstance(res, dict) else {}
            code = str(res.get("code") or "busy")[:20]
            # The local message can name the output; HipiMind gets the code and a sentence built from it.
            return await refuse(code, ANNOUNCE_REFUSALS.get(code, ANNOUNCE_REFUSALS["busy"]))
        await self._send_json({"type": "ack", "req": req, "ok": True,
                               "result": {"id": str(res.get("id") or req)[:64]}})

    async def _run_test(self, msg: dict):
        try:
            async with self.test_slots:
                await self.on_test_model(msg)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            await self._send_json({"type": "ack", "req": msg.get("req"), "ok": False,
                                   "error": {"code": "bad_response", "message": type(e).__name__}})

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
        keys = msg.get("model_keys") if isinstance(msg.get("model_keys"), dict) else None
        ok, err, ignored = await self._apply_config(cfg, keys)
        if ok:
            await self._ack(msg.get("req"), True, ignored=ignored)
        else:
            await self._ack(msg.get("req"), False, err)

    async def _apply_config(self, cfg: dict, keys: dict | None, from_welcome: bool = False):
        """Apply a Config (from a `config` command, or the one in `welcome`). Returns (ok, error, ignored).

        From `welcome`, a missing or null part means "not set on the page" and leaves the device's own
        setting alone: the welcome can set quiet hours, never clear the ones in the device's config.
        """
        ignored = []
        lang = cfg.get("language")
        if lang is not None:
            if lang not in LANGUAGES:
                return False, {"code": "bad_request", "message": "language must be zh or en"}, ignored
            self.language = lang
            if hasattr(self.device, "set_language"):
                await asyncio.to_thread(self.device.set_language, lang)
        rem = dict(cfg.get("reminders")) if isinstance(cfg.get("reminders"), dict) else {}
        if from_welcome and rem.get("quiet_hours") is None:
            rem.pop("quiet_hours", None)
        level = rem.get("level")
        if level is not None:
            if not isinstance(level, str) or level not in MODE_COMMAND:
                return False, {"code": "bad_request", "message": "unknown level"}, ignored
            current = ((self.state or {}).get("reminders") or {}).get("level")
            if level != current:
                code, body = await asyncio.to_thread(self.device.command, MODE_COMMAND[level], "HipiMind")
                if code != 200:
                    return False, {"code": "local_error", "message": str(body.get("message") or code)[:200]}, ignored
        if "quiet_hours" in rem:
            if hasattr(self.device, "set_quiet_hours"):
                try:
                    await asyncio.to_thread(self.device.set_quiet_hours, rem["quiet_hours"])
                except (ValueError, TypeError, AttributeError):
                    return False, {"code": "bad_request", "message": "quiet hours must be HH:MM"}, ignored
            else:
                ignored.append("reminders.quiet_hours")
        models = cfg.get("models") if isinstance(cfg.get("models"), dict) else None
        if models is not None or keys:
            if self.models_capable:
                try:
                    changed = await asyncio.to_thread(self.device.apply_models, models or {}, keys)
                except ValueError as e:  # a key or address with a control character; the text names no key
                    return False, {"code": "bad_request", "message": str(e)[:200]}, ignored
                log.info("models changed for %s", ",".join(changed) or "nothing")
            else:
                ignored.append("models")
        camera = cfg.get("camera") if isinstance(cfg.get("camera"), dict) else None
        if camera is not None:
            if getattr(self.device, "camera_capable", False):
                res = await asyncio.to_thread(self.device.set_camera_config, camera)
                if isinstance(res, tuple) and len(res) == 2 and not res[0]:
                    return False, res[1] if isinstance(res[1], dict) else {"code": "bad_request",
                                                                            "message": "camera setting refused"}, ignored
            else:
                ignored.append("camera")
        await self.poll_once()
        return True, None, ignored

    async def on_camera_action(self, msg: dict):
        action = msg.get("action")
        if not getattr(self.device, "camera_capable", False):
            return await self._ack(msg.get("req"), False, {"code": "unsupported", "message": "no camera drivers"})
        if action not in ("pair", "recover", "wake"):
            return await self._ack(msg.get("req"), False, {"code": "bad_request", "message": "unknown action"})
        ok, detail = await asyncio.to_thread(self.device.camera_action, action)
        if ok:
            await self._send_json({"type": "ack", "req": msg.get("req"), "ok": True,
                                   "result": {"detail": str(detail or "")[:200]}})
        else:
            await self._send_json({"type": "ack", "req": msg.get("req"), "ok": False,
                                   "error": {"code": "driver_unavailable", "message": str(detail or "")[:200]}})

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
            try:
                want_fps = float(msg.get("fps") or 1)
                want_width = int(msg.get("max_width") or 960)
                if want_fps <= 0 or want_width <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                return await self._ack(msg.get("req"), False, {"code": "bad_request",
                                                               "message": "fps and max_width must be positive numbers"})
            fps = min(want_fps, float(conf.get("max_fps", DEFAULT_LIVE_MAX_FPS)),
                      float(self._limit("live_max_fps", DEFAULT_LIVE_MAX_FPS)))
            width = min(want_width, int(conf.get("max_width", 960)))
            self.live_params = {"on": True, "fps": max(0.1, fps), "width": width,
                                "quality": int(conf.get("jpeg_quality", 70)),
                                "max_bytes": self._limit("frame_max_bytes", DEFAULT_FRAME_MAX_BYTES)}
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
        body = {k: v for k, v in (payload or {}).items() if v is not None}
        message = {"type": kind, "req": req, **body}
        cap = self._limit("cloud_message_max_bytes", self._limit("message_max_bytes", DEFAULT_MESSAGE_MAX_BYTES))
        if len(json.dumps(message, ensure_ascii=False)) > cap:
            times.pop()
            return {"ok": False, "error": {"code": "bad_request",
                                           "message": f"the request is larger than HipiMind accepts ({cap} characters)"}}
        fut = asyncio.get_running_loop().create_future()
        self.cloud_waiters[req] = fut
        await self._send_json(message)
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
        # inside the app, a missing or revoked token is waited out: `pair` writes a new one, no restart
        self.bridge = Bridge(load_config_dict({"wait_for_token": True, **hcfg}), device=AppDevice(app))
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
    print(paired_message(res))
    if app_cfg.get("data_dir"):
        # a new pairing is a new owner: remote models and keys chosen on the previous account's page go
        from .models import ModelSettings
        dropped = ModelSettings(app_cfg, os.path.join(app_cfg["data_dir"], "state")).reset_remote()
        if dropped:
            print("models chosen on the previous account's page are back to this device's config: "
                  + ", ".join(dropped))
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
    # -v is for this connector's own lines: the websockets library would log the handshake, token included
    logging.getLogger("websockets").setLevel(logging.INFO)
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
        print(paired_message(res))
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
