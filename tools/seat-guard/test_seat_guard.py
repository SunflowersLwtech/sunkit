"""Tests for seat-guard, against a fake Anthropic (usage, profile, token) on localhost.

    python3 -m unittest test_seat_guard        (in this directory)
"""
import errno, http.server, importlib.machinery, importlib.util, json, os, shutil, tempfile, threading, time, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
F = int(time.time() * 1000) + 3600000
USE = {"tok-A": 100, "tok-B": 3, "tok-B2": 3, "tok-C": 60}
WHO = {"tok-A": "a@x", "tok-B": "b@x", "tok-B2": "b@x", "tok-C": "c@x"}
LIMITED = set()   # tokens whose /usage answers 429, as Anthropic does for a busy active seat
RESET = {"tok-A": "2026-10-25T05:00:00Z", "tok-B2": "2026-10-25T03:00:00Z", "tok-C": "2026-10-25T04:00:00Z"}


class Fake(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, code, obj=None):
        self.send_response(code)
        self.end_headers()
        if obj is not None:
            self.wfile.write(json.dumps(obj).encode())

    def do_GET(self):
        t = self.headers.get("Authorization", "").split()[-1]
        if t not in USE:
            return self.reply(401)
        if self.path.startswith("/usage") and t in LIMITED:
            return self.reply(429)
        if self.path.startswith("/usage"):
            return self.reply(200, {"five_hour": {"utilization": USE[t], "resets_at": RESET.get(t)}, "seven_day": None})
        return self.reply(200, {"account": {"email": WHO[t], "uuid": "u-" + WHO[t]},
                                "organization": {"uuid": "org", "name": "Org"}})

    def do_POST(self):
        d = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if d.get("refresh_token") == "rt-B":
            return self.reply(200, {"access_token": "tok-B2", "refresh_token": "rt-B2", "expires_in": 3600})
        return self.reply(400)


class SeatGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.HTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{cls.srv.server_port}"
        os.environ.update(SEAT_GUARD_USAGE_URL=base + "/usage", SEAT_GUARD_PROFILE_URL=base + "/profile",
                          SEAT_GUARD_TOKEN_URL=base + "/token")

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        self.t = tempfile.mkdtemp()
        os.environ["CLAUDE_CONFIG_DIR"] = self.t
        loader = importlib.machinery.SourceFileLoader("sg", os.path.join(HERE, "seat-guard"))
        spec = importlib.util.spec_from_loader("sg", loader)
        self.sg = importlib.util.module_from_spec(spec)
        loader.exec_module(self.sg)
        os.makedirs(self.sg.SLOTS)
        self.put(self.sg.CREDS, {"claudeAiOauth": {"accessToken": "tok-A", "refreshToken": "rt-A", "expiresAt": F},
                                 "mcpOAuth": {"x": 1}})
        self.put(self.sg.GLOBAL, {"oauthAccount": {"emailAddress": "a@x"}, "other": 1})
        self.seat("b@x", "old", "rt-B", 1)            # expired: refreshed on first look
        self.seat("c@x", "tok-C", "rt-C", F)

    def tearDown(self):
        shutil.rmtree(self.t)

    def put(self, path, obj):
        with open(path, "w") as f:
            json.dump(obj, f)

    def get(self, path):
        with open(path) as f:
            return json.load(f)

    def seat(self, email, at, rt, exp):
        self.put(self.sg.slot_path(email), {"email": email, "oauthAccount": {"emailAddress": email},
                                            "claudeAiOauth": {"accessToken": at, "refreshToken": rt, "expiresAt": exp}})

    def test_used_up_moves_to_the_emptiest_seat(self):
        out = self.sg.tick(False)
        self.assertIn("switched a@x -> b@x", out)
        creds, glob = self.get(self.sg.CREDS), self.get(self.sg.GLOBAL)
        self.assertEqual(creds["claudeAiOauth"]["refreshToken"], "rt-B2")      # refreshed, then loaded
        self.assertEqual(creds["mcpOAuth"], {"x": 1})
        self.assertEqual(glob["oauthAccount"]["emailAddress"], "b@x")
        self.assertEqual(glob["other"], 1)
        self.assertEqual(self.get(self.sg.slot_path("a@x"))["claudeAiOauth"]["refreshToken"], "rt-A")
        self.assertFalse(os.path.exists(self.sg.slot_path("b@x")))           # one holder per family

    def test_no_second_switch_within_the_gap(self):
        self.sg.tick(False)
        USE["tok-B2"] = 100
        try:
            self.assertIn("switched less than", self.sg.tick(False))
        finally:
            USE["tok-B2"] = 3

    def test_nothing_under_low_stays(self):
        USE["tok-B"] = USE["tok-B2"] = USE["tok-C"] = 90
        try:
            self.assertIn("no saved seat under", self.sg.tick(False))
            self.assertEqual(self.get(self.sg.CREDS)["claudeAiOauth"]["accessToken"], "tok-A")
        finally:
            USE["tok-B"] = USE["tok-B2"] = 3
            USE["tok-C"] = 60

    def test_seat_with_room_is_left_alone(self):
        self.put(self.sg.CREDS, {"claudeAiOauth": {"accessToken": "tok-C", "refreshToken": "rt-C", "expiresAt": F}})
        self.put(self.sg.GLOBAL, {"oauthAccount": {"emailAddress": "c@x"}})
        os.remove(self.sg.slot_path("c@x"))
        self.assertIn("active c@x: 5h 60.0%", self.sg.tick(False))

    def test_single_file_bind_mount_is_written_in_place(self):
        real = os.replace

        def busy(src, dst):
            if dst == self.sg.GLOBAL:
                raise OSError(errno.EBUSY, "Device or resource busy")
            return real(src, dst)
        self.sg.os.replace = busy
        try:
            self.sg.switch("b@x", "test")
        finally:
            self.sg.os.replace = real
        self.assertEqual(self.get(self.sg.GLOBAL)["oauthAccount"]["emailAddress"], "b@x")
        self.assertEqual([f for f in os.listdir(self.t) if ".seat-guard-" in f], [])

    def test_failed_write_rolls_back(self):
        real = self.sg.write_json

        def failing(path, obj, mode=0o600):
            if path == self.sg.CREDS:
                raise OSError(errno.EIO, "disk")
            return real(path, obj, mode)
        self.sg.write_json = failing
        with self.assertRaises(OSError):
            self.sg.switch("c@x", "test")
        self.sg.write_json = real
        self.assertEqual(self.get(self.sg.CREDS)["claudeAiOauth"]["refreshToken"], "rt-A")
        self.assertEqual(self.get(self.sg.GLOBAL)["oauthAccount"]["emailAddress"], "a@x")
        self.assertTrue(os.path.exists(self.sg.slot_path("c@x")))
        self.assertFalse(os.path.exists(self.sg.slot_path("a@x")))

    def test_stale_label_never_names_the_saved_family(self):
        # a running Claude Code wrote its old label back: the token is a@x's, the label says c@x
        self.put(self.sg.GLOBAL, {"oauthAccount": {"emailAddress": "c@x"}, "other": 1})
        self.sg.switch("b@x", "test")
        self.assertEqual(self.get(self.sg.slot_path("a@x"))["claudeAiOauth"]["refreshToken"], "rt-A")
        self.assertEqual(self.get(self.sg.slot_path("c@x"))["claudeAiOauth"]["refreshToken"], "rt-C")

    def test_tick_repairs_a_stale_label(self):
        USE["tok-A"] = 10
        try:
            self.put(self.sg.GLOBAL, {"oauthAccount": {"emailAddress": "c@x"}, "other": 1})
            self.sg.tick(False)
            g = self.get(self.sg.GLOBAL)
            self.assertEqual(g["oauthAccount"]["emailAddress"], "a@x")
            self.assertEqual(g["other"], 1)
        finally:
            USE["tok-A"] = 100

    def test_ensure_with_every_seat_used_up_says_so_and_stays(self):
        USE["tok-B2"] = USE["tok-C"] = 99
        try:
            r = self.sg.tick(False, ensure=True)
        finally:
            USE["tok-B2"], USE["tok-C"] = 3, 60
        self.assertEqual(r, {"ok": False, "exhausted": True, "active": "a@x", "resets_at": "2026-10-25T03:00:00Z"})
        self.assertEqual(self.get(self.sg.CREDS)["claudeAiOauth"]["accessToken"], "tok-A")

    def test_ensure_takes_a_seat_between_low_and_high(self):
        # tick wants a seat under LOW (80); a caller already stopped by the limit takes one under HIGH (95)
        USE["tok-B2"], USE["tok-C"] = 90, 97
        try:
            self.assertIn("no saved seat under", self.sg.tick(False))
            r = self.sg.tick(False, ensure=True)
        finally:
            USE["tok-B2"], USE["tok-C"] = 3, 60
        self.assertEqual((r["ok"], r["active"]), (True, "b@x"))
        self.assertEqual(self.get(self.sg.CREDS)["claudeAiOauth"]["refreshToken"], "rt-B2")

    def test_ensure_ignores_the_gap(self):
        self.sg.tick(False)                       # a -> b
        USE["tok-B2"] = 100
        try:
            self.assertIn("switched less than", self.sg.tick(False))
            r = self.sg.tick(False, ensure=True)  # b used up at once: c (60%) has room
        finally:
            USE["tok-B2"] = 3
        self.assertEqual((r["ok"], r["active"]), (True, "c@x"))

    def test_ensure_leaves_a_seat_with_room(self):
        USE["tok-A"] = 50
        try:
            self.assertEqual(self.sg.tick(False, ensure=True), {"ok": True, "active": "a@x", "five_hour": 50.0})
        finally:
            USE["tok-A"] = 100
        self.assertEqual(self.get(self.sg.CREDS)["claudeAiOauth"]["accessToken"], "tok-A")

    def test_unreadable_active_use_comes_from_the_last_reading(self):
        self.sg.tick(False)                       # a -> b
        self.assertIn("active b@x: 5h 3", self.sg.tick(False))   # b read at 3%
        LIMITED.add("tok-B2")
        try:
            self.assertIn("active b@x: 5h 3", self.sg.tick(False))
        finally:
            LIMITED.discard("tok-B2")

    def test_ensure_counts_an_unreadable_active_seat_as_used_up(self):
        LIMITED.add("tok-A")
        try:
            self.assertIn("not readable", self.sg.tick(False))
            r = self.sg.tick(False, ensure=True)
        finally:
            LIMITED.discard("tok-A")
        self.assertEqual((r["ok"], r["active"]), (True, "b@x"))


if __name__ == "__main__":
    unittest.main()
