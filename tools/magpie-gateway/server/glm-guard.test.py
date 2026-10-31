#!/usr/bin/env python3
# glm-guard.py 的离线测试：假卡片接口、假 mesh 中继、假 ntfy 都在 127.0.0.1，假 magpie 只改临时目录里的 providers.json。
# python3 tools/magpie-gateway/server/glm-guard.test.py
import importlib.util, json, os, shutil, sys, tempfile, threading, time, unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("glmguard", os.path.join(HERE, "glm-guard.py"))
gg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gg)
TZ = timezone(timedelta(hours=8))

# 假 magpie：只认 group set <id> models+=/models-= 和 provider on|off <id>；给关着的 provider 加成员会被拒（真 magpie 对
# 不认识的模型也是这样拒的），所以「先 provider on 再加成员」的顺序错了测试会红。
FAKE_MAGPIE = r'''
import json, os, sys
p = os.environ["FAKE_PROVIDERS"]
if os.path.exists(os.environ["FAKE_FAIL"]):
    print("boom"); sys.exit(1)
d = json.load(open(p))
a = sys.argv[1:]
with open(os.environ["FAKE_CALLS"], "a") as f:
    f.write(" ".join(a) + "\n")
if a[:2] == ["provider", "on"] or a[:2] == ["provider", "off"]:
    for pr in d["providers"]:
        if pr["id"] == a[2]:
            if a[1] == "on": pr.pop("off", None)
            else: pr["off"] = True
elif a[:2] == ["group", "set"]:
    g = next(g for g in d["groups"] if g["id"] == a[2])
    k, _, v = a[3].partition("=")
    if k == "models+":
        prov = v.split("/")[0]
        if any(pr["id"] == prov and pr.get("off") for pr in d["providers"]):
            print('magpie knows no model "%s"' % v); sys.exit(1)
        g["members"].append(v)
    elif k == "models-":
        g["members"].remove(v)
    else:
        sys.exit(2)
else:
    sys.exit(2)
json.dump(d, open(p, "w"))
'''


def iso(t):
    return datetime.fromtimestamp(t, TZ).isoformat()


class Fake(BaseHTTPRequestHandler):
    cards, sessions, messages, pushes = [], [], [], []

    def reply(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/v1/magpie/quotas/cards":
            self.reply(200, {"data": Fake.cards})
        elif self.path == "/mesh/v1/sessions":
            assert self.headers["Authorization"] == "Bearer meshtok"
            self.reply(200, Fake.sessions)
        else:
            self.reply(404, {})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        if self.path == "/mesh/v1/messages":
            Fake.messages.append((body, self.headers.get("x-mesh-sender-name")))
            self.reply(201, {"id": "m1"})
        elif self.path == "/relay":
            Fake.pushes.append(body)
            self.reply(200, {})
        else:
            self.reply(404, {})

    def log_message(self, *a):
        pass


T0 = time.mktime((2026, 10, 31, 9, 0, 0, 0, 0, -1))


class GlmGuard(unittest.TestCase):
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
        for d in ("conf", "etc", "var"):
            os.makedirs(os.path.join(self.tmp, d))
        with open(self.tmp + "/etc/mesh.env", "w") as f:
            f.write("MESH_RELAY_URL=http://127.0.0.1:%d/mesh\nMESH_TOKEN=meshtok\n" % port)
        with open(self.tmp + "/ops.env", "w") as f:
            f.write("NTFY_RELAY_URL=http://127.0.0.1:%d/relay\nNTFY_RELAY_TOKEN=t\n" % port)
        with open(self.tmp + "/magpie.py", "w") as f:
            f.write(FAKE_MAGPIE)
        os.environ.update(FAKE_PROVIDERS=self.tmp + "/conf/providers.json", FAKE_CALLS=self.tmp + "/calls",
                          FAKE_FAIL=self.tmp + "/fail")
        gg.EXEC, gg.MAGPIE, gg.BASE = [], [sys.executable, self.tmp + "/magpie.py"], "http://127.0.0.1:%d" % port
        gg.CONF, gg.ETC, gg.VAR, gg.OPS_ENV = self.tmp + "/conf", self.tmp + "/etc", self.tmp + "/var", self.tmp + "/ops.env"
        gg.DWELL, gg.TARGETS = 15 * 60, ["feishu-assistant", "feishu-assistant-backup"]
        self.t = T0
        gg.now = lambda: self.t
        Fake.cards[:], Fake.messages[:], Fake.pushes[:] = [], [], []
        Fake.sessions[:] = [{"name": "feishu-assistant", "session_id": "s-sec", "account": "weiliu", "status": "idle"}]
        self.providers(zcode_off=True)
        self.history({})

    def tearDown(self):
        shutil.rmtree(self.tmp)

    # ---- 造数据 ----
    def providers(self, zcode_off=True, extra=None):
        d = {"providers": [
            {"id": "claude", "accountCaps": {"a@x.com · duocode": 95, "b@x.com · duocode": 95, "c@x.com · duocode": 95},
             "accountWindowCaps": {"c@x.com · duocode": {"5 hours": 100}}},
            {"id": "zcode", "off": True} if zcode_off else {"id": "zcode"},
            {"id": "kiro", "off": True}],
            "groups": [
                {"id": "claude-opus-5-5", "members": ["claude/claude-opus-5-5", "kiro/claude-opus-5.5"] + (extra or [])},
                {"id": "claude-sonnet-5-5", "members": ["claude/claude-sonnet-5-5", "kiro/claude-sonnet-5.5"]},
                {"id": "claude-haiku-5-5", "members": ["claude/claude-haiku-5-5", "kiro/claude-haiku-5.5"]},
                {"id": "frontier", "members": ["zcode/GLM-5.3"]}]}
        self.dump("conf/providers.json", d)

    def dump(self, rel, obj):
        with open(os.path.join(self.tmp, rel), "w") as f:
            json.dump(obj, f)

    def load(self, rel):
        with open(os.path.join(self.tmp, rel)) as f:
            return json.load(f)

    def history(self, h):
        self.dump("conf/quota-history.json", h)

    def seat(self, who, used, reset_in_min, read_ago_min=1, plan="team", week=None):
        windows = [{"name": "5 hours", "used": used}]
        if reset_in_min is not None:
            windows[0]["resetsAt"] = iso(self.t + reset_in_min * 60)
        if week is not None:
            windows.append({"name": "7 days", "used": week[0], "resetsAt": iso(self.t + week[1] * 3600)})
        user = who if plan == "max" else who + " · DuoCode"
        return {"provider": "claude", "kind": "subscription", "plan": plan, "user": user,
                "readAt": iso(self.t - read_ago_min * 60), "windows": windows}

    def state(self, **kw):
        self.dump("var/state.json", kw)

    def read_state(self):
        return self.load("var/state.json")

    def groups(self):
        d = self.load("conf/providers.json")
        return {g["id"]: g["members"] for g in d["groups"]}, next(p for p in d["providers"] if p["id"] == "zcode")

    def calls(self):
        try:
            with open(self.tmp + "/calls") as f:
                return f.read().splitlines()
        except OSError:
            return []

    def run_guard(self):
        return gg.run(False)

    # ---- 测试 ----
    def test_plenty_left_stays_closed(self):
        Fake.cards[:] = [self.seat("a@x.com", 30, 120), self.seat("b@x.com", 5, 200), self.seat("c@x.com", 20, 60)]
        self.assertEqual(self.run_guard(), 0)
        self.assertEqual(self.calls(), [])
        self.assertEqual(Fake.messages, [])
        self.assertFalse(self.read_state()["open"])

    def test_opens_when_every_seat_under_15_percent(self):
        Fake.cards[:] = [self.seat("a@x.com", 90, 100), self.seat("b@x.com", 88, 100), self.seat("c@x.com", 86, 40),
                         self.seat("m@x.com", 0, None, plan="max", week=(100, 50))]
        self.run_guard()
        g, z = self.groups()
        # GLM 排在每个组所有 Claude 成员后面
        self.assertEqual(g["claude-opus-5-5"], ["claude/claude-opus-5-5", "kiro/claude-opus-5.5", "zcode/GLM-5.3"])
        self.assertEqual(g["claude-sonnet-5-5"][-1], "zcode/GLM-5.3")
        self.assertEqual(g["claude-haiku-5-5"][-1], "zcode/GLM-5.3-Flash")
        self.assertNotIn("off", z)
        self.assertEqual(self.calls()[0], "provider on zcode")
        st = self.read_state()
        self.assertTrue(st["open"])
        self.assertTrue(st["zcode_by_guard"])
        self.assertEqual(st["since"], self.t)
        self.assertEqual(len(Fake.messages), 1)
        body, sender = Fake.messages[0]
        self.assertEqual(sender, "magpie-glm-guard")
        self.assertEqual((body["to"], body["to_session"]), ("weiliu", "s-sec"))
        self.assertIn("已自动打开 GLM 兜底", body["content"].splitlines()[0])
        self.assertIn("m@x.com（个人 Max）：7 天额度用完", body["content"])
        # 再跑一轮：已经对齐，不再改、不再发
        self.t += 300
        self.run_guard()
        self.assertEqual(len(self.calls()), 4)
        self.assertEqual(len(Fake.messages), 1)

    def history_burn(self, per_seat, c_reset_min=120):
        """三个座位最近 40 分钟各匀速涨 per_seat（每 10 分钟一个点），a、b 2 小时后重置，c 按 c_reset_min"""
        h = {}
        for who, now_used in (("a@x.com", 85), ("b@x.com", 85), ("c@x.com", 80)):
            reset = self.t + (c_reset_min if who == "c@x.com" else 120) * 60
            pts = []
            for k in range(5):  # -40 -30 -20 -10 0 分钟
                at = self.t - (40 - 10 * k) * 60
                used = now_used - per_seat * (40 - 10 * k) / 30.0
                pts.append({"at": iso(at), "left": 100 - used, "resetsAt": iso(reset)})
            h["claude|%s · duocode" % who] = {"5 hours": pts}
        return h

    def test_opens_when_speed_says_seats_run_out_before_reset(self):
        # 余量到上限 10+10+20=40 个百分点；30 分钟三座位各涨 10 → 1%/分钟 → 40 分钟用完 > 30，不开
        self.history(self.history_burn(10))
        Fake.cards[:] = [self.seat("a@x.com", 85, 120), self.seat("b@x.com", 85, 120), self.seat("c@x.com", 80, 120)]
        self.run_guard()
        self.assertFalse(self.read_state()["open"])
        # 各涨 15 → 1.5%/分钟 → 约 27 分钟用完，早于 2 小时后的重置 → 打开（每个座位都还 ≥15%，靠的是速度）
        self.history(self.history_burn(15))
        self.run_guard()
        self.assertTrue(self.read_state()["open"])
        self.assertIn("按最近 30 分钟的速度", Fake.messages[0][0]["content"].splitlines()[0])

    def test_speed_ignored_when_a_seat_resets_first(self):
        self.history(self.history_burn(15, c_reset_min=10))
        # 同样 27 分钟用完，但 c 在 10 分钟后重置 → 不开
        Fake.cards[:] = [self.seat("a@x.com", 85, 120), self.seat("b@x.com", 85, 120), self.seat("c@x.com", 80, 10)]
        self.run_guard()
        self.assertFalse(self.read_state()["open"])
        self.assertEqual(self.calls(), [])

    def opened(self, minutes_ago, zcode_by_guard=True):
        self.providers(zcode_off=False)
        d = self.load("conf/providers.json")
        for g in d["groups"]:
            if g["id"] in gg.GLM:
                g["members"].append(gg.GLM[g["id"]])
        self.dump("conf/providers.json", d)
        self.state(open=True, since=self.t - minutes_ago * 60, zcode_by_guard=zcode_by_guard)

    def test_close_waits_out_the_dwell(self):
        self.opened(5)
        Fake.cards[:] = [self.seat("a@x.com", 0, 300), self.seat("b@x.com", 95, 100), self.seat("c@x.com", 96, 100)]
        self.run_guard()
        self.assertTrue(self.read_state()["open"])
        self.assertEqual(self.calls(), [])
        self.assertEqual(Fake.messages, [])

    def test_closes_after_a_seat_resets(self):
        self.opened(20)
        Fake.cards[:] = [self.seat("a@x.com", 2, 300), self.seat("b@x.com", 95, 100), self.seat("c@x.com", 96, 100)]
        self.run_guard()
        g, z = self.groups()
        for gid in gg.GLM:
            self.assertFalse(any(m.startswith("zcode/") for m in g[gid]), g[gid])
        self.assertEqual(g["frontier"], ["zcode/GLM-5.3"])  # 别的组不动
        self.assertTrue(z.get("off"))
        self.assertEqual(self.calls()[-1], "provider off zcode")
        st = self.read_state()
        self.assertFalse(st["open"])
        self.assertFalse(st["zcode_by_guard"])
        first = Fake.messages[0][0]["content"].splitlines()[0]
        self.assertIn("已自动关上 GLM 兜底", first)
        self.assertIn("a@x.com 座位剩 98%", first)

    def test_closes_on_reset_even_while_burning_fast(self):
        # 刚重置的座位 2%，最近 30 分钟消耗很快（约 1.5%/分钟）：照样关，把留在 GLM 上的会话赶回 Claude
        self.history(self.history_burn(15))
        self.opened(20)
        Fake.cards[:] = [self.seat("a@x.com", 2, 300), self.seat("b@x.com", 95, 100), self.seat("c@x.com", 96, 100)]
        self.run_guard()
        self.assertFalse(self.read_state()["open"])
        g, _ = self.groups()
        self.assertNotIn("zcode/GLM-5.3", g["claude-opus-5-5"])

    def test_close_leaves_zcode_on_when_someone_else_turned_it_on(self):
        self.opened(20, zcode_by_guard=False)
        Fake.cards[:] = [self.seat("a@x.com", 2, 300), self.seat("b@x.com", 95, 100), self.seat("c@x.com", 96, 100)]
        self.run_guard()
        g, z = self.groups()
        self.assertNotIn("zcode/GLM-5.3", g["claude-opus-5-5"])
        self.assertNotIn("off", z)
        self.assertNotIn("provider off zcode", self.calls())

    def test_stale_reading_does_not_close(self):
        self.opened(20)
        # a 显示 0%，但读数是 30 分钟前、重置时间已过：可能早被别的机器用掉了，不据此关
        Fake.cards[:] = [self.seat("a@x.com", 97, -5, read_ago_min=30), self.seat("b@x.com", 95, 100),
                         self.seat("c@x.com", 96, 100)]
        self.run_guard()
        self.assertTrue(self.read_state()["open"])
        self.assertEqual(self.calls(), [])

    def test_max_with_full_week_is_not_a_seat_with_room(self):
        self.opened(20)
        Fake.cards[:] = [self.seat("a@x.com", 95, 100), self.seat("b@x.com", 95, 100), self.seat("c@x.com", 96, 100),
                         self.seat("m@x.com", 0, None, plan="max", week=(100, 50))]
        self.run_guard()
        self.assertTrue(self.read_state()["open"])
        self.assertEqual(self.calls(), [])

    def test_closed_takes_out_glm_added_by_hand(self):
        self.providers(zcode_off=True, extra=["zcode/GLM-5.3"])
        self.state(open=False, since=0)
        Fake.cards[:] = [self.seat("a@x.com", 30, 120), self.seat("b@x.com", 5, 200), self.seat("c@x.com", 20, 60)]
        self.run_guard()
        g, _ = self.groups()
        self.assertEqual(g["claude-opus-5-5"], ["claude/claude-opus-5-5", "kiro/claude-opus-5.5"])
        self.assertEqual(Fake.messages, [])  # 对账不是切换，不发消息

    def test_paused_changes_nothing(self):
        open(self.tmp + "/etc/paused", "w").close()
        Fake.cards[:] = [self.seat("a@x.com", 99, 100), self.seat("b@x.com", 99, 100), self.seat("c@x.com", 99, 100)]
        self.run_guard()
        self.assertEqual(self.calls(), [])
        self.assertFalse(os.path.exists(self.tmp + "/var/state.json"))

    def test_mesh_without_secretary_falls_back_to_backup_then_ntfy(self):
        Fake.sessions[:] = [{"name": "feishu-assistant-backup", "session_id": "s-bk", "account": "weiliu",
                             "status": "idle"}]
        Fake.cards[:] = [self.seat("a@x.com", 99, 100), self.seat("b@x.com", 99, 100), self.seat("c@x.com", 99, 100)]
        self.run_guard()
        self.assertEqual(Fake.messages[0][0]["to_session"], "s-bk")
        self.assertEqual(Fake.pushes, [])
        # 都不在：走 ntfy
        Fake.sessions[:], Fake.messages[:] = [], []
        self.t += 20 * 60
        Fake.cards[:] = [self.seat("a@x.com", 0, 300), self.seat("b@x.com", 99, 100), self.seat("c@x.com", 99, 100)]
        self.run_guard()
        self.assertEqual(Fake.messages, [])
        self.assertEqual(len(Fake.pushes), 1)
        self.assertIn("已自动关上", Fake.pushes[0]["message"])

    def test_failure_is_reported_once_and_state_kept(self):
        open(self.tmp + "/fail", "w").close()
        Fake.cards[:] = [self.seat("a@x.com", 99, 100), self.seat("b@x.com", 99, 100), self.seat("c@x.com", 99, 100)]
        self.assertEqual(self.run_guard(), 1)
        self.assertFalse(self.read_state()["open"])
        self.assertEqual(len(Fake.messages), 1)
        self.assertIn("切换失败", Fake.messages[0][0]["content"])
        self.t += 300
        self.run_guard()
        self.assertEqual(len(Fake.messages), 1)
        os.remove(self.tmp + "/fail")
        self.t += 300
        self.run_guard()
        self.assertTrue(self.read_state()["open"])
        self.assertNotIn("failing", self.read_state())

    def test_cards_unreadable_changes_nothing(self):
        gg.BASE = "http://127.0.0.1:1"
        self.opened(60)
        self.run_guard()
        self.assertTrue(self.read_state()["open"])
        self.assertEqual(self.calls(), [])
        with open(self.tmp + "/var/log") as f:
            self.assertIn("inputs unreadable", f.read())

    def test_consumed_counts_a_new_window_from_zero(self):
        t = self.t
        r1, r2 = iso(t - 10 * 60), iso(t + 290 * 60)
        pts = [{"at": iso(t - 40 * 60), "left": 30, "resetsAt": r1},   # 基线 70%
               {"at": iso(t - 20 * 60), "left": 10, "resetsAt": r1},   # +20
               {"at": iso(t - 5 * 60), "left": 92, "resetsAt": r2}]    # 重置后 8%：+8
        self.assertAlmostEqual(gg.consumed(pts, None, t), 28.0)


if __name__ == "__main__":
    unittest.main()
