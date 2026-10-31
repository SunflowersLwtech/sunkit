#!/usr/bin/env python3
# seat-refresh.py 的离线测试：假网关在 127.0.0.1，curl 在本机直接连它（SR_EXEC 设空串，不进容器）。
# python3 tools/magpie-gateway/server/seat-refresh.test.py
import importlib.util, json, os, shutil, tempfile, threading, time, unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

os.environ["SR_EXEC"] = ""
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("seatrefresh", os.path.join(HERE, "seat-refresh.py"))
sr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sr)

TZ = timezone(timedelta(hours=8))


def at(seconds):
    """seconds from now, as magpie writes times: nanoseconds, +08:00"""
    return (datetime.now(TZ) + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%S.%f") + "123+08:00"


def card(user, five=None, week=None, read=-60, plan="team", error=None):
    ws = []
    if five is not None:
        w = {"name": "5 hours", "used": five[0]}
        if five[1] is not None:
            w["resetsAt"] = at(five[1])
        ws.append(w)
    if week is not None:
        w = {"name": "7 days", "used": week[0]}
        if week[1] is not None:
            w["resetsAt"] = at(week[1])
        ws.append(w)
    c = {"provider": "claude", "name": "Claude Code", "plan": plan, "user": user, "kind": "subscription",
         "windows": ws, "readAt": at(read)}
    if error:
        c["error"] = error
    return c


class Fake(BaseHTTPRequestHandler):
    cards, refreshed, after, down, broken = [], [], {}, False, set()

    def reply(self, code, out):
        data = json.dumps(out).encode()
        self.send_response(code)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if Fake.down:
            return self.reply(502, {"error": "down"})
        if urlparse(self.path).path != "/v1/magpie/quotas/cards":
            return self.reply(404, {})
        self.reply(200, {"object": "list", "data": Fake.cards})

    def do_POST(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path != "/v1/magpie/quotas/refresh" or q.get("provider") != ["claude"]:
            return self.reply(404, {})
        user = q["user"][0]
        Fake.refreshed.append(user)
        if user in Fake.broken:
            return self.reply(500, {"error": "Claude Code can't be run from here"})
        if user in Fake.after:
            Fake.cards = [Fake.after[user] if c["user"] == user else c for c in Fake.cards]
        self.reply(200, {"object": "list", "data": Fake.cards})

    def log_message(self, *a):
        pass


class SeatRefresh(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        sr.BASE = "http://127.0.0.1:%d" % self.srv.server_address[1]
        sr.VAR = self.tmp
        sr.STATE, sr.LOG = self.tmp + "/state.json", self.tmp + "/log"
        Fake.cards, Fake.refreshed, Fake.after, Fake.down, Fake.broken = [], [], {}, False, set()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def state(self):
        with open(sr.STATE) as f:
            return json.load(f)

    def backdate(self, user, seconds):
        s = self.state()
        s[user.lower()]["at"] -= seconds
        with open(sr.STATE, "w") as f:
            json.dump(s, f)

    def logged(self):
        with open(sr.LOG) as f:
            return f.read()

    def test_unknown_reset_is_read_and_the_card_keeps_its_name(self):
        # the reported case: a spare seat at 0% whose last reset passed, shown with no reset time
        u = "weiliu@duocodetech.com · DuoCode"
        Fake.cards = [card(u, five=(0, None), read=-12 * 3600)]
        Fake.after[u] = card(u, five=(1, 6600), read=0)
        self.assertEqual(sr.main(), 0)
        self.assertEqual(Fake.refreshed, [u])  # the middle dot and spaces reach magpie as they are
        self.assertTrue(self.state()[u.lower()]["five_reset"])
        self.assertIn("before: 5 hours 0%", self.logged())
        self.assertIn("after: 5 hours 1% ↻", self.logged())

    def test_a_reset_in_the_past_counts_as_unknown(self):
        # was capped and read a minute ago; its window renewed since, before magpie cleared the reset
        u = "a@x.com · DuoCode"
        Fake.cards = [card(u, five=(97, -30), read=-60)]
        sr.main()
        self.assertEqual(Fake.refreshed, [u])
        self.assertIn("5h reset unknown", self.logged())

    def test_capped_seats_are_left_alone(self):
        Fake.cards = [card("five@x.com · DuoCode", five=(96, 3600), read=-3600),
                      card("cap@x.com · DuoCode", five=(95, 3600), read=-3600),
                      card("week@x.com", five=(0, None), week=(100, 2 * 86400), plan="max", read=-86400)]
        sr.main()
        self.assertEqual(Fake.refreshed, [])

    def test_just_under_the_cap_is_still_read(self):
        u = "near@x.com · DuoCode"
        Fake.cards = [card(u, five=(94, 3600), read=-11 * 60)]
        sr.main()
        self.assertEqual(Fake.refreshed, [u])

    def test_fresh_readings_are_not_read_again_and_stale_ones_are(self):
        Fake.cards = [card("fresh@x.com · DuoCode", five=(20, 3600), read=-9 * 60),
                      card("stale@x.com · DuoCode", five=(20, 3600), read=-11 * 60)]
        sr.main()
        self.assertEqual(Fake.refreshed, ["stale@x.com · DuoCode"])

    def test_unknown_reset_waits_five_minutes_between_reads(self):
        u = "a@x.com · DuoCode"
        Fake.cards = [card(u, five=(0, None), read=-3600)]
        Fake.after[u] = card(u, five=(3, 3 * 3600), read=0)
        sr.main()
        Fake.cards = [card(u, five=(0, None), read=-3600)]  # say its reading was lost again
        sr.main()
        self.assertEqual(len(Fake.refreshed), 1)
        self.backdate(u, 4 * 60)
        sr.main()
        self.assertEqual(len(Fake.refreshed), 1)
        self.backdate(u, 61)
        sr.main()
        self.assertEqual(len(Fake.refreshed), 2)

    def test_a_seat_nobody_used_since_its_reset_is_read_every_fifteen_minutes(self):
        # /usage says 0% and no reset: the window starts on the seat's next request
        u = "idle@x.com · DuoCode"
        Fake.cards = [card(u, five=(0, None), read=-3600)]
        sr.main()
        self.assertFalse(self.state()[u.lower()]["five_reset"])
        self.backdate(u, 6 * 60)
        sr.main()
        self.assertEqual(len(Fake.refreshed), 1)
        self.backdate(u, 9 * 60)
        sr.main()
        self.assertEqual(len(Fake.refreshed), 2)

    def test_at_most_four_a_run_oldest_first(self):
        # stale readings that a refresh doesn't renew (magpie's own 30-second gap): every seat stays due
        users = ["s%d@x.com · DuoCode" % i for i in range(6)]
        Fake.cards = [card(u, five=(20, 3600), read=-3600) for u in users]
        sr.main()
        self.assertEqual(len(Fake.refreshed), 4)
        for u in Fake.refreshed:
            self.backdate(u, 6 * 60)
        first = list(Fake.refreshed)
        Fake.refreshed[:] = []
        sr.main()
        # the two not read last time come first
        self.assertEqual(sorted(Fake.refreshed[:2]), sorted(set(users) - set(first)))

    def test_magpie_down_writes_a_line_and_nothing_else(self):
        Fake.down = True
        self.assertEqual(sr.main(), 0)
        self.assertIn("cards unreadable", self.logged())
        self.assertFalse(os.path.exists(sr.STATE))

    def test_a_failed_refresh_is_not_retried_at_once(self):
        u = "bad@x.com · DuoCode"
        Fake.cards = [card(u, five=(0, None), read=-3600)]
        Fake.broken.add(u)
        sr.main()
        sr.main()
        self.assertEqual(Fake.refreshed, [u])
        self.assertIn("refresh failed", self.logged())

    def test_other_providers_and_plans_cards_are_ignored(self):
        Fake.cards = [{"provider": "codex", "kind": "subscription", "user": "c@x.com", "windows": []},
                      {"provider": "claude", "kind": "balance", "user": "k", "windows": []}]
        sr.main()
        self.assertEqual(Fake.refreshed, [])

    def test_nanosecond_times_parse(self):
        self.assertAlmostEqual(sr.parse_time("2026-10-31T06:59:15.935630364+08:00"),
                               datetime(2026, 10, 30, 22, 59, 15, 935630, tzinfo=timezone.utc).timestamp(), places=3)
        self.assertIsNone(sr.parse_time(None))
        self.assertIsNone(sr.parse_time("not a time"))

    def test_the_unit_can_read_busy_seats_every_three_minutes(self):
        # magpie v0.1.2421's interactive mode tells nothing of the allowance on an answered turn, so the unit sets
        # SR_STALE=180 SR_UNKNOWN_GAP=180; a copy of the script loaded with them, against the same fake gateway
        global sr
        old = sr
        os.environ.update(SR_STALE="180", SR_UNKNOWN_GAP="180")
        try:
            s = importlib.util.spec_from_file_location("seatrefresh3", os.path.join(HERE, "seat-refresh.py"))
            sr = importlib.util.module_from_spec(s)
            s.loader.exec_module(sr)
            for k in ("BASE", "VAR", "STATE", "LOG"):
                setattr(sr, k, getattr(old, k))
            self.assertEqual((sr.STALE, sr.UNKNOWN_GAP), (180, 180))
            Fake.cards = [card("young@x.com · DuoCode", five=(20, 3600), read=-2 * 60),
                          card("old@x.com · DuoCode", five=(20, 3600), read=-4 * 60)]
            sr.main()
            # 4 minutes old is read now (the default 10 would leave it), 2 minutes old is not
            self.assertEqual(Fake.refreshed, ["old@x.com · DuoCode"])
            # the seat it just read, its reading old again: not before 3 minutes have passed since, then yes
            Fake.cards = [card("old@x.com · DuoCode", five=(30, 3600), read=-4 * 60)]
            Fake.refreshed = []
            self.backdate("old@x.com · DuoCode", 2 * 60)
            sr.main()
            self.assertEqual(Fake.refreshed, [])
            self.backdate("old@x.com · DuoCode", 2 * 60)
            sr.main()
            self.assertEqual(Fake.refreshed, ["old@x.com · DuoCode"])
        finally:
            for k in ("SR_STALE", "SR_UNKNOWN_GAP"):
                os.environ.pop(k, None)
            sr = old


if __name__ == "__main__":
    unittest.main()
