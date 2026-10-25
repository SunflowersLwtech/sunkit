"""Camera drivers and automatic recovery.

Video always comes from the camera's official USB webcam mode (the `uvc` driver, i.e. the video
pipeline). The Bluetooth drivers do not carry video; they bring the camera back when it has dropped
out of webcam mode (after a power cut or a restart it waits for a tap on "Webcam"): wake it, switch it
to webcam mode, then check that the webcam shows up again. They are tried in order (official first,
the community protocol only if the user allowed it), and the status says which one is in use and
why an earlier one was skipped.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
from collections import deque

from . import duml, rsdk
from .bridge import BleBridge, BridgeError, wait_until
from .catalog import CATALOG, DRIVER_IDS, LABELS, ConfigError, control_chain, normalize

UVC_MODE = rsdk.MODE_CODES["uvc_webcam"]
STATES = ("off", "starting", "running", "waiting_device", "error")


class StepFailed(Exception):
    """One driver could not do its part; the message is plain language for the status line."""


def _write_private(path: str, obj: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _read_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            v = json.load(f)
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


class BleControl:
    """What both Bluetooth drivers share: find the camera, wake it, connect."""

    id = ""

    def __init__(self, mgr: "CameraManager"):
        self.m = mgr

    def _connect(self, wake: bool):
        b = self.m.bridge
        name = self.m.config["ble"]["device"] or "osmo"
        addr = self.m.ble_state.get("addr") if not self.m.config["ble"]["device"] else None
        r = b.call("connect", timeout=60, name=name, scan_seconds=8, **({"addr": addr} if addr else {}))
        if not r.get("ok") and wake and self.m.ble_state.get("addr"):
            # asleep (it stops advertising): the official wake-up broadcast works within 30 min of sleep
            w = b.call("wake_adv", timeout=20, addr=self.m.ble_state["addr"], seconds=2)
            self.m.note(self.id, "wake", w)
            self.m.sleep(3)
            r = b.call("connect", timeout=60, name=name, scan_seconds=8)
        if not r.get("ok"):
            raise StepFailed("蓝牙找不到相机（关机了、没电了，或休眠超过 30 分钟）")
        if r.get("addr"):
            self.m.remember(addr=r["addr"])

    def _disconnect(self):
        self.m.bridge.call("disconnect", timeout=15)


class OfficialBle(BleControl):
    id = "dji-ble-official"

    def handshake(self, wait: float):
        st = self.m.ble_state
        if "sender_mac" not in st:
            self.m.remember(sender_mac=secrets.token_hex(6), sender_id=0x5A000000 | secrets.randbelow(1 << 16))
        r = self.m.bridge.call("rsdk_connect", timeout=wait + 20, sender_id=self.m.ble_state["sender_id"],
                               sender_mac=self.m.ble_state["sender_mac"], verify_mode=0, wait=wait)
        self.m.note(self.id, "connect", r)
        if r.get("ok"):
            self.m.remember(rsdk_paired=True, model=r.get("model"))
            return
        if r.get("error") == "no_tap":
            self.m.remember(rsdk_paired=False)
            raise StepFailed("相机还没允许电脑用官方蓝牙连接：第一次要在相机屏幕上点一次允许（设置里点「配对」）")
        if r.get("error") == "rejected":
            raise StepFailed("相机拒绝了官方蓝牙连接")
        raise StepFailed(f"官方蓝牙握手没成功（{r.get('error')}）")

    def recover(self):
        self._connect(self.m.config["recover"]["wake"])
        try:
            self.handshake(wait=5)
            self.m.bridge.call("rsdk_subscribe", timeout=10, mode=1)
            self.m.sleep(1.0)
            if (self.m.camera_info.get("power_mode") == "sleep") and self.m.config["recover"]["wake"]:
                self.m.note(self.id, "power_normal", self.m.bridge.call(
                    "rsdk", timeout=15, set=0x00, cid=0x1A, payload=rsdk.power_mode(False).hex(), reply_s=3))
            r = self.m.bridge.call("rsdk", timeout=15, set=0x1D, cid=0x04, payload=rsdk.mode_switch(UVC_MODE).hex(), reply_s=5)
            self.m.note(self.id, "mode_uvc", r)
            ret = rsdk.ret_code(bytes.fromhex(r["reply"])) if r.get("reply") else None
            if ret is None:
                raise StepFailed("相机没有回应「切到网络摄像头」")
            if ret != 0:
                raise StepFailed(f"相机不接受用官方蓝牙切到网络摄像头（返回 {ret}）")
        finally:
            self._disconnect()

    def pair(self, wait: float):
        self._connect(True)
        try:
            self.handshake(wait=wait)
        finally:
            self._disconnect()

    def command(self, action: str):
        self._connect(True)
        try:
            self.handshake(wait=5)
            if action == "sleep":
                r = self.m.bridge.call("rsdk", timeout=15, set=0x00, cid=0x1A, payload=rsdk.power_mode(True).hex(), reply_s=3)
            elif action == "stop_recording":
                r = self.m.bridge.call("rsdk", timeout=15, set=0x1D, cid=0x03, payload=rsdk.record(False).hex(), reply_s=3)
            else:
                raise StepFailed(f"unknown action {action}")
            self.m.note(self.id, action, r)
            ret = rsdk.ret_code(bytes.fromhex(r["reply"])) if r.get("reply") else None
            if ret != 0:
                raise StepFailed(f"相机没有执行（返回 {ret}）")
        finally:
            self._disconnect()


class DumlBle(BleControl):
    id = "dji-duml"

    def handshake(self, wait: float):
        if "identifier" not in self.m.ble_state:
            self.m.remember(identifier=secrets.token_hex(16))
        r = self.m.bridge.call("duml_pair", timeout=wait + 30, identifier=self.m.ble_state["identifier"],
                               token="ROOM", wait=wait)
        self.m.note(self.id, "pair", r)
        if r.get("ok"):
            self.m.remember(duml_paired=True)
            return
        if r.get("error") == "no_tap":
            self.m.remember(duml_paired=False)
            raise StepFailed("相机还没允许电脑用社区协议连接：第一次要在相机屏幕上点一次允许（设置里点「配对」）")
        raise StepFailed(f"社区协议配对没成功（{r.get('error')}）")

    def recover(self):
        self._connect(self.m.config["recover"]["wake"])
        try:
            self.handshake(wait=5)
            ok = False
            for to in (duml.ADDR_CAMERA, duml.ADDR_DM368_0):
                r = self.m.bridge.call("duml", timeout=15, to=to, set=0x02, cid=0xE1,
                                       payload=bytes([duml.MODES["uvc_webcam"]]).hex(), reply_s=3)
                self.m.note(self.id, f"mode_uvc_to_{to:02x}", r)
                if r.get("reply") == "00":
                    ok = True
                    break
            if not ok:
                raise StepFailed("相机没有接受用社区协议切到网络摄像头")
        finally:
            self._disconnect()

    def pair(self, wait: float):
        self._connect(True)
        try:
            self.handshake(wait=wait)
        finally:
            self._disconnect()


class CameraManager:
    def __init__(self, cfg: dict, video, events, notify=None, bridge=None, clock=time.time, sleep=time.sleep,
                 monotonic=time.monotonic):
        self.cfg = cfg
        d = cfg["data_dir"]
        self.choice_path = os.path.join(d, "state", "camera.json")
        self.ble_path = os.path.join(d, "state", "camera_ble.json")
        self.video = video
        self.events = events
        self.notify = notify or (lambda text: None)
        self.clock = clock
        self.sleep = sleep
        self.monotonic = monotonic
        self.host = cfg.get("camera_host") or {}
        self.recover_after_s = float(self.host.get("recover_after_s", 20))
        self.uvc_wait_s = float(self.host.get("uvc_wait_s", 25))
        self.file_config = self._file_config()
        self.config = self._load_choice()
        self.ble_state = _read_json(self.ble_path)
        self._bridge = bridge
        self.camera_info: dict = {}
        self.drivers = {"dji-ble-official": OfficialBle(self), "dji-duml": DumlBle(self)}
        self.status_by_driver = {i: {"available": i == "uvc", "last_error": None} for i in DRIVER_IDS if i != "auto"}
        self._ble_checked = False
        self.control = None
        self.fallback = None
        self.busy = None          # what the manager is doing right now ("recover", "pair"...)
        self.gave_up = False      # recovery tried every allowed driver and the camera is still missing
        self.last_failure = None
        self.next_try_at = 0.0
        self.backoff = 60.0
        self.attempts = deque(maxlen=12)
        self.need_tap = None
        self._lock = threading.Lock()

    # ---- config ----
    def _file_config(self) -> dict:
        try:
            return normalize(self.cfg.get("camera"))
        except ConfigError as e:
            self.events.add("camera_config_error", detail=str(e)[:200])
            return normalize(None)

    def _load_choice(self) -> dict:
        saved = _read_json(self.choice_path)
        if not saved:
            return self.file_config
        try:
            return normalize(saved, base=self.file_config)
        except ConfigError:
            return self.file_config

    def set_config(self, raw) -> tuple[bool, str | None, str | None]:
        """A choice from a settings page. Returns (ok, error code, message); saved to state/camera.json."""
        try:
            new = normalize(raw, base=self.config)
        except ConfigError as e:
            return False, e.code, str(e)
        if not self.ble_available() and new["driver"] in ("dji-ble-official", "dji-duml"):
            return False, "driver_unavailable", "这台电脑上没有可用的蓝牙助手，选不了蓝牙驱动"
        try:
            _write_private(self.choice_path, new)
        except OSError as e:
            return False, "save_failed", f"没能保存：{e}"
        old, self.config = self.config, new
        self.gave_up, self.next_try_at, self.backoff = False, 0.0, 60.0
        self.events.add("camera_config", driver=new["driver"], allow_unofficial=new["allow_unofficial"],
                        previous=old["driver"])
        return True, None, None

    # ---- Bluetooth helper ----
    @property
    def bridge(self) -> BleBridge:
        if self._bridge is None:
            self._bridge = BleBridge(python=self.host.get("python"), helper_dir=self.host.get("helper_dir"),
                                     on_event=self._on_event)
        return self._bridge

    def start(self):
        """Check the Bluetooth helper in the background (starting it can take a few seconds)."""
        threading.Thread(target=self.ble_available, name="camera-check", daemon=True).start()

    def shutdown(self):
        if self._bridge is not None:
            self._bridge.stop()

    def ble_available(self) -> bool:
        if not self._ble_checked:
            self._ble_checked = True
            ok, err = False, None
            if self.host.get("bluetooth", True) is False:
                err = "这台电脑的配置关掉了蓝牙"
            else:
                try:
                    ok = bool(self.bridge.call("check", timeout=30).get("ok"))
                    err = None if ok else "蓝牙助手起不来"
                except BridgeError as e:
                    err = str(e)[:200]
            for i in ("dji-ble-official", "dji-duml"):
                self.status_by_driver[i] = {"available": ok, "last_error": err}
        return self.status_by_driver["dji-ble-official"]["available"]

    def _on_event(self, ev: dict):
        kind = ev.get("ev")
        if kind == "status":
            self.camera_info.update({k: ev.get(k) for k in ("mode", "power_mode", "temperature", "battery", "status")})
            self.camera_info["at"] = self.clock()
        elif kind == "battery" and ev.get("percent") is not None:
            self.camera_info["battery"] = ev["percent"]
            self.camera_info["at"] = self.clock()
        elif kind == "need_tap":
            self.need_tap = {"proto": ev.get("proto"), "at": self.clock()}

    def remember(self, **kw):
        self.ble_state.update(kw)
        try:
            _write_private(self.ble_path, self.ble_state)
        except OSError:
            pass

    def note(self, driver: str, step: str, result: dict):
        r = {k: v for k, v in (result or {}).items() if k not in ("id", "addr")}
        self.events.add("camera_step", driver=driver, step=step, result=json.dumps(r, ensure_ascii=False)[:200])

    # ---- recovery ----
    def tick(self, now: float | None = None):
        """Called every few seconds. Starts a recovery in the background when video is on and the
        webcam has been missing for a while."""
        now = now or self.clock()
        v = self.video
        vstate = getattr(v, "state", "off")
        if vstate == "running":
            if self.gave_up or self.fallback:
                self.events.add("camera_back", control=self.control)
            self.gave_up, self.backoff, self.next_try_at = False, 60.0, 0.0
            return
        if vstate != "waiting_device" or not getattr(v, "waiting_since", None):
            return
        if self.busy or now < self.next_try_at or now - v.waiting_since < self.recover_after_s:
            return
        if not self.config["recover"]["auto_webcam"] or not self.chain():
            if self._ble_checked:
                self.gave_up = True
            return
        self.busy = "recover"
        threading.Thread(target=self._recover_bg, name="camera-recover", daemon=True).start()

    def chain(self) -> list[str]:
        ch = control_chain(self.config)
        return [c for c in ch if self.status_by_driver[c]["available"]]

    def _uvc_back(self) -> bool:
        return wait_until(lambda: self.video.find_device() is not None, self.uvc_wait_s, step=2.0, sleep=self.sleep,
                          clock=self.monotonic)

    def _recover_bg(self):
        try:
            self.recover()
        except Exception as e:
            self.events.add("camera_recover_error", detail=str(e)[:200])
        finally:
            self.busy = None

    def recover(self) -> tuple[bool, str]:
        """Try each allowed driver until the webcam is back. Returns (ok, plain-language detail)."""
        with self._lock:
            reasons = []
            for did in self.chain():
                drv = self.drivers[did]
                t0 = self.clock()
                try:
                    drv.recover()
                    if not self._uvc_back():
                        raise StepFailed("相机接受了切换，但电脑上还是没出现网络摄像头")
                except (StepFailed, BridgeError) as e:
                    msg = f"{LABELS[did]}：{e}"
                    reasons.append(msg)
                    self.status_by_driver[did]["last_error"] = str(e)[:200]
                    self.attempts.append({"at": t0, "driver": did, "ok": False, "detail": str(e)[:120]})
                    self.events.add("camera_recover", driver=did, ok=False, detail=str(e)[:200])
                    continue
                self.status_by_driver[did]["last_error"] = None
                self.attempts.append({"at": t0, "driver": did, "ok": True, "detail": "切回网络摄像头"})
                self.events.add("camera_recover", driver=did, ok=True, seconds=round(self.clock() - t0, 1))
                self.control = did
                self.fallback = ("；".join(reasons) + f" → 改用{LABELS[did]}")[:200] if reasons else None
                self.gave_up, self.last_failure = False, None
                self.backoff, self.next_try_at = 60.0, 0.0
                self.notify(f"房间AI：相机掉出了网络摄像头模式，已经用{LABELS[did]}把它切回来了。")
                return True, f"已用{LABELS[did]}切回网络摄像头"
            self.fallback = "；".join(reasons)[:200] or None
            self.last_failure = self.fallback
            self.gave_up = True
            self.next_try_at = self.clock() + self.backoff
            self.backoff = min(self.backoff * 2, 900.0)
            return False, self.fallback or "没有可用的自动恢复方式"

    # ---- actions from a settings page ----
    def action(self, name: str) -> tuple[bool, str]:
        if name not in ("pair", "recover", "wake", "sleep", "stop_recording"):
            return False, f"unknown action {name}"
        if not self.ble_available():
            return False, "这台电脑上没有可用的蓝牙助手"
        if self.busy:
            return False, "正在忙：" + self.busy
        self.busy = name
        try:
            if name == "recover":
                return self.recover()
            if name == "wake":
                if not self.ble_state.get("addr"):
                    return False, "还没连过这台相机，不知道唤醒谁"
                r = self.bridge.call("wake_adv", timeout=20, addr=self.ble_state["addr"], seconds=2)
                self.note("dji-ble-official", "wake", r)
                return bool(r.get("ok")), "已发出唤醒广播（相机休眠 30 分钟以内才有效）" if r.get("ok") else "唤醒广播没发出去"
            chain = self.chain() if self.config["driver"] in ("auto",) else [self.config["driver"]]
            chain = [c for c in chain if c in self.drivers]
            if name == "pair":
                done = []
                for did in chain:
                    try:
                        self.drivers[did].pair(wait=30)
                        done.append(LABELS[did])
                    except (StepFailed, BridgeError) as e:
                        self.status_by_driver[did]["last_error"] = str(e)[:200]
                        return False, f"{LABELS[did]}：{e}"
                return bool(done), ("已配对：" + "、".join(done)) if done else "没有要配对的蓝牙驱动"
            # sleep / stop_recording: only the official protocol has them
            try:
                self.drivers["dji-ble-official"].command(name)
                return True, {"sleep": "相机已休眠", "stop_recording": "已让相机停止录像"}[name]
            except (StepFailed, BridgeError) as e:
                return False, str(e)
        finally:
            self.busy = None
            self.need_tap = None

    # ---- status ----
    def status(self) -> dict:
        """The shared `state.camera` object. No addresses, serials or keys: it is shown in a browser."""
        v = self.video
        state = getattr(v, "state", "off")
        state = state if state in STATES else "error"
        name = self.ble_state.get("model") or (v.device.name if getattr(v, "device", None) else None)
        if state == "running":
            detail = None
        elif self.busy:
            detail = {"recover": "相机掉线了，正在用蓝牙让它切回网络摄像头", "pair": "正在配对：请在相机屏幕上点允许"}.get(
                self.busy, "正在操作相机")
        elif state == "waiting_device" and self.gave_up:
            detail = ("自动恢复没成功，请在相机屏幕上点一次「网络摄像头」。" + (self.last_failure or ""))[:200]
        elif state == "waiting_device":
            detail = "没找到网络摄像头（相机要开机并进入网络摄像头模式）"
        else:
            detail = (getattr(v, "detail", "") or None) and v.detail[:200]
        return {
            "driver": self.config["driver"],
            "active": "uvc" if state == "running" else None,
            "control": self.control,
            "fallback": self.fallback,
            "state": state,
            "name": (name or None) and str(name)[:80],
            "detail": detail,
            "drivers": {k: dict(v) for k, v in self.status_by_driver.items()},
        }

    def detail_status(self) -> dict:
        """Extra local view for this machine's own page (still no address)."""
        info = dict(self.camera_info)
        return {
            "config": self.config,
            "catalog": CATALOG,
            "busy": self.busy,
            "need_tap": self.need_tap,
            "paired": {"dji-ble-official": bool(self.ble_state.get("rsdk_paired")),
                       "dji-duml": bool(self.ble_state.get("duml_paired"))},
            "camera": info,
            "attempts": list(self.attempts)[-5:],
        }
