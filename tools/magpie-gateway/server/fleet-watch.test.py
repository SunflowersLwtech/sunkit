#!/usr/bin/env python3
# fleet-watch.py 的离线测试：假 routing 日志、假网关、假 ntfy 中继，全在 127.0.0.1。
# python3 tools/magpie-gateway/server/fleet-watch.test.py
import gzip, importlib.util, json, os, shutil, tempfile, threading, time, unittest
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("fleetwatch", os.path.join(HERE, "fleet-watch.py"))
fw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fw)


class Fake(BaseHTTPRequestHandler):
    seen, pushes, fail = [], [], set()

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        if self.path == "/relay":
            Fake.pushes.append(body)
            code, out = 200, {}
        else:
            Fake.seen.append((body["model"], self.headers.get("x-api-key"), self.headers.get("user-agent")))
            if body["model"] in Fake.fail:
                code, out = 503, {"error": "all members failed"}
            else:
                code, out = 200, {"model": "claude-opus-5-5"}
        data = json.dumps(out).encode()
        self.send_response(code)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


class FleetWatch(unittest.TestCase):
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
        port = self.srv.server_address[1]
        os.makedirs(self.tmp + "/routing")
        with open(self.tmp + "/ops.env", "w") as f:
            f.write("NTFY_RELAY_URL=http://127.0.0.1:%d/relay\nNTFY_RELAY_TOKEN=t\n" % port)
        fw.ROUTING, fw.VAR, fw.OPS_ENV = self.tmp + "/routing", self.tmp + "/var", self.tmp + "/ops.env"
        fw.KEY_FILE, fw.BASE = self.tmp + "/key", "http://127.0.0.1:%d" % port
        fw.STATE, fw.DAILY, fw.LOG = fw.VAR + "/state.json", fw.VAR + "/daily.jsonl", fw.VAR + "/log"
        Fake.seen[:], Fake.pushes[:] = [], []
        Fake.fail = set()
        self.now = time.time()
        # 默认每个组 10 分钟前都有一次成功，所以不会被探
        for g in fw.GROUPS:
            self.rec(g, 200, ago=600)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def rec(self, group, status, ago=60, done=True, agent="claude", day_offset=0, **extra):
        t = datetime.fromtimestamp(self.now - ago, fw.TZ) + timedelta(days=day_offset)
        r = {"time": t.strftime("%Y-%m-%dT%H:%M:%S.%f") + "123+08:00", "group": {"id": group}, "status": status,
             "done": done, "agent": agent, **extra}
        with open("%s/%s.jsonl" % (fw.ROUTING, t.strftime("%Y-%m-%d")), "a") as f:
            f.write(json.dumps(r) + "\n")

    def key(self):
        with open(fw.KEY_FILE, "w") as f:
            f.write("k-test\n")

    def run_at(self, offset=0):
        real = time.time
        fw.time.time = lambda: self.now + offset
        try:
            fw.main()
        finally:
            fw.time.time = real

    def titles(self):
        return [p["title"] for p in Fake.pushes]

    def test_passive_down_then_up(self):
        for _ in range(4):
            self.rec("long-opus", 400, error="tool name invalid")
        self.rec("long-opus", 200, ago=30)
        self.run_at()
        self.assertEqual(self.titles(), ["magpie 分组 long-opus 坏了"])
        self.assertIn("4 次失败、2 次成功", Fake.pushes[0]["message"])
        self.assertIn("tool name invalid", Fake.pushes[0]["message"])
        self.assertEqual(Fake.pushes[0]["priority"], 4)
        self.run_at(60)  # 还坏着：不重复告警
        self.assertEqual(len(Fake.pushes), 1)
        # 20 分钟后：失败都出了窗口，down 之后又有成功
        self.rec("long-opus", 200, ago=-1200)
        self.run_at(1260)
        self.assertEqual(self.titles()[1:], ["magpie 分组 long-opus 恢复"])

    def test_cancelled_and_streaming_are_not_failures(self):
        for _ in range(5):
            self.rec("frontier", 499)
            self.rec("frontier", None, done=False)
        self.run_at()
        self.assertEqual(Fake.pushes, [])

    def test_few_failures_among_many_successes_are_not_down(self):
        for _ in range(3):
            self.rec("claude-opus-5-5", 429)
        for _ in range(4):
            self.rec("claude-opus-5-5", 200)
        self.run_at()
        self.assertEqual(Fake.pushes, [])

    def test_idle_groups_probed_once_an_hour_with_probe_key(self):
        shutil.rmtree(fw.ROUTING)
        os.makedirs(fw.ROUTING)
        self.rec("frontier", 200, ago=120)  # 只有 frontier 最近有成功
        self.run_at()
        self.assertEqual(Fake.seen, [])  # 没有 key：只看日志，不探
        self.key()
        self.run_at(10)
        probed = sorted(m for m, _, _ in Fake.seen)
        self.assertEqual(probed, sorted("group/" + g for g in fw.GROUPS if g != "frontier"))
        self.assertTrue(all(k == "k-test" and ua == "fleet-watch/1" for _, k, ua in Fake.seen))
        self.run_at(600)  # 一小时内不再探
        self.assertEqual(len(Fake.seen), len(fw.GROUPS) - 1)
        self.run_at(10 + 3600)
        self.assertEqual(len(Fake.seen), 2 * (len(fw.GROUPS) - 1) + 1)  # 一小时后 frontier 也闲了
        self.assertEqual(Fake.pushes, [])

    def test_probe_failures_alert_and_recover(self):
        shutil.rmtree(fw.ROUTING)
        os.makedirs(fw.ROUTING)
        for g in fw.GROUPS:
            if g != "always-up":
                self.rec(g, 200, ago=120)
        self.key()
        Fake.fail = {"group/always-up"}
        self.run_at()
        self.assertEqual(Fake.pushes, [])  # 一次失败不报
        self.run_at(300)  # 失败中每轮都探
        self.assertEqual(self.titles(), ["magpie 分组 always-up 坏了"])
        self.assertIn("连续 2 次探测失败", Fake.pushes[0]["message"])
        self.assertEqual([m for m, _, _ in Fake.seen], ["group/always-up"] * 2)
        Fake.fail = set()
        self.run_at(600)
        self.assertEqual(self.titles()[1:], ["magpie 分组 always-up 恢复"])

    def test_probes_one_at_a_time_within_budget(self):
        # 一个探完再探下一个；一轮花满 BUDGET 就停，剩下的下一轮接着探
        shutil.rmtree(fw.ROUTING)
        os.makedirs(fw.ROUTING)
        self.key()
        clock, calls = [self.now], []

        def slow(key, g):
            calls.append(g)
            clock[0] += 100
            return True, "200 100000ms served=x"
        real_probe, real_time = fw.probe, fw.time.time
        fw.probe, fw.time.time = slow, lambda: clock[0]
        try:
            fw.main()
            self.assertEqual(len(calls), 3)
            clock[0] += 300
            fw.main()
        finally:
            fw.probe, fw.time.time = real_probe, real_time
        self.assertEqual(len(calls), 6)
        self.assertEqual(len(set(calls)), 6)

    def test_client_success_clears_probe_failure(self):
        # 探测失败一次后客户端成功过：一小时后再失败一次，不能和旧的那次凑成「连续 2 次」
        shutil.rmtree(fw.ROUTING)
        os.makedirs(fw.ROUTING)
        for g in fw.GROUPS:
            if g != "long-haiku":
                self.rec(g, 200, ago=-5000)  # 整个测试期间别的组都不闲
        self.key()
        Fake.fail = {"group/long-haiku"}
        self.run_at()
        self.rec("long-haiku", 200, ago=-60)  # 探测之后一分钟，客户端成功
        self.run_at(120)
        self.run_at(60 + 3600 + 10)
        self.assertEqual([m for m, _, _ in Fake.seen], ["group/long-haiku"] * 2)
        self.assertEqual(Fake.pushes, [])

    def test_down_group_with_recent_success_still_probed(self):
        # 坏了以后客户端不再来：即使一小时内有过成功，也要每轮探，靠探测判恢复
        for _ in range(4):
            self.rec("long-sonnet", 500)
        self.key()
        self.run_at()
        self.assertEqual(self.titles(), ["magpie 分组 long-sonnet 坏了"])
        self.assertEqual(Fake.seen, [])
        Fake.fail = {"group/long-sonnet"}
        self.run_at(1200)  # 失败已出窗口，但探测仍失败
        self.assertEqual([m for m, _, _ in Fake.seen], ["group/long-sonnet"])
        self.assertEqual(len(Fake.pushes), 1)
        Fake.fail = set()
        self.run_at(1500)
        self.assertEqual(self.titles()[1:], ["magpie 分组 long-sonnet 恢复"])

    def test_daily_record_once_for_yesterday(self):
        u = [{"provider": "bedrock-glm5", "in": 900, "out": 5, "cache_read": 0, "cache_write": 0}]
        self.rec("always-up", 200, agent="fleet-watch", day_offset=-1, tokens=905, out=5, usage=u)
        self.rec("claude-opus-5-5", 200, agent="gw-fallback", day_offset=-1, tokens=1710, out=5)
        self.rec("claude-opus-5-5", 200, agent="claude", day_offset=-1, tokens=99999)
        # magpie 第二天会把前一天的日志压成 .gz
        prev = (datetime.fromtimestamp(self.now, fw.TZ) - timedelta(days=1)).strftime("%Y-%m-%d")
        path = "%s/%s.jsonl" % (fw.ROUTING, prev)
        with open(path, "rb") as f, gzip.open(path + ".gz", "wb") as g:
            g.write(f.read())
        os.remove(path)
        self.run_at()
        self.run_at(300)
        with open(fw.DAILY) as f:
            rows = [json.loads(l) for l in f]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["fleet-watch"]["providers"], {"bedrock-glm5": 905})
        self.assertEqual(rows[0]["gw-fallback"]["tokens"], 1710)
        self.assertNotIn("claude", rows[0])


if __name__ == "__main__":
    unittest.main()
