# Tests for seat-guard.py with stand-ins (providers.json, seat-offclaude, the sweep's stamp): python3 seat-guard.test.py
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
MIN = 60 * 1000
HOUR = 60 * MIN
T0 = 1795200000000  # 2026-11-20 something Z; every run sets SG_NOW
S1, S2, S3 = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333"

# the gateway's providers.json as it stood 11-18 04:22 to 11-21 07:41 +08 (trimmed)
NOV18 = ["devin/claude-opus-5-5", "devin/swe-2", "zcode/GLM-5.3"]


def providers(fallback, zcode_off=True, groups=()):
    return {"providers": [
        {"id": "claude", "fallback": fallback, "accountCaps": {"x": 95}},
        {"id": "devin", "name": ""},
        {"id": "zcode", "name": "", "off": True} if zcode_off else {"id": "zcode", "name": ""},
        {"id": "kiro", "name": "", "off": True},
    ], "groups": list(groups)}


def off_row(s, listed=True, secretary=False, served="devin/swe-2", turns=3):
    return {"session": s, "turns": turns, "served": {served: turns}, "requested": {"claude/claude-opus-5-5": turns},
            "first": "2026-11-20T11:19:21+08:00", "last": "2026-11-20T11:30:00+08:00", "listed": listed,
            "secretary": secretary, "worker": False}


class SeatGuard(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.tellf = os.path.join(self.d, "told.txt")
        self.asked = os.path.join(self.d, "asked-sweep")
        self.allow = os.path.join(self.d, "allow-fallback")
        self.off = os.path.join(self.d, "off.json")
        self.prov = os.path.join(self.d, "providers.json")
        self.calls = os.path.join(self.d, "calls.txt")
        fake = os.path.join(self.d, "seat-offclaude")
        with open(fake, "w") as f:
            f.write("#!%s\nimport sys,json\nd=%r\nopen(d+'/calls.txt','a').write(' '.join(sys.argv[1:])+'\\n')\n"
                    "o=json.load(open(d+'/off.json'))\nif o.get('exit'): sys.stderr.write('boom'); sys.exit(o['exit'])\n"
                    "print(json.dumps(o))\n" % (sys.executable, self.d))
        os.chmod(fake, 0o755)
        self.fake = fake
        self.set_providers(["devin/claude-opus-5-5"])
        self.set_off([])
        self.set_asked(T0)
        self.sweep_comes = True

    def set_providers(self, fallback, **kw):
        with open(self.prov, "w") as f:
            json.dump(providers(fallback, **kw), f)

    def set_off(self, sessions, rows=500, exit=0):
        with open(self.off, "w") as f:
            json.dump({"minutes": 15, "rows": rows, "watched": 3, "lease": "off", "sessions": sessions, "exit": exit}, f)

    def set_asked(self, ms):
        with open(self.asked, "w") as f:
            f.write(str(ms))

    def run_it(self, now, *args):
        if self.sweep_comes:  # tests about other checks: the stuck-sweep came a few minutes ago
            self.set_asked(now - 3 * MIN)
        env = dict(os.environ, SG_PROVIDERS=self.prov, SG_OFFCLAUDE=self.fake, SG_ASKED=self.asked, SG_VAR=os.path.join(self.d, "var"),
                   SG_ALLOW=self.allow, SG_TELL=self.tellf, SG_NOW=str(now))
        return subprocess.run([sys.executable, "-I", os.path.join(HERE, "seat-guard.py"), *args], env=env,
                              capture_output=True, text=True, timeout=60)

    def told(self):
        try:
            with open(self.tellf) as f:
                return [l for l in f.read().splitlines() if l]
        except OSError:
            return []

    # --- fallback ---

    def test_the_nov18_chain_is_told(self):
        # the cause of 11-18..11-21: SWE-2 behind the seats, on a provider that is on
        self.set_providers(NOV18)
        r = self.run_it(T0)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        t = self.told()
        self.assertEqual(len(t), 1, t)
        named = t[0].split("其中 ", 1)[1].split(" 不是 Claude", 1)[0]  # the members told as not Claude
        self.assertIn("devin/swe-2", named)
        self.assertNotIn("zcode/GLM-5.3", named, "zcode is off: GLM answers nothing, so it is not named")
        self.assertNotIn("claude-opus-5-5", named, "Devin's Opus is Claude")

    def test_claude_only_chain_is_quiet(self):
        for chain in (["devin/claude-opus-5-5"], [], ["devin/claude-opus-5-5", "zcode/GLM-5.3"], ["kiro/claude-opus-5.5"]):
            self.setUp()
            self.set_providers(chain)
            r = self.run_it(T0)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(self.told(), [], chain)

    def test_glm_counts_once_zcode_is_on(self):
        self.set_providers(["devin/claude-opus-5-5", "zcode/GLM-5.3"], zcode_off=False)
        self.run_it(T0)
        t = self.told()
        self.assertEqual(len(t), 1, t)
        self.assertIn("zcode/GLM-5.3", t[0])

    def test_groups_are_followed(self):
        g = [{"id": "opus", "members": ["claude/claude-opus-5-5", "devin/claude-opus-5-5"]},
             {"id": "mixed", "members": ["group/opus", "devin/swe-2"]}]
        self.set_providers(["group/opus"], groups=g)
        self.run_it(T0)
        self.assertEqual(self.told(), [], "a group of Claude members is Claude")
        self.set_providers(["group/mixed"], groups=g)
        self.run_it(T0 + 10 * MIN)
        t = self.told()
        self.assertEqual(len(t), 1, t)
        self.assertIn("devin/swe-2 in group/mixed", t[0])

    def test_told_once_per_chain_then_daily(self):
        self.set_providers(NOV18)
        for i in range(6):
            self.run_it(T0 + i * 10 * MIN)
        self.assertEqual(len(self.told()), 1, "told again within the day")
        self.set_providers(["devin/swe-2"])
        self.run_it(T0 + 70 * MIN)
        self.assertEqual(len(self.told()), 2, "a different chain is news")
        self.run_it(T0 + 70 * MIN + 24 * HOUR)
        self.assertEqual(len(self.told()), 3, "still there a day later: told again")

    def test_a_fixed_chain_ends_the_spell(self):
        self.set_providers(NOV18)
        self.run_it(T0)
        self.set_providers(["devin/claude-opus-5-5"])
        self.run_it(T0 + 10 * MIN)
        self.set_providers(NOV18)
        self.run_it(T0 + 20 * MIN)
        self.assertEqual(len(self.told()), 2, "put back after a fix: told at once")

    def test_an_accepted_chain_is_not_told(self):
        with open(self.allow, "w") as f:
            f.write("# accepted 11-21 by the secretary\n" + " ".join(NOV18) + "\n")
        self.set_providers(NOV18)
        r = self.run_it(T0)
        self.assertEqual(self.told(), [])
        self.assertIn("allowed", r.stdout)
        self.set_providers(["devin/swe-2", "devin/claude-opus-5-5"])
        self.run_it(T0 + 10 * MIN)
        self.assertEqual(len(self.told()), 1, "only the chain written down is accepted, not any chain with those members")

    # --- off-Claude turns ---

    def test_listed_sessions_off_claude_are_told_once(self):
        self.set_off([off_row(S1), off_row(S2, listed=False, secretary=True), off_row(S3, listed=False)])
        self.run_it(T0)
        t = self.told()
        self.assertEqual(len(t), 1, t)
        self.assertIn(S1[:8], t[0])
        self.assertNotIn(S2[:8], t[0], "the secretary's own groups end in SWE-2 on purpose")
        self.assertNotIn(S3[:8], t[0], "a session not on the whitelist was never meant for Claude")
        self.assertIn("--by seat-guard", open(self.calls).read(), "the guard's runs must not count as the sweep's")
        self.run_it(T0 + 10 * MIN)
        self.assertEqual(len(self.told()), 1, "the same session told again within two hours")
        self.set_off([off_row(S1), off_row(S2)])  # S2 now on the whitelist
        self.run_it(T0 + 20 * MIN)
        t = self.told()
        self.assertEqual(len(t), 2, t)
        self.assertIn(S2[:8], t[1])
        self.assertNotIn(S1[:8], t[1])
        self.set_off([off_row(S1)])
        self.run_it(T0 + 2 * HOUR + MIN)
        self.assertEqual(len(self.told()), 3, "still off Claude two hours on: told again")

    def test_a_quiet_window_is_not_clear_forever(self):
        self.set_off([], rows=0)
        for i in range(30):  # 5 hours of empty windows: quiet
            r = self.run_it(T0 + i * 10 * MIN)
            self.assertEqual(r.returncode, 0, r.stdout)
        for i in range(30, 40):  # past 6 hours: blind, and told as a failing check
            self.run_it(T0 + i * 10 * MIN)
        t = self.told()
        self.assertEqual(len(t), 1, t)
        self.assertIn("offclaude", t[0])

    # --- the stuck-sweep still coming ---

    def test_a_silent_sweep_is_told(self):
        self.sweep_comes = False
        self.set_asked(T0 - 41 * MIN)
        self.run_it(T0)
        t = self.told()
        self.assertEqual(len(t), 1, t)
        self.assertIn("stuck-sweep", t[0])
        self.assertIn("dda56b65", t[0])
        for i in range(1, 6):
            self.run_it(T0 + i * 10 * MIN)
        self.assertEqual(len(self.told()), 1, "the same silent spell told again within 12 hours")
        self.run_it(T0 + 12 * HOUR)
        self.assertEqual(len(self.told()), 2, "still silent 12 hours on: told again")

    def test_a_coming_sweep_is_quiet(self):
        self.sweep_comes = False
        for i in range(10):
            self.set_asked(T0 + i * 10 * MIN - 3 * MIN)
            self.run_it(T0 + i * 10 * MIN)
        self.assertEqual(self.told(), [])

    def test_no_stamp_yet_waits_from_the_first_run(self):
        self.sweep_comes = False
        os.remove(self.asked)
        self.run_it(T0)
        self.run_it(T0 + 30 * MIN)
        self.assertEqual(self.told(), [], "just installed: give the sweep its 40 minutes")
        self.run_it(T0 + 41 * MIN)
        t = self.told()
        self.assertEqual(len(t), 1, t)
        self.assertIn("一次都没有", t[0])

    def test_a_returning_sweep_ends_the_spell(self):
        self.sweep_comes = False
        self.set_asked(T0 - 50 * MIN)
        self.run_it(T0)
        self.set_asked(T0 + 5 * MIN)
        self.run_it(T0 + 10 * MIN)
        self.run_it(T0 + 60 * MIN)
        self.assertEqual(len(self.told()), 2, "a new silent spell after the sweep came back is news")

    # --- the guard itself ---

    def test_a_failing_check_is_told_once_and_does_not_stop_the_others(self):
        self.set_off([], exit=2)
        self.set_providers(NOV18)
        rcs = [self.run_it(T0 + i * 10 * MIN).returncode for i in range(5)]
        self.assertEqual(rcs, [1] * 5)
        t = self.told()
        self.assertEqual(len(t), 2, t)
        self.assertIn("devin/swe-2", t[0], "the fallback check ran although seat-offclaude failed")
        self.assertIn("offclaude 连续 3 次失败", t[1])
        self.set_off([])
        self.assertEqual(self.run_it(T0 + 60 * MIN).returncode, 0)
        self.set_off([], exit=2)
        for i in range(3):
            self.run_it(T0 + 70 * MIN + i * 10 * MIN)
        self.assertEqual(len(self.told()), 3, "a new failing spell after a success is told again")

    def test_a_broken_providers_file_is_a_failure_not_all_clear(self):
        with open(self.prov, "w") as f:
            f.write('{"providers": [{"id": "devin"}]}')
        r = self.run_it(T0)
        self.assertEqual(r.returncode, 1)
        self.assertIn("fallback failed", r.stdout)

    def test_status_tells_no_one_and_saves_nothing(self):
        self.set_providers(NOV18)
        self.set_off([off_row(S1)])
        r = self.run_it(T0, "status")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("fallback not Claude", r.stdout)
        self.assertEqual(self.told(), [])
        self.assertFalse(os.path.exists(os.path.join(self.d, "var", "state.json")))
        self.run_it(T0 + MIN)
        self.assertEqual(len(self.told()), 2, "status must not have marked anything as told")


if __name__ == "__main__":
    unittest.main()
