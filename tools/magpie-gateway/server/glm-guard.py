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

GLM = {"claude-opus-5-5": "zcode/GLM-5.3", "claude-sonnet-5-5": "zcode/GLM-5.3",
       "claude-haiku-5-5": "zcode/GLM-5.3-Flash"}
GLM_PROVIDER = "zcode"
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
    if not s:
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


def plan(prov, want_open, state):
    """把 providers.json 对齐到 want_open 要跑的 magpie 命令。还给出不能拿的 zcode 成员，和每条拿掉别的组 zcode 成员的
    命令要记下的位置。打开：先拿掉别的组的 zcode 成员，再 provider on，再往 claude-* 加；关上：先从 claude-* 拿掉，再把
    别的组的成员放回原位，最后 provider off"""
    cmds, missing, kept, strips = [], [], [], {}
    zoff = provider_off(prov, GLM_PROVIDER)
    if want_open and (zoff or state.get("zcode_by_guard")):
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
    if want_open and zoff:
        cmds.append(["provider", "on", GLM_PROVIDER])
    for gid, m in GLM.items():
        ms = members(prov, gid)
        if ms is None:
            missing.append(gid)
        elif want_open and m not in ms:
            cmds.append(["group", "set", gid, "models+=" + m])
        elif not want_open and m in ms:
            cmds.append(["group", "set", gid, "models-=" + m])
    if not want_open and not zoff:
        cmds += restores(prov, state)
    if not want_open and state.get("zcode_by_guard") and not zoff:
        cmds.append(["provider", "off", GLM_PROVIDER])
    return cmds, missing, kept, strips


def aligned(prov, want_open, state=None, restored=()):
    """读回核对：claude-* 的 GLM 成员对上；开着时 zcode 开着，zcode 是守护开的就别的组里能拿的都拿掉了；关着时 zcode
    开着就没有欠着没放回的成员，这轮放回过的组都放回了"""
    state = state or {}
    for gid, m in GLM.items():
        ms = members(prov, gid)
        if ms is not None and (m in ms) != want_open:
            return False
    zoff = provider_off(prov, GLM_PROVIDER)
    if want_open:
        return not zoff and not (state.get("zcode_by_guard") and any(ok for _, _, ok in holders(prov)))
    return not any(not zoff or e["group"] in restored for e in owed(prov, state))


def magpie(args):
    p = subprocess.run(MAGPIE + args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
    if p.returncode != 0:
        raise RuntimeError("magpie %s: exit %d: %s" % (" ".join(args), p.returncode,
                                                       p.stdout.decode("utf-8", "replace").strip()[:200]))


def zcode_line(history, t):
    parts = []
    for k, v in history.items():
        if not k.startswith(GLM_PROVIDER + "|"):
            continue
        for name in ("5 hours", "Weekly"):
            pts = v.get(name) or []
            if pts and pts[-1].get("left") is not None:
                r = parse_time(pts[-1].get("resetsAt"))
                parts.append("%s 剩 %g%%%s" % ("5 小时" if name == "5 hours" else "周", round(float(pts[-1]["left"]), 1),
                                               "（%s 重置）" % hm(r) if r and r > t else ""))
    return "、".join(parts)


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


def message(opened, why, ss, a, history, zcode_on, t, others=()):
    if opened:
        if why == "low":
            head = "magpie 已自动打开 GLM 兜底：Claude 座位都只剩不到 %d%%%s，座位到上限后的请求改落 ZCode GLM。" % (
                LOW, "（读不到的按没有余量算）" if any(s["unread"] for s in ss) else "")
        else:
            head = "magpie 已自动打开 GLM 兜底：按最近 30 分钟的速度，Claude 座位约 %s 到上限%s，之后的请求改落 ZCode GLM。" % (
                hm(t + a["to_empty"] * 60), "，早于最早一次重置 %s" % hm(a["first_reset"]) if a["first_reset"] else "")
    else:
        b = max(a["back"], key=lambda s: s["left"])
        head = "magpie 已自动关上 GLM 兜底：%s 座位剩 %g%%，claude-* 组回到只用 Claude。" % (
            b["user"].replace(" · DuoCode", ""), round(b["left"], 1))
    lines = [head, "", "座位："] + ["- " + x for x in seat_lines(ss)]
    lines.append("最近 30 分钟每分钟用掉约 %.1f 个百分点，到上限前还有 %.0f 个百分点%s。" % (
        a["rate"], a["headroom"], "，约 %.0f 分钟用完" % a["to_empty"] if a["to_empty"] is not None else ""))
    z = zcode_line(history, t)
    if z:
        lines.append("ZCode：" + z + "。")
    if opened:
        lines.append("改动：claude-opus-5-5、claude-sonnet-5-5 末尾加 zcode/GLM-5.3，claude-haiku-5-5 末尾加 zcode/GLM-5.3-Flash"
                     + ("；zcode provider 原来关着，已打开" if zcode_on else "") + "。")
    else:
        lines.append("改动：三个组里的 zcode GLM 成员已拿掉" + ("；guard 打开的 zcode provider 已关回" if zcode_on else "") + "。")
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
        # 第一次跑：按组里现在有没有 GLM 定初始状态，不算一次切换
        state = {"open": aligned(prov, True) and any(GLM[g] in (members(prov, g) or []) for g in GLM), "since": 0}
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
    cmds, missing, kept, strips = plan(prov, want, state)
    restored = [c[2] for c in cmds if c[:2] == ["group", "set"] and c[3].startswith("models=")]
    line = "%s -> %s (%s) | %s%s" % ("open" if state.get("open") else "closed", "open" if want else "closed", why,
                                     summary(ss, a), " | zcode left alone in: " + ", ".join(kept) if kept else "")
    if dry:
        print(line)
        for c in cmds:
            print("would run: magpie " + " ".join(c))
        if want != bool(state.get("open")):
            print(message(want, why, ss, a, history, want and provider_off(prov, GLM_PROVIDER), t,
                          others_lines(want, {"stripped": list(strips.values())} if want else {}, kept, restored)))
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
        if not aligned(after, want, state, restored):
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
    switched = want != bool(state.get("open"))
    if switched:
        state.update({"open": want, "since": t})
    log(line + ("" if not cmds else " | ran: " + "; ".join(" ".join(c) for c in cmds)))
    if switched:
        tell(message(want, why, ss, a, history, (bool(state.get("zcode_by_guard")) if want
                                                 else bool(cmds and cmds[-1][:2] == ["provider", "off"])), t,
                     others_lines(want, state, kept, restored)))
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
