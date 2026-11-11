#!/usr/bin/python3
"""Renews the secretary's seat lease on magpie's route-all-flash middleware.

The middleware sends a secretary session's request to group/secretary-seat
(the Claude seats first) only while options.seatUntil is a moment still ahead
(see the middleware's comment). This renews that lease while some Claude seat
has room, and clears it otherwise, so the secretary goes to group/flash-paid.

A seat has room when its week is below WEEK and, if magpie shows it a 5-hour
window, that window is at or below THRESHOLD. magpie shows no 5-hour window for
the Max seat, the one that answers most requests; until 2026-11-11 such a seat
never counted, so the lease followed the Team seats, all at their weekly caps,
and dropped while the Max seat still had room. A lease that stops being renewed
runs out by itself, so a dead timer never leaves the secretary on the seats.
"""
import fcntl
import json
import subprocess
import time

CONTAINER = "magpie-magpie-1"
NAME = "/plugins/route-all-flash.middleware.js"
THRESHOLD = 60          # the seats' 5-hour share this may stand at
WEEK = 95               # the seats' account cap (magpie provider account-cap claude … 95): at it a seat has no room
LEASE_MS = 180_000      # how long one renewal lasts
RENEW_WHEN_MS = 90_000  # renew when this little of the lease is left
LOCK = "/var/lock/magpie-seat-allow.lock"  # shared with seat-allow-core


def magpie(*args):
    return subprocess.run(
        ["docker", "exec", CONTAINER, "magpie", *args],
        capture_output=True, text=True, timeout=60,
    )


def used(window):
    """A window's percent used, or None when magpie has no number for it."""
    v = window.get("used") if window else None
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def room():
    """(True, the seat with the most room) when some seat has room, else (False, what was read)."""
    r = magpie("accounts", "claude", "--json")
    if r.returncode != 0:
        raise RuntimeError("accounts failed: " + (r.stderr or r.stdout).strip()[:120])
    best, seen = None, []
    for a in json.loads(r.stdout):
        if a.get("on") is False:
            continue
        w = {x.get("name"): x for x in (a.get("windows") or [])}
        five, week = used(w.get("5 hours")), used(w.get("7 days"))
        if five is None and week is None:
            continue  # no reading: unknown is not room
        who = "%s %s" % (a.get("user") or "?", "5h %d%% 7d %s" % (five, "?" if week is None else "%d%%" % week) if five is not None else "7d %d%%" % week)
        seen.append(who)
        if (week is None or week < WEEK) and (five is None or five <= THRESHOLD):
            key = (five if five is not None else 0, week if week is not None else 0)
            if best is None or key < best[0]:
                best = (key, who)
    if best:
        return True, best[1]
    return False, "no seat with room (" + ("; ".join(seen) or "no reading") + ")"


def main():
    with open(LOCK, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return renew()


def renew():
    allow, why = room()
    r = magpie("plugin", "options", NAME)
    out = (r.stdout or "").strip()
    if not out.startswith("{"):
        return "no options to renew"
    opts = json.loads(out)
    now = int(time.time() * 1000)
    until = opts.get("seatUntil") or 0
    if allow and until - now > RENEW_WHEN_MS:
        return "kept: %s, lease %ds left" % (why, (until - now) // 1000)
    if not allow and until == 0:
        return "off: %s" % why
    opts["seatUntil"] = now + LEASE_MS if allow else 0
    r = magpie("plugin", "options", NAME, json.dumps(opts))
    if r.returncode != 0:
        return "write failed: " + (r.stderr or r.stdout).strip()[:120]
    return "%s: %s" % ("renewed +%ds" % (LEASE_MS // 1000) if allow else "cleared", why)


if __name__ == "__main__":
    print(main())
