#!/usr/bin/env python3
# seat-refresh（2026-10-31，sunkit tools/magpie-gateway）：让 magpie 一直知道每个 Claude 座位的 5 小时 / 7 天额度和重置时间。
# 为什么要它：magpie 只在两种时候读一个座位的额度——这个座位经 magpie 答了请求（Claude Code 的 rate_limit_event），
#   或者有人在用量页按了这个座位卡片的刷新（v0.1.1689 的 claudeWindows：备用座位只在卡片刷新时读，magpie 自己从不去读）。
#   读数里的重置时间一过，magpie 把那个窗口清成「0%、没有重置时间」（elapsed），直到下次再读。备用座位常常几个小时
#   不经 magpie 答请求，但各机器直连一直在用，于是 CLI 和网页显示「5h 0%」、没有重置时间，路由也按这份旧读数挑座位
#   （10-31 06:5x 实查：weiliu@ 的读数停在 10-30 19:16，Anthropic 那边是 1%、08:50 重置）。用量高、撞限的座位刚答过
#   请求，所以一直有重置时间。
# 做法：systemd timer 每 2 分钟跑一次。先读 magpie 内存里已有的卡片（GET /v1/magpie/quotas/cards，不问 Anthropic），
#   挑出要刷新的座位，在容器里对 127.0.0.1:3425 POST /v1/magpie/quotas/refresh?provider=claude&user=<座位>。这就是用量页的
#   刷新按钮：magpie 在这个座位自己的配置目录里跑一次 Claude Code 的 /usage（不调模型、不花额度，约 2 秒），读数进 magpie
#   内存，CLI（magpie accounts）、网页和路由都用它。容器外连 3425 不算本机、要 key，所以经 docker exec 在容器里用 curl。
# 什么时候刷新一个座位：
#   - 撞线的不碰：5 小时 ≥ CAP（95%，magpie 给每个座位设的上限）且重置在后面，或 7 天 ≥100% 且重置在后面。它们的重置
#     时间已经在显示，magpie 也不往那里派活；等重置时间过了再按下一条读。撞限座位的显示和轮换因此跟以前一样。
#   - 5 小时窗口没有重置时间（过了重置被清掉，或从没读过）：最多每 5 分钟一次；上一次刷新回来也没有重置时间（这个座位
#     自上次重置后没人用过，窗口还没开始），放宽到每 15 分钟。
#   - 读数超过 10 分钟：刷新（别的机器直连在用，额度会涨）。
#   每轮最多刷新 4 个，一个接一个。三个座位加一个 Max，正常每个座位约 10 分钟读一次，一小时约 18 次 /usage。
# 2026-11-01 magpie 升到 v0.1.2421：座位答请求改走 Claude Code 的交互模式（v0.1.2266 起默认），成功的回合不再带
#   rate_limit_event（claudetui 只在被拒时转出它），magpie 对座位的读数只剩这里和容器里登着的那个座位 5–15 分钟一次的
#   /usage。所以「读数多旧就刷新」和「同一座位两次刷新至少隔多久」可以用 SR_STALE、SR_UNKNOWN_GAP（秒）改，线上
#   unit 都设成 180：在接活的座位约 3–4 分钟读一次，一小时约 50 次 /usage（不调模型、不花额度）。
# 刷新前后的读数写进 $VAR/log（一行一个座位），出错只记日志、不告警。--dry-run 只打印每个座位刷不刷、为什么，不刷新。
import json, os, re, subprocess, sys, time
from datetime import datetime, timedelta, timezone

CONTAINER = os.environ.get("SR_CONTAINER", "magpie-magpie-1")
# 在哪里跑 curl：默认进容器（127.0.0.1 才算本机）；测试设成空串，curl 直接在本机跑、连假网关
EXEC = os.environ.get("SR_EXEC", "docker exec %s" % CONTAINER).split()
BASE = os.environ.get("SR_BASE", "http://127.0.0.1:3425")
VAR = os.environ.get("SR_VAR", "/var/lib/magpie-seat-refresh")
STATE, LOG = VAR + "/state.json", VAR + "/log"
TZ = timezone(timedelta(hours=8))
CAP = 95.0             # 5 小时到这个百分比且重置在后面，算撞线，不刷新
STALE = int(os.environ.get("SR_STALE", 10 * 60))             # 读数比这旧就刷新
UNKNOWN_GAP = int(os.environ.get("SR_UNKNOWN_GAP", 5 * 60))  # 5 小时没有重置时间的座位最多这么久刷一次；也是同一座位两次刷新的最小间隔
IDLE_GAP = 15 * 60     # 上次刷新回来也没有重置时间（窗口没开始），放宽到这么久
MAX_PER_RUN = 4
TIMEOUT = 50           # 一次刷新最多等多久（magpie 那边自己 30 秒超时）


def log(msg):
    with open(LOG, "a") as f:
        f.write("%s %s\n" % (datetime.now(TZ).strftime("%F %T"), msg))


def parse_time(s):
    """magpie 的时间是纳秒精度（2026-10-31T06:59:15.935630364+08:00），Python 3.9 只认到微秒"""
    if not s:
        return None
    s = re.sub(r"(\.\d{6})\d+", r"\1", s.replace("Z", "+00:00"))
    try:
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        return None


def curl(method, path, params=()):
    cmd = EXEC + ["curl", "-s", "-m", str(TIMEOUT), "-X", method, "-w", "\n%{http_code}"]
    if params:
        cmd.append("-G")
        for k, v in params:
            cmd += ["--data-urlencode", "%s=%s" % (k, v)]
    cmd.append(BASE + path)
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=TIMEOUT + 15)
    body, _, code = p.stdout.decode("utf-8", "replace").rpartition("\n")
    if p.returncode != 0 or code != "200":
        raise RuntimeError("%s %s: exit %d, http %s, %s" % (method, path, p.returncode, code or "-",
                                                            (p.stderr.decode("utf-8", "replace") or body).strip()[:200]))
    return json.loads(body)


def seats(cards):
    """magpie 的卡片里每个 Claude 订阅（团队座位和 Max）"""
    return [c for c in cards if c.get("provider") == "claude" and c.get("kind") == "subscription" and c.get("user")]


def window(card, name):
    for w in card.get("windows") or []:
        if w.get("name") == name:
            return w
    return None


def describe(card):
    out = []
    for w in card.get("windows") or []:
        t = parse_time(w.get("resetsAt"))
        out.append("%s %g%%%s" % (w.get("name"), round(w.get("used") or 0, 1),
                                  " ↻" + datetime.fromtimestamp(t, TZ).strftime("%m-%d %H:%M") if t else ""))
    if card.get("error"):
        out.append("error: " + card["error"][:120])
    return ", ".join(out) or "no windows"


def due(card, mine, now):
    """要不要刷新这个座位，和为什么；mine 是本脚本上次刷新它的记录"""
    five, week = window(card, "5 hours"), window(card, "7 days")
    five_reset = parse_time(five.get("resetsAt")) if five else None
    week_reset = parse_time(week.get("resetsAt")) if week else None
    if five_reset and five_reset > now and (five.get("used") or 0) >= CAP:
        return None
    if week_reset and week_reset > now and (week.get("used") or 0) >= 100:
        return None
    since = now - mine.get("at", 0)
    if not five_reset or five_reset <= now:
        gap = UNKNOWN_GAP if mine.get("five_reset", True) else IDLE_GAP
        return "5h reset unknown" if since >= gap else None
    read = parse_time(card.get("readAt")) or parse_time(card.get("asOf")) or 0
    if now - read >= STALE and since >= UNKNOWN_GAP:
        return "read %d min ago" % ((now - read) // 60)
    return None


def main():
    os.makedirs(VAR, exist_ok=True)
    try:
        with open(STATE) as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}
    try:
        cards = seats(curl("GET", "/v1/magpie/quotas/cards").get("data") or [])
    except Exception as e:
        log("cards unreadable: %s" % e)
        return 0
    now = time.time()
    todo = []
    for c in cards:
        why = due(c, state.get(c["user"].lower(), {}), now)
        if why:
            todo.append((c, why))
    # 最久没刷新的先
    todo.sort(key=lambda x: state.get(x[0]["user"].lower(), {}).get("at", 0))
    if "--dry-run" in sys.argv:
        for c in cards:
            why = next((w for x, w in todo[:MAX_PER_RUN] if x is c), None)
            print("%s: %s | %s" % (c["user"], "refresh (%s)" % why if why else "leave", describe(c)))
        return 0
    for c, why in todo[:MAX_PER_RUN]:
        user = c["user"]
        mine = {"at": time.time(), "five_reset": True}
        try:
            after = [a for a in seats(curl("POST", "/v1/magpie/quotas/refresh",
                                           [("provider", "claude"), ("user", user)]).get("data") or [])
                     if a["user"].lower() == user.lower()]
        except Exception as e:
            log("%s: refresh failed (%s): %s" % (user, why, e))
            state[user.lower()] = mine
            continue
        a = after[0] if after else {}
        five = window(a, "5 hours")
        five_reset = parse_time(five.get("resetsAt")) if five else None
        mine["five_reset"] = bool(five_reset and five_reset > time.time())
        state[user.lower()] = mine
        log("%s: %s | before: %s | after: %s" % (user, why, describe(c), describe(a) if a else "card gone"))
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, STATE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
