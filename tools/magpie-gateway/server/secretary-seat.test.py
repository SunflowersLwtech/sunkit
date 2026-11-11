#!/usr/bin/env python3
# secretary-seat.py 的离线测试：magpie() 换成假的，读 accounts / options、记下写进去的 options，不碰 docker。
# python3 tools/magpie-gateway/server/secretary-seat.test.py
import importlib.util, json, os, tempfile, time, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("secretaryseat", os.path.join(HERE, "secretary-seat.py"))
ss = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ss)


class Done:
    def __init__(self, out, code=0):
        self.stdout, self.stderr, self.returncode = out, "", code


def team(user, five, week, **kw):
    return {"agent": "claude", "user": user + " · DuoCode", "plan": "team", "on": True,
            "windows": [{"name": "5 hours", "used": five}, {"name": "7 days", "used": week}], **kw}


def max_seat(week, **kw):
    # magpie shows the Max seat a week and no 5-hour window
    return {"agent": "claude", "user": "max@example.com", "plan": "max", "on": True,
            "windows": [{"name": "7 days", "used": week}, {"name": "7 days · Fable", "used": 0}], **kw}


class SecretarySeat(unittest.TestCase):
    def setUp(self):
        self.accounts, self.writes = [], []
        self.opts = {"sessions": ["s1", "s2"], "secretary": ["dev"], "seatUntil": 0}
        ss.LOCK = tempfile.mktemp()
        real = ss.magpie

        def fake(*args):
            if args[:2] == ("accounts", "claude"):
                return Done(json.dumps(self.accounts))
            if args[:2] == ("plugin", "options") and len(args) == 3:
                return Done(json.dumps(self.opts))
            if args[:2] == ("plugin", "options") and len(args) == 4:
                self.opts = json.loads(args[3])
                self.writes.append(self.opts)
                return Done("")
            raise AssertionError(args)
        ss.magpie = fake
        self.addCleanup(setattr, ss, "magpie", real)
        self.addCleanup(lambda: os.path.exists(ss.LOCK) and os.remove(ss.LOCK))

    def leased(self):
        return self.opts["seatUntil"] > time.time() * 1000

    def test_max_seat_with_week_room_renews_while_team_seats_are_at_cap(self):
        # 11-11 10:46–10:58 +08: Team seats at their weekly caps, Max at 80% of its week → was "no seat with room"
        self.accounts = [team("a", 0, 100), team("b", 0, 96), team("c", 0, 95), max_seat(80)]
        out = ss.main()
        self.assertTrue(out.startswith("renewed"), out)
        self.assertIn("max@example.com 7d 80%", out)
        self.assertTrue(self.leased())

    def test_max_seat_at_its_week_cap_has_no_room(self):
        self.accounts = [team("a", 0, 100), max_seat(95)]
        self.opts["seatUntil"] = int(time.time() * 1000) + 60000
        out = ss.main()
        self.assertTrue(out.startswith("cleared"), out)
        self.assertEqual(self.opts["seatUntil"], 0)

    def test_team_seat_at_its_account_cap_has_no_room(self):
        # accountCaps 95: magpie no longer sends a seat at 96% of its week anything
        self.accounts = [team("a", 0, 96)]
        out = ss.main()
        self.assertTrue(out.startswith("off"), out)
        self.assertEqual(self.writes, [])

    def test_team_seat_with_5h_room_renews(self):
        self.accounts = [team("a", 30, 50)]
        out = ss.main()
        self.assertTrue(out.startswith("renewed"), out)
        self.assertIn("a · DuoCode 5h 30% 7d 50%", out)

    def test_busy_team_seat_but_max_week_room_renews(self):
        self.accounts = [team("a", 70, 50), max_seat(50)]
        self.assertTrue(ss.main().startswith("renewed"))

    def test_busy_5h_window_alone_has_no_room(self):
        self.accounts = [team("a", 61, 10)]
        self.assertTrue(ss.main().startswith("off"))

    def test_no_room_clears_a_running_lease_at_once(self):
        # before, "no seat with room" returned before reading the options and left the lease to run out
        self.accounts = [team("a", 0, 100)]
        self.opts["seatUntil"] = int(time.time() * 1000) + 120000
        out = ss.main()
        self.assertTrue(out.startswith("cleared"), out)
        self.assertEqual(self.opts["seatUntil"], 0)
        self.assertEqual(len(self.writes), 1)

    def test_account_turned_off_is_no_room(self):
        self.accounts = [max_seat(10, on=False), team("a", 0, 100)]
        self.assertTrue(ss.main().startswith("off"))

    def test_window_with_no_number_is_no_reading(self):
        self.accounts = [{"agent": "claude", "user": "x", "on": True, "windows": [{"name": "5 hours", "used": None}, {"name": "7 days", "used": "n/a"}]}]
        out = ss.main()
        self.assertTrue(out.startswith("off"), out)
        self.assertIn("no reading", out)

    def test_lease_with_time_left_is_kept_without_a_write(self):
        self.accounts = [max_seat(50)]
        self.opts["seatUntil"] = int(time.time() * 1000) + 150000
        out = ss.main()
        self.assertTrue(out.startswith("kept"), out)
        self.assertEqual(self.writes, [])

    def test_renewal_keeps_the_other_options(self):
        self.accounts = [max_seat(50)]
        ss.main()
        self.assertEqual(self.opts["sessions"], ["s1", "s2"])
        self.assertEqual(self.opts["secretary"], ["dev"])


if __name__ == "__main__":
    unittest.main()
