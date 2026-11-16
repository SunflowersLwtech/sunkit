# Tests for seat-offclaude with a stand-in magpie (plugin options + usage CSV from files): python3 seat-offclaude.test.py
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HEAD = ("time,agent,requested_model,provider,model,served_model,status,session,error_message")
S1, S2, S3 = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333"


class SeatOffClaude(unittest.TestCase):
    def run_it(self, csv_text, opts=None, args=()):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "usage.csv"), "w") as f:
            f.write(csv_text)
        with open(os.path.join(d, "opts.json"), "w") as f:
            json.dump(opts or {"sessions": [S1], "seatUntil": 0}, f)
        fake = os.path.join(d, "magpie")
        with open(fake, "w") as f:
            f.write("#!%s\nimport sys\na=sys.argv[1:]\nd=%r\nprint(open(d+('/opts.json' if a[0]=='plugin' else '/usage.csv')).read(), end='')\n" % (sys.executable, d))
        os.chmod(fake, 0o755)
        return subprocess.run([sys.executable, "-I", os.path.join(HERE, "seat-offclaude"), *args], env=dict(os.environ, SO_MAGPIE=fake),
                              capture_output=True, text=True, timeout=60)

    def test_off_claude_turns_of_watched_sessions_are_listed(self):
        rows = [HEAD,
                "2026-11-16T10:00:00+08:00,claude,group/flash-ds,devin,swe-2,swe-2,200,%s," % S1,
                "2026-11-16T10:00:05+08:00,claude,claude/claude-opus-5-5,claude,claude-opus-5-5,claude-opus-5-5,200,%s," % S1,
                "2026-11-16T10:00:09+08:00,claude,group/flash-ds,devin,swe-2,swe-2,200,%s," % S2,          # not watched
                "2026-11-16T10:00:10+08:00,claude,group/secretary-seat,devin,swe-2,swe-2,200,%s," % S3,     # the secretary's
                "2026-11-16T10:00:11+08:00,claude,group/flash-ds,devin,swe-2,,429,%s,limit" % S1]           # not answered
        r = self.run_it("\n".join(rows) + "\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        self.assertEqual(d["rows"], 5)
        got = {e["session"]: (e["turns"], e["secretary"]) for e in d["sessions"]}
        self.assertEqual(got, {S1: (1, False), S3: (1, True)})

    def test_a_missing_column_exits_non_zero_not_all_clear(self):
        for drop in ("served_model", "session", "status"):
            cols = [c for c in HEAD.split(",") if c != drop]
            r = self.run_it(",".join(cols) + "\n" + ",".join("x" for _ in cols) + "\n")
            self.assertEqual(r.returncode, 2, "%s missing read as all clear: %s" % (drop, r.stdout))
            self.assertIn("lacks %s" % drop, r.stderr)
            self.assertEqual(r.stdout, "")

    def test_no_csv_at_all_exits_non_zero(self):
        r = self.run_it("")
        self.assertEqual(r.returncode, 2, r.stdout)

    def test_a_quiet_window_says_zero_rows(self):
        r = self.run_it(HEAD + "\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["rows"], 0)


if __name__ == "__main__":
    unittest.main()
