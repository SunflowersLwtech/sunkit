#!/usr/bin/python3
"""pool-watch - while magpie's Claude Code pool is full, the leased secretary skips the seats (2026-11-16, seat-fix3).

magpie runs at most claudeRunsMost Claude Code processes (18 here). One more waits for room up to 2 minutes
(claudeRoomWait, fixed in internal/gateway/claude_room.go) and only then does its group try the next member. The
secretary's group/secretary-seat starts with the seats, so on 11-16 01:56-02:12Z its turns waited 2 minutes each
and then landed on SWE-2. magpie has no per-caller reserve, so this follows the gateway's log and, on a
"... waits for room" or "found no room" line, sets route-all-flash's options.poolFullUntil HOLD seconds ahead
(renewed while such lines keep coming). Meanwhile the middleware sends the leased secretary to group/flash-paid
(Devin Opus, the Team API lane, then the seats). The value runs out by itself, so a dead watcher leaves nothing
on. The first secretary turn of a full spell still waits: the line it causes is what this reads.

Self-check (magpie-pool-watch-check.timer, every 10 minutes): this matches one fixed sentence of magpie's log, so a
reworded line would turn the bypass off without a sound. `selfcheck` counts the Claude Code processes in the container
(their binary is .../claude-code/<version>/claude), and when the pool was full at some point since the last match while
no line has matched for 24 hours (or the watcher has not run), it tells the secretary once (mesh, else ntfy).

  pool-watch.py              follow the log (magpie-pool-watch.service)
  pool-watch.py set <secs>   set it by hand (drills); pool-watch.py clear; pool-watch.py status
  pool-watch.py selfcheck    the 24-hour self-check
"""
import fcntl
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

CONTAINER = os.environ.get("PW_CONTAINER", "magpie-magpie-1")
MAGPIE = os.environ.get("PW_MAGPIE", "docker exec %s magpie" % CONTAINER).split()
LOGS = os.environ.get("PW_LOGS", "docker logs -f --since 1s %s" % CONTAINER).split()
NAME = "/plugins/route-all-flash.middleware.js"
LOCK = os.environ.get("PW_LOCK", "/var/lock/magpie-seat-allow.lock")  # shared with seat-allow-core and secretary-seat.py
HOLD_MS = int(os.environ.get("PW_HOLD", 300)) * 1000    # how long one sighting keeps the bypass on
RENEW_MS = int(os.environ.get("PW_RENEW", 240)) * 1000  # write again only when less than this is left
LINE = re.compile(r"claude: .*(?: waits for room: \d+ Claude Code processes run| found no room in )")
VAR = os.environ.get("PW_VAR", "/var/lib/magpie-pool-watch")  # last-match, started, selfcheck.json
TOP = os.environ.get("PW_TOP", "docker top %s -eo pid,args" % CONTAINER).split()  # docker top refuses a ps format without pid
SETTINGS = os.environ.get("PW_SETTINGS", "/opt/magpie/config/magpie/settings.json")
MESH_ENV = os.environ.get("PW_MESH_ENV", "/etc/magpie-glm-guard/mesh.env")
OPS_ENV = os.environ.get("PW_OPS_ENV", "/etc/llm-gateway/ops.env")
TARGETS = os.environ.get("PW_TARGETS", "feishu-assistant,feishu-assistant-backup").split(",")
DAY_MS = int(os.environ.get("PW_QUIET", 24 * 3600)) * 1000
CLAUDE_BIN = re.compile(r"/claude-code/[^/\s]+/claude$")  # a Claude Code process; magpie's own helpers that wrap one are not


def stamp(name, ms=None, only_if_absent=False):
    """Writes (or reads, with ms None) a millisecond time in VAR/name."""
    p = os.path.join(VAR, name)
    if ms is None:
        try:
            with open(p) as f:
                return int(f.read().strip() or 0)
        except (OSError, ValueError):
            return 0
    if only_if_absent and os.path.exists(p):
        return stamp(name)
    os.makedirs(VAR, exist_ok=True)
    with open(p + ".tmp", "w") as f:
        f.write(str(int(ms)))
    os.replace(p + ".tmp", p)
    return int(ms)


def magpie(*args):
    r = subprocess.run(MAGPIE + list(args), capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError("magpie %s: %s" % (args[0], (r.stderr or r.stdout).strip()[:200]))
    return r.stdout


def set_until(until):
    """Writes options.poolFullUntil (0 clears it) under the lock, keeping every other key; returns what reads back."""
    with open(LOCK, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        opts = json.loads(magpie("plugin", "options", NAME))
        before = {k: v for k, v in opts.items() if k != "poolFullUntil"}
        if until:
            opts["poolFullUntil"] = until
        else:
            opts.pop("poolFullUntil", None)
        magpie("plugin", "options", NAME, json.dumps(opts))
        back = json.loads(magpie("plugin", "options", NAME))
        if {k: v for k, v in back.items() if k != "poolFullUntil"} != before or back.get("poolFullUntil", 0) != (until or 0):
            raise RuntimeError("read-back differs")
        return back.get("poolFullUntil", 0)


def follow():
    until = noted = 0
    try:  # the self-check's bookkeeping: failing it must never stop the bypass itself
        stamp("started", int(time.time() * 1000), only_if_absent=True)
    except OSError as e:
        print("started stamp: %s" % e, flush=True)
    p = subprocess.Popen(LOGS, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace", bufsize=1)
    for line in p.stdout:
        if not LINE.search(line):
            continue
        now = int(time.time() * 1000)
        if now - noted > 60_000:  # for the self-check: when a line last matched, at most one write a minute
            try:
                noted = stamp("last-match", now)
            except OSError as e:
                noted = now
                print("last-match stamp: %s" % e, flush=True)
        if until - now > RENEW_MS:
            continue
        try:
            until = set_until(now + HOLD_MS)
            print("pool full: %s; secretary bypass until %s" % (line.strip()[20:140], time.strftime("%H:%M:%SZ", time.gmtime(until / 1000))),
                  flush=True)
        except Exception as e:  # noqa: BLE001
            print("set failed: %s" % e, flush=True)
    return p.wait() or 1  # the log ended (container restarted): systemd starts us again


def claude_runs():
    """(Claude Code processes running in the container, claudeRunsMost)."""
    r = subprocess.run(TOP, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError("process list: %s" % (r.stderr or r.stdout).strip()[:200])
    n = sum(1 for l in r.stdout.splitlines()[1:] if len(l.split()) > 1 and CLAUDE_BIN.search(l.split()[1]))  # PID then the command
    try:
        with open(SETTINGS) as f:
            most = int(json.load(f).get("claudeRunsMost") or 18)
    except (OSError, ValueError):
        most = 18
    return n, most


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
    """To the secretary over mesh, else the ntfy relay; PW_TELL=<file> appends there instead (tests)."""
    if os.environ.get("PW_TELL"):
        with open(os.environ["PW_TELL"], "a") as f:
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
                    "Authorization": auth, "Content-Type": "application/json", "x-mesh-sender-name": "pool-watch",
                    "idempotency-key": uuid.uuid4().hex})
                try:
                    if http(req)[0] == 201:
                        return name
                except urllib.error.HTTPError:
                    pass
    except Exception as e:  # noqa: BLE001
        print("mesh failed: %s %s" % (type(e).__name__, str(e)[:160]), flush=True)
    ops = env(OPS_ENV)
    body = json.dumps({"title": "magpie pool-watch", "message": text, "tags": ["magpie"], "priority": 4}).encode()
    req = urllib.request.Request(ops["NTFY_RELAY_URL"], data=body, headers={
        "Authorization": "Bearer " + ops["NTFY_RELAY_TOKEN"], "Content-Type": "application/json"})
    return "ntfy %s" % http(req)[0]


def selfcheck():
    now = int(time.time() * 1000)
    p = os.path.join(VAR, "selfcheck.json")
    try:
        with open(p) as f:
            st = json.load(f)
    except (OSError, ValueError):
        st = {}
    n, most = claude_runs()
    if n >= most:
        st["last_full"] = now
    anchor = max(stamp("last-match"), stamp("started"))  # quiet since the last match, or since the watcher first ran
    hm = lambda ms: time.strftime("%m-%d %H:%MZ", time.gmtime(ms / 1000))  # noqa: E731
    due = bool(anchor) and now - anchor >= DAY_MS and st.get("last_full", 0) > anchor and st.get("alerted_for") != anchor
    if due:
        how = tell("[pool-watch] magpie 的 Claude Code 进程池 %s 之后满过（最近一次 %s，%d/%d），但池满监视器自 %s 起一次都没认出"
                   "「waits for room」日志：多半是 magpie 改了这句日志的写法，或者监视器没在跑。这期间秘书池满时的插队不生效。"
                   "查：网关主机上 systemctl status magpie-pool-watch；docker logs magpie-magpie-1 | grep -i room 看现在的原文，"
                   "照着改 /opt/magpie/monitor/pool-watch.py 的 LINE（源码 sunkit tools/magpie-gateway/server/pool-watch.py）。"
                   % (hm(anchor), hm(st["last_full"]), n, most, hm(anchor)))
        st["alerted_for"] = anchor
        st["alerted_at"] = now
        st["told"] = how
    os.makedirs(VAR, exist_ok=True)
    with open(p + ".tmp", "w") as f:
        json.dump(st, f)
    os.replace(p + ".tmp", p)
    print("runs %d/%d, last match %s, last full %s, %s" % (n, most, hm(anchor) if anchor else "never",
          hm(st["last_full"]) if st.get("last_full") else "never", "told " + st["told"] if due else "quiet"))
    return 0


def main(argv):
    if len(argv) == 1:
        return follow()
    if argv[1] == "selfcheck":
        return selfcheck()
    if argv[1] == "set" and len(argv) == 3:
        print(set_until(int(time.time() * 1000) + int(argv[2]) * 1000))
        return 0
    if argv[1] == "clear":
        print(set_until(0))
        return 0
    if argv[1] == "status":
        u = json.loads(magpie("plugin", "options", NAME)).get("poolFullUntil", 0)
        left = (u - time.time() * 1000) / 1000
        print("on, %ds left" % left if left > 0 else "off")
        return 0
    print(__doc__.strip())
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
