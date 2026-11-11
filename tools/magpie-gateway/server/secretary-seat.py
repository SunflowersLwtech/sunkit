#!/usr/bin/python3
"""Renews the secretary's seat lease on magpie's route-all-flash middleware.

The middleware upgrades a secretary session's request to claude/claude-opus-5-5
only while options.seatUntil is a moment still ahead (see the middleware's
comment). This renews that lease while the Claude seats have room: the
roomiest seat's 5-hour window at or below THRESHOLD percent used, and its week
below the accounts' own cap. Otherwise the lease is set to 0 and the secretary
stays on DeepSeek. A lease that stops being renewed runs out by itself, so a
dead timer never leaves the secretary on the seats.
"""
import fcntl
import json
import subprocess
import time

CONTAINER = "magpie-magpie-1"
NAME = "/plugins/route-all-flash.middleware.js"
THRESHOLD = 60          # the seats' 5-hour share this may stand at
WEEK = 100              # the accounts' account cap: past it a seat has no room
LEASE_MS = 180_000      # how long one renewal lasts
RENEW_WHEN_MS = 90_000  # renew when this little of the lease is left
LOCK = "/var/lock/magpie-seat-allow.lock"  # shared with seat-allow-core


def magpie(*args):
    return subprocess.run(
        ["docker", "exec", CONTAINER, "magpie", *args],
        capture_output=True, text=True, timeout=60,
    )


def roomiest():
    """The least 5-hour usage among the accounts with week room, or None."""
    r = magpie("accounts", "claude", "--json")
    if r.returncode != 0:
        raise RuntimeError("accounts failed: " + (r.stderr or r.stdout).strip()[:120])
    best = None
    for a in json.loads(r.stdout):
        w = {x.get("name"): x for x in (a.get("windows") or [])}
        five, week = w.get("5 hours"), w.get("7 days")
        if not five or five.get("used") is None:
            continue
        if week and (week.get("used") or 0) >= WEEK:
            continue
        used = five["used"]
        if best is None or used < best:
            best = used
    return best


def main():
    with open(LOCK, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return renew()


def renew():
    best = roomiest()
    if best is None:
        return "no seat with room"
    r = magpie("plugin", "options", NAME)
    out = (r.stdout or "").strip()
    if not out.startswith("{"):
        return "no options to renew"
    opts = json.loads(out)
    now = int(time.time() * 1000)
    until = opts.get("seatUntil") or 0
    allow = best <= THRESHOLD
    if allow and until - now > RENEW_WHEN_MS:
        return "kept: seat 5h %d%%, lease %ds left" % (best, (until - now) // 1000)
    if not allow and until == 0:
        return "off: seat 5h %d%%" % best
    opts["seatUntil"] = now + LEASE_MS if allow else 0
    r = magpie("plugin", "options", NAME, json.dumps(opts))
    if r.returncode != 0:
        return "write failed: " + (r.stderr or r.stdout).strip()[:120]
    return "%s: seat 5h %d%%" % ("renewed +%ds" % (LEASE_MS // 1000) if allow else "cleared", best)


if __name__ == "__main__":
    print(main())
