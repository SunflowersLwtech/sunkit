#!/usr/bin/env python3
# Offline tests for gw-fallback.n150.py and the fallback block in claude-bypass.n150.sh.
# A local fake gateway, a fake config.toml and a fake /proc; the fake claude processes use pids
# above pid_max, so a SIGTERM sent by mistake can't reach a real process.
# Run: python3 tools/magpie-gateway/client/gw-fallback.test.py
import http.server, json, os, subprocess, sys, tempfile, threading, time, unittest
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "gw-fallback.n150.py")
BYPASS = os.path.join(HERE, "claude-bypass.n150.sh")
GW_PID, DIRECT_PID, OTHER_PID, STRANGER_PID = 99999901, 99999902, 99999903, 99999904


class Fake(http.server.BaseHTTPRequestHandler):
    status, seen = 200, []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        Fake.seen.append((self.path, self.headers.get("X-Test-Key"), body.get("model")))
        out = json.dumps({"model": "fake-served", "content": [{"type": "text", "text": "PONG"}]} if Fake.status == 200
                         else {"error": {"message": "upstream down"}}).encode()
        self.send_response(Fake.status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


def ts(ago):
    return (datetime.now().astimezone() - timedelta(seconds=ago)).isoformat(timespec="milliseconds")


BUSY = 'time=%s level=INFO msg="message received" platform=feishu\n' % ts(5)
IDLE = 'time=%s level=INFO msg="message received"\ntime=%s level=INFO msg="turn complete" session=s1\n' % (ts(300), ts(120))


class GwFallback(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_port

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self.tmp.name, "home")
        self.proc = os.path.join(self.tmp.name, "proc")
        os.makedirs(self.home)
        self.config("magpie")
        self.procs({7: ("/feishu-cc/bin/cc-connect", "cc-connect", 1, []),
                    GW_PID: ("claude", "claude", 7, ["ANTHROPIC_BASE_URL=" + self.base, "ANTHROPIC_CUSTOM_HEADERS=X-Test-Key: k1"]),
                    OTHER_PID: ("claude", "claude", 7, ["ANTHROPIC_MODEL=claude-opus-5-5"]),
                    STRANGER_PID: ("claude", "claude", 1, ["ANTHROPIC_BASE_URL=" + self.base])})
        Fake.status, Fake.seen = 200, []

    def tearDown(self):
        self.tmp.cleanup()

    def config(self, provider):
        with open(os.path.join(self.home, "config.toml"), "w") as f:
            f.write('[[projects]]\nname = "assistant"\n[projects.agent]\ntype = "claudecode"\n'
                    '[projects.agent.options]\nprovider = "%s"\nmodel = "claude-opus-5-5"\n'
                    '[[projects.agent.providers]]\nname = "anthropic"\nmodel = "claude-opus-5-5"\n'
                    '[[projects.agent.providers]]\nname = "magpie"\nbase_url = "%s"\nmodel = "claude-opus-5-5"\n'
                    '[projects.agent.providers.env]\nANTHROPIC_CUSTOM_HEADERS = "X-Test-Key: k1"\n' % (provider, self.base))

    def procs(self, table):
        for pid, (argv0, name, ppid, env) in table.items():
            d = os.path.join(self.proc, str(pid))
            os.makedirs(d, exist_ok=True)
            open(os.path.join(d, "cmdline"), "wb").write(argv0.encode() + b"\0--config\0x\0")
            open(os.path.join(d, "status"), "w").write("Name:\t%s\nPPid:\t%d\n" % (name, ppid))
            open(os.path.join(d, "environ"), "wb").write(b"\0".join(e.encode() for e in env) + b"\0")

    def run_once(self, logs=IDLE):
        r = subprocess.run([sys.executable, SCRIPT], input=logs, capture_output=True, text=True,
                           env={**os.environ, "GWF_HOME": self.home, "GWF_PROC": self.proc})
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def state(self):
        return json.load(open(os.path.join(self.home, "gw-fallback/state.json")))

    def patch_state(self, **kw):
        st = self.state()
        st.update(kw)
        json.dump(st, open(os.path.join(self.home, "gw-fallback/state.json"), "w"))

    def log(self):
        return open(os.path.join(self.home, "gw-fallback/log")).read()

    def flag(self):
        p = os.path.join(self.home, "gw-fallback/direct")
        return open(p).read() if os.path.exists(p) else None

    def test_probe_sends_the_secretary_key_and_model_and_waits_between_probes(self):
        self.run_once()
        self.assertEqual(Fake.seen, [("/v1/messages", "k1", "claude-opus-5-5")])
        self.run_once()
        self.assertEqual(len(Fake.seen), 1, "a second run inside 290 s must not probe again")
        self.assertIsNone(self.flag())
        self.assertIn("probe ok 200", self.log())

    def test_three_failures_switch_to_direct_and_wait_for_idle(self):
        Fake.status = 503
        out = ""
        for i in range(3):
            out += self.run_once(BUSY)
            if i < 2:
                self.assertIsNone(self.flag(), "switched after %d failures" % (i + 1))
        self.assertEqual(self.flag(), self.base)
        self.assertIn("已切直连席位", out)
        self.assertIn("503", out)
        self.assertIn("pending direct: busy, waiting", self.log())
        self.assertNotIn("SIGTERM", self.log())
        self.run_once(IDLE)
        self.assertIn("SIGTERM %d (idle)" % GW_PID, self.log())
        self.assertNotIn(str(OTHER_PID), self.log())
        self.assertNotIn(str(STRANGER_PID), self.log())
        self.assertEqual(self.state()["pending"], "direct", "the process is still there, so the switch isn't done")
        os.remove(os.path.join(self.proc, str(GW_PID), "status"))  # it exited
        self.run_once(IDLE)
        self.assertIsNone(self.state()["pending"])
        self.assertIn("pending direct: done", self.log())

    def test_busy_for_twenty_minutes_forces_the_switch(self):
        Fake.status = 503
        for _ in range(3):
            self.run_once(BUSY)
        self.assertNotIn("SIGTERM", self.log())
        self.patch_state(down_since=time.time() - 21 * 60)
        out = self.run_once(BUSY)
        self.assertIn("SIGTERM %d (forced)" % GW_PID, self.log())
        self.assertIn("强制重起", out)
        self.assertNotIn("强制重起", self.run_once(BUSY), "the forced-restart alert goes out once")

    def test_five_good_probes_switch_back_and_restart_the_direct_process(self):
        Fake.status = 503
        for _ in range(3):
            self.run_once(IDLE)
        self.procs({GW_PID: ("claude", "claude", 7, ["GW_FALLBACK_DIRECT=1", "ANTHROPIC_MODEL=claude-opus-5-5"])})
        Fake.status = 200
        out = ""
        for i in range(5):
            out += self.run_once(BUSY)
            if i < 4:
                self.assertEqual(self.flag(), self.base, "switched back after %d good probes" % (i + 1))
        self.assertIsNone(self.flag())
        self.assertIn("网关恢复", out)
        self.assertIn("pending gateway: busy, waiting", self.log())
        self.run_once(IDLE)
        self.assertIn("pending gateway: SIGTERM %d (idle)" % GW_PID, self.log())

    def test_a_drill_is_labelled_until_the_secretary_is_back_on_the_gateway(self):
        self.run_once()
        self.patch_state(mode="direct", pending="direct", since=time.time(), drill=True)
        open(os.path.join(self.home, "gw-fallback/direct"), "w").write(self.base)
        self.run_once(IDLE)
        self.assertIn("pending direct: SIGTERM %d (idle)" % GW_PID, self.log())
        self.procs({GW_PID: ("claude", "claude", 7, ["GW_FALLBACK_DIRECT=1"])})
        out = "".join(self.run_once(IDLE) for _ in range(5))
        self.assertIn("【演练】网关恢复", out)
        self.assertIsNone(self.flag())
        os.remove(os.path.join(self.proc, str(GW_PID), "status"))
        self.run_once(IDLE)
        self.assertFalse(self.state()["drill"])
        self.patch_state(last_probe=0)
        Fake.status = 503
        out = "".join(self.run_once() for _ in range(3))
        self.assertIn("已切直连席位", out)
        self.assertNotIn("演练", out)

    def test_one_good_probe_resets_the_failure_count(self):
        Fake.status = 503
        self.run_once(); self.run_once()
        Fake.status = 200
        self.run_once()
        Fake.status = 503
        self.run_once(); self.run_once()
        self.assertIsNone(self.flag())

    def test_not_pinned_to_magpie_alerts_without_switching(self):
        self.config("anthropic")
        Fake.status = 503
        out = "".join(self.run_once() for _ in range(3))
        self.assertIsNone(self.flag())
        self.assertIn("秘书的网关不通", out)
        self.assertNotIn("SIGTERM", self.log())

    def test_a_hung_timer_line_counts_as_busy(self):
        Fake.status = 503
        busy_timer = IDLE + 'time=%s level=ERROR msg="timer: job failed" id=x error="session \\"k\\" is busy"\n' % ts(3)
        for _ in range(4):
            self.run_once(busy_timer)
        self.assertNotIn("SIGTERM", self.log())


class Bypass(unittest.TestCase):
    """The fallback block in claude-bypass, run with a fake claude that prints what it got."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.flag = os.path.join(d, "direct")
        fake = os.path.join(d, "claude")
        open(fake, "w").write('#!/bin/bash\necho "args=$*"\nfor v in ANTHROPIC_BASE_URL ANTHROPIC_CUSTOM_HEADERS CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST '
                              'ANTHROPIC_MODEL GW_FALLBACK_DIRECT IS_SANDBOX; do echo "$v=${!v-<unset>}"; done\n')
        os.chmod(fake, 0o755)
        src = open(BYPASS).read()
        self.assertEqual(src.count("/feishu-cc/npm-global/bin/claude"), 1)
        self.assertEqual(src.count("/feishu-cc/gw-fallback/direct"), 1)
        self.script = os.path.join(d, "bypass")
        open(self.script, "w").write(src.replace("/feishu-cc/npm-global/bin/claude", fake).replace("/feishu-cc/gw-fallback/direct", self.flag))
        os.chmod(self.script, 0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def run_bypass(self, model="claude-opus-5-5", flag=None, base="http://100.116.218.86:3425", env_model="claude-opus-5-5"):
        if flag is not None:
            open(self.flag, "w").write(flag)
        env = {k: v for k, v in os.environ.items() if not k.startswith(("ANTHROPIC_", "CLAUDE_CODE_", "GW_FALLBACK"))}
        env.update({"ANTHROPIC_BASE_URL": base, "ANTHROPIC_CUSTOM_HEADERS": "X-Key: k1", "CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST": "1",
                    "ANTHROPIC_MODEL": env_model, "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "160000"})
        r = subprocess.run([self.script, "--permission-mode", "auto", "--resume", "abc", "--model", model],
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return dict(line.split("=", 1) for line in r.stdout.splitlines())

    def test_no_flag_keeps_the_gateway(self):
        out = self.run_bypass()
        self.assertEqual(out["ANTHROPIC_BASE_URL"], "http://100.116.218.86:3425")
        self.assertEqual(out["GW_FALLBACK_DIRECT"], "<unset>")
        self.assertIn("--permission-mode bypassPermissions", out["args"])
        self.assertIn("CLAUDE_CODE_AUTO_COMPACT_WINDOW", out["args"])

    def test_flag_for_this_gateway_goes_direct(self):
        out = self.run_bypass(flag="http://100.116.218.86:3425")
        for v in ("ANTHROPIC_BASE_URL", "ANTHROPIC_CUSTOM_HEADERS", "CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST"):
            self.assertEqual(out[v], "<unset>", v)
        self.assertEqual(out["GW_FALLBACK_DIRECT"], "1")
        self.assertEqual(out["IS_SANDBOX"], "1")
        self.assertTrue(out["args"].endswith("--model claude-opus-5-5"), out["args"])
        self.assertIn("--permission-mode bypassPermissions", out["args"])

    def test_gateway_only_model_names_become_opus_when_direct(self):
        out = self.run_bypass(model="auto/kimi-k3", env_model="frontier", flag="http://100.116.218.86:3425")
        self.assertTrue(out["args"].endswith("--model claude-opus-5-5"), out["args"])
        self.assertEqual(out["ANTHROPIC_MODEL"], "claude-opus-5-5")
        out = self.run_bypass(model="claude-sonnet-5-5", env_model="claude-sonnet-5-5", flag="http://100.116.218.86:3425")
        self.assertTrue(out["args"].endswith("--model claude-sonnet-5-5"), out["args"])

    def test_flag_for_another_gateway_changes_nothing(self):
        out = self.run_bypass(flag="http://10.0.0.1:3425")
        self.assertEqual(out["ANTHROPIC_BASE_URL"], "http://100.116.218.86:3425")
        self.assertEqual(out["GW_FALLBACK_DIRECT"], "<unset>")
        out = self.run_bypass(model="auto/kimi-k3", flag="http://10.0.0.1:3425")
        self.assertTrue(out["args"].endswith("--model auto/kimi-k3"), out["args"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
