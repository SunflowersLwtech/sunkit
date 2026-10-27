#!/usr/bin/env python3
# gw-fallback（2026-10-27，sunkit tools/magpie-gateway）：飞书秘书的网关兜底。
# 秘书钉在 provider=magpie（刘维 10-26 定）；网关一挂，秘书就整段失联（10-26/27 两次整夜）。
# 这里每 5 分钟用秘书自己的网关 key 发一个最小的真实请求（和秘书同一个模型名、同一条网络路径；
# 网关上 Opus 座位答一个词约 25 秒、约 1.7K token，一天 288 次约 0.5M 座位 token），出现失败后改为每分钟探，
#   连续 3 次失败 → 写标记 gw-fallback/direct（内容 = 失败的网关地址），ntfy 告警；
#     claude-bypass 看到标记就去掉网关的环境变量，新起的秘书进程直连容器里登录的席位；
#     秘书空闲时（最后一条是 turn complete 且 60 秒没动静）结束还连着网关的那个 claude 进程，
#     cc-connect 在下一条消息时用 --resume 原样接上；网关挂满 20 分钟仍不空闲就直接结束它。
#   直连期间每分钟探一次，连续 5 次正常 → 删标记、ntfy 告知，空闲时让直连进程重起、回到网关。
# 不改 config.toml、不重启 cc-connect 或容器；provider 不是 magpie 时只探测、不切换。
# 宿主机 cron 每分钟跑 gw-fallback.n150.sh，它把 feishu-cc 最近的日志从 stdin 喂进来，
# 并把这里打印的 NOTIFY 行交给 /opt/data/sre/notify.sh。日志 gw-fallback/log，状态 gw-fallback/state.json。
import json, os, re, signal, sys, time, tomllib, urllib.error, urllib.request, uuid
from datetime import datetime

HOME = os.environ.get("GWF_HOME", "/feishu-cc")
PROC = os.environ.get("GWF_PROC", "/proc")
DIR = HOME + "/gw-fallback"
STATE, FLAG, LOG = DIR + "/state.json", DIR + "/direct", DIR + "/log"
CFG = HOME + "/config.toml"
FAIL_N, OK_N = 3, 5   # 连续失败几次切直连、连续正常几次切回
EVERY = 290           # 一切正常时两次探测的间隔（秒）；失败中或直连中每分钟探
TIMEOUT = 120         # 网关这么久没答完就算失败（座位正常约 25 秒）
IDLE = 60             # 最后一回合结束后这么久没新动静才算空闲
FORCE = 20 * 60       # 网关挂了这么久仍不空闲，就不等了


def log(msg):
    with open(LOG, "a") as f:
        f.write("%s %s\n" % (datetime.now().strftime("%F %T"), msg))


DRILL = [False]  # 演练：state.json 里 drill=true 时通知标题加「【演练】」，切回网关后自动清掉


def notify(title, body, prio=3):
    title = ("【演练】" if DRILL[0] else "") + title
    print("NOTIFY\t%s\t%s\t%d" % (title, body.replace("\n", " "), prio), flush=True)


def gateway():
    """(base_url, headers, model, active provider) of the magpie provider in config.toml, or None."""
    cfg = tomllib.load(open(CFG, "rb"))
    for proj in cfg.get("projects", []):
        agent = proj.get("agent") or {}
        opts = agent.get("options") or {}
        for p in agent.get("providers", []):
            if p.get("name") != "magpie" or not p.get("base_url"):
                continue
            headers = {}
            for line in str((p.get("env") or {}).get("ANTHROPIC_CUSTOM_HEADERS") or "").splitlines():
                k, sep, v = line.partition(":")
                if sep and k.strip():
                    headers[k.strip()] = v.strip()
            if p.get("api_key"):
                headers["Authorization"] = "Bearer " + p["api_key"]
            return p["base_url"].rstrip("/"), headers, opts.get("model") or p.get("model") or "claude-opus-5-5", opts.get("provider")
    return None


def probe(base, headers, model):
    """One small real request, the kind the secretary sends. -> (ok, status, ms, detail)"""
    body = {"model": model, "max_tokens": 64,  # 只是健康探测：答一个词，不是产品调用
            "messages": [{"role": "user", "content": "Health check %s. Reply with the word PONG." % uuid.uuid4().hex[:12]}]}
    req = urllib.request.Request(base + "/v1/messages", data=json.dumps(body).encode(), method="POST", headers={
        **headers, "content-type": "application/json", "anthropic-version": "2023-06-01", "user-agent": "gw-fallback/1"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 和秘书的 claude 一样不走代理
    t = time.time()
    try:
        with opener.open(req, timeout=TIMEOUT) as r:
            data = json.loads(r.read() or b"{}")
            return True, r.status, int((time.time() - t) * 1000), "served=%s" % data.get("model")
    except urllib.error.HTTPError as e:
        return False, e.code, int((time.time() - t) * 1000), e.read(200).decode("utf-8", "replace").replace("\n", " ")
    except Exception as e:
        return False, 0, int((time.time() - t) * 1000), ("%s %s" % (type(e).__name__, e))[:200]


LINE = re.compile(r'^time=(\S+) .*?msg="(message received|processing message|turn complete|timer: job failed)"(.*)$')


def idle(lines, now):
    """True when the secretary's last activity is a finished turn at least IDLE seconds old."""
    last = None
    for line in lines:
        m = LINE.match(line)
        if not m or (m.group(2) == "timer: job failed" and "is busy" not in m.group(3)):
            continue
        try:
            ts = datetime.fromisoformat(m.group(1)).timestamp()
        except ValueError:
            continue
        kind = "busy" if m.group(2) == "timer: job failed" else m.group(2)
        last = (kind, ts)
    if last is None:
        return True
    return last[0] == "turn complete" and now - last[1] >= IDLE


def secretary_procs(base):
    """[(pid, 'gateway'|'direct'|'other')] for the claude processes cc-connect started."""
    def read(pid, name):
        try:
            with open("%s/%s/%s" % (PROC, pid, name), "rb") as f:
                return f.read()
        except OSError:
            return b""
    pids = [d for d in os.listdir(PROC) if d.isdigit()]
    cc = {d for d in pids if read(d, "cmdline").split(b"\0")[0].endswith(b"/cc-connect")}
    out = []
    for d in pids:
        status = read(d, "status").decode("utf-8", "replace")
        name = re.search(r"^Name:\s*(\S+)", status, re.M)
        ppid = re.search(r"^PPid:\s*(\d+)", status, re.M)
        if not name or name.group(1) != "claude" or not ppid or ppid.group(1) not in cc:
            continue
        env = read(d, "environ").split(b"\0")
        if b"GW_FALLBACK_DIRECT=1" in env:
            out.append((int(d), "direct"))
        elif b"ANTHROPIC_BASE_URL=" + base.encode() in env:
            out.append((int(d), "gateway"))
        else:
            out.append((int(d), "other"))
    return out


def main():
    os.makedirs(DIR, exist_ok=True)
    now = time.time()
    lines = sys.stdin.read().splitlines() if not sys.stdin.isatty() else []
    try:
        st = json.load(open(STATE))
    except (OSError, ValueError):
        st = {}
    st.setdefault("mode", "gateway")
    for k in ("fails", "oks", "last_probe", "down_since"):
        st.setdefault(k, 0)
    st.setdefault("pending", None)
    DRILL[0] = bool(st.get("drill"))

    try:
        gw = gateway()
    except Exception as e:
        gw = None
        log("config unreadable: %s" % e)
    if not gw:
        if not st.get("no_config"):
            notify("秘书网关兜底停了", "config.toml 里找不到 magpie provider，gw-fallback 没法探测", 4)
        st["no_config"] = True
        json.dump(st, open(STATE, "w"))
        return
    st["no_config"] = False
    base, headers, model, active = gw
    pinned = active == "magpie"

    if st["mode"] == "direct" or st["fails"] or now - st["last_probe"] >= EVERY:
        ok, status, ms, detail = probe(base, headers, model)
        st["last_probe"] = now
        log("probe %s %s %dms %s" % ("ok" if ok else "FAIL", status, ms, detail))
        if ok:
            st["fails"], st["oks"] = 0, st["oks"] + 1
            st["down_since"] = 0
        else:
            st["fails"], st["oks"] = st["fails"] + 1, 0
            st["down_since"] = st["down_since"] or now
            st["last_error"] = "%s %s" % (status, detail[:120])

        if st["mode"] == "gateway" and st["fails"] >= FAIL_N:
            st["mode"], st["since"] = "direct", now
            if pinned:
                with open(FLAG + ".tmp", "w") as f:
                    f.write(base)
                os.replace(FLAG + ".tmp", FLAG)
                st["pending"] = "direct"
            notify("秘书的网关不通，已切直连席位" if pinned else "秘书的网关不通",
                   "网关连续 %d 次探测失败（最近一次：%s）。%s" % (
                       FAIL_N, st["last_error"],
                       "秘书空闲时换成直连本机席位接着同一段对话；网关恢复后自动切回。" if pinned else "秘书现在的 provider 是 %s，没有切换。" % active), 4)
            log("switch -> direct (pinned=%s)" % pinned)
        elif st["mode"] == "direct" and st["oks"] >= OK_N:
            minutes = int((now - st.get("since", now)) / 60)
            st["mode"] = "gateway"
            if os.path.exists(FLAG):
                os.remove(FLAG)
                st["pending"] = "gateway"
            notify("网关恢复，秘书切回网关", "连续 %d 次探测正常；直连持续了约 %d 分钟。秘书空闲时切回。" % (OK_N, minutes), 2)
            log("switch -> gateway after %d min" % minutes)

    if st["pending"]:
        want = st["pending"]
        wrong = [pid for pid, mode in secretary_procs(base) if mode == ("gateway" if want == "direct" else "direct")]
        if not wrong:  # 已经没有走错路的进程（结束了，或本来就没有）才算办完
            log("pending %s: done" % want)
            st["pending"], st["forced_note"] = None, False
            if want == "gateway":
                st["drill"] = False
        else:
            free = idle(lines, now)
            force = want == "direct" and st["down_since"] and now - st["down_since"] >= FORCE
            if free or force:
                for pid in wrong:
                    log("pending %s: SIGTERM %d (%s)" % (want, pid, "idle" if free else "forced"))
                    try:
                        os.kill(pid, signal.SIGTERM)
                    except OSError as e:
                        log("pending %s: kill %d failed: %s" % (want, pid, e))
                if force and not free and not st.get("forced_note"):
                    notify("秘书进程被强制重起", "网关已挂满 %d 分钟、秘书一直没空闲；已结束还连着网关的进程，下一条消息直连接上。排队中的消息可能要重发。" % (FORCE // 60), 4)
                    st["forced_note"] = True
            else:
                log("pending %s: busy, waiting" % want)

    json.dump(st, open(STATE + ".tmp", "w"))
    os.replace(STATE + ".tmp", STATE)


if __name__ == "__main__":
    main()
