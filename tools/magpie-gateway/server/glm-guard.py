#!/usr/bin/env python3
# glm-guard（2026-10-31，sunkit tools/magpie-gateway）：Claude 座位快用完时，自动把 GLM 加回 claude-* 三个组、排在 Claude
#   成员后面；座位恢复后再拿掉。跑在网关本机，systemd timer 每 5 分钟一次（magpie-glm-guard.timer）。
# 为什么要它：刘维 10-31「暂时不用glm了，你也确保额度不要打满，假设有必要可以打开glm，任务效率和我的需求高于一切」。
#   claude-opus/sonnet/haiku-5-5 平时只有 Claude（座位 → Kiro/Devin/Zed 上的 Claude），三个 Team 座位都到上限时请求就停住；
#   这时让溢出的请求落到 ZCode 的 GLM（付费 GLM Coding Max），活不停。组是 order 路由，GLM 排在所有 Claude 成员后面，
#   所以打开着的时候座位还有余量也没有请求去 GLM，只有座位全到上限才溢出。
# 读什么（都不问 Anthropic、不花额度）：
#   - 每个 Claude 订阅的 5 小时用量、重置时间、读数时间：容器里 GET 127.0.0.1:3425/v1/magpie/quotas/cards（magpie 内存里的
#     卡片，seat-refresh 让它保持新鲜）。7 天窗口满了的账号（个人 Max）算没有余量。
#   - 每个座位的上限：providers.json 里 claude 的 accountWindowCaps「5 hours」，没有就 accountCaps，再没有就 100。
#   - 最近 30 分钟用掉多少：quota-history.json 里每个座位的读数点，相邻两点的涨幅相加（中间重置过就从 0 算）。
# 什么时候打开（关着，且距上次切换 ≥15 分钟）：
#   - 每个座位都只剩不到 15%；或
#   - 按最近 30 分钟的消耗速度，所有座位到上限前的余量会在 30 分钟内、且在最早一个座位重置之前用完。
#   magpie 给不出读数的座位（卡片没有 5 小时窗口）在这里按没有余量算。
# 什么时候关上（开着，且距上次切换 ≥15 分钟）：有座位读数在 20 分钟内、余量 ≥50%（一般是它刚重置）；读不到的座位
#   不算回来，卡片或 providers.json 整个读不到时什么都不改。不再看速度：
#   magpie 让一个还在活跃的会话留在答过它的成员上（stays=auto），GLM 留在组里，落到 GLM 的会话就一直在 GLM；
#   座位一回来就拿掉 GLM，把它们赶回 Claude。之后速度还是快，15 分钟后由「打开」那条再加回来。
# 动作：magpie group set <组> models+=<GLM> / models-=<GLM>（providers.json 热生效，不重启）；zcode provider 关着就先
#   provider on，关上时只把自己打开的再 provider off。每轮都对账：关着的时候组里出现这几个 GLM 成员也会被拿掉。
#   provider on 是全局的：zcode 由守护打开期间，别的组（frontier、auto-glm-5-3 这些直接点名 zcode 模型的）也会用到它。
#   所以守护打开 zcode 之前，先把别的在用组里的 zcode 成员拿掉（models-= 不看 provider 开没开，排在 provider on 之前，
#   这些组一刻也碰不到 zcode），记下原来的位置；关上时按原位放回（group set <组> models=<整份成员>；magpie 只让开着的
#   provider 的成员进组，所以放回排在 provider off 之前），再关 zcode。zcode 是别人开着的就不动别的组。拿掉会丢设置
#   （成员上挂着规则、权重、off、pick，或组用了 fast、match 模式）或会把组拿空的，不拿，写进日志和消息。
#   切换写日志，经 mesh 发给 feishu-assistant（不在就 feishu-assistant-backup，都不行走 ntfy）。
# 加哪个 GLM（11-01 起）：ZCode 自己也有额度。11-01 20:09 守护照常加了 GLM-5.3，可 ZCode Max 周额度早用完了，兜底其实是空的。
#   所以每轮先看 ZCode 的余量（卡片里有 ZCode 就用卡片，zcode 关着时 magpie 不出它的卡片，就用 quota-history.json 里
#   最新的读数；只算 magpie 还在读的账号，过了重置时间的窗口按重新开始算）：GLM Coding Max 的「5 hours」「Weekly」都还剩
#   ≥2% 就加 Max 的成员（GLM-5.3，haiku 是 GLM-5.3-Flash）；不然加免费 Start Plan 的 Trial（GLM-5.3-Trial，haiku 是
#   GLM-5.3-Flash-Trial，各有各的每日桶，23:59 重置）；也用完就什么都不加、不开 zcode，消息里写「兜底已空」。
#   开着期间每轮都重新挑：Max 用完换 Trial、Trial 用完拿空、重置后再加回，组里的成员变了就发一条消息。读不到、读数不全或
#   看不懂（没有数字）的一律算不知道：Max 要两个窗口都有数字读数，Trial 要它的桶有数字读数，ZCode 一个读数都没有就什么都
#   不加，消息写「读不到 ZCode 余量」。关上时这几个成员（Max 和 Trial 的）都拿掉。
# Trial 开关（11-02 起，默认关）：Start Plan 的请求要装成 ZCode 客户端、从机房 IP 发，社区报过 3012 风控封整个 ZCode 账号（连
#   付费套餐和官方 App），用不用由刘维定（工作台卡 glm-trial-risk）。/etc/magpie-glm-guard/use-trial 在才加 Trial 成员、才解除
#   账号休息；不在时 Max 用完就什么都不加，消息写「兜底已空」并说 Trial 没开。
# 账号休息（11-02 起）：magpie 把一次拒绝记在整个账号上（rest key「zcode@<账号>」），只有 -Trial 条目自己被拒才只歇那个条目。
#   Max 回 1310（周/月上限）时同账号的 Trial 一起歇到周额度重置，组里有 Trial 也一个请求都到不了它（11-02 01:10 实测）。rest 只
#   在 routing 日志里看得到（每个请求 order[] 里 ZCode 那一项），守护读今天和昨天日志里最新一条含该账号的记录。账号在歇（until
#   在将来）就不加它的 Max；风控（3012，why=restricted）整个账号的成员都不加，消息说只有 ZCode 客服能解；不是 Max 周额度上限造成
#   的账号休息，Trial 也不加（解不了、到不了）。只在 Trial 开关开着、这轮用着该账号的 Trial、而且是 Max 周额度上限造成的账号级
#   休息（key 是 zcode@<账号>、错误是 [1310]、until 和 Weekly 窗口的重置时间差不到 1 小时）时，才经 magpie 网页
#   POST /api/gateway/unrest 解除（容器里 3430 端口，cookie magpie_web_3430=$MAGPIE_WEB_KEY，key 只在容器里拼、经 stdin 给 curl，
#   不进命令行）；Trial 条目自己的休息不解除。限频：每次打开一次，之后最多每小时一次（只算真解除了的），每次都写日志（结果、
#   之前的 why/until）。组先对齐、再解除：先解除的话，组里还在的 Max 成员可能先被问到、又把账号歇掉。
# 停用：touch /etc/magpie-glm-guard/paused（每轮直接退出，不改任何东西）；或 systemctl disable --now magpie-glm-guard.timer。
# --dry-run：只打印判断和会做的动作，不改、不发。
import fcntl, json, os, re, subprocess, sys, time, urllib.error, urllib.request, uuid
from datetime import datetime, timedelta, timezone

CONTAINER = os.environ.get("GG_CONTAINER", "magpie-magpie-1")
# 在哪里跑 curl 和 magpie：默认进容器（127.0.0.1:3425 在容器里才算本机）；测试设成空串 / 假 magpie
EXEC = os.environ.get("GG_EXEC", "docker exec %s" % CONTAINER).split()
MAGPIE = os.environ.get("GG_MAGPIE", "docker exec %s magpie" % CONTAINER).split()
BASE = os.environ.get("GG_BASE", "http://127.0.0.1:3425")
CONF = os.environ.get("GG_CONF", "/opt/magpie/config/magpie")      # providers.json、quota-history.json
ETC = os.environ.get("GG_ETC", "/etc/magpie-glm-guard")            # mesh.env、paused
OPS_ENV = os.environ.get("GG_OPS_ENV", "/etc/llm-gateway/ops.env")  # ntfy 中继（兜底）
VAR = os.environ.get("GG_VAR", "/var/lib/magpie-glm-guard")
TZ = timezone(timedelta(hours=8))
ROUTING = os.environ.get("GG_ROUTING", CONF + "/routing")         # magpie 的 routing 日志（每天一个 jsonl）
WEB = os.environ.get("GG_WEB", "http://127.0.0.1:3430")            # magpie 网页（容器里），解除账号休息用
WEB_COOKIE = os.environ.get("GG_WEB_COOKIE", "magpie_web_3430")

GLM = {"claude-opus-5-5": "zcode/GLM-5.3", "claude-sonnet-5-5": "zcode/GLM-5.3",
       "claude-haiku-5-5": "zcode/GLM-5.3-Flash"}
# Max 用完时改加的免费 Start Plan 成员：每个都有自己的每日桶（卡片和历史里叫「GLM-5.3-Trial · ZCode Start Plan」）
TRIAL = {"claude-opus-5-5": "zcode/GLM-5.3-Trial", "claude-sonnet-5-5": "zcode/GLM-5.3-Trial",
         "claude-haiku-5-5": "zcode/GLM-5.3-Flash-Trial"}
GLM_PROVIDER = "zcode"
PLAN_WINDOWS = ("5 hours", "Weekly")   # GLM Coding Max 的两个窗口，Max 成员要两个都有余量
ZEMPTY = 2.0            # ZCode 窗口剩不到这么多 % 算用完
TRIAL_SWITCH = "use-trial"   # ETC 下这个文件在才用 Trial（默认关）
LIFT_GAP = 3600         # 同一次打开里，两次解除账号休息至少隔这么久
WEEK_SLACK = 3600       # 账号休息的 until 和 Weekly 窗口的重置时间差在这以内，才算 Max 周额度上限造成的
ZLIVE = 6 * 3600        # zcode 关着时，账号的最新读数比 zcode 最新读数旧这么多以上就不算（magpie 已经不读它，账号删了）
LOW = 15.0              # 每个座位都只剩不到这么多 % → 打开
BACK = 50.0             # 有座位余量回到这么多 % 以上 → 可以关上
OPEN_WITHIN = 30        # 推算这么多分钟内用完（且早于最早重置）→ 打开
DWELL = int(os.environ.get("GG_DWELL", 15 * 60))   # 打开和关闭之间至少隔这么久（演练时可调小）
RATE_WINDOW = 30 * 60   # 消耗速度看最近多久
FRESH = 20 * 60         # 关上要看的读数不能比这旧
TARGETS = os.environ.get("GG_TARGETS", "feishu-assistant,feishu-assistant-backup").split(",")  # 演练时发给自己
SENDER = "magpie-glm-guard"


def now():
    return time.time()


def log(msg):
    path = VAR + "/log"
    if os.path.exists(path) and os.path.getsize(path) > 2 << 20:
        os.replace(path, path + ".1")
    with open(path, "a") as f:
        f.write("%s %s\n" % (datetime.now(TZ).strftime("%F %T"), msg))


def parse_time(s):
    """magpie 的时间是纳秒精度（2026-10-31T06:59:15.935630364+08:00），Python 3.9 只认到微秒"""
    if not s or not isinstance(s, str):
        return None
    s = re.sub(r"(\.\d{6})\d+", r"\1", s.replace("Z", "+00:00"))
    try:
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        return None


def hm(t):
    d = datetime.fromtimestamp(t, TZ)
    return d.strftime("%H:%M") if d.date() == datetime.fromtimestamp(now(), TZ).date() else d.strftime("%m-%d %H:%M")


def env(path):
    out = {}
    with open(path) as f:
        for line in f:
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                out[k] = v
    return out


def read_json(path):
    with open(path) as f:
        return json.load(f)


def read_cards():
    cmd = EXEC + ["curl", "-s", "-m", "30", "-w", "\n%{http_code}", BASE + "/v1/magpie/quotas/cards"]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    body, _, code = p.stdout.decode("utf-8", "replace").rpartition("\n")
    if p.returncode != 0 or code != "200":
        raise RuntimeError("cards: exit %d, http %s, %s" % (p.returncode, code or "-",
                                                          (p.stderr.decode("utf-8", "replace") or body).strip()[:200]))
    return json.loads(body).get("data") or []


def window(card, name):
    for w in card.get("windows") or []:
        if w.get("name") == name:
            return w
    return None


def claude_provider(prov):
    return next((p for p in prov.get("providers") or [] if p.get("id") == "claude"), {})


def cap_for(user, cp):
    k = user.lower()
    w = (cp.get("accountWindowCaps") or {}).get(k) or {}
    if w.get("5 hours") is not None:
        return float(w["5 hours"])
    c = (cp.get("accountCaps") or {}).get(k)
    return float(c) if c is not None else 100.0


def seats(cards, prov, t):
    """每个 Claude 订阅（三个 Team 座位和个人 Max）此刻的余量"""
    cp = claude_provider(prov)
    out = []
    for c in cards:
        if c.get("provider") != "claude" or c.get("kind") != "subscription" or not c.get("user"):
            continue
        five, week = window(c, "5 hours"), window(c, "7 days")
        # magpie 给不出 5 小时读数（登录失效这类错误不留旧读数，卡片没有窗口）：打开那边按没有余量算，读不到的座位
        # 多半也接不了请求；关上那边只认 20 分钟内的读数，读不到的本来就不算回来
        unread = five is None
        five = five or {}
        used, reset = float(five.get("used") or 0), parse_time(five.get("resetsAt"))
        raw = (parse_time(c.get("readAt")) or parse_time(c.get("asOf")), used, reset)
        if reset is not None and reset <= t:
            # 过了重置时间、magpie 还没再读：窗口已经从 0 重新开始
            used, reset = 0.0, None
        week_reset = parse_time(week.get("resetsAt")) if week else None
        week_full = bool(week and (week.get("used") or 0) >= 100 and (week_reset is None or week_reset > t))
        cap = cap_for(c["user"], cp)
        read = raw[0]
        no_room = week_full or unread
        out.append({
            "user": c["user"], "plan": c.get("plan") or "", "used": used, "cap": cap, "reset": reset, "read": read,
            "raw": raw, "ok": not week_full, "week_reset": week_reset if week_full else None, "unread": unread,
            "headroom": 0.0 if no_room else max(0.0, cap - used),
            "left": 0.0 if no_room else max(0.0, 100.0 - used),
            "fresh": read is not None and t - read <= FRESH,
        })
    return out


def same_window(a, b):
    """a 在前、b 在后的两个读数（时间, 用量, 重置时间）是不是同一个 5 小时窗口：b 读在 a 的重置时间之后，或用量掉了，
    就是新窗口。不拿两个重置时间直接比：同一个窗口的重置时间在读数里会差一两分钟，卡片和历史也可能不一致。"""
    if a[2] is not None and b[0] >= a[2]:
        return False
    return b[1] >= a[1] - 1


def consumed(points, cur, t):
    """一个座位最近 RATE_WINDOW 里用掉了多少个百分点"""
    start = t - RATE_WINDOW
    pts = []
    for p in points or []:
        at = parse_time(p.get("at"))
        if at is not None and at <= t and p.get("left") is not None:
            pts.append((at, 100.0 - float(p["left"]), parse_time(p.get("resetsAt"))))
    if cur and cur[0] is not None and cur[0] <= t:
        pts.append(cur)
    pts.sort(key=lambda x: x[0])
    base, total = None, 0.0
    for q in pts:
        if q[0] > start and base is not None:
            total += max(0.0, q[1] - base[1]) if same_window(base, q) else q[1]
        base = q
    return total


def assess(ss, history, t):
    for s in ss:
        pts = ((history.get("claude|" + s["user"].lower()) or {}).get("5 hours")) or []
        s["burn"] = consumed(pts, s["raw"], t)
    rate = sum(s["burn"] for s in ss) / (RATE_WINDOW / 60)          # 百分点 / 分钟
    headroom = sum(s["headroom"] for s in ss)
    resets = [s["reset"] for s in ss if s["ok"] and s["reset"] and s["reset"] > t]
    first_reset = min(resets) if resets else None
    to_empty = headroom / rate if rate > 0 else None                 # 分钟
    to_reset = (first_reset - t) / 60 if first_reset else None

    def runs_out(within):
        return to_empty is not None and to_empty < within and (to_reset is None or to_empty < to_reset)

    low = bool(ss) and all(s["left"] < LOW for s in ss)
    back = [s for s in ss if s["ok"] and s["fresh"] and s["left"] >= BACK]
    return {"rate": rate, "headroom": headroom, "to_empty": to_empty, "first_reset": first_reset, "low": low,
            "soon": runs_out(OPEN_WITHIN), "back": back}


def decide(state, a, t):
    """返回 (要不要开着, 理由)"""
    is_open = bool(state.get("open"))
    if is_open:
        want = not a["back"]
    else:
        want = a["low"] or a["soon"]
    if want != is_open and t - state.get("since", 0) < DWELL:
        return is_open, "hold (%d min since last switch)" % ((t - state.get("since", 0)) // 60)
    if want and not is_open:
        return True, "low" if a["low"] else "soon"
    if not want and is_open:
        return False, "back"
    return is_open, "keep"


def num(v):
    """读数里的数字；不是数（缺、null、"n/a"、布尔、NaN）就是 None：没有数字的窗口或点不算读数"""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")):
        return None
    return float(v)


def zcode_windows(cards, history, t):
    """ZCode 每个账号每个窗口此刻剩多少：{账号: {窗口名: {"left": %, "reset": 时间或 None, "at": 读数时间}}}。
    卡片和 quota-history.json 里同一个窗口取读得晚的那个（zcode 关着时卡片里没有它，只剩历史）。卡片里有 ZCode 就只算
    卡片里的账号；没有就按读数时间筛：magpie 一次把一个 provider 的账号都读一遍，删掉的账号读数停在过去。
    过了重置时间的窗口按重新开始算（满额）。卡片上只是一行字的窗口（要去 App 领的赠送套餐）不是读数，不算"""
    acc = {}

    def put(user, name, left, reset, at):
        cur = acc.setdefault(user, {}).get(name)
        if left is not None and at is not None and (cur is None or at >= cur["at"]):
            acc[user][name] = {"left": left, "reset": reset, "at": at}
    for k, v in history.items():
        if k.startswith(GLM_PROVIDER + "|") and isinstance(v, dict):
            for name, pts in v.items():
                pts = [p for p in pts if isinstance(p, dict)] if isinstance(pts, list) else []
                # 最新的、有数字的点（magpie 按时间先后存）
                p = next((p for p in reversed(pts) if num(p.get("left")) is not None), None)
                if p:
                    put(k.split("|", 1)[1].lower(), name, num(p["left"]), parse_time(p.get("resetsAt")),
                        parse_time(p.get("at")))
    carded = set()
    for c in cards:
        if not isinstance(c, dict) or c.get("provider") != GLM_PROVIDER or not isinstance(c.get("user"), str):
            continue
        user, at = c["user"].lower(), parse_time(c.get("readAt")) or parse_time(c.get("asOf"))
        carded.add(user)
        for w in c.get("windows") or []:
            if isinstance(w, dict) and isinstance(w.get("name"), str) and not w.get("text"):
                used = num(w.get("used"))
                put(user, w["name"], 100.0 if w.get("unlimited") is True else None if used is None else 100.0 - used,
                    parse_time(w.get("resetsAt")), at)
    acc = {u: ws for u, ws in acc.items() if ws}
    if carded:
        acc = {u: ws for u, ws in acc.items() if u in carded}
    elif acc:
        newest = max(w["at"] for ws in acc.values() for w in ws.values())
        acc = {u: ws for u, ws in acc.items() if max(w["at"] for w in ws.values()) >= newest - ZLIVE}
    for ws in acc.values():
        for w in ws.values():
            if w["reset"] is not None and w["reset"] <= t:
                w["left"], w["reset"] = 100.0, None
    return acc


def bucket(name, model):
    """窗口 name 是不是 Trial 成员 model 的每日桶（「GLM-5.3-Trial · ZCode Start Plan」；只有一个套餐时可能就叫模型名）"""
    m = model.split("/", 1)[1]
    return name == m or name.startswith(m + " · ")


def blocks_max(r):
    """账号休息挡不挡 Max：账号级的挡；只歇某个 -Trial 条目的不挡"""
    return r is not None and not (r["model"] or "").lower().endswith("-trial")


def liftable(u, r, zw):
    """账号 u 的休息 r 守护能不能解除：账号级（key 没有 /模型）、不是风控、错误是 [1310]、until 和 Weekly 的重置时间对得上"""
    if r is None or r["restricted"] or r["model"] is not None or "1310" not in r["error"]:
        return False
    wr = ((zw.get(u) or {}).get("Weekly") or {}).get("reset")
    return wr is not None and abs(r["until"] - wr) <= WEEK_SLACK


def trial_reachable(u, r, zw, model):
    """Trial 成员 model 在账号 u 上请求到得了：账号没歇，或者歇的是别的 -Trial 条目，或者是守护能解除的 Max 周额度上限"""
    m = model.split("/", 1)[1].lower()
    return r is None or liftable(u, r, zw) or (r["model"] is not None and r["model"].lower() != m)


def pick(zw, rests=None, trial_on=False):
    """每个 claude-* 组这次加哪个 ZCode 成员：Max 有余量用 Max，不然（Trial 开关开着时）Trial 桶有余量、请求到得了就用 Trial，
    都没有（或不知道）就 None。Max 要一个账号两个窗口都有读数、都 ≥ZEMPTY，账号又没在歇；ZCode 一个读数都没有就都是 None。
    rests（zcode_rests() 给的）里风控歇着的账号整个不算"""
    rests = rests or {}
    live = {u: ws for u, ws in zw.items() if not (rests.get(u) or {}).get("restricted")}
    max_room = any(all(n in ws and ws[n]["left"] >= ZEMPTY for n in PLAN_WINDOWS) and not blocks_max(rests.get(u))
                   for u, ws in live.items())
    out = {}
    for gid in GLM:
        trial_room = trial_on and any(
            w["left"] >= ZEMPTY and trial_reachable(u, rests.get(u), zw, TRIAL[gid])
            for u, ws in live.items() for n, w in ws.items() if bucket(n, TRIAL[gid]))
        out[gid] = GLM[gid] if max_room else TRIAL[gid] if trial_room else None
    return out


def lift_users(zw, rests, use):
    """要解除休息的账号：这轮用着它的 Trial（桶有余量），而它正因 Max 周额度上限歇着"""
    used = set(m for m in use.values() if m in TRIAL.values())
    return sorted(u for u, ws in zw.items() if liftable(u, rests.get(u), zw)
                  and any(w["left"] >= ZEMPTY for n, w in ws.items() for m in used if bucket(n, m)))


def zcode_rests(t):
    """magpie 把 ZCode 账号歇着的情况（只有 routing 日志里有：每个请求的 order[] 里 ZCode 那一项带 rest）。取今天和昨天的
    日志里最新一条 order 含该账号的记录：{账号: {"until", "why", "error", "key", "model", "restricted"}}，只留 until 在将来
    的；model 是 None 就是账号级（key 没有 /模型）。最新那条没 rest 就是不在歇（被解除或答过一次就清掉了）。读不到日志就
    是 {}：不知道歇没歇，也就不解除"""
    newest = {}
    day = datetime.fromtimestamp(t, TZ)
    for d in (day - timedelta(days=1), day):
        for f in (ROUTING + "/%s.jsonl" % d.strftime("%Y-%m-%d"),):
            try:
                fh = open(f, encoding="utf-8", errors="replace")
            except OSError:
                continue
            with fh:
                for line in fh:
                    if '"zcode' not in line:
                        continue
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    at = parse_time(r.get("time")) if isinstance(r, dict) else None
                    if at is None:
                        continue
                    for o in r.get("order") or []:
                        if isinstance(o, dict) and o.get("provider") == GLM_PROVIDER and isinstance(o.get("who"), str):
                            u = o["who"].lower()
                            if u not in newest or at >= newest[u][0]:
                                newest[u] = (at, o.get("rest") if isinstance(o.get("rest"), dict) else None)
    out = {}
    for u, (at, rest) in newest.items():
        until = parse_time(rest.get("until")) if rest else None
        if until is not None and until > t:
            err, key = str(rest.get("error") or ""), str(rest.get("key") or "")
            out[u] = {"until": until, "why": str(rest.get("why") or ""), "error": err[:160], "key": key,
                      "model": key.split("/", 1)[1] if "/" in key else None,
                      "restricted": rest.get("why") == "restricted" or "3012" in err}
    return out


def unrest(user):
    """经 magpie 网页解除账号 <GLM_PROVIDER>@<user> 的休息：True 解除了，False 本来没歇；失败抛错。cookie 在容器里用
    MAGPIE_WEB_KEY 拼、经 stdin 给 curl，key 不进命令行、不进输出"""
    script = ('printf "Cookie: %s=%s\\n" "$1" "$MAGPIE_WEB_KEY" | curl -s -m 20 -H @- -H "Content-Type: application/json" '
              '-X POST --data "$2" -w "\\n%{http_code}" "$3"')
    cmd = EXEC + ["sh", "-c", script, "sh", WEB_COOKIE, json.dumps({"key": GLM_PROVIDER + "@" + user}),
                  WEB + "/api/gateway/unrest"]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    body, _, code = p.stdout.decode("utf-8", "replace").rpartition("\n")
    if p.returncode != 0 or code != "200":
        raise RuntimeError("unrest: exit %d, http %s, %s" % (p.returncode, code or "-", body.strip()[:120]))
    return bool(json.loads(body).get("lifted"))


def managed(gid):
    """守护在组 gid 里管的成员：Max 的和 Trial 的"""
    return [GLM[gid], TRIAL[gid]]


def wanted(want_open, picks):
    """每个 claude-* 组这轮该有的 ZCode 成员（None：一个都不该有）"""
    return {gid: (picks.get(gid) if want_open else None) for gid in GLM}


def members(prov, gid):
    g = next((g for g in prov.get("groups") or [] if g.get("id") == gid), None)
    return None if g is None else list(g.get("members") or [])


def provider_off(prov, pid):
    p = next((p for p in prov.get("providers") or [] if p.get("id") == pid), None)
    return p is None or bool(p.get("off"))


def editable(g, m):
    """把组 g 里的 zcode 成员 m 拿掉、以后按原位放回，会不会丢东西：magpie 存组时把不在组里的成员的 off、pick、规则、
    权重一并清掉，按整份成员写回（models=）又会清掉 fast 和 match 模式；组里只剩 zcode 成员时拿空了 magpie 也不让"""
    if g.get("match") or g.get("fast") or g.get("pick") == m or g.get("classifier") == m:
        return False
    if m in (g.get("off") or []) or m in (g.get("weights") or {}) or m in json.dumps(g.get("rules") or []):
        return False
    return any(not x.startswith(GLM_PROVIDER + "/") for x in g.get("members") or [])


def holders(prov):
    """claude-* 三个组以外、没停用的组里直接点名的 zcode 成员：[(组, 成员, 能不能拿)]。停用的组 magpie 不派活，经它
    （always-up 里的 group/zcode）也到不了；经别的组间接含的，在直接点名它的那个组里拿"""
    out = []
    for g in prov.get("groups") or []:
        if g.get("id") in GLM or g.get("disabled") or g.get("hidden"):
            continue
        for m in g.get("members") or []:
            if m.startswith(GLM_PROVIDER + "/"):
                out.append((g["id"], m, editable(g, m)))
    return out


def owed(prov, state):
    """state 里记着、还没放回的成员：组还在、成员不在组里"""
    return [e for e in state.get("stripped") or [] if e["member"] not in (members(prov, e["group"]) or [e["member"]])]


def restores(prov, state):
    """按拿掉时的位置把成员放回，每个组一条 group set <组> models=<整份成员>；倒着放（后拿的先放），同一个组连着拿掉
    的几个成员也回到原来的次序"""
    lists = {}
    for e in reversed(owed(prov, state)):
        ms = lists.setdefault(e["group"], members(prov, e["group"]))
        i = ms.index(e["after"]) + 1 if e.get("after") in ms else min(e.get("at", len(ms)), len(ms))
        ms.insert(i, e["member"])
    return [["group", "set", gid, "models=" + ",".join(ms)] for gid, ms in lists.items()]


def plan(prov, use, state):
    """把 providers.json 对齐到 use（wanted() 给的每组该有的 ZCode 成员）要跑的 magpie 命令。还给出不能拿的 zcode 成员，
    和每条拿掉别的组 zcode 成员的命令要记下的位置。有组要用 ZCode：先拿掉别的组的 zcode 成员，再 provider on，再往
    claude-* 加该有的、拿掉不该有的（先加后拿，换成员时组里不空一下）；一个组都不用（关着，或开着但 ZCode 用完了）：先从
    claude-* 拿掉，再把别的组的成员放回原位，最后 provider off"""
    cmds, missing, kept, strips = [], [], [], {}
    active = any(use.values())
    zoff = provider_off(prov, GLM_PROVIDER)
    if active and (zoff or state.get("zcode_by_guard")):
        left = {}
        for gid, m, ok in holders(prov):
            if not ok:
                kept.append("%s:%s" % (gid, m))
                continue
            ms = left.setdefault(gid, members(prov, gid))
            i = ms.index(m)
            c = ["group", "set", gid, "models-=" + m]
            strips[tuple(c)] = {"group": gid, "member": m, "after": ms[i - 1] if i else None, "at": i}
            ms.pop(i)
            cmds.append(c)
    if active and zoff:
        cmds.append(["provider", "on", GLM_PROVIDER])
    for gid in GLM:
        ms = members(prov, gid)
        if ms is None:
            missing.append(gid)
            continue
        if use[gid] and use[gid] not in ms:
            cmds.append(["group", "set", gid, "models+=" + use[gid]])
        cmds += [["group", "set", gid, "models-=" + m] for m in managed(gid) if m in ms and m != use[gid]]
    if not active and not zoff:
        cmds += restores(prov, state)
    if not active and state.get("zcode_by_guard") and not zoff:
        cmds.append(["provider", "off", GLM_PROVIDER])
    return cmds, missing, kept, strips


def aligned(prov, use, state=None, restored=()):
    """读回核对：claude-* 里守护管的成员正好是 use 里那一个（或一个都没有）；有组用 ZCode 时 zcode 开着，zcode 是守护开的
    就别的组里能拿的都拿掉了；都不用时 zcode 开着就没有欠着没放回的成员，这轮放回过的组都放回了"""
    state = state or {}
    for gid in GLM:
        ms = members(prov, gid)
        if ms is not None and [m for m in managed(gid) if m in ms] != ([use[gid]] if use[gid] else []):
            return False
    zoff = provider_off(prov, GLM_PROVIDER)
    if any(use.values()):
        return not zoff and not (state.get("zcode_by_guard") and any(ok for _, _, ok in holders(prov)))
    return not any(not zoff or e["group"] in restored for e in owed(prov, state))


def magpie(args):
    p = subprocess.run(MAGPIE + args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
    if p.returncode != 0:
        raise RuntimeError("magpie %s: exit %d: %s" % (" ".join(args), p.returncode,
                                                       p.stdout.decode("utf-8", "replace").strip()[:200]))


def zcode_text(zw):
    """消息里 ZCode 那一句：magpie 还在读的账号，每个窗口剩多少、什么时候重置"""
    if not zw:
        return "读不到余量（magpie 没有 ZCode 的读数）"
    parts = []
    for user, ws in sorted(zw.items()):
        names = [n for n in PLAN_WINDOWS if n in ws] + sorted(n for n in ws if n not in PLAN_WINDOWS)
        for n in names:
            label = {"5 hours": "Max 5 小时", "Weekly": "Max 周"}.get(n) or n.split(" · ")[0] + " "
            parts.append("%s%s剩 %g%%%s" % (user + " " if len(zw) > 1 else "", label, round(ws[n]["left"], 1),
                                            "（%s 重置）" % hm(ws[n]["reset"]) if ws[n]["reset"] else ""))
    return "、".join(parts)


def changes(cmds):
    """消息里「改动」那句：claude-* 组加了什么、拿掉了什么"""
    adds, drops = {}, {}
    for c in cmds:
        if c[:2] == ["group", "set"] and c[2] in GLM:
            k, _, m = c[3].partition("=")
            (adds if k == "models+" else drops).setdefault(m, []).append(c[2])
    return "；".join(["%s 末尾加 %s" % ("、".join(g), m) for m, g in adds.items()]
                    + ["%s 拿掉 %s" % ("、".join(g), m) for m, g in drops.items()])


def seat_lines(ss):
    out = []
    for s in ss:
        who = s["user"].replace(" · DuoCode", "") + ("（个人 Max）" if s["plan"] == "max" else "")
        if not s["ok"]:
            out.append("%s：7 天额度用完%s" % (who, "，%s 重置" % hm(s["week_reset"]) if s["week_reset"] else ""))
        elif s["unread"]:
            out.append("%s：读不到（magpie 给不出读数，按没有余量算）" % who)
        else:
            out.append("%s：剩 %g%%（上限 %g%%）%s" % (who, round(s["left"], 1), s["cap"],
                                                   "，%s 重置" % hm(s["reset"]) if s["reset"] else ""))
    return out


def rest_text(r):
    return "%s（%s）" % (hm(r["until"]), (r["error"] or r["why"])[:80])


def rest_lines(rests, lifts, deferred, zw, trial_on):
    """消息里关于 ZCode 账号休息的几句。lifts：这轮解除的结果 {账号: True/False/"错误"}；deferred：限频没解除的 {账号: 下次时间}"""
    out = []
    for u, r in sorted(rests.items()):
        if r["restricted"]:
            out.append("ZCode 账号 %s 被 ZCode 风控挡住，magpie 歇到 %s；这种只有 ZCode 客服能解，守护不解除、不加它的成员。"
                       % (u, rest_text(r)))
        elif lifts.get(u) is True:
            out.append("ZCode 账号 %s 在 magpie 里歇到 %s：Max 被拒时 magpie 把整个账号歇掉，Trial 一起挡住；已解除，Trial 能接了。"
                       % (u, rest_text(r)))
        elif u in lifts and lifts[u] is not False:
            out.append("ZCode 账号 %s 在 magpie 里歇到 %s，解除失败（%s），组里的 Trial 暂时到不了，下一轮再试。"
                       % (u, rest_text(r), lifts[u]))
        elif u in deferred:
            out.append("ZCode 账号 %s 又被 magpie 歇到 %s；解除每小时最多一次，下次 %s。" % (u, rest_text(r), hm(deferred[u])))
        else:
            out.append("ZCode 账号 %s 在 magpie 里歇到 %s：magpie 拒一次就歇整个账号，这期间它的成员一个请求都到不了%s。" % (
                u, rest_text(r), "" if r["model"] is not None
                else "；Trial 开关没开，守护不解除" if liftable(u, r, zw) and not trial_on
                else "；守护只解除 Max 周额度上限（1310）造成的账号休息" if not liftable(u, r, zw) else ""))
    return out


def message(kind, why, ss, a, zw, use, cmds, t, zcode_on=False, others=(), rests=None, lifts=None, deferred=None,
            trial_on=False):
    """kind：open（打开）、close（关上）、swap（开着期间 ZCode 成员变了：Max 换 Trial、拿空、恢复）"""
    rests = rests or {}
    empty = [gid for gid in GLM if not use.get(gid)]
    using = "、".join(sorted(set(m for m in use.values() if m)))
    trial = any(m in TRIAL.values() for m in use.values() if m)
    blocked = any(r["restricted"] for r in rests.values())
    gone = ("读不到 ZCode 的余量（magpie 没有 ZCode 的读数）" if not zw
            else "ZCode 被风控挡住（见下）" if blocked
            else "ZCode 账号在 magpie 里歇着（见下）" if rests
            else "ZCode Max 用完了或读不到，免费 Trial 没开" if not trial_on
            else "ZCode 的 Max 和 Trial 都用完了或读不到（各窗口的重置时间见下）")
    stops = "座位到上限后请求会停住，ZCode 一恢复守护自动加上"
    tier = "（ZCode Max 用完，用免费 Trial）" if trial else ""
    if kind == "open":
        if why == "low":
            reason = "Claude 座位都只剩不到 %d%%%s" % (LOW, "（读不到的按没有余量算）" if any(s["unread"] for s in ss) else "")
        else:
            reason = "按最近 30 分钟的速度，Claude 座位约 %s 到上限%s" % (
                hm(t + a["to_empty"] * 60), "，早于最早一次重置 %s" % hm(a["first_reset"]) if a["first_reset"] else "")
        if not using and not zw:
            head = "magpie 要打开 GLM 兜底，但读不到 ZCode 余量，兜底没加：%s；%s。" % (reason, stops)
        elif not using:
            head = "magpie 要打开 GLM 兜底，但兜底已空：%s，而%s，什么都没加；%s。" % (reason, gone, stops)
        else:
            head = "magpie 已自动打开 GLM 兜底：%s，座位到上限后的请求改落 %s%s。" % (reason, using, tier)
    elif kind == "close":
        b = max(a["back"], key=lambda s: s["left"])
        head = "magpie 已自动关上 GLM 兜底：%s 座位剩 %g%%，claude-* 组回到只用 Claude。" % (
            b["user"].replace(" · DuoCode", ""), round(b["left"], 1))
    elif not using:
        head = "magpie GLM 兜底已空：%s，claude-* 组里的 ZCode 成员已拿掉；%s。" % (gone, stops)
    else:
        head = "magpie GLM 兜底改用 %s%s。" % (using, tier or "（ZCode Max 有余量）")
    if using and empty:
        head += "兜底已空：%s 的 Max 和 Trial 都用完了、读不到或到不了，这些组%s。" % ("、".join(empty), stops)
    lines = [head, "", "座位："] + ["- " + x for x in seat_lines(ss)]
    lines.append("最近 30 分钟每分钟用掉约 %.1f 个百分点，到上限前还有 %.0f 个百分点%s。" % (
        a["rate"], a["headroom"], "，约 %.0f 分钟用完" % a["to_empty"] if a["to_empty"] is not None else ""))
    lines.append("ZCode：" + zcode_text(zw) + "。")
    lines += rest_lines(rests, lifts or {}, deferred or {}, zw, trial_on)
    if kind != "close" and not trial_on and empty and any(pick(zw, rests, True).values()):
        lines.append("免费 Trial（ZCode Start Plan）还有余量，但开关没开：用它可能被 ZCode 风控（3012）封掉整个 ZCode 账号（连付费"
                     "套餐和官方 App），要不要用由刘维定（工作台卡 glm-trial-risk）。打开：sudo touch /etc/magpie-glm-guard/"
                     + TRIAL_SWITCH + "。")
    if trial:
        lines.append("Trial 是 ZCode 免费的 Start Plan：GLM-5.3 每天 300 万 token、GLM-5.3-Flash 每天 500 万，23:59 重置。")
    # zcode 开没开：打开时看 zcode 是不是守护开的（provider on 可能在上一轮半途失败时就跑过了），别的看这轮的命令
    on = zcode_on if kind == "open" else ["provider", "on", GLM_PROVIDER] in cmds
    off = ["provider", "off", GLM_PROVIDER] in cmds
    done = changes(cmds)
    if done or off:
        lines.append("改动：" + (done or "claude-* 组没变") + ("；zcode provider 原来关着，已打开" if on else "")
                     + ("；守护打开的 zcode provider 已关回" if off else "") + "。")
    lines += list(others)
    lines.append("停用：llm-gateway 上 sudo touch /etc/magpie-glm-guard/paused（日志 /var/lib/magpie-glm-guard/log）。")
    return "\n".join(lines)


def http(req, timeout=20):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as r:
        return r.status, r.read()


def mesh_send(text):
    cfg = env(ETC + "/mesh.env")
    base, auth = cfg["MESH_RELAY_URL"].rstrip("/"), "Bearer " + cfg["MESH_TOKEN"]
    _, body = http(urllib.request.Request(base + "/v1/sessions", headers={"Authorization": auth}))
    live = json.loads(body)
    for name in TARGETS:
        cands = sorted((s for s in live if s.get("name") == name), key=lambda s: s.get("status") == "reconnecting")
        for s in cands:
            data = json.dumps({"to": s["account"], "to_session": s["session_id"], "kind": "chat",
                               "content": text}).encode()
            req = urllib.request.Request(base + "/v1/messages", data=data, method="POST", headers={
                "Authorization": auth, "Content-Type": "application/json", "x-mesh-sender-name": SENDER,
                "idempotency-key": uuid.uuid4().hex})
            try:
                code, _ = http(req)
            except urllib.error.HTTPError as e:
                code = e.code
            if code == 201:
                return name
            log("mesh to %s: http %s" % (name, code))
    return None


def ntfy(title, text):
    ops = env(OPS_ENV)
    body = json.dumps({"title": title, "message": text, "tags": ["magpie"], "priority": 4}).encode()
    req = urllib.request.Request(ops["NTFY_RELAY_URL"], data=body, headers={
        "Authorization": "Bearer " + ops["NTFY_RELAY_TOKEN"], "Content-Type": "application/json"})
    return http(req)[0]


def tell(text):
    try:
        who = mesh_send(text)
        if who:
            log("told %s over mesh" % who)
            return
        log("mesh: no live %s" % " / ".join(TARGETS))
    except Exception as e:
        log("mesh failed: %s %s" % (type(e).__name__, str(e)[:160]))
    try:
        log("ntfy: http %s" % ntfy("magpie GLM 兜底", text))
    except Exception as e:
        log("ntfy failed: %s %s" % (type(e).__name__, str(e)[:160]))


def zsummary(zw, picks, rests=None, trial_on=False):
    """日志行里 ZCode 那段：各窗口剩多少，账号休息，Trial 开关，每个组挑的成员"""
    z = " ".join("%s:%s" % (u, ",".join("%s=%g" % (n.split(" · ")[0], round(w["left"], 1)) for n, w in sorted(ws.items())))
                 for u, ws in sorted(zw.items())) or "unread"
    r = " ".join("%s%s:%s-until-%s" % (u, "/" + x["model"] if x["model"] else "",
                                       "restricted" if x["restricted"] else x["why"] or "rest", hm(x["until"]))
                 for u, x in sorted((rests or {}).items()))
    return "zcode[%s]%s trial=%s pick=%s" % (z, " rest[%s]" % r if r else "", "on" if trial_on else "off",
                                   ",".join("%s:%s" % (g.split("-")[1], (picks[g] or "-").split("/")[-1]) for g in GLM))


def summary(ss, a):
    seat = " ".join("%s%s=%s/%g%s" % (s["user"].replace(" · DuoCode", ""), "(max)" if s["plan"] == "max" else "",
                                      "unread" if s["unread"] else "%g%%" % round(s["used"], 1), s["cap"],
                                      "" if s["ok"] else "(7d full)") for s in ss)
    return "%s rate=%.2f%%/min headroom=%.0f to_empty=%s first_reset=%s low=%s soon=%s back=%d" % (
        seat, a["rate"], a["headroom"], "-" if a["to_empty"] is None else "%.0fm" % a["to_empty"],
        hm(a["first_reset"]) if a["first_reset"] else "-", a["low"], a["soon"], len(a["back"]))


def run(dry):
    if os.path.exists(ETC + "/paused"):
        if dry:
            print("paused: %s/paused exists" % ETC)
        return 0
    os.makedirs(VAR, exist_ok=True)
    statef = VAR + "/state.json"
    try:
        state = read_json(statef)
    except (OSError, ValueError):
        state = {}
    t = now()
    try:
        prov = read_json(CONF + "/providers.json")
        cards = read_cards()
    except Exception as e:
        log("inputs unreadable, nothing changed: %s %s" % (type(e).__name__, str(e)[:200]))
        return 0
    try:
        history = read_json(CONF + "/quota-history.json")
    except (OSError, ValueError):
        history = {}
    if "open" not in state:
        # 第一次跑：按组里现在有没有守护管的 GLM 成员（zcode 开着）定初始状态，不算一次切换
        state = {"open": not provider_off(prov, GLM_PROVIDER) and any(
            m in (members(prov, g) or []) for g in GLM for m in managed(g)), "since": 0}
    if provider_off(prov, GLM_PROVIDER) and state.get("zcode_by_guard"):
        # zcode 关着（守护自己关的，或开着期间被人关了）：已经不是守护开着的，之后谁再打开都不归守护关
        state["zcode_by_guard"] = False
    if state.get("stripped"):
        # 已经回到组里的（有人手动加回、或上一轮放回了）不再欠着；组没了的也不欠
        state["stripped"] = owed(prov, state)
    ss = seats(cards, prov, t)
    if not ss:
        log("no Claude seat in magpie's cards, nothing changed")
        return 0
    a = assess(ss, history, t)
    want, why = decide(state, a, t)
    try:
        zw = zcode_windows(cards, history, t)
    except Exception as e:
        # 读数怪到算不出来：当成读不到（什么都不加），不让整轮崩掉、守护既开不了也关不了
        log("zcode readings unusable, counted as unknown: %s %s" % (type(e).__name__, str(e)[:160]))
        zw = {}
    try:
        rests = zcode_rests(t) if want else {}
    except Exception as e:
        log("routing log unreadable, account rests unknown: %s %s" % (type(e).__name__, str(e)[:160]))
        rests = {}
    trial_on = os.path.exists(ETC + "/" + TRIAL_SWITCH)
    picks = pick(zw, rests, trial_on)
    use = wanted(want, picks)
    active = any(use.values())
    cmds, missing, kept, strips = plan(prov, use, state)
    restored = [c[2] for c in cmds if c[:2] == ["group", "set"] and c[3].startswith("models=")]
    line = "%s -> %s (%s) | %s %s%s" % ("open" if state.get("open") else "closed", "open" if want else "closed", why,
                                        summary(ss, a), zsummary(zw, picks, rests, trial_on),
                                        " | zcode left alone in: " + ", ".join(kept) if kept else "")
    switched = want != bool(state.get("open"))
    # 开着期间 claude-* 里的 ZCode 成员变了（Max 换 Trial、拿空、恢复）也报；关着时的对账（拿掉手动加的）不报
    swapped = want and not switched and any(c[:2] == ["group", "set"] and c[2] in GLM for c in cmds)
    kind = ("open" if want else "close") if switched else "swap"
    # 要解除休息的账号（Max 周额度上限造成的、这轮用着它的 Trial）；限频：这次打开里还没解除过就解，解除过就隔够 LIFT_GAP
    open_since = t if switched else state.get("since", 0)
    lift_ok = state.get("lift_open") != open_since or t - state.get("lift_at", 0) >= LIFT_GAP
    to_lift = lift_users(zw, rests, use) if want else []
    deferred = {} if lift_ok else {u: state.get("lift_at", 0) + LIFT_GAP for u in to_lift}
    to_lift = to_lift if lift_ok else []
    if dry:
        print(line)
        for c in cmds:
            print("would run: magpie " + " ".join(c))
        for u in to_lift:
            print("would lift magpie's rest on %s@%s (%s)" % (GLM_PROVIDER, u, rest_text(rests[u])))
        for u, at in deferred.items():
            print("rest on %s@%s not lifted before %s (at most one lift an hour)" % (GLM_PROVIDER, u, hm(at)))
        if switched or swapped:
            print(message(kind, why, ss, a, zw, use, cmds, t, active and provider_off(prov, GLM_PROVIDER),
                          others_lines(active, {"stripped": list(strips.values())} if active else {}, kept, restored),
                          rests, {}, deferred, trial_on))
        return 0
    if missing:
        log("groups missing, left alone: %s" % ", ".join(missing))
    try:
        for c in cmds:
            magpie(c)
            # zcode 归不归守护管，provider on/off 一成功就记：打开时 provider on 成功、后面的 group set 失败，这轮记 FAILED，
            # 下一轮 zcode 已开着、不再跑 provider on，等到全部成功才记就再也记不上，关上后 zcode 一直开着
            # （frontier、always-up 这些组照样用 GLM）
            if c[:2] == ["provider", "on"]:
                state["zcode_by_guard"] = True
            elif c[:2] == ["provider", "off"]:
                state["zcode_by_guard"] = False
            elif tuple(c) in strips:
                # 拿掉别的组的 zcode 成员也是一成功就记：后面哪条失败了，关上或对账时照样能放回原位
                state.setdefault("stripped", []).append(strips[tuple(c)])
        after = read_json(CONF + "/providers.json")
        if any(c[:2] == ["provider", "off"] for c in cmds) and not provider_off(after, GLM_PROVIDER):
            # provider off 退出 0 却没关上：zcode 还是守护开着的，下一轮再关（不然标记已清，它就一直开着，别的组照样用到它）
            state["zcode_by_guard"] = True
            raise RuntimeError("zcode still on after provider off")
        if not aligned(after, use, state, restored):
            raise RuntimeError("providers.json not as expected after the change")
    except Exception as e:
        log("%s | FAILED: %s" % (line, str(e)[:300]))
        if not state.get("failing"):
            state["failing"] = True
            tell("magpie GLM 兜底切换失败（要%s）：%s\n日志 llm-gateway /var/lib/magpie-glm-guard/log。"
                 % ("打开" if want else "关上", str(e)[:300]))
        write_state(statef, state)
        return 1
    state.pop("failing", None)
    state["stripped"] = owed(after, state)
    if not state["stripped"]:
        state.pop("stripped")
    if switched:
        state.update({"open": want, "since": t})
    # 组已经对齐（Trial 在里面）之后再解除：先解除的话，组里还在的 Max 成员可能先被问到、又把账号歇掉
    lifts = {}
    for u in to_lift:
        try:
            lifts[u] = unrest(u)
        except Exception as e:
            lifts[u] = "%s %s" % (type(e).__name__, str(e)[:120])
        if lifts[u] is True:
            state.update({"lift_at": t, "lift_open": open_since})
    log(line + ("" if not cmds else " | ran: " + "; ".join(" ".join(c) for c in cmds))
        + "".join(" | unrest %s@%s: %s (was %s until %s, %s)" % (
            GLM_PROVIDER, u, "lifted" if v is True else "not resting" if v is False else "FAILED " + v,
            rests[u]["why"], hm(rests[u]["until"]), rests[u]["error"][:60]) for u, v in lifts.items())
        + "".join(" | unrest %s@%s: deferred to %s" % (GLM_PROVIDER, u, hm(at)) for u, at in deferred.items()))
    if switched or swapped:
        tell(message(kind, why, ss, a, zw, use, cmds, t, bool(state.get("zcode_by_guard")),
                     others_lines(active, state, kept, restored), rests, lifts, deferred, trial_on))
    write_state(statef, state)
    return 0


def others_lines(opened, state, kept, restored):
    """切换消息里关于别的组的几句"""
    out = []
    held = list(dict.fromkeys(e["group"] for e in state.get("stripped") or []))
    if opened and held:
        out.append("别的组：%s 里的 zcode 成员先拿掉了，守护开着期间只有 claude-* 三个组用得到 zcode；关上时放回原位。"
                   % "、".join(held))
    if opened and kept:
        out.append("没拿掉：%s（拿掉会丢它们自己的设置或把组拿空），这些组在守护开着期间也会用到 zcode。" % "、".join(kept))
    if not opened and restored:
        out.append("别的组：%s 里的 zcode 成员已放回原位。" % "、".join(restored))
    if not opened and held:
        out.append("%s 里拿掉的 zcode 成员要等 zcode 开着才放得回去（magpie 只让开着的 provider 的成员进组），"
                   "下次它开着时守护放回。" % "、".join(held))
    return out


def write_state(path, state):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, path)


def main():
    dry = "--dry-run" in sys.argv
    if dry:
        return run(True)
    os.makedirs(VAR, exist_ok=True)
    with open(VAR + "/lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        return run(False)


if __name__ == "__main__":
    sys.exit(main())
