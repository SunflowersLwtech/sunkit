import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

import claude_rescue as cr

CONNREFUSED = "API Error: Connection refused — a firewall or proxy may be blocking it (ECONNREFUSED)"


def ok(text="done"):
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def api_error(text=CONNREFUSED):
    return {"type": "assistant", "isApiErrorMessage": True, "error": "server_error",
            "message": {"model": "<synthetic>", "role": "assistant", "content": [{"type": "text", "text": text}]}}


def user(text="hi"):
    return {"type": "user", "message": {"role": "user", "content": text}}


def dead_pid():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


class RescueTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name
        self._env = {k: os.environ.get(k) for k in ("HOME", "CLAUDE_CONFIG_DIR")}
        os.environ["HOME"] = self.home
        os.environ.pop("CLAUDE_CONFIG_DIR", None)
        self.claude = os.path.join(self.home, ".claude")
        os.makedirs(os.path.join(self.claude, "sessions"))
        os.makedirs(os.path.join(self.claude, "projects"))
        vdir = os.path.join(self.home, ".local/share/claude/versions")
        for v in ("2.1.290", "2.1.295", "2.1.296"):
            os.makedirs(os.path.join(vdir, v))
        os.makedirs(os.path.join(self.home, ".local/bin"))
        os.symlink(os.path.join(vdir, "2.1.295"), os.path.join(self.home, ".local/bin/claude"))
        self.n = 0

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def session(self, records, name=None, pid=None, version="2.1.295", project="-Users-me-proj", **extra):
        self.n += 1
        sid = "%08d-0000-4000-8000-000000000000" % self.n
        pid = os.getpid() if pid is None else pid
        info = {"pid": pid, "sessionId": sid, "cwd": "/Users/me/proj", "name": name or "s%d" % self.n,
                "version": version, "kind": "interactive", "status": "idle",
                "startedAt": int(time.time() * 1000) - 60000, "updatedAt": int(time.time() * 1000)}
        info.update(extra)
        with open(os.path.join(self.claude, "sessions", "%d-%d.json" % (pid, self.n)), "w") as f:
            json.dump(info, f)
        self.transcript(sid, records, project)
        return sid

    def transcript(self, sid, records, project):
        d = os.path.join(self.claude, "projects", project)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, sid + ".jsonl")
        with open(path, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
        return path

    def row(self, sid):
        return next(r for r in cr.scan(include_all=True) if r["sessionId"] == sid)

    # -- classification

    def test_stuck_after_repeated_connection_errors(self):
        sid = self.session([user(), ok(), user(), api_error(), user(), api_error()])
        r = self.row(sid)
        self.assertEqual(r["state"], "STUCK")
        self.assertEqual(r["trailingErrors"], 2)
        self.assertEqual(r["errorKinds"], ["ECONNREFUSED"])

    def test_healthy_session(self):
        sid = self.session([user(), ok(), user(), ok("all good")])
        r = self.row(sid)
        self.assertEqual(r["state"], "OK")
        self.assertEqual(r["trailingErrors"], 0)

    def test_recovered_after_errors_is_not_stuck(self):
        sid = self.session([user(), api_error(), api_error(), api_error(), user(), ok("back")])
        r = self.row(sid)
        self.assertEqual(r["state"], "OK")
        self.assertEqual(r["trailingErrors"], 0)

    def test_single_connection_error_is_not_stuck(self):
        sid = self.session([user(), ok(), user(), api_error()])
        self.assertEqual(self.row(sid)["state"], "ERROR")

    def test_overloaded_errors_are_not_connection_stuck(self):
        sid = self.session([ok(), api_error("API Error: 529 Overloaded"), api_error("API Error: 529 Overloaded")])
        r = self.row(sid)
        self.assertEqual(r["state"], "ERROR")
        self.assertEqual(r["errorKinds"], ["overloaded"])

    def test_mixed_connection_kinds(self):
        sid = self.session([ok(), api_error("API Error: socket hang up (ECONNRESET)"),
                            api_error("API Error: Request timed out (ETIMEDOUT)")])
        r = self.row(sid)
        self.assertEqual(r["state"], "STUCK")
        self.assertEqual(r["errorKinds"], ["ECONNRESET", "ETIMEDOUT"])

    def test_sidechain_success_does_not_hide_main_thread_errors(self):
        side = ok("subagent reply")
        side["isSidechain"] = True
        sid = self.session([ok(), api_error(), side, api_error()])
        self.assertEqual(self.row(sid)["state"], "STUCK")

    def test_error_text_without_flag(self):
        rec = api_error()
        del rec["isApiErrorMessage"]
        sid = self.session([ok(), rec, rec])
        self.assertEqual(self.row(sid)["state"], "STUCK")

    def test_large_transcript_reverse_read(self):
        filler = [user("x" * 500), ok("y" * 500)] * 400
        sid = self.session(filler + [api_error(), api_error(), api_error()])
        r = self.row(sid)
        self.assertEqual(r["state"], "STUCK")
        self.assertEqual(r["trailingErrors"], 3)

    # -- versions

    def test_version_staleness_uses_launcher_target(self):
        old = self.session([ok()], version="2.1.290")
        same = self.session([ok()], version="2.1.295")
        self.assertEqual(cr.installed_version(), "2.1.295")
        self.assertTrue(self.row(old)["versionStale"])
        self.assertFalse(self.row(same)["versionStale"])

    # -- transcripts in more than one project dir

    def test_duplicate_project_dir_picks_most_recent(self):
        sid = self.session([ok(), api_error(), api_error()], project="-old-path")
        old = os.path.join(self.claude, "projects", "-old-path", sid + ".jsonl")
        os.utime(old, (time.time() - 3600, time.time() - 3600))
        new = self.transcript(sid, [ok(), api_error(), api_error(), ok("recovered")], "-new-path")
        r = self.row(sid)
        self.assertEqual(r["transcript"], new)
        self.assertEqual(r["state"], "OK")

    # -- liveness and lookup

    def test_dead_sessions_hidden_by_default(self):
        live = self.session([ok()])
        dead = self.session([ok()], pid=dead_pid())
        ids = [r["sessionId"] for r in cr.scan()]
        self.assertIn(live, ids)
        self.assertNotIn(dead, ids)
        self.assertEqual(self.row(dead)["state"], "DEAD")

    def test_reused_pid_with_other_start_time_is_dead(self):
        sid = self.session([ok()], procStart="Thu Jan  1 00:00:00 1970")
        self.assertEqual(self.row(sid)["state"], "DEAD")

    def test_resolve_by_name_pid_and_id(self):
        sid = self.session([ok()], name="worker")
        self.assertEqual(cr.resolve("worker")["sessionId"], sid)
        self.assertEqual(cr.resolve(sid)["sessionId"], sid)
        self.assertEqual(cr.resolve(sid[:8])["sessionId"], sid)
        with self.assertRaises(SystemExit):
            cr.resolve("nobody")

    def test_resolve_ambiguous_name_refuses(self):
        self.session([ok()], name="dup")
        self.session([ok()], name="dup")
        with self.assertRaises(SystemExit):
            cr.resolve("dup")


if __name__ == "__main__":
    unittest.main()
