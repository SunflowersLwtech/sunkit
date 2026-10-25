"""Tests for bin/harness-run, with fake clients and a fake ssh/scp that run against a temp "remote" home.

    python3 -m unittest discover -s plugins/frontier/tests
"""
import json, os, shutil, subprocess, sys, tempfile, textwrap, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HR = os.path.join(HERE, "..", "bin", "harness-run")

FAKE_AGY = """#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
prompt = a[a.index("-p") + 1]
open(os.path.join(os.environ["FAKE_LOG"], "agy-args.json"), "w").write(json.dumps({"argv": a, "cwd": os.getcwd()}))
if "FAILME" in prompt:
    print(json.dumps({"status": "ERROR", "error": "Gemini weekly limit reached"}))
    sys.exit(0)
if os.path.exists("in.txt"):
    open("out.txt", "w").write(open("in.txt").read()[::-1])
print(json.dumps({"status": "SUCCESS", "response": "agy says: " + prompt}))
"""
# ssh [opts…] host cmd   -> cmd runs under sh with HOME=$REMOTE_HOME; the host is logged
FAKE_SSH = """#!/usr/bin/env python3
import os, subprocess, sys
a = [x for x in sys.argv[1:]]
while a and a[0] == "-o":
    a = a[2:]
host, cmd = a[0], a[1]
open(os.path.join(os.environ["FAKE_LOG"], "hosts"), "a").write(host + "\\n")
env = dict(os.environ, HOME=os.environ["REMOTE_HOME"])
sys.exit(subprocess.run(["/bin/sh", "-c", cmd], cwd=env["HOME"], env=env).returncode)
"""
# scp [opts…] src… dst, where host:path is a path under $REMOTE_HOME
FAKE_SCP = """#!/usr/bin/env python3
import os, shutil, sys
a = [x for x in sys.argv[1:] if x != "-q"]
while a and a[0] == "-o":
    a = a[2:]
r = lambda p: os.path.join(os.environ["REMOTE_HOME"], p.split(":", 1)[1]) if ":" in p else p
*srcs, dst = a
for s in srcs:
    d = r(dst)
    shutil.copy(r(s), os.path.join(d, os.path.basename(s)) if os.path.isdir(d) else d)
"""
FAKE_ECHO = """#!/usr/bin/env python3
import json, os, sys
print(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd(), "stdin": sys.stdin.read() if not sys.stdin.isatty() else "",
                  "claudecode": os.environ.get("CLAUDECODE")}))
"""


def script(path, body):
    with open(path, "w") as f:
        f.write(body)
    os.chmod(path, 0o755)
    return path


class HarnessRun(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp()
        self.remote = os.path.join(self.t, "remote")
        self.log = os.path.join(self.t, "log")
        self.work = os.path.join(self.t, "work")
        for d in (self.remote, self.log, self.work, os.path.join(self.remote, ".local", "bin")):
            os.makedirs(d, exist_ok=True)
        script(os.path.join(self.remote, ".local", "bin", "agy"), FAKE_AGY)
        ssh = script(os.path.join(self.t, "ssh"), FAKE_SSH)
        scp = script(os.path.join(self.t, "scp"), FAKE_SCP)
        self.echo = script(os.path.join(self.t, "echo-client"), FAKE_ECHO)
        self.settings = os.path.join(self.t, "magpie-settings.json")
        with open(self.settings, "w") as f:
            json.dump({"env": {"ANTHROPIC_BASE_URL": "http://gw", "ANTHROPIC_CUSTOM_HEADERS": "x-api-key: k"}}, f)
        self.env = dict(os.environ, HARNESS_SSH=ssh, HARNESS_SCP=scp, REMOTE_HOME=self.remote, FAKE_LOG=self.log,
                        HARNESS_HOST_AGY_PRO="fakehost", HARNESS_HOST_AGY_TRIAL="otherhost",
                        HARNESS_OPENCODE_BIN=self.echo, HARNESS_CLAUDE_BIN=self.echo, HARNESS_GW_SETTINGS=self.settings,
                        CLAUDECODE="1")

    def tearDown(self):
        shutil.rmtree(self.t)

    def hr(self, *args, stdin=None):
        return subprocess.run([sys.executable, HR, *args], cwd=self.work, env=self.env, input=stdin,
                              capture_output=True, text=True, timeout=60)

    def test_agy_job_copies_files_in_and_new_files_back(self):
        with open(os.path.join(self.work, "in.txt"), "w") as f:
            f.write("abc")
        p = self.hr("agy-pro", "-f", "in.txt", "--out", "back", "reverse", "it")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(p.stdout.startswith("agy says: reverse it\n"))
        self.assertEqual(open(os.path.join(self.work, "back", "out.txt")).read(), "cba")
        self.assertFalse(os.path.exists(os.path.join(self.work, "back", "in.txt")))   # unchanged input stays there
        a = json.load(open(os.path.join(self.log, "agy-args.json")))
        self.assertIn("--sandbox", a["argv"])
        self.assertEqual(a["argv"][a["argv"].index("--model") + 1], "gemini-4-argon-medium")
        self.assertIn("/.harness-jobs/", a["cwd"])

    def test_a_failed_agy_run_fails_and_tries_no_other_account(self):
        p = self.hr("agy-pro", "FAILME")
        self.assertEqual(p.returncode, 1)
        self.assertIn("Gemini weekly limit reached", p.stderr)
        self.assertEqual(open(os.path.join(self.log, "hosts")).read().split(), ["fakehost", "fakehost"])

    def test_unreachable_host_is_reported(self):
        self.env["HARNESS_SSH"] = "false"
        p = self.hr("agy-trial", "hi")
        self.assertEqual(p.returncode, 1)
        self.assertIn("cannot reach otherhost", p.stderr)

    def test_zen_reads_by_default_and_writes_with_edit(self):
        d = json.loads(self.hr("zen", "look").stdout.split("\n---\n")[0])
        self.assertEqual(d["argv"][:5], ["run", "-m", "opencode/deepseek-v4.1-flash-free", "--agent", "plan"])
        self.assertEqual(os.path.realpath(d["cwd"]), os.path.realpath(self.work))
        with open(os.path.join(self.work, "a.png"), "w") as f:
            f.write("x")
        d = json.loads(self.hr("zen", "--edit", "-m", "opencode/glm-5.3-flash-free", "-f", "a.png", "fix").stdout.split("\n---\n")[0])
        self.assertEqual(d["argv"], ["run", "-m", "opencode/glm-5.3-flash-free", "--auto", "-f", "a.png", "fix"])

    def test_gw_runs_headless_claude_on_the_gateway_in_plan_mode(self):
        d = json.loads(self.hr("gw", "-m", "frontier", "-", stdin="the task\n").stdout.split("\n---\n")[0])
        a = d["argv"]
        self.assertEqual(a[a.index("--settings") + 1], self.settings)
        self.assertEqual(a[a.index("--model") + 1], "frontier")
        self.assertEqual(a[a.index("--permission-mode") + 1], "plan")
        self.assertEqual(d["stdin"], "the task\n")
        self.assertIsNone(d["claudecode"])          # a nested Claude Code is not told it is nested

    def test_gw_without_setup_says_so(self):
        os.remove(self.settings)
        p = self.hr("gw", "hi")
        self.assertEqual(p.returncode, 1)
        self.assertIn("magpie-client setup", p.stderr)

    def test_bad_calls(self):
        self.assertIn("unknown harness", self.hr("nope", "x").stderr)
        self.assertIn("empty prompt", self.hr("zen", "  ").stderr)
        self.assertIn("no such file", self.hr("zen", "-f", "missing.txt", "x").stderr)
        self.assertIn("agy-pro", self.hr("list").stdout)


if __name__ == "__main__":
    unittest.main()
