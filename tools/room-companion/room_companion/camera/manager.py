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
from .catalog import UNOFFICIAL_WARNINGS, DRIVER_IDS, ConfigError, catalog_for, control_chain, label, normalize
from .texts import t

UVC_MODE = rsdk.MODE_CODES["uvc_webcam"]
STATES = ("off", "starting", "running", "waiting_device", "error")


class StepFailed(Exception):
    """One driver could not do its part. Carries a text key so the status can be shown in the owner's
    language whenever it is read."""

    def __init__(self, key: str, **kw):
        super().__init__(key)
        self.key, self.kw = key, kw

    def text(self, lang: str) -> str:
        return t(self.key, lang, **self.kw)


def _failure(e: Exception) -> StepFailed:
    return e if isinstance(e, StepFailed) else StepFailed("helper", detail=str(e)[:150])


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
            raise StepFailed("not_found")
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
            raise StepFailed("rsdk_need_tap")
        if r.get("error") == "rejected":
            raise StepFailed("rsdk_rejected")
        raise StepFailed("rsdk_failed", error=r.get("error"))

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
                raise StepFailed("no_answer_uvc")
            if ret != 0:
                raise StepFailed("rsdk_uvc_refused", ret=ret)
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
                raise ValueError(f"unknown action {action}")
            self.m.note(self.id, action, r)
            ret = rsdk.ret_code(bytes.fromhex(r["reply"])) if r.get("reply") else None
            if ret != 0:
                raise StepFailed("not_done", ret=ret)
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
            raise StepFailed("duml_need_tap")
        raise StepFailed("duml_failed", error=r.get("error"))

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
                raise StepFailed("duml_uvc_refused")
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
        self.lang = lambda: "zh"  # the app points this at its own language setting
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
        self.available = {i: i == "uvc" for i in DRIVER_IDS if i != "auto"}
        self.errors: dict[str, StepFailed | None] = {i: None for i in self.available}
        self._ble_checked = False
        self.control = None
        self.reasons: list[tuple[str, StepFailed]] = []  # why earlier drivers were passed over, last round
        self._used = None
        self.busy = None          # what the manager is doing right now ("recover", "pair"...)
        self.gave_up = False      # recovery tried every allowed driver and the camera is still missing
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
            msg = t("unofficial_needed", self.lang(), warning=UNOFFICIAL_WARNINGS.get(self.lang(), UNOFFICIAL_WARNINGS["zh"])) \
                if e.code == "unofficial_not_allowed" else str(e)
            return False, e.code, msg
        if not self.ble_available() and new["driver"] in ("dji-ble-official", "dji-duml"):
            return False, "driver_unavailable", t("no_helper", self.lang())
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
                err = StepFailed("bt_off")
            else:
                try:
                    ok = bool(self.bridge.call("check", timeout=30).get("ok"))
                    err = None if ok else StepFailed("helper_down")
                except BridgeError as e:
                    err = _failure(e)
            for i in ("dji-ble-official", "dji-duml"):
                self.available[i], self.errors[i] = ok, err
        return self.available["dji-ble-official"]

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
            if self.gave_up:  # came back after recovery had given up (e.g. someone tapped "Webcam")
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
        return [c for c in ch if self.available[c]]

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

    @property
    def fallback(self) -> str | None:
        return self._reasons_text(self.lang()) if self.reasons else None

    @property
    def last_failure(self) -> str | None:
        return self.fallback if self.gave_up else None

    def _reasons_text(self, lang: str, used: str | None = None) -> str:
        sep = t("sep", lang)
        text = sep.join(f"{label(d, lang)}: {e.text(lang)}" if lang == "en" else f"{label(d, lang)}：{e.text(lang)}"
                        for d, e in self.reasons)
        if used:
            text += t("then_use", lang, label=label(used, lang))
        return text[:200]

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
                        raise StepFailed("uvc_not_back")
                except (StepFailed, BridgeError) as e:
                    f = _failure(e)
                    reasons.append((did, f))
                    self.errors[did] = f
                    self.attempts.append({"at": t0, "driver": did, "ok": False, "detail": f.text(self.lang())[:120]})
                    self.events.add("camera_recover", driver=did, ok=False, detail=f.key)
                    continue
                self.errors[did] = None
                self.attempts.append({"at": t0, "driver": did, "ok": True, "detail": t("recovered", self.lang(), label=label(did, self.lang()))})
                self.events.add("camera_recover", driver=did, ok=True, seconds=round(self.clock() - t0, 1))
                self.control = did
                self.reasons = reasons
                self._used = did
                self.gave_up = False
                self.backoff, self.next_try_at = 60.0, 0.0
                lang = self.lang()
                self.notify(t("recovered_notice", lang, label=label(did, lang)))
                return True, t("recovered", lang, label=label(did, lang))
            self.reasons = reasons
            self._used = None
            self.gave_up = True
            self.next_try_at = self.clock() + self.backoff
            self.backoff = min(self.backoff * 2, 900.0)
            return False, self.fallback or t("nothing_to_try", self.lang())

    # ---- actions from a settings page ----
    def action(self, name: str) -> tuple[bool, str]:
        lang = self.lang()
        if name not in ("pair", "recover", "wake", "sleep", "stop_recording"):
            return False, f"unknown action {name}"
        if not self.ble_available():
            return False, t("no_helper", lang)
        if self.busy:
            return False, t("busy", lang, what=self.busy)
        self.busy = name
        try:
            if name == "recover":
                return self.recover()
            if name == "wake":
                if not self.ble_state.get("addr"):
                    return False, t("no_addr", lang)
                r = self.bridge.call("wake_adv", timeout=20, addr=self.ble_state["addr"], seconds=2)
                self.note("dji-ble-official", "wake", r)
                return bool(r.get("ok")), t("wake_sent" if r.get("ok") else "wake_failed", lang)
            chain = self.chain() if self.config["driver"] == "auto" else [self.config["driver"]]
            chain = [c for c in chain if c in self.drivers and self.available.get(c)]
            if name == "pair":
                done = []
                for did in chain:
                    try:
                        self.drivers[did].pair(wait=30)
                        self.errors[did] = None
                        done.append(label(did, lang))
                    except (StepFailed, BridgeError) as e:
                        f = _failure(e)
                        self.errors[did] = f
                        return False, f"{label(did, lang)}：{f.text(lang)}"
                return bool(done), t("paired", lang, labels="、".join(done)) if done else t("nothing_to_pair", lang)
            # sleep / stop_recording: only the official protocol has them
            try:
                self.drivers["dji-ble-official"].command(name)
                return True, t({"sleep": "slept", "stop_recording": "stopped"}[name], lang)
            except (StepFailed, BridgeError) as e:
                return False, _failure(e).text(lang)
        finally:
            self.busy = None
            self.need_tap = None

    # ---- status ----
    def status(self) -> dict:
        """The shared `state.camera` object, in the owner's language. No addresses, serials or keys:
        it is shown in a browser."""
        lang = self.lang()
        v = self.video
        state = getattr(v, "state", "off")
        state = state if state in STATES else "error"
        # only the model name from the camera's own protocol (a fixed table); never the capture
        # device's name or capture error output: this object leaves the machine
        name = self.ble_state.get("model")
        if state == "running":
            detail = None
        elif self.busy:
            detail = t({"recover": "d_recovering", "pair": "d_pairing"}.get(self.busy, "d_busy"), lang)
        elif state == "waiting_device" and self.gave_up:
            detail = t("d_gave_up", lang, why=self.fallback or "")
        elif state == "waiting_device":
            detail = t("d_missing", lang)
        elif state == "error":
            detail = t("d_error", lang)
        else:
            detail = None
        fallback = self._reasons_text(lang, getattr(self, "_used", None)) if self.reasons else None
        return {
            "driver": self.config["driver"],
            "active": "uvc" if state == "running" else None,
            "control": self.control,
            "fallback": fallback,
            "state": state,
            "name": (name or None) and str(name)[:80],
            "detail": (detail or None) and str(detail)[:200],
            "drivers": {k: {"available": self.available[k],
                            "last_error": self.errors[k].text(lang)[:200] if self.errors[k] else None}
                        for k in self.available},
        }

    def detail_status(self) -> dict:
        """Extra local view for this machine's own page (still no address)."""
        return {
            "config": self.config,
            "catalog": catalog_for(self.lang()),
            "busy": self.busy,
            "need_tap": self.need_tap,
            "paired": {"dji-ble-official": bool(self.ble_state.get("rsdk_paired")),
                       "dji-duml": bool(self.ble_state.get("duml_paired"))},
            "camera": dict(self.camera_info),
            "attempts": list(self.attempts)[-5:],
        }
