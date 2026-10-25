"""The camera drivers, their settings, and the plain-language text shown where a user picks one.

The same config object is used in the local config file (`camera`), in `state/camera.json` (a choice
made on a web page) and by a remote settings page that pushes it to this device. The device decides;
a server never talks to the camera.
"""
from __future__ import annotations

DRIVER_IDS = ("auto", "uvc", "dji-ble-official", "dji-duml")
UNOFFICIAL = {"dji-duml"}
UNOFFICIAL_WARNING = "这是社区逆向出来的协议，不是 DJI 官方支持的，相机固件更新后可能失效。"

# id, label, what it does, what it needs (each at most 120 characters), unofficial
CATALOG = [
    {"id": "auto", "label": "自动（推荐）",
     "does": "画面走 USB 网络摄像头；相机掉线时先用官方蓝牙让它自己切回来，勾选了社区协议的话再用社区协议补",
     "needs": "USB 线；有蓝牙时能自动恢复", "unofficial": False},
    {"id": "uvc", "label": "USB 网络摄像头（官方）",
     "does": "相机用 DJI 官方的网络摄像头模式经 USB 传画面和声音；相机断电或重启后要在它屏幕上点一次「网络摄像头」",
     "needs": "一根 USB 线", "unofficial": False},
    {"id": "dji-ble-official", "label": "DJI 官方蓝牙协议",
     "does": "不传画面，只控制相机：唤醒和休眠、切模式（包括切回网络摄像头）、停止录像、读电量和温度",
     "needs": "电脑有蓝牙，第一次要在相机屏幕上点一次允许；画面仍走 USB", "unofficial": False},
    {"id": "dji-duml", "label": "社区逆向协议（非官方）",
     "does": "DJI App 自己用的内部协议，由社区解析：让相机自己切回网络摄像头，读电量",
     "needs": "电脑有蓝牙，第一次要在相机屏幕上点一次允许", "unofficial": True},
]
LABELS = {d["id"]: d["label"] for d in CATALOG}

DEFAULT_CONFIG = {
    "driver": "auto",
    "allow_unofficial": False,
    "ble": {"device": None},
    "recover": {"auto_webcam": True, "wake": True},
}


class ConfigError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _bool(v, default: bool) -> bool:
    return v if isinstance(v, bool) else default


def normalize(raw, base: dict | None = None) -> dict:
    """Validate a camera config. Unknown keys are dropped; missing ones come from `base` or the defaults.
    Raises ConfigError("unofficial_not_allowed" | "bad_config", message)."""
    base = base or DEFAULT_CONFIG
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError("bad_config", "camera config must be an object")
    driver = raw.get("driver", base.get("driver", "auto"))
    if driver not in DRIVER_IDS:
        raise ConfigError("bad_config", f"unknown camera driver: {driver}")
    allow = _bool(raw.get("allow_unofficial"), base.get("allow_unofficial", False))
    if driver in UNOFFICIAL and not allow:
        raise ConfigError("unofficial_not_allowed",
                          "选社区逆向协议要先勾选「允许非官方协议」：" + UNOFFICIAL_WARNING)
    ble_in = raw.get("ble") if isinstance(raw.get("ble"), dict) else {}
    device = ble_in.get("device", (base.get("ble") or {}).get("device"))
    if device is not None and (not isinstance(device, str) or len(device) > 64):
        raise ConfigError("bad_config", "ble.device must be a string of at most 64 characters, or null")
    rec_in = raw.get("recover") if isinstance(raw.get("recover"), dict) else {}
    rec_base = base.get("recover") or {}
    out = {
        "driver": driver,
        "allow_unofficial": allow,
        "ble": {"device": device or None},
        "recover": {"auto_webcam": _bool(rec_in.get("auto_webcam"), rec_base.get("auto_webcam", True)),
                    "wake": _bool(rec_in.get("wake"), rec_base.get("wake", True))},
    }
    opts = raw.get("options", base.get("options"))
    if opts is not None:
        if not isinstance(opts, dict) or len(opts) > 20 or len(str(opts)) > 2048 or \
                any(not isinstance(k, str) or not isinstance(v, (str, int, float, bool)) for k, v in opts.items()):
            raise ConfigError("bad_config", "options must be flat (string/number/bool), at most 20 keys and 2 KB")
        out["options"] = dict(opts)
    return out


def control_chain(cfg: dict) -> list[str]:
    """Which drivers may try to bring the camera back, in order. The unofficial one only takes part
    when the user allowed it."""
    d = cfg["driver"]
    allow = cfg.get("allow_unofficial", False)
    if d == "auto":
        return ["dji-ble-official"] + (["dji-duml"] if allow else [])
    if d == "dji-ble-official":
        return ["dji-ble-official"]
    if d == "dji-duml":
        return ["dji-duml"] if allow else []
    return []
