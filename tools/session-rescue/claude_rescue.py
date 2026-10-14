#!/usr/bin/env python3
"""
claude_rescue.py - find and restart Claude Code sessions stuck on API connection errors.

Symptom: one long-running interactive `claude` session answers every request with
`API Error: Connection refused ... (ECONNREFUSED)` (or ECONNRESET / ETIMEDOUT)
while other sessions on the same machine work fine. Exiting that session and
resuming it with `claude --resume <sessionId>` brings it back with its history.

Commands:
    scan                     list live sessions and flag the stuck ones (default)
    revive <name|pid|id>     /exit the session in its terminal pane and resume it
    revive --all-stuck       revive every session that scan marks STUCK
    watch                    periodic scan; with --auto, revive stuck sessions

Pane control works through herdr or tmux. Pure Python 3 standard library.
"""

import argparse
import datetime as dt
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

DEFAULT_PROMPT = (
    "The previous session hit repeated API connection errors and was restarted; "
    "continue where you left off."
)
EXIT_DIALOG_MARKER = "Exit and stop tasks"
STUCK_MIN_ERRORS = 2

# (kind, regex) checked in order against the text of an "API Error:" message.
ERROR_KINDS = [
    ("ECONNREFUSED", re.compile(r"ECONNREFUSED|connection refused", re.I)),
    ("ECONNRESET", re.compile(r"ECONNRESET|connection reset|socket hang up", re.I)),
    ("ETIMEDOUT", re.compile(r"ETIMEDOUT|timed? ?out", re.I)),
    ("ENOTFOUND", re.compile(r"ENOTFOUND|EAI_AGAIN|getaddrinfo", re.I)),
    ("EPIPE", re.compile(r"EPIPE|broken pipe", re.I)),
    ("connection", re.compile(r"connection error|fetch failed|network", re.I)),
    ("overloaded", re.compile(r"overloaded|\b529\b", re.I)),
    ("rate_limit", re.compile(r"rate.?limit|\b429\b", re.I)),
    ("auth", re.compile(r"\b401\b|\b403\b|auth|login", re.I)),
    ("server", re.compile(r"\b5\d\d\b|internal server error", re.I)),
]
# Kinds that point at the local connection rather than the API as a whole.
CONNECTION_KINDS = {"ECONNREFUSED", "ECONNRESET", "ETIMEDOUT", "ENOTFOUND", "EPIPE", "connection"}


# ---------------------------------------------------------------- paths

def claude_dir():
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")


def sessions_dir():
    return os.path.join(claude_dir(), "sessions")


def projects_dir():
    return os.path.join(claude_dir(), "projects")


def parse_version(v):
    try:
        return tuple(int(x) for x in str(v).split("."))
    except ValueError:
        return None


def installed_version():
    """Version the `claude` launcher currently points at, else the newest installed."""
    link = os.path.expanduser("~/.local/bin/claude")
    if os.path.islink(link):
        target = os.path.basename(os.path.realpath(link))
        if parse_version(target):
            return target
    vdir = os.path.expanduser("~/.local/share/claude/versions")
    versions = [v for v in os.listdir(vdir) if parse_version(v)] if os.path.isdir(vdir) else []
    return max(versions, key=parse_version) if versions else None


def find_transcript(session_id):
    """Top-level <sessionId>.jsonl; the same id can live under several project dirs."""
    paths = glob.glob(os.path.join(glob.escape(projects_dir()), "*", glob.escape(session_id) + ".jsonl"))
    return max(paths, key=os.path.getmtime) if paths else None


# ---------------------------------------------------------------- processes

def run(cmd, timeout=10):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.stdout if p.returncode == 0 else None


def pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def proc_start_utc(pid):
    # Session files record procStart in UTC; ps prints lstart in local time.
    env = dict(os.environ, TZ="UTC")
    try:
        p = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True,
                           text=True, timeout=5, env=env)
        out = p.stdout if p.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        out = None
    return " ".join(out.split()) if out and out.strip() else None


def is_same_process(info):
    """pid is alive and (when recorded) started at the time the session file says."""
    pid = info.get("pid")
    if not isinstance(pid, int) or not pid_alive(pid):
        return False
    recorded = info.get("procStart")
    if not recorded:
        return True
    actual = proc_start_utc(pid)
    return actual is None or actual == " ".join(recorded.split())


def pid_tty(pid):
    out = run(["ps", "-o", "tty=", "-p", str(pid)])
    tty = out.strip() if out else ""
    if not tty or tty in ("?", "??"):
        return None
    return tty if tty.startswith("/dev/") else "/dev/" + tty


def claude_pids_on_tty(tty):
    out = run(["ps", "-t", tty.replace("/dev/", ""), "-o", "pid=,comm="]) or ""
    pids = []
    for line in out.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and os.path.basename(parts[1].strip()) == "claude":
            pids.append(int(parts[0]))
    return pids


# ---------------------------------------------------------------- transcript

def classify_error(text):
    for kind, rx in ERROR_KINDS:
        if rx.search(text):
            return kind
    return "other"


def message_text(rec):
    content = (rec.get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
    return ""


def is_api_error(rec):
    return bool(rec.get("isApiErrorMessage")) or message_text(rec).startswith("API Error:")


def iter_lines_reverse(path, chunk=1 << 16):
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        pos = f.tell()
        tail = b""
        while pos > 0:
            step = min(chunk, pos)
            pos -= step
            f.seek(pos)
            buf = f.read(step) + tail
            lines = buf.split(b"\n")
            tail = lines.pop(0)
            for line in reversed(lines):
                if line.strip():
                    yield line
        if tail.strip():
            yield tail


def trailing_errors(path):
    """Walk the transcript backwards over main-thread assistant turns.

    Returns (errors, last_ok_ts): the API errors after the last successful
    assistant turn (oldest first) and that turn's timestamp.
    """
    errors = []
    for line in iter_lines_reverse(path):
        if b'"assistant"' not in line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("type") != "assistant" or rec.get("isSidechain"):
            continue
        if is_api_error(rec):
            text = message_text(rec)
            errors.append({"kind": classify_error(text), "text": text[:200], "timestamp": rec.get("timestamp")})
        else:
            errors.reverse()
            return errors, rec.get("timestamp")
    errors.reverse()
    return errors, None


def is_stuck(errors):
    return sum(1 for e in errors if e["kind"] in CONNECTION_KINDS) >= STUCK_MIN_ERRORS


# ---------------------------------------------------------------- scan

def load_sessions(include_all=False):
    out = []
    for path in glob.glob(os.path.join(glob.escape(sessions_dir()), "*.json")):
        try:
            with open(path) as f:
                info = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(info, dict) or "sessionId" not in info:
            continue
        info["alive"] = is_same_process(info)
        if not include_all and (not info["alive"] or info.get("kind", "interactive") != "interactive"):
            continue
        out.append(info)
    return out


def analyze(info, current=None):
    sid = info["sessionId"]
    transcript = find_transcript(sid)
    errors, last_ok = trailing_errors(transcript) if transcript else ([], None)
    version = info.get("version")
    stale = bool(current and parse_version(version) and parse_version(current)
                 and parse_version(version) < parse_version(current))
    if not info.get("alive", True):
        state = "DEAD"
    elif is_stuck(errors):
        state = "STUCK"
    elif errors:
        state = "ERROR"
    else:
        state = "OK"
    return {
        "name": info.get("name"),
        "pid": info.get("pid"),
        "sessionId": sid,
        "cwd": info.get("cwd"),
        "status": info.get("status"),
        "version": version,
        "installedVersion": current,
        "versionStale": stale,
        "startedAt": info.get("startedAt"),
        "updatedAt": info.get("updatedAt"),
        "transcript": transcript,
        "transcriptMtime": os.path.getmtime(transcript) if transcript else None,
        "trailingErrors": len(errors),
        "errorKinds": sorted({e["kind"] for e in errors}),
        "lastError": errors[-1]["text"] if errors else None,
        "lastSuccessAt": last_ok,
        "state": state,
    }


def scan(include_all=False):
    current = installed_version()
    rows = [analyze(s, current) for s in load_sessions(include_all)]
    rows.sort(key=lambda r: (r["state"] != "STUCK", -(r["transcriptMtime"] or 0)))
    return rows


def fmt_age(seconds):
    if seconds is None:
        return "-"
    seconds = max(0, int(seconds))
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return "%d%s" % (seconds // size, unit)
    return "%ds" % seconds


def print_table(rows):
    now = time.time()
    if not rows:
        print("No live Claude Code sessions found in %s" % sessions_dir())
        return
    current = rows[0]["installedVersion"]
    header = ("STATE", "NAME", "PID", "VERSION", "AGE", "LAST", "ERRS", "SESSION")
    table = [header]
    for r in rows:
        ver = (r["version"] or "?") + ("*" if r["versionStale"] else "")
        age = fmt_age(now - r["startedAt"] / 1000) if r["startedAt"] else "-"
        last = fmt_age(now - r["transcriptMtime"]) if r["transcriptMtime"] else "-"
        errs = str(r["trailingErrors"])
        if r["errorKinds"]:
            errs += " " + ",".join(r["errorKinds"])
        table.append((r["state"], r["name"] or "-", str(r["pid"]), ver, age, last, errs, r["sessionId"]))
    widths = [max(len(row[i]) for row in table) for i in range(len(header))]
    for row in table:
        print("  ".join(c.ljust(w) for c, w in zip(row, widths)).rstrip())
    if any(r["versionStale"] for r in rows):
        print("\n* older than the installed version (%s)" % current)
    stuck = [r for r in rows if r["state"] == "STUCK"]
    if stuck:
        print("\n%d stuck: %s" % (len(stuck), ", ".join(r["name"] or str(r["pid"]) for r in stuck)))
        print("Restart with: %s revive <name>   (add --dry-run to preview)" % os.path.basename(sys.argv[0]))


# ---------------------------------------------------------------- panes

class Pane:
    """A terminal pane we can read and type into."""

    def __init__(self, backend, pane_id):
        self.backend, self.pane_id = backend, pane_id

    def __str__(self):
        return "%s pane %s" % (self.backend, self.pane_id)

    def send_text_cmd(self, text):
        if self.backend == "herdr":
            return ["herdr", "pane", "send-text", self.pane_id, text]
        return ["tmux", "send-keys", "-t", self.pane_id, "-l", text]

    def enter_cmd(self):
        if self.backend == "herdr":
            return ["herdr", "pane", "send-keys", self.pane_id, "enter"]
        return ["tmux", "send-keys", "-t", self.pane_id, "Enter"]

    def type_line(self, text):
        for cmd in (self.send_text_cmd(text), self.enter_cmd()):
            if subprocess.run(cmd, capture_output=True).returncode != 0:
                raise RuntimeError("failed: %s" % " ".join(cmd))
            time.sleep(0.3)

    def press_enter(self):
        subprocess.run(self.enter_cmd(), capture_output=True, check=True)

    def read(self, lines=40):
        if self.backend == "herdr":
            return run(["herdr", "pane", "read", self.pane_id, "--lines", str(lines)]) or ""
        return run(["tmux", "capture-pane", "-p", "-t", self.pane_id, "-S", "-%d" % lines]) or ""


def find_pane(session_id, tty):
    if shutil.which("herdr"):
        out = run(["herdr", "pane", "list"])
        try:
            panes = json.loads(out)["result"]["panes"] if out else []
        except (ValueError, KeyError, TypeError):
            panes = []
        for p in panes:
            if ((p.get("agent_session") or {}).get("value")) == session_id:
                return Pane("herdr", p["pane_id"])
    if tty and shutil.which("tmux"):
        out = run(["tmux", "list-panes", "-a", "-F", "#{pane_id} #{pane_tty}"]) or ""
        for line in out.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1] == tty:
                return Pane("tmux", parts[0])
    return None


# ---------------------------------------------------------------- revive

def resolve(target, include_dead=False):
    sessions = load_sessions(include_all=True)
    if not include_dead:
        sessions = [s for s in sessions if s["alive"]]
    for key in (lambda s: s.get("name") == target,
                lambda s: str(s.get("pid")) == target,
                lambda s: s["sessionId"] == target,
                lambda s: len(target) >= 6 and s["sessionId"].startswith(target)):
        hits = [s for s in sessions if key(s)]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise SystemExit("'%s' matches %d sessions (pids %s); use the pid or session id"
                             % (target, len(hits), ", ".join(str(s["pid"]) for s in hits)))
    raise SystemExit("no live session matches '%s'" % target)


def wait_for(predicate, timeout, interval=0.5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return None


def manual_steps(info):
    return ("In the terminal running session '%s' (pid %s):\n"
            "  1. type /exit and press Enter (if asked, choose \"%s\")\n"
            "  2. run: claude --resume %s\n"
            "  3. send a prompt such as: %s"
            % (info.get("name"), info.get("pid"), EXIT_DIALOG_MARKER, info["sessionId"], DEFAULT_PROMPT))


def revive_one(info, args):
    report = analyze(info, installed_version())
    label = "%s (pid %s, %s)" % (info.get("name"), info["pid"], info["sessionId"])
    print("Session %s: %s, %d trailing API error(s)%s" % (
        label, report["state"], report["trailingErrors"],
        " [%s]" % ",".join(report["errorKinds"]) if report["errorKinds"] else ""))
    if report["state"] != "STUCK" and not args.force:
        print("  not stuck; nothing to do (pass --force to restart it anyway)")
        if not args.dry_run:
            return 0
        print("  plan below is what --force would do:")

    tty = pid_tty(info["pid"])
    pane = find_pane(info["sessionId"], tty)
    resume_cmd = "%s --resume %s" % (args.claude_bin, info["sessionId"])
    prompt = None if args.no_prompt else (args.prompt or DEFAULT_PROMPT)
    if pane is None:
        print("  no herdr or tmux pane found for tty %s; do it by hand:" % (tty or "?"))
        print("  " + manual_steps(info).replace("\n", "\n  "))
        return 2

    plan = [
        "type '/exit' + Enter into %s" % pane,
        "if the pane shows \"%s\", press Enter (option 1)" % EXIT_DIALOG_MARKER,
        "wait up to %ds for pid %s to exit" % (args.timeout, info["pid"]),
        "type '%s' + Enter" % resume_cmd,
        "wait up to %ds for a new claude process on %s" % (args.timeout, tty),
    ]
    if prompt:
        plan.append("type prompt + Enter: %r" % prompt)
    if args.dry_run:
        print("  dry run, would:")
        for i, step in enumerate(plan, 1):
            print("    %d. %s" % (i, step))
        return 0

    old_pid = info["pid"]
    print("  -> /exit in %s" % pane)
    pane.type_line("/exit")
    gone = wait_for(lambda: not pid_alive(old_pid), 3)
    if not gone:
        screen = pane.read()
        if EXIT_DIALOG_MARKER in screen:
            if not re.search(r"1\.\s*" + re.escape(EXIT_DIALOG_MARKER), screen):
                print("  exit dialog found but option 1 is not \"%s\"; stopping" % EXIT_DIALOG_MARKER)
                return 3
            print("  -> confirming \"%s\"" % EXIT_DIALOG_MARKER)
            pane.press_enter()
        gone = wait_for(lambda: not pid_alive(old_pid), args.timeout)
    if not gone:
        print("  pid %s still running after %ds; leaving it alone" % (old_pid, args.timeout))
        return 4

    print("  -> %s" % resume_cmd)
    time.sleep(1)
    pane.type_line(resume_cmd)
    new_pids = wait_for(lambda: [p for p in claude_pids_on_tty(tty) if p != old_pid], args.timeout) if tty else None
    if not new_pids:
        print("  no new claude process on %s after %ds; check the pane" % (tty, args.timeout))
        return 5
    new_pid = new_pids[0]
    ready = wait_for(lambda: os.path.exists(os.path.join(sessions_dir(), "%d.json" % new_pid)), args.timeout)
    print("  resumed as pid %d%s" % (new_pid, "" if ready else " (session file not seen yet)"))
    if prompt:
        time.sleep(3)
        print("  -> sending prompt")
        pane.type_line(prompt)
    return 0


def cmd_revive(args):
    if args.all_stuck:
        targets = [s for s in load_sessions() if analyze(s)["state"] == "STUCK"]
        if not targets:
            print("No stuck sessions.")
            return 0
    elif args.target:
        targets = [resolve(args.target)]
    else:
        raise SystemExit("revive needs a session (name, pid or id) or --all-stuck")
    rc = 0
    for info in targets:
        rc = max(rc, revive_one(info, args))
    return rc


def cmd_watch(args):
    cooldown, per_hour = args.cooldown, args.max_per_hour
    last_revive, history = {}, []
    while True:
        rows = scan()
        stamp = dt.datetime.now().strftime("%H:%M:%S")
        stuck = [r for r in rows if r["state"] == "STUCK"]
        print("[%s] %d session(s), %d stuck%s" % (
            stamp, len(rows), len(stuck),
            ": " + ", ".join(r["name"] or str(r["pid"]) for r in stuck) if stuck else ""), flush=True)
        if args.auto:
            now = time.time()
            history = [t for t in history if now - t < 3600]
            for r in stuck:
                if now - last_revive.get(r["sessionId"], 0) < cooldown:
                    print("  %s: in cooldown" % r["name"])
                    continue
                if len(history) >= per_hour:
                    print("  revive limit reached (%d/hour)" % per_hour)
                    break
                info = next((s for s in load_sessions() if s["sessionId"] == r["sessionId"]), None)
                if info is None:
                    continue
                last_revive[r["sessionId"]] = now
                history.append(now)
                revive_one(info, args)
        if args.once:
            return 0
        time.sleep(args.interval)


# ---------------------------------------------------------------- cli

def add_revive_opts(p):
    p.add_argument("--dry-run", action="store_true", help="print the plan, touch nothing")
    p.add_argument("--force", action="store_true", help="restart even if the session is not stuck")
    p.add_argument("--prompt", help="follow-up prompt after resume (default: a neutral 'continue')")
    p.add_argument("--no-prompt", action="store_true", help="do not send a follow-up prompt")
    p.add_argument("--timeout", type=int, default=30, help="seconds to wait for exit / restart (default 30)")
    p.add_argument("--claude-bin", default="claude", help="command typed to resume (default: claude)")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Find and restart Claude Code sessions stuck on API connection errors.")
    sub = ap.add_subparsers(dest="cmd")

    p_scan = sub.add_parser("scan", help="list sessions and flag stuck ones (default)")
    p_scan.add_argument("--json", action="store_true", help="machine-readable output")
    p_scan.add_argument("--all", action="store_true", help="include dead and non-interactive sessions")

    p_rev = sub.add_parser("revive", help="exit and resume a stuck session in its pane")
    p_rev.add_argument("target", nargs="?", help="session name, pid, or session id")
    p_rev.add_argument("--all-stuck", action="store_true", help="revive every STUCK session")
    add_revive_opts(p_rev)

    p_watch = sub.add_parser("watch", help="scan periodically; --auto revives stuck sessions")
    p_watch.add_argument("--interval", type=int, default=60)
    p_watch.add_argument("--auto", action="store_true")
    p_watch.add_argument("--cooldown", type=int, default=600, help="seconds between revives of one session")
    p_watch.add_argument("--max-per-hour", type=int, default=3)
    p_watch.add_argument("--once", action="store_true", help=argparse.SUPPRESS)
    add_revive_opts(p_watch)

    args = ap.parse_args(argv)
    if args.cmd in (None, "scan"):
        rows = scan(include_all=getattr(args, "all", False))
        if getattr(args, "json", False):
            print(json.dumps(rows, indent=2))
        else:
            print_table(rows)
        return 0
    if args.cmd == "revive":
        return cmd_revive(args)
    if args.cmd == "watch":
        try:
            return cmd_watch(args)
        except KeyboardInterrupt:
            return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
