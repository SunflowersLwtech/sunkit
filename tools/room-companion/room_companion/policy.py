"""When to speak up: turns scene observations into a few well-timed reminders.

Rules (defaults; all in config):
- quiet hours 23:00-08:00, asleep, or nobody in the room: say nothing;
- someone is talking or on a call, cooking with hot oil, or mid-yoga: wait;
- coding or working on the router: wait for a 2-minute break;
- at most 6 reminders a day, each kind at most once a day;
- "不用" after a reminder: that kind is off for the rest of the day;
  "别再提醒这个": that kind is off for good;
- 08:30: a short summary of yesterday and last night.
Only scene labels and minutes are kept (data/state/policy.json), never images or words.
"""
from __future__ import annotations

import json
import os
import threading
import time

from .vision import SCENES

BUSY = ("coding", "router")
MODES = {"quiet": "安静（只发通知，不出声）", "balanced": "平衡（出声并发通知）", "active": "主动（提醒得更早）"}
CATEGORIES = {"久坐": "久坐提醒", "路由器": "改路由器前备份", "手机": "沙发上看手机", "晾衣服": "晾衣服",
              "厨房": "做完饭关火通风", "运动后": "运动后补水拉伸"}
LANGUAGES = ("zh", "en")
# What a reminder says, per language ("language" in the config, or chosen on the HipiMind page).
TEXTS = {
    "厨房": {"zh": "做完饭记得确认关火、开窗通风。", "en": "Done cooking? Check the stove is off and open a window."},
    "运动后": {"zh": "练完了，记得补水、拉伸一下。", "en": "Workout done: drink some water and stretch."},
    "晾衣服": {"zh": "洗衣服差不多该好了，记得晾衣服。", "en": "The laundry should be done; time to hang it up."},
    "久坐": {"zh": "已经连续写了约 {m} 分钟代码，起来活动一下、喝口水吧。",
            "en": "About {m} minutes of coding in a row: stand up, move and drink some water."},
    "路由器": {"zh": "配置路由器有一阵了，改动前记得先备份配置，改坏了好回滚。",
             "en": "You've been on the router a while: back up its settings before changing them."},
    "手机": {"zh": "在沙发上看手机快 {m} 分钟了，起来走走、看看远处吧。",
            "en": "Almost {m} minutes on the phone on the sofa: get up, walk, look far away."},
}
SCENES_EN = {"laundry": "laundry", "cooking": "cooking", "coding": "coding", "router": "router setup", "yoga": "yoga",
             "sofa_phone": "phone on the sofa", "sleeping": "sleeping", "other": "other", "empty": "nobody"}


def _hm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def _day(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def _minute_of_day(ts: float) -> int:
    t = time.localtime(ts)
    return t.tm_hour * 60 + t.tm_min


class Policy:
    def __init__(self, path: str, cfg: dict, deliver, events=None, clock=time.time):
        self.path = path
        self.cfg = cfg
        self.deliver = deliver  # deliver(text, category, speak: bool)
        self.events = events
        self.clock = clock
        self._lock = threading.RLock()
        self.scene = None
        self.scene_since = None
        self._cand, self._cand_n = None, 0
        self.last_obs = None
        self.last_obs_at = None
        self.busy_seen_at = 0.0
        self.pending: dict[str, dict] = {}
        self.timers: list[tuple[float, str, str]] = []
        self.ai_on = False
        self.talking_at = 0.0
        self.language = "zh"  # set by the app; the reminder and summary wording follows it
        self.state = self._load()

    # ---- persistence ----
    def _load(self) -> dict:
        base = {"day": _day(self.clock()), "delivered": [], "suppress_today": [], "suppress_forever": [],
                "minutes": {}, "sleep": {"start": None, "wake": None}, "summary_sent": None,
                "mode": self.cfg.get("mode", "balanced")}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                base.update({k: d[k] for k in base if k in d})
        except (OSError, ValueError):
            pass
        if base["mode"] not in MODES:
            base["mode"] = "balanced"
        return base

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False)
        os.replace(tmp, self.path)

    def _rollover(self, now):
        today = _day(now)
        if self.state["day"] != today:
            self.state["day"] = today
            self.state["delivered"] = []
            self.state["suppress_today"] = []
            keep = {d: m for d, m in self.state["minutes"].items() if d >= _day(now - 3 * 86400)}
            self.state["minutes"] = keep
            self.pending.clear()
            self._save()

    # ---- thresholds ----
    def _minutes(self, key, default):
        v = self.cfg.get(key, default)
        return v * (2 / 3 if self.state["mode"] == "active" else 1) * 60

    def quiet_now(self, now) -> bool:
        a, b = (_hm(x) for x in self.cfg.get("quiet_hours", ["23:00", "08:00"]))
        m = _minute_of_day(now)
        return (a <= m or m < b) if a > b else (a <= m < b)

    # ---- inputs ----
    def set_context(self, ai_on: bool, talking_at: float):
        self.ai_on = ai_on
        self.talking_at = talking_at

    def observe(self, obs: dict, now=None):
        now = now or self.clock()
        with self._lock:
            self._rollover(now)
            if self.scene is not None and self.last_obs_at is not None:
                gap = min(now - self.last_obs_at, self.cfg.get("max_gap_s", 360))
                mins = self.state["minutes"].setdefault(_day(now), {})
                mins[self.scene] = round(mins.get(self.scene, 0) + gap / 60, 1)
            self.last_obs, self.last_obs_at = obs, now
            s = obs["scene"]
            if s in BUSY:
                self.busy_seen_at = now
            if s == self.scene:
                self._cand, self._cand_n = None, 0
            else:
                self._cand_n = self._cand_n + 1 if s == self._cand else 1
                self._cand = s
                if self.scene is None or self._cand_n >= self.cfg.get("debounce", 2):
                    self._switch(s, now)
            self._triggers(now)
            self._flush(now)
            self._save()

    def _t(self, cat, **kw) -> str:
        lang = self.language if self.language in LANGUAGES else "zh"
        return TEXTS[cat][lang].format(**kw)

    def _switch(self, new, now):
        old, since = self.scene, self.scene_since
        self.scene, self.scene_since = new, now
        self._cand, self._cand_n = None, 0
        if self.events:
            self.events.add("scene", scene=new)
        lasted = (now - since) if since else 0
        if old == "cooking" and lasted >= 5 * 60:
            self._queue("厨房", self._t("厨房"), now)
        if old == "yoga" and lasted >= 10 * 60:
            self._queue("运动后", self._t("运动后"), now)
        if new == "laundry":
            self.timers.append((now + self.cfg.get("laundry_minutes", 45) * 60, "晾衣服", self._t("晾衣服")))
        h = time.localtime(now).tm_hour
        sl = self.state["sleep"]
        if new == "sleeping" and (h >= 20 or h < 5) and (not sl["start"] or now - sl["start"] > 18 * 3600):
            sl["start"], sl["wake"] = now, None
        if old == "sleeping" and new != "empty" and 4 <= h < 13 and sl["start"]:
            sl["wake"] = now

    def _triggers(self, now):
        if self.scene is None or self.scene_since is None:
            return
        dur = now - self.scene_since
        if self.scene == "coding" and dur >= self._minutes("coding_minutes", 90):
            self._queue("久坐", self._t("久坐", m=int(dur // 60)), now)
        if self.scene == "router" and dur >= self._minutes("router_minutes", 30):
            self._queue("路由器", self._t("路由器"), now)
        if self.scene == "sofa_phone" and dur >= self._minutes("phone_minutes", 45):
            self._queue("手机", self._t("手机", m=int(dur // 60)), now)

    def _queue(self, cat, text, now):
        if cat in self.pending or self._blocked(cat):
            return
        self.pending[cat] = {"text": text, "created": now, "expires": now + self.cfg.get("pending_hours", 3) * 3600}
        if self.events:
            self.events.add("reminder_queued", category=cat)

    def _blocked(self, cat) -> bool:
        s = self.state
        return (cat in s["suppress_forever"] or cat in s["suppress_today"]
                or any(d["cat"] == cat for d in s["delivered"]))

    # ---- delivery ----
    def why_not(self, now) -> str | None:
        """Reason a reminder cannot be said right now, or None if it can."""
        if not self.ai_on:
            return "AI 关着"
        if self.quiet_now(now):
            return "安静时段"
        if len(self.state["delivered"]) >= self.cfg.get("max_per_day", 6):
            return "今天已经说够了"
        if self.scene in (None, "empty"):
            return "房间里没人"
        if self.scene == "sleeping":
            return "在睡觉"
        if now - self.talking_at < self.cfg.get("talk_grace_s", 45):
            return "有人在说话"
        o = self.last_obs or {}
        if o.get("on_phone_call"):
            return "在打电话"
        if o.get("hot_oil"):
            return "正在热油炒菜"
        if self.scene == "yoga":
            return "正在做瑜伽"
        if self.scene in BUSY or now - self.busy_seen_at < self.cfg.get("busy_break_s", 120):
            return "在写代码或配路由器，等停下 2 分钟"
        return None

    def _flush(self, now):
        for cat in [c for c, p in self.pending.items() if p["expires"] <= now or self._blocked(c)]:
            del self.pending[cat]
        if not self.pending or self.why_not(now):
            return
        cat, p = min(self.pending.items(), key=lambda kv: kv[1]["created"])
        del self.pending[cat]
        self.state["delivered"].append({"t": now, "cat": cat})
        if self.events:
            self.events.add("reminder", category=cat)
        self.deliver(p["text"], cat, self.state["mode"] != "quiet")

    def tick(self, now=None):
        now = now or self.clock()
        with self._lock:
            self._rollover(now)
            due = [t for t in self.timers if t[0] <= now]
            self.timers = [t for t in self.timers if t[0] > now]
            for _, cat, text in due:
                self._queue(cat, text, now)
            if self.scene is not None:
                self._triggers(now)
            self._flush(now)
            self._summary(now)

    def _summary(self, now):
        today = _day(now)
        m = _minute_of_day(now)
        if self.state["summary_sent"] == today or not self.ai_on or not (_hm(self.cfg.get("summary_at", "08:30")) <= m < 12 * 60):
            return
        self.state["summary_sent"] = today
        self._save()
        en = self.language == "en"
        y = self.state["minutes"].get(_day(now - 86400), {})
        parts = [(f"{SCENES_EN.get(k, k)} about {_fmt_minutes(v, 'en')}" if en else f"{SCENES[k]}约 {_fmt_minutes(v)}")
                 for k, v in sorted(y.items(), key=lambda kv: -kv[1])
                 if k not in ("empty", "other", "sleeping") and v >= 5]
        sl = self.state["sleep"]
        night = ""
        if sl.get("start") and now - sl["start"] < 18 * 3600:
            start = time.strftime('%H:%M', time.localtime(sl['start']))
            night = f"slept around {start}" if en else f"昨晚约 {start} 睡"
            if sl.get("wake"):
                wake = time.strftime('%H:%M', time.localtime(sl['wake']))
                night += f", up at {wake}" if en else f"，{wake} 起"
        if not parts and not night:
            return
        if en:
            text = ("Good morning." + (" Yesterday: " + ", ".join(parts) + "." if parts else "")
                    + (" Last night you " + night + "." if night else ""))
        else:
            text = "早上好。" + ("昨天：" + "，".join(parts) + "。" if parts else "") + (night + "。" if night else "")
        if self.events:
            self.events.add("summary")
        self.deliver(text, "早报", self.state["mode"] != "quiet" and self.scene not in (None, "empty", "sleeping"))

    # ---- replies and settings ----
    def last_delivered(self, within_s=None, now=None):
        now = now or self.clock()
        d = [x for x in self.state["delivered"] if within_s is None or now - x["t"] <= within_s]
        return d[-1] if d else None

    def on_reply(self, text: str, within_s=None, now=None) -> str | None:
        now = now or self.clock()
        t = text.replace(" ", "")
        forever = any(w in t for w in ("别再提醒", "不要再提醒", "以后别提醒", "不用再提醒"))
        today = forever or any(w in t for w in ("不用", "不需要"))
        if not today:
            return None
        with self._lock:
            last = self.last_delivered(within_s, now)
            if last is None:
                return None
            cat = last["cat"]
            key = "suppress_forever" if forever else "suppress_today"
            if cat not in self.state[key]:
                self.state[key].append(cat)
            self.pending.pop(cat, None)
            self._save()
        if self.events:
            self.events.add("reminder_off", category=cat, forever=forever)
        return f"好的，以后不再提醒「{CATEGORIES.get(cat, cat)}」。" if forever else f"好的，今天不再提「{CATEGORIES.get(cat, cat)}」。"

    def set_mode(self, mode: str) -> str:
        with self._lock:
            self.state["mode"] = mode
            self._save()
        return MODES[mode]

    def reset_suppressions(self):
        with self._lock:
            self.state["suppress_today"], self.state["suppress_forever"] = [], []
            self._save()

    def status(self, now=None):
        now = now or self.clock()
        with self._lock:
            return {
                "mode": self.state["mode"], "mode_text": MODES[self.state["mode"]],
                "scene": self.scene, "scene_text": SCENES.get(self.scene, "还不知道") if self.scene else "还不知道",
                "scene_minutes": int((now - self.scene_since) // 60) if self.scene_since else None,
                "note": (self.last_obs or {}).get("note"), "observed_at": self.last_obs_at,
                "delivered_today": len(self.state["delivered"]), "max_per_day": self.cfg.get("max_per_day", 6),
                "pending": sorted(self.pending), "blocked_now": self.why_not(now) if self.pending else None,
                "suppress_today": self.state["suppress_today"], "suppress_forever": self.state["suppress_forever"],
            }


def _fmt_minutes(v: float, lang: str = "zh") -> str:
    if lang == "en":
        return f"{v / 60:.1f} h" if v >= 90 else f"{int(round(v))} min"
    return f"{v / 60:.1f} 小时" if v >= 90 else f"{int(round(v))} 分钟"


def parse_policy_command(text: str):
    """Mode and reminder commands shared by the text API and voice: returns ("mode", m) / ("reset",) / None."""
    t = text.replace(" ", "")
    for m, words in (("quiet", ("安静模式", "别出声")), ("balanced", ("平衡模式", "正常模式")),
                     ("active", ("主动模式",))):
        if any(w in t for w in words):
            return ("mode", m)
    if "恢复提醒" in t or "恢复所有提醒" in t:
        return ("reset",)
    return None
