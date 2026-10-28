#!/usr/bin/env python3
# fleet-watch（2026-10-27，sunkit tools/magpie-gateway）：magpie 网关各路由组的健康告警，跑在网关本机。
# systemd timer 每 5 分钟跑一次（magpie-fleet-watch.timer）。
#   被动：读 magpie 当天的 routing 日志，看最近 15 分钟每个组回给客户端的结果；
#         失败（不含 499 客户端自己断开）≥3 次且占一半以上 → 告警「坏了」，之后见到成功且失败占比回落 → 告警「恢复」。
#   主动：某个组 60 分钟里一次成功都没有（没人用，或者一直在失败），才发一条极小的真实请求探一下；
#         连续 2 次探测失败也算「坏了」。各组平时都有人用，所以绝大多数时候一条探测都不发。
# 探测用专门的网关 key fleet-watch（日上限 $1 / 2M token，key 归 key-rotate 管），user-agent fleet-watch/1，
# 在 routing 日志里 agent=fleet-watch，每天的探测次数、token、落到哪些 provider 写进 daily.jsonl。
# 告警走 /etc/llm-gateway/ops.env 的 ntfy 中继（和 budget_alert.py 同一条）。
import gzip, json, os, sys, time, urllib.error, urllib.request, uuid
from datetime import datetime, timedelta, timezone

ROUTING = os.environ.get("FW_ROUTING", "/opt/magpie/config/magpie/routing")
VAR = os.environ.get("FW_VAR", "/var/lib/magpie-fleet-watch")
OPS_ENV = os.environ.get("FW_OPS_ENV", "/etc/llm-gateway/ops.env")
KEY_FILE = os.environ.get("FW_KEY", "/etc/llm-gateway/fleet-watch.key")
BASE = os.environ.get("FW_BASE", "http://127.0.0.1:3425")
STATE, DAILY, LOG = VAR + "/state.json", VAR + "/daily.jsonl", VAR + "/log"
TZ = timezone(timedelta(hours=8))  # routing 日志按北京时间分天
GROUPS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1",
          "long-opus", "long-sonnet", "long-haiku", "frontier", "always-up"]
WINDOW = 15 * 60       # 被动统计看最近多久
BAD_N = 3              # 窗口里至少这么多次失败
BAD_RATIO = 0.5        # 且失败占比至少这么多，才算坏
IDLE = 60 * 60         # 一个组这么久没有成功，才主动探
PROBE_FAILS = 2        # 连续几次探测失败算坏
TIMEOUT = 360          # 组内逐个换成员可能要等，探测给足时间（组的首字超时是 300 秒）
BUDGET = 240           # 一轮里探测最多花这么久，没轮到的组下一轮（5 分钟后）再探
AGENT = "fleet-watch"


def log(msg):
    with open(LOG, "a") as f:
        f.write("%s %s\n" % (datetime.now(TZ).strftime("%F %T"), msg))


def env(path):
    out = {}
    with open(path) as f:
        for line in f:
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                out[k] = v
    return out


def push(title, message, priority):
    ops = env(OPS_ENV)
    body = json.dumps({"title": title, "message": message, "tags": ["magpie"], "priority": priority}).encode()
    req = urllib.request.Request(ops["NTFY_RELAY_URL"], data=body, headers={
        "Authorization": "Bearer " + ops["NTFY_RELAY_TOKEN"], "Content-Type": "application/json"})
    try:
        return urllib.request.urlopen(req, timeout=20).status
    except Exception as e:
        log("push failed: %s %s" % (type(e).__name__, str(e)[:120]))
        return 0


def parse_time(s):
    # 2026-10-27T17:13:58.866754539+08:00：纳秒截到微秒，3.9 的 fromisoformat 才认
    return datetime.fromisoformat(s[:26] + s[-6:]).timestamp()


def open_day(day):
    """One day's routing log; magpie gzips the older days (2026-10-26.jsonl.gz)."""
    path = "%s/%s.jsonl" % (ROUTING, day)
    try:
        return open(path)
    except OSError:
        return gzip.open(path + ".gz", "rt")


def records(now):
    """Routing records of the last IDLE seconds (today's file, plus yesterday's near midnight)."""
    days = {datetime.fromtimestamp(now - IDLE, TZ).strftime("%Y-%m-%d"), datetime.fromtimestamp(now, TZ).strftime("%Y-%m-%d")}
    out = []
    for day in sorted(days):
        try:
            f = open_day(day)
        except OSError:
            continue
        with f:
            for line in f:
                try:
                    r = json.loads(line)
                    t = parse_time(r["time"])
                except (ValueError, KeyError):
                    continue
                if now - t <= IDLE:
                    g = r.get("group")
                    r["_g"], r["_t"] = (g.get("id") if isinstance(g, dict) else g), t
                    out.append(r)
    return out


def final(r):
    """'ok' / 'bad' / None (still streaming, or the client walked away) for one request as the client saw it."""
    st = r.get("status")
    if not r.get("done") or st is None or st == 499:
        return None
    return "ok" if 200 <= st < 300 else "bad"


def probe(key, group):
    body = {"model": "group/" + group, "max_tokens": 256,  # 健康探测：答一个词，不是产品调用
            "messages": [{"role": "user", "content": "Health check %s. Reply with the word PONG." % uuid.uuid4().hex[:12]}]}
    req = urllib.request.Request(BASE + "/v1/messages", data=json.dumps(body).encode(), method="POST", headers={
        "x-api-key": key, "content-type": "application/json", "anthropic-version": "2023-06-01", "user-agent": AGENT + "/1"})
    t = time.time()
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=TIMEOUT) as r:
            data = json.loads(r.read() or b"{}")
            return True, "%d %dms served=%s" % (r.status, (time.time() - t) * 1000, data.get("model"))
    except urllib.error.HTTPError as e:
        return False, "%d %dms %s" % (e.code, (time.time() - t) * 1000, e.read(200).decode("utf-8", "replace").replace("\n", " "))
    except Exception as e:
        return False, "0 %dms %s" % ((time.time() - t) * 1000, ("%s %s" % (type(e).__name__, e))[:200])


def daily(st, now, recs):
    """Once a day, record yesterday's probe traffic (ours and the secretary's gw-fallback)."""
    day = datetime.fromtimestamp(now, TZ).strftime("%Y-%m-%d")
    if st.get("daily_for") == day:
        return
    st["daily_for"] = day
    prev = (datetime.fromtimestamp(now, TZ) - timedelta(days=1)).strftime("%Y-%m-%d")
    rows = {}
    try:
        f = open_day(prev)
    except OSError:
        return
    with f:
        for line in f:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("agent") not in (AGENT, "gw-fallback"):
                continue
            row = rows.setdefault(r["agent"], {"requests": 0, "ok": 0, "tokens": 0, "out": 0, "providers": {}})
            row["requests"] += 1
            row["ok"] += final(r) == "ok"
            row["tokens"] += r.get("tokens") or 0
            row["out"] += r.get("out") or 0
            for u in r.get("usage") or []:
                p = u.get("provider") or "?"
                row["providers"][p] = row["providers"].get(p, 0) + (u.get("in") or 0) + (u.get("out") or 0) + (u.get("cache_read") or 0) + (u.get("cache_write") or 0)
    with open(DAILY, "a") as f:
        f.write(json.dumps({"day": prev, **rows}, ensure_ascii=False) + "\n")


def main():
    os.makedirs(VAR, exist_ok=True)
    now = time.time()
    try:
        with open(STATE) as f:
            st = json.load(f)
    except (OSError, ValueError):
        st = {}
    groups = st.setdefault("groups", {})
    recs = records(now)
    try:
        daily(st, now, recs)
    except Exception as e:
        log("daily failed: %s" % e)

    try:
        with open(KEY_FILE) as f:
            key = f.read().strip()
    except OSError:
        key = ""
        if not st.get("no_key"):
            log("no probe key at %s: passive only" % KEY_FILE)
        st["no_key"] = True
    else:
        st["no_key"] = False

    view = {}
    for g in GROUPS:
        mine = [r for r in recs if r["_g"] == g]
        win = [final(r) for r in mine if now - r["_t"] <= WINDOW]
        ok_times = [r["_t"] for r in mine if final(r) == "ok"]
        view[g] = {"ok": win.count("ok"), "bad": win.count("bad"), "last_ok": max(ok_times) if ok_times else 0,
                   "errors": [(r.get("status"), (r.get("error") or "")[:100]) for r in mine if now - r["_t"] <= WINDOW and final(r) == "bad"][-3:]}

    # 主动探测：只探 60 分钟没成功过、且离上次探测满 60 分钟的组；坏了或探测失败中则每轮都探，直到见到成功。
    # 一个接一个地探：座位都满了的时候各组都落到同一个付费兜底（GLM-5 那把 key 只许 12 个并发），
    # 10-27 17:21 六个探测同时发，自己就顶出了 429，还连带了客户端
    todo = []
    for g in GROUPS:
        s = groups.setdefault(g, {"down": False, "probe_fails": 0, "last_probe": 0})
        if view[g]["last_ok"] > s["last_probe"]:
            s["probe_fails"] = 0  # 探测之后客户端已经成功过，旧的探测失败不算数了
        if s["down"] and view[g]["last_ok"] > s.get("down_since", 0):
            continue  # 坏了之后客户端已经成功过，等被动统计判恢复，不用探
        idle = now - view[g]["last_ok"] >= IDLE
        if key and (idle or s["down"]) and (s["probe_fails"] or s["down"] or now - s["last_probe"] >= IDLE):
            todo.append(g)
    for g in todo:
        if time.time() - now > BUDGET:
            log("probe budget spent, left for the next run: %s" % " ".join(todo[todo.index(g):]))
            break
        ok, detail = probe(key, g)
        s = groups[g]
        s["last_probe"] = now
        s["probe_fails"] = 0 if ok else s["probe_fails"] + 1
        if ok:
            view[g]["last_ok"] = now
        log("probe %s %s %s" % (g, "ok" if ok else "FAIL", detail))
        if not ok:
            s["last_probe_error"] = detail[:160]

    for g in GROUPS:
        s, v = groups[g], view[g]
        bad_now = (v["bad"] >= BAD_N and v["bad"] >= BAD_RATIO * (v["ok"] + v["bad"])) or s["probe_fails"] >= PROBE_FAILS
        if bad_now and not s["down"]:
            s["down"], s["down_since"] = True, now
            why = ("最近 15 分钟回给客户端 %d 次失败、%d 次成功" % (v["bad"], v["ok"])) if v["bad"] >= BAD_N else \
                ("连续 %d 次探测失败：%s" % (s["probe_fails"], s.get("last_probe_error", "")))
            sample = "；".join("%s %s" % e for e in v["errors"])
            push("magpie 分组 %s 坏了" % g, why + ("。最近的错误：" + sample if sample else ""), 4)
            log("down %s: %s" % (g, why))
        elif s["down"] and not bad_now and v["last_ok"] > s.get("down_since", 0):
            minutes = int((now - s.get("down_since", now)) / 60)
            s["down"] = False
            push("magpie 分组 %s 恢复" % g, "又有成功的请求了；坏了约 %d 分钟。" % minutes, 2)
            log("up %s after %d min" % (g, minutes))

    st["last_run"] = now
    with open(STATE + ".tmp", "w") as f:
        json.dump(st, f)
    os.replace(STATE + ".tmp", STATE)


if __name__ == "__main__":
    main()
