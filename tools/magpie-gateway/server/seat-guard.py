#!/usr/bin/python3
"""seat-guard - a whitelisted session is answered by Claude, and someone is looking (2026-11-21, gw-route-pr5).

route-all-flash sends a whitelisted session (options.sessions) to the claude provider's own model
(claude/claude-opus-5-5), so once every seat is out, the claude provider's fallback answers it. On 11-18 04:22 +08 that
fallback went from zcode/GLM-5.3 (switched off, so a 429 and the session stops) to devin/claude-opus-5-5 ->
devin/swe-2 -> zcode/GLM-5.3, by a hand edit of providers.json. The seats were out for the week from about 04:00 that
day to 11-21 06:00, Devin's Opus too, and for those 74 hours every whitelisted session got SWE-2: 40 worker
sessions, 6,245 turns, merges and production deploys among them. The off-Claude check that would have said so runs
in the secretary's stuck-sweep on N150, whose cron had been switched off since 11-17 02:42.

So, every 10 minutes (magpie-seat-guard.timer) and with no model in the loop, this checks three things and tells
the secretary (mesh, else the ntfy relay):

  fallback   the claude provider's fallback, groups followed, holds a model that is not claude-* on a provider that
             is switched on: a whitelisted session gets it once the seats are out. Told once per chain, again every
             REPEAT_FALLBACK hours while it stays. A chain someone has decided to accept goes in ALLOW, one per line,
             members separated by spaces, and is then not told.
  offclaude  a whitelisted session answered 200 by a model that is not claude-* in the last WINDOW minutes
             (seat-offclaude). Told once per session every REPEAT_SESSION hours. The secretary's own sessions are left
             out: its groups end in SWE-2 on purpose. A window with no request at all is quiet, not clear: ZERO_BLIND
             hours of such windows count as the check failing.
  sweep      the stuck-sweep has not run seat-offclaude for SWEEP_STALE minutes (its stamp, written by seat-offclaude,
             or since this guard first ran): the off-Claude check here is then the only one, and the sweep that wakes
             or moves sessions stuck at a limit is most likely off too. Told once a spell, again every REPEAT_SWEEP
             hours.

A check that fails FAIL_ROUNDS runs in a row is told once a spell; one failing check does not stop the others.

  seat-guard.py           run the checks (magpie-seat-guard.service)
  seat-guard.py status    print what the checks see now, tell no one
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

PROVIDERS = os.environ.get("SG_PROVIDERS", "/opt/magpie/config/magpie/providers.json")
OFFCLAUDE = os.environ.get("SG_OFFCLAUDE", "/usr/local/bin/seat-offclaude").split()
ASKED = os.environ.get("SG_ASKED", "/var/lib/seat-offclaude/asked-sweep")  # seat-offclaude's stamp of the stuck-sweep's runs
VAR = os.environ.get("SG_VAR", "/var/lib/magpie-seat-guard")
ALLOW = os.environ.get("SG_ALLOW", "/etc/magpie-seat-guard/allow-fallback")
MESH_ENV = os.environ.get("SG_MESH_ENV", "/etc/magpie-glm-guard/mesh.env")
OPS_ENV = os.environ.get("SG_OPS_ENV", "/etc/llm-gateway/ops.env")
TARGETS = os.environ.get("SG_TARGETS", "feishu-assistant,feishu-assistant-backup").split(",")
WINDOW = int(os.environ.get("SG_WINDOW", 15))  # minutes
HOUR = 3600 * 1000
REPEAT_FALLBACK = int(os.environ.get("SG_REPEAT_FALLBACK", 24)) * HOUR
REPEAT_SESSION = int(os.environ.get("SG_REPEAT_SESSION", 2)) * HOUR
REPEAT_SWEEP = int(os.environ.get("SG_REPEAT_SWEEP", 12)) * HOUR
SWEEP_STALE = int(os.environ.get("SG_SWEEP_STALE", 40)) * 60 * 1000
ZERO_BLIND = int(os.environ.get("SG_ZERO_BLIND", 6)) * HOUR  # this long with no request at all in the window reads as blind
FAIL_ROUNDS = int(os.environ.get("SG_FAIL_ROUNDS", 3))
SEAT = "claude"  # the provider route-all-flash sends whitelisted sessions to


def now_ms():
    return int(os.environ.get("SG_NOW") or time.time() * 1000)


def hm(ms):
    return time.strftime("%m-%d %H:%MZ", time.gmtime(ms / 1000))


def env(path):
    out = {}
    with open(path) as f:
        for line in f:
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                out[k] = v
    return out


def http(req, timeout=20):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as r:
        return r.status, r.read()


def tell(text):
    """To the secretary over mesh, else the ntfy relay; SG_TELL=<file> appends there instead (tests)."""
    if os.environ.get("SG_TELL"):
        with open(os.environ["SG_TELL"], "a") as f:
            f.write(text + "\n")
        return "file"
    try:
        cfg = env(MESH_ENV)
        base, auth = cfg["MESH_RELAY_URL"].rstrip("/"), "Bearer " + cfg["MESH_TOKEN"]
        live = json.loads(http(urllib.request.Request(base + "/v1/sessions", headers={"Authorization": auth}))[1])
        for name in TARGETS:
            for s in sorted((s for s in live if s.get("name") == name), key=lambda s: s.get("status") == "reconnecting"):
                data = json.dumps({"to": s["account"], "to_session": s["session_id"], "kind": "chat", "content": text}).encode()
                req = urllib.request.Request(base + "/v1/messages", data=data, method="POST", headers={
                    "Authorization": auth, "Content-Type": "application/json", "x-mesh-sender-name": "seat-guard",
                    "idempotency-key": uuid.uuid4().hex})
                try:
                    if http(req)[0] == 201:
                        return name
                except urllib.error.HTTPError:
                    pass
    except Exception as e:  # noqa: BLE001
        print("mesh failed: %s %s" % (type(e).__name__, str(e)[:160]), flush=True)
    ops = env(OPS_ENV)
    body = json.dumps({"title": "magpie seat-guard", "message": text, "tags": ["magpie"], "priority": 4}).encode()
    req = urllib.request.Request(ops["NTFY_RELAY_URL"], data=body, headers={
        "Authorization": "Bearer " + ops["NTFY_RELAY_TOKEN"], "Content-Type": "application/json"})
    return "ntfy %s" % http(req)[0]


def is_claude(member):
    """provider/model whose model is a Claude one (devin/claude-opus-5-5, kiro/claude-opus-5.5 count)."""
    return member.split("/", 1)[-1].startswith("claude-")


def fallback_chain():
    """(the claude provider's fallback as written, [(member, why)] for each member a whitelisted session could get
    that is not Claude). Groups are followed; a provider switched off ("off": true) answers nothing."""
    with open(PROVIDERS) as f:
        d = json.load(f)
    provs = {p.get("id"): p for p in d.get("providers") or [] if isinstance(p, dict)}
    groups = {g.get("id"): g for g in d.get("groups") or [] if isinstance(g, dict)}
    if SEAT not in provs:
        raise RuntimeError("%s has no provider %r" % (PROVIDERS, SEAT))
    chain = provs[SEAT].get("fallback") or []
    if not isinstance(chain, list):
        raise RuntimeError("the %s provider's fallback is %r, not a list" % (SEAT, chain))
    bad, seen = [], set()

    def walk(m, via):
        if m in seen:
            return
        seen.add(m)
        if m.startswith("group/"):
            g = groups.get(m[len("group/"):])
            if g is None:
                bad.append((m + via, "a group magpie does not list"))
                return
            for x in g.get("members") or []:
                walk(x, " in " + m + via)
            return
        prov = m.split("/", 1)[0]
        if is_claude(m) or (provs.get(prov) or {}).get("off") is True:
            return
        bad.append((m + via, "provider %s is on" % prov if prov in provs else "provider %s unknown" % prov))

    for m in chain:
        walk(str(m), "")
    return chain, bad


def allowed(chain):
    try:
        with open(ALLOW) as f:
            return any(line.split() == chain for line in f if line.strip() and not line.startswith("#"))
    except OSError:
        return False


def check_fallback(st, now):
    chain, bad = fallback_chain()
    key = " ".join(chain)
    f = st.setdefault("fallback", {})
    if not bad or allowed(chain):
        st["fallback"] = {}
        return "fallback ok: %s" % (key or "(none)") + (" (allowed)" if bad else "")
    if f.get("chain") == key and now - f.get("told", 0) < REPEAT_FALLBACK:
        return "fallback not Claude, told %s: %s" % (hm(f["told"]), key)
    how = tell("[seat-guard] 网关 claude 座位的兜底链是「%s」，其中 %s 不是 Claude：座位一满，白名单会话（复审、合并、写生产的 worker）"
               "就会被它悄悄接过去，屏幕上照常在答，transcript 里才看得出不是 Claude（11-18 到 11-21 就这样 74 小时 6,245 个回合落在 "
               "SWE-2）。要恢复成只走 Claude：网关主机上 sudo docker exec magpie-magpie-1 magpie provider fallback claude "
               "devin/claude-opus-5-5（座位满时会 429 停住，等座位恢复由唤醒巡检叫醒）。若确定要接受这条链，把它原样写进 %s 一行，"
               "就不再提醒。"
               % (" → ".join(chain), "、".join("%s（%s）" % b for b in bad), ALLOW))
    st["fallback"] = {"chain": key, "told": now, "how": how}
    return "fallback not Claude, told %s: %s" % (how, key)


def check_offclaude(st, now):
    r = subprocess.run(OFFCLAUDE + ["--minutes", str(WINDOW), "--by", "seat-guard"], capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        raise RuntimeError("seat-offclaude exit %d: %s" % (r.returncode, (r.stderr or r.stdout).strip()[:200]))
    d = json.loads(r.stdout)
    if not d.get("rows"):  # a quiet window or a blind one: fleet-watch's probes alone send some every hour, so hours of 0 are blind
        st["zero_since"] = st.get("zero_since") or now
        if now - st["zero_since"] >= ZERO_BLIND:
            raise RuntimeError("seat-offclaude has seen no requests since %s" % hm(st["zero_since"]))
        return "offclaude 0 rows in %dm (quiet since %s)" % (WINDOW, hm(st["zero_since"]))
    st.pop("zero_since", None)
    told = st.setdefault("sessions", {})
    for s in list(told):
        if now - told[s] >= REPEAT_SESSION:
            del told[s]
    off = [e for e in d.get("sessions") or [] if e.get("listed")]
    new = [e for e in off if e["session"] not in told]
    if new:
        lines = ["%s… %d 回合 %s（%s 到 %s）" % (e["session"][:8], e["turns"], "、".join(sorted(e.get("served") or {})),
                                             e["first"][11:16], e["last"][11:16]) for e in new]
        tell("[seat-guard] 最近 %d 分钟有 %d 个座位白名单里的会话被非 Claude 模型答了：%s。它们做的合并、复审、部署要按规矩 34 停下或补 "
             "Claude 复审。会话名在 N150 上 seat-allow ls 里对；查原因：网关主机 sudo /usr/local/bin/seat-offclaude --minutes 60、"
             "magpie provider fallback claude。" % (WINDOW, len(new), "；".join(lines)))
        for e in new:
            told[e["session"]] = now
    return "offclaude %d listed off Claude, %d new told (window %dm, %d rows)" % (len(off), len(new), WINDOW, d["rows"])


def stamp(path):
    try:
        with open(path) as f:
            return int(f.read().strip() or 0)
    except (OSError, ValueError):
        return 0


def check_sweep(st, now):
    asked = stamp(ASKED)
    anchor = asked or st.get("started", now)  # no stamp yet (just installed): count from this guard's first run
    w = st.setdefault("sweep", {})
    if now - anchor < SWEEP_STALE:
        st["sweep"] = {}
        return "sweep asked %s" % (hm(asked) if asked else "never (guard started %s)" % hm(st.get("started", now)))
    if w.get("since") == anchor and now - w.get("told", 0) < REPEAT_SWEEP:
        return "sweep silent since %s, told %s" % (hm(anchor), hm(w["told"]))
    last = "上次来查是 %s" % hm(asked) if asked else "本检查 %s 装上以来一次都没有" % hm(st["started"])
    tell("[seat-guard] N150 的撞限额巡检（stuck-sweep）%d 分钟没来网关查「白名单会话有没有落到非 Claude」了（%s，正常是 10 分钟一次），"
         "多半是它的定时任务被停了或者跑挂了：这期间停在限额上的会话没人叫醒或迁移，非 Claude 应答只剩网关这一道检查。查：N150 "
         "feishu-cc 容器里 CC_DATA_DIR=/feishu-cc/data cc-connect cron info dda56b65（enabled、last_run）；停用是有意的就把恢复条件和日期"
         "写进笔记，这条每 %d 小时提醒一次。"
         % ((now - anchor) // 60000, last, REPEAT_SWEEP // HOUR))
    st["sweep"] = {"since": anchor, "told": now}
    return "sweep silent since %s, told" % hm(anchor)


CHECKS = (("fallback", check_fallback), ("offclaude", check_offclaude), ("sweep", check_sweep))


def run(quiet=False):
    now = now_ms()
    p = os.path.join(VAR, "state.json")
    try:
        with open(p) as f:
            st = json.load(f)
    except (OSError, ValueError):
        st = {}
    st.setdefault("started", now)
    fails = st.setdefault("fails", {})
    rc = 0
    global tell
    real_tell = tell
    if quiet:
        tell = lambda text: "not told (status)"  # noqa: E731
    try:
        for name, fn in CHECKS:
            try:
                print(fn(st, now), flush=True)
                fails.pop(name, None)
            except Exception as e:  # noqa: BLE001
                rc = 1
                f = fails.get(name) or {}
                f = {"n": f.get("n", 0) + 1, "since": f.get("since") or now, "last": "%s: %s" % (type(e).__name__, str(e)[:200]),
                     "told": f.get("told")}
                fails[name] = f
                print("%s failed (%d in a row): %s" % (name, f["n"], f["last"]), flush=True)
                if f["n"] >= FAIL_ROUNDS and not f["told"]:
                    try:
                        tell("[seat-guard] 网关上「白名单会话只给 Claude」的检查 %s 连续 %d 次失败（自 %s，最近一次：%s），这期间它看不出问题。"
                             "查：网关主机 journalctl -u magpie-seat-guard -n 30。" % (name, f["n"], hm(f["since"]), f["last"]))
                        f["told"] = now
                    except Exception as te:  # noqa: BLE001  (not told: the next failed run tries again)
                        print("tell failed: %s" % te, flush=True)
    finally:
        tell = real_tell
    if not quiet:
        os.makedirs(VAR, exist_ok=True)
        with open(p + ".tmp", "w") as f:
            json.dump(st, f)
        os.replace(p + ".tmp", p)
    return rc


def main(argv):
    if len(argv) == 1:
        return run()
    if argv[1] == "status":
        return run(quiet=True)
    print(__doc__.strip())
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
