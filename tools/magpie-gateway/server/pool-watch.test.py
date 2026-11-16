# Tests for pool-watch.py: which log lines mean a full pool, and that a spell is one write keeping the other options.
#   python3 pool-watch.test.py   (nothing leaves the machine: magpie and the log are stand-ins)
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("pool_watch", os.path.join(HERE, "pool-watch.py"))
pw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pw)


class PoolWatch(unittest.TestCase):
    def test_the_log_lines_that_mean_a_full_pool(self):
        yes = ["2026/11/16 09:54:26 claude: a Claude Code run on claude-opus-5-5 waits for room: 18 Claude Code processes run, 18 may (claudeRunsMost in settings)",
               "2026/11/16 09:55:42 claude: a Claude Code run on claude-opus-5-5 found no room in 2m0s",
               "2026/11/16 09:57:10 claude: a Claude Code /usage read waits for room: 18 Claude Code processes run, 18 may (claudeRunsMost in settings)"]
        no = ["2026/11/16 09:54:12 claude: a Claude Code run on claude-opus-5-5 had room after 18.444s",
              "2026/11/16 09:54:12 claude: an idle run on claude-opus-5-5 is let go to make room (18 may run at once); its conversation's next turn resumes its session",
              "2026/11/16 09:55:03 Claude Code on claude-opus-5-5: tool results no run waiting: the run that made the calls ended 3m20s ago: magpie let it go to make room for another Claude Code (18 may run at once)"]
        for l in yes:
            self.assertTrue(pw.LINE.search(l), l)
        for l in no:
            self.assertFalse(pw.LINE.search(l), l)

    def test_follow_writes_once_per_spell_and_keeps_the_other_options(self):
        d = tempfile.mkdtemp()
        opts = os.path.join(d, "opts.json")
        with open(opts, "w") as f:
            json.dump({"sessions": ["a"], "secretary": ["d"], "seatUntil": 123}, f)
        fake = os.path.join(d, "magpie")
        with open(fake, "w") as f:
            f.write("#!%s\nimport sys,json\np=%r\na=sys.argv[1:]\nopen(p+'.calls','a').write(' '.join(a[:2])+chr(10))\n"
                    "if len(a)==3: print(open(p).read())\nelse: open(p,'w').write(a[3])\n" % (sys.executable, opts))
        os.chmod(fake, 0o755)
        log = os.path.join(d, "log.txt")
        with open(log, "w") as f:
            f.write("2026/11/16 09:54:26 claude: x waits for room: 18 Claude Code processes run, 18 may (claudeRunsMost in settings)\n" * 5)
            f.write("2026/11/16 09:54:30 claude: a Claude Code run on claude-opus-5-5 had room after 1s\n")
        env = dict(os.environ, PW_MAGPIE=fake, PW_LOGS="cat " + log, PW_LOCK=os.path.join(d, "lock"), PW_VAR=os.path.join(d, "var"))
        r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "pool-watch.py")], env=env, capture_output=True, text=True, timeout=60)
        with open(opts) as f:
            back = json.load(f)
        self.assertEqual({k: v for k, v in back.items() if k != "poolFullUntil"}, {"sessions": ["a"], "secretary": ["d"], "seatUntil": 123})
        self.assertGreater(back["poolFullUntil"], 0, r.stdout + r.stderr)
        with open(opts + ".calls") as f:
            writes = [c for c in f.read().split("\n") if c == "plugin options" ]
        # each write is read, write, read back: one spell of five lines is one write
        self.assertEqual(len(writes), 3, writes)
        # the self-check's stamps: when the watcher first ran, and when a line last matched
        self.assertGreater(int(open(os.path.join(d, "var", "last-match")).read()), 0)
        self.assertTrue(os.path.exists(os.path.join(d, "var", "started")))

    def test_follow_keeps_bypassing_when_its_stamps_cannot_be_written(self):
        d = tempfile.mkdtemp()
        opts = os.path.join(d, "opts.json")
        with open(opts, "w") as f:
            json.dump({"seatUntil": 1}, f)
        fake = os.path.join(d, "magpie")
        with open(fake, "w") as f:
            f.write("#!%s\nimport sys\np=%r\na=sys.argv[1:]\nif len(a)==3: print(open(p).read())\nelse: open(p,'w').write(a[3])\n" % (sys.executable, opts))
        os.chmod(fake, 0o755)
        log = os.path.join(d, "log.txt")
        with open(log, "w") as f:
            f.write("2026/11/16 09:54:26 claude: x waits for room: 18 Claude Code processes run, 18 may (claudeRunsMost in settings)\n")
        blocker = os.path.join(d, "not-a-dir")
        open(blocker, "w").close()
        env = dict(os.environ, PW_MAGPIE=fake, PW_LOGS="cat " + log, PW_LOCK=os.path.join(d, "lock"), PW_VAR=os.path.join(blocker, "var"))
        r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "pool-watch.py")], env=env, capture_output=True, text=True, timeout=60)
        with open(opts) as f:
            self.assertGreater(json.load(f).get("poolFullUntil", 0), 0, "the bypass must not depend on the self-check's bookkeeping: " + r.stdout + r.stderr)


class SelfCheck(unittest.TestCase):
    """selfcheck against a stand-in process list, settings and clock-shifted stamps; PW_TELL catches what it would send."""
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.var = os.path.join(self.d, "var"); os.makedirs(self.var)
        self.top = os.path.join(self.d, "top.txt")
        with open(os.path.join(self.d, "settings.json"), "w") as f:
            json.dump({"claudeRunsMost": 18}, f)
        self.told = os.path.join(self.d, "told.txt")
        self.usage = os.path.join(self.d, "usage.csv")
        self.served(0)

    def procs(self, claude, helpers=6):
        # what `docker top <container> -eo pid,args` prints (11-16: without pid it refuses, "Couldn't find PID field")
        lines = ["PID                 COMMAND"] + ["%d /config/cache/magpie/claude-code/2.1.310/claude -p --input-format stream-json" % (1000 + i) for i in range(claude)]
        lines += ["%d /magpie claude-tui-helper /config/cache/magpie/claude-code/2.1.310/claude -p" % (2000 + i) for i in range(helpers)] + ["3000 /magpie web --addr 0.0.0.0:3430"]
        with open(self.top, "w") as f:
            f.write("\n".join(lines) + "\n")

    def stamp(self, name, hours_ago):
        with open(os.path.join(self.var, name), "w") as f:
            f.write(str(int((time.time() - hours_ago * 3600) * 1000)))

    def check(self, rc=0, **env_extra):
        env = dict(os.environ, PW_VAR=self.var, PW_TOP="cat " + self.top, PW_SETTINGS=os.path.join(self.d, "settings.json"), PW_TELL=self.told,
                   PW_USAGE="cat " + self.usage)
        env.update(env_extra)
        r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "pool-watch.py"), "selfcheck"], env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, rc, r.stdout + r.stderr)
        return r.stdout

    def served(self, claude, other=2):
        # what `magpie usage --csv --last 15m` prints, cut to the columns read here
        rows = ["time,provider,served_model,status"] + ["2026-11-16T20:00:00+08:00,claude,claude-opus-5-5,200"] * claude
        rows += ["2026-11-16T20:00:01+08:00,devin,swe-2,200"] * other
        with open(self.usage, "w") as f:
            f.write("\n".join(rows) + "\n")

    def state(self, **kw):
        p = os.path.join(self.var, "selfcheck.json")
        if kw:
            with open(p, "w") as f:
                json.dump(kw, f)
        with open(p) as f:
            return json.load(f)

    def told_n(self):
        try:
            with open(self.told) as f:
                return len([l for l in f if l.strip()])
        except OSError:
            return 0

    def test_a_full_pool_and_a_day_without_a_match_is_told_once(self):
        self.stamp("started", 30); self.stamp("last-match", 25); self.procs(18)
        out = self.check()
        self.assertIn("runs 18/18", out)
        self.assertEqual(self.told_n(), 1, "full pool, no match for 25h: the secretary must hear of it")
        self.assertIn("waits for room", open(self.told).read())
        self.check()
        self.assertEqual(self.told_n(), 1, "told twice for the same quiet spell")
        self.stamp("last-match", 0)
        self.check()
        self.assertEqual(self.told_n(), 1, "a match ends the spell")

    def test_no_word_while_matches_keep_coming_or_the_pool_was_not_full(self):
        self.stamp("started", 30); self.stamp("last-match", 23); self.procs(18)
        self.check()
        self.assertEqual(self.told_n(), 0, "a match 23h ago is within the day")
        os.remove(os.path.join(self.var, "selfcheck.json"))  # a fresh scenario: never full
        self.stamp("last-match", 25); self.procs(17)
        self.check()
        self.assertEqual(self.told_n(), 0, "17 of 18 is not a full pool: no match is expected")

    def test_magpie_helpers_wrapping_a_run_are_not_counted(self):
        self.stamp("started", 30); self.stamp("last-match", 25); self.procs(17, helpers=6)
        self.assertIn("runs 17/18", self.check())
        self.assertEqual(self.told_n(), 0)

    def test_the_pool_must_have_been_full_since_the_last_match(self):
        self.stamp("started", 30); self.stamp("last-match", 25); self.procs(17)
        with open(os.path.join(self.var, "selfcheck.json"), "w") as f:
            json.dump({"last_full": int((time.time() - 26 * 3600) * 1000)}, f)
        self.check()
        self.assertEqual(self.told_n(), 0, "full only before the last match: the match covered it")

    def test_a_watcher_that_never_ran_since_install_is_told_too(self):
        self.stamp("started", 25); self.procs(18)
        self.check()
        self.assertEqual(self.told_n(), 1, "no match at all since the watcher started a day ago")

    # 11-16, pr-cap2's review of #78: the count's own blind spot, and the check itself failing
    def test_a_count_of_zero_while_claude_answers_is_told_once_after_six_hours(self):
        self.stamp("started", 1); self.stamp("last-match", 0); self.procs(0, helpers=0); self.served(40)
        self.state(zero_since=int((time.time() - 7 * 3600) * 1000))
        self.assertIn("zero since", self.check())
        self.assertEqual(self.told_n(), 1, "0 Claude Code processes for 7 hours while the claude provider answers: the pattern is stale")
        self.assertIn("CLAUDE_BIN", open(self.told).read())
        self.check()
        self.assertEqual(self.told_n(), 1, "told twice for the same zero spell")
        self.procs(18)
        self.check()
        self.assertNotIn("zero_since", self.state(), "a count above 0 ends the zero spell")

    def test_a_count_of_zero_starts_the_clock_and_idle_zero_is_no_zero(self):
        self.stamp("started", 1); self.stamp("last-match", 0); self.procs(0, helpers=0); self.served(40)
        self.check()
        self.assertTrue(self.state().get("zero_since"), "a zero while claude answers must start the clock")
        self.assertEqual(self.told_n(), 0, "one zero is not six hours")
        self.state(zero_since=int((time.time() - 7 * 3600) * 1000))
        self.served(0)
        self.check()
        self.assertEqual(self.told_n(), 0, "no claude traffic: 0 processes is just idle")
        self.assertNotIn("zero_since", self.state(), "an idle check must reset the zero clock")
        self.state(zero_since=int((time.time() - 5 * 3600) * 1000))
        self.served(40)
        self.check()
        self.assertEqual(self.told_n(), 0, "five hours is not yet six")

    def test_a_failing_self_check_is_told_after_three_runs_once_a_spell(self):
        self.stamp("started", 1); self.procs(18)
        broken = dict(PW_TOP="false")
        self.check(1, **broken); self.check(1, **broken)
        self.assertEqual(self.told_n(), 0, "two failures are not yet a spell")
        self.check(1, **broken)
        self.assertEqual(self.told_n(), 1, "three failed self-checks must reach the secretary")
        self.assertIn("自检连续 3 次失败", open(self.told).read())
        self.check(1, **broken)
        self.assertEqual(self.told_n(), 1, "told twice for the same failing spell")
        self.check()
        self.assertFalse(os.path.exists(os.path.join(self.var, "selfcheck-fail.json")), "a good run must clear the count")
        self.check(1, **broken); self.check(1, **broken); self.check(1, **broken)
        self.assertEqual(self.told_n(), 2, "a new failing spell is told again")


if __name__ == "__main__":
    unittest.main()
