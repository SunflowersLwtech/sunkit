#!/usr/bin/env python3
# glm-guard.py 的离线测试：假卡片接口、假 mesh 中继、假 ntfy 都在 127.0.0.1，假 magpie 只改临时目录里的 providers.json。
# python3 tools/magpie-gateway/server/glm-guard.test.py
import gzip, importlib.util, json, os, shutil, sys, tempfile, threading, time, unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("glmguard", os.path.join(HERE, "glm-guard.py"))
gg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gg)
TZ = timezone(timedelta(hours=8))

# 假 magpie：只认 group set <id> models+=/models-= 和 provider on|off <id>；给关着的 provider 加成员会被拒（真 magpie 对
# 不认识的模型也是这样拒的），所以「先 provider on 再加成员」的顺序错了测试会红。
# FAKE_FAIL 文件在：以文件内容开头的命令失败（空文件 = 每条都失败）；FAKE_NOOP 同样按开头匹配，命中的命令退出 0 却什么都不改。
FAKE_MAGPIE = r'''
import json, os, sys
p = os.environ["FAKE_PROVIDERS"]
a = sys.argv[1:]


def hit(flag):
    f = os.environ[flag]
    return os.path.exists(f) and " ".join(a).startswith(open(f).read())


if hit("FAKE_FAIL"):
    print("boom"); sys.exit(1)
d = json.load(open(p))
with open(os.environ["FAKE_CALLS"], "a") as f:
    f.write(" ".join(a) + "\n")
if hit("FAKE_NOOP"):
    sys.exit(0)
if a[:2] == ["provider", "on"] or a[:2] == ["provider", "off"]:
    for pr in d["providers"]:
        if pr["id"] == a[2]:
            if a[1] == "on": pr.pop("off", None)
            else: pr["off"] = True
elif a[:2] == ["group", "set"]:
    g = next(g for g in d["groups"] if g["id"] == a[2])
    k, _, v = a[3].partition("=")
    off = {pr["id"] for pr in d["providers"] if pr.get("off")}
    if k == "models+":
        if v.split("/")[0] in off:
            print('magpie knows no model "%s"' % v); sys.exit(1)
        g["members"].append(v)
    elif k == "models-":
        g["members"].remove(v)
        if not g["members"]:
            print("a group needs a model in it"); sys.exit(1)
    elif k == "models":
        # 整份换掉：组里原有的成员照收（provider 关着也收），新加的要 provider 开着
        new = v.split(",")
        bad = [x for x in new if x not in g["members"] and x.split("/")[0] in off]
        if bad:
            print('magpie knows no model "%s"' % bad[0]); sys.exit(1)
        g["members"] = new
    else:
        sys.exit(2)
else:
    sys.exit(2)
json.dump(d, open(p, "w"))
'''


def iso(t):
    return datetime.fromtimestamp(t, TZ).isoformat()


WEBKEY = "test-web-key-0123456789abcdef"


class Fake(BaseHTTPRequestHandler):
    cards, sessions, messages, pushes, unrests = [], [], [], [], []
    unrest_reply = (200, {"lifted": False})

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
        elif self.path == "/web/api/gateway/unrest":
            # magpie 网页：没有对的 cookie 就 401（真 magpie 也这样）
            if self.headers.get("Cookie") != "magpie_web_3430=" + WEBKEY:
                self.reply(401, {"error": "no cookie"})
                return
            try:
                with open(os.environ["FAKE_CALLS"]) as f:
                    n = len(f.read().splitlines())
            except OSError:
                n = 0
            Fake.unrests.append((body.get("key"), n))
            self.reply(*Fake.unrest_reply)
        else:
            self.reply(404, {})

    def log_message(self, *a):
        pass


T0 = time.mktime((2026, 10, 31, 9, 0, 0, 0, 0, -1))

# claude-* 以外含 zcode 的组，照网关 11-01 的样子：frontier、auto-glm-5-3、auto-glm-5-3-flash 直接点名 zcode 的模型；
# always-up 只经停用的 zcode 组间接含它
FRONTIER = ["zed/gpt-6.1-sol", "zcode/GLM-5.3", "trae-cn/glm-5.3", "group/always-up"]
GLM53 = ["opencode-go/glm-5.3", "zcode/GLM-5.3", "workbuddy/glm-5.3"]
GLM53F = ["opencode-go/glm-5.3-flash", "zcode/GLM-5.3-Flash", "trae-cn/glm-5.3-flash"]
OTHERS = [{"id": "frontier", "routing": "order", "members": FRONTIER},
          {"id": "always-up", "routing": "order", "members": ["devin/swe-2", "group/zcode"]},
          {"id": "auto-glm-5-3", "members": GLM53},
          {"id": "auto-glm-5-3-flash", "members": GLM53F},
          {"id": "zcode", "disabled": True,
           "members": ["zcode/GLM-5.3", "zcode/GLM-5.3-Flash", "zcode/GLM-5.3-Trial", "trae-cn/glm-5.3"]}]
# 守护打开 zcode 时要先拿掉的成员（组, 成员）
STRIPPED = [("frontier", "zcode/GLM-5.3"), ("auto-glm-5-3", "zcode/GLM-5.3"),
            ("auto-glm-5-3-flash", "zcode/GLM-5.3-Flash")]


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
                          FAKE_FAIL=self.tmp + "/fail", FAKE_NOOP=self.tmp + "/noop")
        gg.EXEC, gg.MAGPIE, gg.BASE = [], [sys.executable, self.tmp + "/magpie.py"], "http://127.0.0.1:%d" % port
        gg.CONF, gg.ETC, gg.VAR, gg.OPS_ENV = self.tmp + "/conf", self.tmp + "/etc", self.tmp + "/var", self.tmp + "/ops.env"
        gg.DWELL, gg.TARGETS = 15 * 60, ["feishu-assistant", "feishu-assistant-backup"]
        gg.WEB, gg.WEB_COOKIE, gg.ROUTING = "http://127.0.0.1:%d/web" % port, "magpie_web_3430", self.tmp + "/conf/routing"
        os.makedirs(gg.ROUTING)
        os.environ["MAGPIE_WEB_KEY"] = WEBKEY
        self.t = T0
        gg.now = lambda: self.t
        Fake.cards[:], Fake.messages[:], Fake.pushes[:], Fake.unrests[:] = [], [], [], []
        Fake.unrest_reply = (200, {"lifted": False})
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
                {"id": "claude-haiku-5-5", "members": ["claude/claude-haiku-5-5", "kiro/claude-haiku-5.5"]}]
            + [dict(g, members=list(g["members"])) for g in OTHERS]}
        self.dump("conf/providers.json", d)

    def dump(self, rel, obj):
        with open(os.path.join(self.tmp, rel), "w") as f:
            json.dump(obj, f)

    def load(self, rel):
        with open(os.path.join(self.tmp, rel)) as f:
            return json.load(f)

    def history(self, h):
        self.dump("conf/quota-history.json", h)

    def trial_on(self):
        """打开 Trial 开关（/etc/magpie-glm-guard/use-trial；默认关，和网关一样）"""
        open(os.path.join(self.tmp, "etc", "use-trial"), "w").close()

    def zroom(self):
        """ZCode Max 两个窗口和两个 Trial 桶都有余量（历史里还没有 ZCode 时才加，已有的不动）：#42 之前的测试默认 GLM-5.3
        能加，靠的就是这个；不调就是「读不到 ZCode 余量」，守护什么都不加"""
        self.history(dict(self.zhist(stale=False), **self.load("conf/quota-history.json")))

    def seat(self, who, used, reset_in_min, read_ago_min=1, plan="team", week=None):
        windows = [{"name": "5 hours", "used": used}]
        if reset_in_min is not None:
            windows[0]["resetsAt"] = iso(self.t + reset_in_min * 60)
        if week is not None:
            windows.append({"name": "7 days", "used": week[0], "resetsAt": iso(self.t + week[1] * 3600)})
        user = who if plan == "max" else who + " · DuoCode"
        return {"provider": "claude", "kind": "subscription", "plan": plan, "user": user,
                "readAt": iso(self.t - read_ago_min * 60), "windows": windows}

    def unread(self, who):
        """magpie 读不到的座位（v0.1.1689：登录失效这类错误不留旧读数）：有 error，没有窗口，没有 readAt/asOf"""
        return {"provider": "claude", "kind": "subscription", "plan": "team", "user": who + " · DuoCode",
                "error": "Claude Code isn't signed in", "windows": []}

    def flag(self, name, prefix=""):
        with open(os.path.join(self.tmp, name), "w") as f:
            f.write(prefix)

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
        self.zroom()
        Fake.cards[:] = [self.seat("a@x.com", 90, 100), self.seat("b@x.com", 88, 100), self.seat("c@x.com", 86, 40),
                         self.seat("m@x.com", 0, None, plan="max", week=(100, 50))]
        self.run_guard()
        g, z = self.groups()
        # GLM 排在每个组所有 Claude 成员后面
        self.assertEqual(g["claude-opus-5-5"], ["claude/claude-opus-5-5", "kiro/claude-opus-5.5", "zcode/GLM-5.3"])
        self.assertEqual(g["claude-sonnet-5-5"][-1], "zcode/GLM-5.3")
        self.assertEqual(g["claude-haiku-5-5"][-1], "zcode/GLM-5.3-Flash")
        self.assertNotIn("off", z)
        # zcode 先打开，再往组里加（关着的 provider 的成员 magpie 加不进去）
        on = self.calls().index("provider on zcode")
        self.assertTrue(all(i > on for i, c in enumerate(self.calls()) if "models+=" in c), self.calls())
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
        n = len(self.calls())
        self.t += 300
        self.run_guard()
        self.assertEqual(len(self.calls()), n)
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
        return dict(h, **self.zhist(stale=False))

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
        """守护打开着的样子；zcode 是守护打开的，别的组里的 zcode 成员也已经被它拿掉、记在 state 里"""
        self.providers(zcode_off=False)
        d = self.load("conf/providers.json")
        stripped = []
        for g in d["groups"]:
            if g["id"] in gg.GLM:
                g["members"].append(gg.GLM[g["id"]])
            elif zcode_by_guard and (g["id"], next((m for m in g["members"] if m.startswith("zcode/")), None)) in STRIPPED:
                m = next(m for m in g["members"] if m.startswith("zcode/"))
                i = g["members"].index(m)
                stripped.append({"group": g["id"], "member": m, "after": g["members"][i - 1] if i else None, "at": i})
                g["members"].remove(m)
        self.dump("conf/providers.json", d)
        self.state(open=True, since=self.t - minutes_ago * 60, zcode_by_guard=zcode_by_guard,
                   **({"stripped": stripped} if stripped else {}))
        self.zroom()

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
        self.assertEqual(g["frontier"], FRONTIER)  # zcode 不是守护打开的：别的组一直没动过

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
        self.zroom()
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
        self.zroom()
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

    def all_low(self):
        Fake.cards[:] = [self.seat(x, 99, 100) for x in ("a@x.com", "b@x.com", "c@x.com")]

    def a_reset(self):
        Fake.cards[:] = [self.seat("a@x.com", 2, 300), self.seat("b@x.com", 99, 100), self.seat("c@x.com", 99, 100)]

    # ---- 半途失败后 zcode 归谁 ----
    def test_half_finished_open_still_turns_zcode_off_on_close(self):
        # provider on zcode 成功、接着往 claude-* 加成员失败：这轮记失败；下一轮 zcode 已开着、只加组；关上时 zcode 也要关回
        self.zroom()
        self.flag("fail", "group set claude-")
        self.all_low()
        self.assertEqual(self.run_guard(), 1)
        _, z = self.groups()
        self.assertNotIn("off", z)
        os.remove(self.tmp + "/fail")
        self.t += 300
        self.all_low()
        self.assertEqual(self.run_guard(), 0)
        self.assertTrue(self.read_state()["open"])
        self.t += 20 * 60
        self.a_reset()
        self.run_guard()
        g, z = self.groups()
        self.assertFalse(self.read_state()["open"])
        self.assertNotIn("zcode/GLM-5.3", g["claude-opus-5-5"])
        self.assertTrue(z.get("off"), "zcode left on after the close: %s" % z)
        self.assertEqual(self.calls()[-1], "provider off zcode")

    def test_half_finished_open_turns_zcode_back_off_when_seats_recover(self):
        # 同样半途失败，但重试前座位就回来了：守护一直是关着的，对账时把自己打开的 zcode 关回，不发切换消息
        self.zroom()
        self.flag("fail", "group set claude-")
        self.all_low()
        self.assertEqual(self.run_guard(), 1)
        os.remove(self.tmp + "/fail")
        self.t += 20 * 60
        Fake.cards[:] = [self.seat("a@x.com", 30, 120), self.seat("b@x.com", 5, 200), self.seat("c@x.com", 20, 60)]
        self.assertEqual(self.run_guard(), 0)
        g, z = self.groups()
        self.assertTrue(z.get("off"), "zcode left on with the guard closed: %s" % z)
        self.assertEqual([c for c in self.calls() if c.startswith("provider")], ["provider on zcode", "provider off zcode"])
        self.assertFalse(self.read_state()["open"])
        self.assertEqual(len(Fake.messages), 1)  # 只有那条「切换失败」

    def test_failed_close_lets_go_of_zcode_once_it_is_off(self):
        # 关上时 provider off zcode 成功，但读回发现组里还有 GLM（CLI 退出 0 却没改）：这轮记失败。zcode 已经不归守护管了：
        # 之后有人手动打开 zcode，守护补完关上时不能把它关掉
        self.opened(20)
        self.flag("noop", "group set")
        self.a_reset()
        self.assertEqual(self.run_guard(), 1)
        _, z = self.groups()
        self.assertTrue(z.get("off"))
        os.remove(self.tmp + "/noop")
        d = self.load("conf/providers.json")
        next(p for p in d["providers"] if p["id"] == "zcode").pop("off")
        self.dump("conf/providers.json", d)
        self.t += 300
        self.a_reset()
        self.assertEqual(self.run_guard(), 0)
        g, z = self.groups()
        self.assertFalse(self.read_state()["open"])
        self.assertNotIn("zcode/GLM-5.3", g["claude-opus-5-5"])
        self.assertNotIn("off", z)

    # ---- 读不到的座位 ----
    def test_unread_seat_counts_as_no_room_when_opening(self):
        # 两个座位到上限、第三个 magpie 读不到：读不到的按没有余量算，打开
        self.zroom()
        Fake.cards[:] = [self.seat("a@x.com", 99, 100), self.seat("b@x.com", 98, 100), self.unread("c@x.com")]
        self.run_guard()
        self.assertTrue(self.read_state()["open"], "an unread seat was counted as room")
        g, _ = self.groups()
        self.assertEqual(g["claude-opus-5-5"][-1], "zcode/GLM-5.3")
        self.assertIn("c@x.com：读不到", Fake.messages[0][0]["content"])

    def test_seat_whose_window_restarted_is_room_not_unread(self):
        # 过了重置时间、还没再读的座位，magpie 显示 0%、没有重置时间：这是有余量，不是读不到，不开
        Fake.cards[:] = [self.seat("a@x.com", 99, 100), self.seat("b@x.com", 98, 100), self.seat("c@x.com", 0, None)]
        self.run_guard()
        self.assertFalse(self.read_state()["open"])
        self.assertEqual(self.calls(), [])

    def test_unread_seats_never_close(self):
        # 开着时三个座位都读不到：关上那边不动（读不到就不改）
        self.opened(60)
        Fake.cards[:] = [self.unread(x) for x in ("a@x.com", "b@x.com", "c@x.com")]
        self.run_guard()
        self.assertTrue(self.read_state()["open"])
        self.assertEqual(self.calls(), [])

    # ---- 复审指出的三处测试缺口 ----
    def test_reopen_waits_out_the_dwell_after_a_close(self):
        self.opened(20)
        self.a_reset()
        self.run_guard()
        self.assertFalse(self.read_state()["open"])
        n = len(self.calls())
        # 关上 5 分钟后座位又全满：还在 15 分钟里，不开
        self.t += 5 * 60
        self.all_low()
        self.run_guard()
        self.assertFalse(self.read_state()["open"], "re-opened 5 minutes after a close")
        self.assertEqual(len(self.calls()), n)
        self.assertEqual(len(Fake.messages), 1)
        # 关上满 15 分钟：打开
        self.t += 10 * 60
        self.all_low()
        self.run_guard()
        self.assertTrue(self.read_state()["open"])
        self.assertEqual(len(Fake.messages), 2)

    def test_card_without_reading_time_is_not_fresh(self):
        # a 显示 2%，但卡片上没有 readAt 也没有 asOf：不知道是什么时候读的，不据此关
        self.opened(20)
        self.a_reset()
        del Fake.cards[0]["readAt"]
        self.run_guard()
        self.assertTrue(self.read_state()["open"], "closed on a card with no reading time")
        self.assertEqual(self.calls(), [])

    def test_change_is_read_back(self):
        # magpie 加成员退出 0 却没改 providers.json：读回核对要抓到，记失败、报一次、不算打开
        self.zroom()
        self.flag("noop", "group set")
        self.all_low()
        self.assertEqual(self.run_guard(), 1)
        self.assertFalse(self.read_state()["open"])
        self.assertEqual(len(Fake.messages), 1)
        self.assertIn("切换失败", Fake.messages[0][0]["content"])
        with open(self.tmp + "/var/log") as f:
            self.assertIn("providers.json not as expected", f.read())
        os.remove(self.tmp + "/noop")
        self.t += 300
        self.all_low()
        self.assertEqual(self.run_guard(), 0)
        self.assertTrue(self.read_state()["open"])

    # ---- 守护打开的 zcode 只给 claude-* 三个组用 ----
    def zcode_by_hand(self, off):
        d = self.load("conf/providers.json")
        z = next(p for p in d["providers"] if p["id"] == "zcode")
        if off:
            z["off"] = True
        else:
            z.pop("off", None)
        self.dump("conf/providers.json", d)

    def test_open_takes_zcode_out_of_the_other_groups_first(self):
        # zcode 关着、由守护打开：先把别的组里的 zcode 成员拿掉（models-= 不看 provider 开没开），再 provider on
        self.zroom()
        self.all_low()
        self.assertEqual(self.run_guard(), 0)
        g, z = self.groups()
        self.assertNotIn("off", z)
        self.assertEqual(g["frontier"], ["zed/gpt-6.1-sol", "trae-cn/glm-5.3", "group/always-up"])
        self.assertEqual(g["auto-glm-5-3"], ["opencode-go/glm-5.3", "workbuddy/glm-5.3"])
        self.assertEqual(g["auto-glm-5-3-flash"], ["opencode-go/glm-5.3-flash", "trae-cn/glm-5.3-flash"])
        self.assertEqual(g["always-up"], ["devin/swe-2", "group/zcode"])  # 只经停用的组含 zcode，碰不到
        self.assertEqual(g["zcode"], OTHERS[-1]["members"])  # 停用的组不动
        calls = self.calls()
        on = calls.index("provider on zcode")
        strips = [i for i, c in enumerate(calls) if "models-=" in c]
        self.assertEqual(len(strips), 3, calls)
        self.assertTrue(max(strips) < on, "zcode turned on before the other groups lost it: %s" % calls)
        self.assertIn("frontier、auto-glm-5-3、auto-glm-5-3-flash", Fake.messages[0][0]["content"])

    def test_close_puts_the_other_groups_back_as_they_were(self):
        self.opened(20)
        g, _ = self.groups()
        self.assertNotIn("zcode/GLM-5.3", g["frontier"])
        self.a_reset()
        self.assertEqual(self.run_guard(), 0)
        g, z = self.groups()
        self.assertEqual(g["frontier"], FRONTIER, "frontier not put back as it was")
        self.assertEqual(g["auto-glm-5-3"], GLM53)
        self.assertEqual(g["auto-glm-5-3-flash"], GLM53F)
        self.assertTrue(z.get("off"))
        # 放回去要 zcode 开着（关着的 provider 的成员 magpie 加不进去），所以先放回、最后才关 zcode
        self.assertEqual(self.calls()[-1], "provider off zcode")
        self.assertFalse(self.read_state().get("stripped"))
        self.assertIn("放回原位", Fake.messages[0][0]["content"])

    def test_zcode_already_on_leaves_the_other_groups_alone(self):
        # zcode 是别人开着的：别的组本来就在用它，守护打开时不去动
        self.zroom()
        self.providers(zcode_off=False)
        self.state(open=False, since=0)
        self.all_low()
        self.assertEqual(self.run_guard(), 0)
        g, _ = self.groups()
        self.assertTrue(self.read_state()["open"])
        self.assertEqual(g["frontier"], FRONTIER)
        self.assertEqual(g["auto-glm-5-3"], GLM53)
        self.assertEqual([c for c in self.calls() if "models-=" in c], [])
        self.assertFalse(self.read_state().get("zcode_by_guard"))

    def test_member_with_its_own_settings_is_left_alone(self):
        # 拿掉会丢设置（成员上挂着规则）或会把组拿空（magpie 不让）的，不拿，日志和消息里写出来
        self.zroom()
        d = self.load("conf/providers.json")
        next(g for g in d["groups"] if g["id"] == "frontier")["rules"] = [{"use": "zcode/GLM-5.3", "longer": 100000}]
        d["groups"].append({"id": "glm-only", "members": ["zcode/GLM-5.3"]})
        self.dump("conf/providers.json", d)
        self.all_low()
        self.assertEqual(self.run_guard(), 0)
        g, _ = self.groups()
        self.assertEqual(g["frontier"], FRONTIER)
        self.assertEqual(g["glm-only"], ["zcode/GLM-5.3"])
        self.assertNotIn("zcode/GLM-5.3", g["auto-glm-5-3"])
        with open(self.tmp + "/var/log") as f:
            self.assertIn("left alone", f.read())
        msg = Fake.messages[0][0]["content"]
        self.assertIn("没拿掉", msg)
        self.assertIn("glm-only", msg)

    def test_member_put_back_once_zcode_is_on_again(self):
        # 开着期间有人把 zcode 关了，座位恢复时守护关上：放回成员要 zcode 开着，这时放不回，记着、不报失败；
        # zcode 已经不是守护开着的了，之后有人再打开它，守护把成员放回原位，不去关 zcode
        self.opened(20)
        self.zcode_by_hand(off=True)
        self.a_reset()
        self.assertEqual(self.run_guard(), 0)
        g, _ = self.groups()
        self.assertFalse(self.read_state()["open"])
        self.assertNotIn("zcode/GLM-5.3", g["frontier"])
        self.assertTrue(self.read_state().get("stripped"))
        self.zcode_by_hand(off=False)
        self.t += 300
        self.a_reset()
        self.assertEqual(self.run_guard(), 0)
        g, z = self.groups()
        self.assertEqual(g["frontier"], FRONTIER, "frontier not put back once zcode was on again")
        self.assertFalse(self.read_state().get("stripped"))
        self.assertNotIn("off", z, "turned off a zcode someone else turned on")

    def test_half_finished_strip_is_still_put_back(self):
        # 拿 frontier 的成员成功、拿 auto-glm-5-3 的失败：这轮记失败，但 frontier 那条要已经记下；下一轮补完打开，关上时都放回
        self.zroom()
        self.flag("fail", "group set auto-glm-5-3 ")
        self.all_low()
        self.assertEqual(self.run_guard(), 1)
        g, z = self.groups()
        self.assertNotIn("zcode/GLM-5.3", g["frontier"])
        self.assertTrue(z.get("off"))
        os.remove(self.tmp + "/fail")
        self.t += 300
        self.all_low()
        self.assertEqual(self.run_guard(), 0)
        self.assertTrue(self.read_state()["open"])
        self.t += 20 * 60
        self.a_reset()
        self.assertEqual(self.run_guard(), 0)
        g, z = self.groups()
        self.assertEqual(g["frontier"], FRONTIER, "frontier lost its zcode member for good")
        self.assertEqual(g["auto-glm-5-3"], GLM53)
        self.assertTrue(z.get("off"))

    def test_put_back_is_read_back(self):
        # 放回成员的命令退出 0 却没改：读回要抓到，记失败；那个成员还记着，以后再放
        self.opened(20)
        self.flag("noop", "group set frontier models=")
        self.a_reset()
        self.assertEqual(self.run_guard(), 1)
        with open(self.tmp + "/var/log") as f:
            self.assertIn("providers.json not as expected", f.read())
        self.assertIn("frontier", [e["group"] for e in self.read_state().get("stripped") or []])

    # ---- 复审第二轮记下的测试缺口 ----
    def test_two_zcode_members_go_back_in_their_order(self):
        # 一个组里连着两个 zcode 成员：拿掉时都记成「排在 zed 后面」，放回要倒着放，次序才对
        self.zroom()
        two = ["zed/gpt-6.1-sol", "zcode/GLM-5.3", "zcode/GLM-5.3-Flash", "trae-cn/glm-5.3", "group/always-up"]
        d = self.load("conf/providers.json")
        next(g for g in d["groups"] if g["id"] == "frontier")["members"] = list(two)
        self.dump("conf/providers.json", d)
        self.all_low()
        self.assertEqual(self.run_guard(), 0)
        g, _ = self.groups()
        self.assertEqual(g["frontier"], ["zed/gpt-6.1-sol", "trae-cn/glm-5.3", "group/always-up"])
        self.t += 20 * 60
        self.a_reset()
        self.assertEqual(self.run_guard(), 0)
        g, _ = self.groups()
        self.assertEqual(g["frontier"], two, "frontier's zcode members came back out of order")

    def test_open_read_back_catches_a_group_still_holding_zcode(self):
        # 拿 frontier 的 zcode 成员那条退出 0 却没改：打开的读回要抓到（zcode 已开着，frontier 还能用到它），记失败
        self.zroom()
        self.flag("noop", "group set frontier models-=")
        self.all_low()
        self.assertEqual(self.run_guard(), 1, "opened with zcode still in frontier")
        g, z = self.groups()
        self.assertIn("zcode/GLM-5.3", g["frontier"])
        self.assertNotIn("off", z)
        with open(self.tmp + "/var/log") as f:
            self.assertIn("providers.json not as expected", f.read())
        self.assertFalse(self.read_state()["open"])
        os.remove(self.tmp + "/noop")
        self.t += 300
        self.all_low()
        self.assertEqual(self.run_guard(), 0)
        g, _ = self.groups()
        self.assertNotIn("zcode/GLM-5.3", g["frontier"])
        self.assertTrue(self.read_state()["open"])

    def test_provider_off_is_read_back(self):
        # 关上时 provider off 退出 0 却没关上：读回要抓到、记失败；zcode 仍算守护开着的，下一轮再关
        self.opened(20)
        self.flag("noop", "provider off")
        self.a_reset()
        self.assertEqual(self.run_guard(), 1, "a provider off that didn't take was counted as done")
        _, z = self.groups()
        self.assertNotIn("off", z)
        with open(self.tmp + "/var/log") as f:
            self.assertIn("zcode still on after provider off", f.read())
        self.assertTrue(self.read_state().get("zcode_by_guard"))
        os.remove(self.tmp + "/noop")
        self.t += 300
        self.a_reset()
        self.assertEqual(self.run_guard(), 0)
        g, z = self.groups()
        self.assertTrue(z.get("off"), "zcode left on after the close: %s" % z)
        self.assertEqual(g["frontier"], FRONTIER)
        self.assertFalse(self.read_state()["open"])

    def test_speed_open_counts_an_unread_seat_as_no_room(self):
        # a、b 各剩 10 个百分点到上限，c 读不到；三个座位最近 30 分钟各涨 10 → 1%/分钟。c 按没有余量算：20 分钟用完 → 打开；
        # c 要是按满额算，余量 120、120 分钟才用完，不开
        self.history(self.history_burn(10))
        Fake.cards[:] = [self.seat("a@x.com", 85, 120), self.seat("b@x.com", 85, 120), self.unread("c@x.com")]
        self.run_guard()
        self.assertTrue(self.read_state()["open"], "an unread seat was counted as room in the speed rule")
        first = Fake.messages[0][0]["content"].splitlines()[0]
        self.assertIn("按最近 30 分钟的速度", first)

    # ---- ZCode 自己的余量：Max 用完改用 Trial，Trial 也用完就不开 ----
    def zhist(self, five=100, week=100, trial=100, flash=100, ago_min=2, five_reset_min=None, week_reset_min=100 * 60,
              trial_reset_min=15 * 60, stale=True):
        """quota-history.json 里 ZCode 的样子（照网关 11-01）：otmrzlm7 是 GLM Coding Max，另有 Start Plan 两个 Trial 桶；
        stale 再加一个 3 天前就不再读的旧账号，它的窗口都过了重置时间，算进来就会被当成满额"""
        at = iso(self.t - ago_min * 60)

        def pt(left, reset_min):
            p = {"at": at, "left": left}
            if reset_min is not None:
                p["resetsAt"] = iso(self.t + reset_min * 60)
            return [p]
        h = {"zcode|otmrzlm7": {"5 hours": pt(five, five_reset_min), "Weekly": pt(week, week_reset_min),
                                "GLM-5.3-Trial · ZCode Start Plan": pt(trial, trial_reset_min),
                                "GLM-5.3-Flash-Trial · ZCode Start Plan": pt(flash, trial_reset_min)}}
        if stale:
            old, gone = iso(self.t - 72 * 3600), iso(self.t - 48 * 3600)
            h["zcode|old@x.com"] = {name: [{"at": old, "left": 0, "resetsAt": gone}] for name in
                                   ("5 hours", "Weekly", "GLM-5.3-Trial · ZCode Start Plan", "GLM-5.3")}
        return h

    def zcard(self, five=0, week=0, trial=0, flash=0, ago_min=1, trial_reset_min=15 * 60, trial_text=False):
        """ZCode 开着时 magpie 卡片里的 ZCode 账号（used 是用掉的 %）"""
        def w(name, used, reset_min):
            return {"name": name, "used": used, "resetsAt": iso(self.t + reset_min * 60)}
        trials = [w("GLM-5.3-Trial · ZCode Start Plan", trial, trial_reset_min),
                  w("GLM-5.3-Flash-Trial · ZCode Start Plan", flash, trial_reset_min)]
        if trial_text:
            # 还没生效、要去 ZCode App 领的赠送套餐：magpie 把它当一行字放在卡片上，used 0 不是读数
            trials = [dict(x, used=0, text=True, display="ZCode gift plan not started yet") for x in trials]
        return {"provider": "zcode", "kind": "subscription", "plan": "GLM Coding Max", "user": "otmrzlm7",
                "readAt": iso(self.t - ago_min * 60),
                "windows": [w("5 hours", five, 120), w("Weekly", week, 100 * 60)] + trials}

    def zcode_members(self):
        g, _ = self.groups()
        return {gid: [m for m in g[gid] if m.startswith("zcode/")] for gid in gg.GLM}

    TRIALS = {"claude-opus-5-5": ["zcode/GLM-5.3-Trial"], "claude-sonnet-5-5": ["zcode/GLM-5.3-Trial"],
              "claude-haiku-5-5": ["zcode/GLM-5.3-Flash-Trial"]}
    MAXES = {"claude-opus-5-5": ["zcode/GLM-5.3"], "claude-sonnet-5-5": ["zcode/GLM-5.3"],
             "claude-haiku-5-5": ["zcode/GLM-5.3-Flash"]}
    NONE = {"claude-opus-5-5": [], "claude-sonnet-5-5": [], "claude-haiku-5-5": []}

    def test_week_used_up_opens_with_trial(self):
        # 11-01 20:09 的样子：ZCode Max 周额度 0%（11-06 才重置），座位全满。不加 GLM-5.3，改加免费 Trial
        self.trial_on()
        self.history(self.zhist(week=0))
        self.all_low()
        self.assertEqual(self.run_guard(), 0)
        self.assertEqual(self.zcode_members(), self.TRIALS, "added a Max member with the week used up")
        _, z = self.groups()
        self.assertNotIn("off", z)
        self.assertTrue(self.read_state()["open"])
        msg = Fake.messages[0][0]["content"]
        self.assertIn("已自动打开 GLM 兜底", msg.splitlines()[0])
        self.assertIn("Trial", msg.splitlines()[0])
        self.assertIn("周剩 0%", msg)
        self.assertIn("zcode/GLM-5.3-Trial", msg)
        self.assertNotIn("兜底已空", msg)

    def test_5h_used_up_opens_with_trial(self):
        self.trial_on()
        self.history(self.zhist(five=0, five_reset_min=120, week=60))
        self.all_low()
        self.run_guard()
        self.assertEqual(self.zcode_members(), self.TRIALS, "added a Max member with its 5 hours used up")

    def test_trial_used_up_too_does_not_open(self):
        # Max 周额度和两个 Trial 桶都用完：什么都不加、不开 zcode、不动别的组，消息里明说兜底已空，下一轮不重复发
        self.trial_on()
        self.history(self.zhist(week=0, trial=0, flash=0))
        self.all_low()
        self.assertEqual(self.run_guard(), 0)
        self.assertEqual(self.calls(), [], "changed the groups with nothing left to add")
        g, z = self.groups()
        self.assertTrue(z.get("off"))
        self.assertEqual(g["frontier"], FRONTIER)
        self.assertEqual(len(Fake.messages), 1)
        msg = Fake.messages[0][0]["content"]
        self.assertIn("兜底已空", msg.splitlines()[0])
        self.assertIn("周剩 0%", msg)
        self.t += 300
        self.all_low()
        self.run_guard()
        self.assertEqual(self.calls(), [])
        self.assertEqual(len(Fake.messages), 1)

    def test_haiku_keeps_flash_trial_when_glm53_trial_is_spent(self):
        # 两个 Trial 是各自的桶：GLM-5.3-Trial 用完、Flash-Trial 还有，haiku 照样加 Flash-Trial，opus、sonnet 什么都不加
        self.trial_on()
        self.history(self.zhist(week=0, trial=0, flash=50))
        self.all_low()
        self.run_guard()
        self.assertEqual(self.zcode_members(), dict(self.NONE, **{"claude-haiku-5-5": ["zcode/GLM-5.3-Flash-Trial"]}))
        msg = Fake.messages[0][0]["content"]
        self.assertIn("兜底已空", msg.splitlines()[0])
        self.assertIn("claude-opus-5-5", msg.splitlines()[0])

    def test_max_with_room_is_still_used_first(self):
        # Max 还有余量就照旧用 Max（Trial 每天额度小，留着）
        self.history(self.zhist(five=70, week=60))
        self.all_low()
        self.run_guard()
        self.assertEqual(self.zcode_members(), self.MAXES)

    def test_account_magpie_no_longer_reads_does_not_count(self):
        # 旧账号 3 天前就不再读了、它的窗口都过了重置时间：不能把它当成有余量的 Max 或 Trial
        self.trial_on()
        self.history(self.zhist(week=0, trial=0, flash=0, stale=True))
        h = self.load("conf/quota-history.json")
        for pts in h["zcode|old@x.com"].values():
            pts[0]["left"] = 100
        self.history(h)
        self.all_low()
        self.run_guard()
        self.assertEqual(self.calls(), [], "counted a dropped ZCode account as room")

    def test_window_past_its_reset_is_room_again(self):
        # 周额度读数是 0%，但重置时间已经过了、magpie 还没再读（zcode 关着不读）：周额度已经重新开始，用 Max
        self.history(self.zhist(week=0, week_reset_min=-10))
        self.all_low()
        self.run_guard()
        self.assertEqual(self.zcode_members(), self.MAXES)

    def test_open_swaps_to_trial_when_max_runs_out(self):
        # 开着、用的是 Max；ZCode 开着后卡片读到周额度用完（比历史里那个旧读数新）：换成 Trial，先加后拿，zcode 一直开着
        self.trial_on()
        self.history(self.zhist(week=60, ago_min=30))
        self.opened(20)
        self.all_low()
        Fake.cards.append(self.zcard(week=100))
        self.assertEqual(self.run_guard(), 0)
        self.assertEqual(self.zcode_members(), self.TRIALS, "kept the Max member after its week ran out")
        calls = self.calls()
        self.assertLess(calls.index("group set claude-opus-5-5 models+=zcode/GLM-5.3-Trial"),
                        calls.index("group set claude-opus-5-5 models-=zcode/GLM-5.3"), calls)
        self.assertNotIn("provider off zcode", calls)
        g, z = self.groups()
        self.assertNotIn("off", z)
        self.assertNotIn("zcode/GLM-5.3", g["frontier"])  # 别的组还拿着
        st = self.read_state()
        self.assertTrue(st["open"])
        self.assertEqual(st["since"], self.t - 20 * 60)
        self.assertEqual(len(Fake.messages), 1)
        first = Fake.messages[0][0]["content"].splitlines()[0]
        self.assertIn("改用", first)
        self.assertIn("Trial", first)

    def test_open_goes_empty_then_back_when_trial_resets(self):
        self.trial_on()
        self.history(self.zhist(week=0))
        self.all_low()
        self.run_guard()
        self.assertEqual(self.zcode_members(), self.TRIALS)
        # Trial 也用完：拿掉 Trial，放回别的组，关回守护开的 zcode，消息说兜底已空；守护仍算开着
        self.t += 300
        self.all_low()
        Fake.cards.append(self.zcard(week=100, trial=100, flash=100, trial_reset_min=60))
        self.history(self.zhist(week=0, trial=0, flash=0, ago_min=1, trial_reset_min=60))
        self.assertEqual(self.run_guard(), 0)
        self.assertEqual(self.zcode_members(), self.NONE)
        g, z = self.groups()
        self.assertTrue(z.get("off"))
        self.assertEqual(g["frontier"], FRONTIER)
        self.assertTrue(self.read_state()["open"])
        self.assertEqual(len(Fake.messages), 2)
        self.assertIn("兜底已空", Fake.messages[1][0]["content"].splitlines()[0])
        # zcode 关着、卡片里没有它；历史里 Trial 的重置时间一过就重新有余量：再加上 Trial，消息说恢复
        self.t += 61 * 60
        self.all_low()
        self.assertEqual(self.run_guard(), 0)
        self.assertEqual(self.zcode_members(), self.TRIALS)
        g, z = self.groups()
        self.assertNotIn("off", z)
        self.assertNotIn("zcode/GLM-5.3", g["frontier"])
        self.assertEqual(len(Fake.messages), 3)
        self.assertIn("Trial", Fake.messages[2][0]["content"].splitlines()[0])
        self.assertNotIn("兜底已空", Fake.messages[2][0]["content"].splitlines()[0])

    def test_close_takes_out_the_trial_members(self):
        self.trial_on()
        self.history(self.zhist(week=0))
        self.all_low()
        self.run_guard()
        self.t += 20 * 60
        self.a_reset()
        self.assertEqual(self.run_guard(), 0)
        self.assertEqual(self.zcode_members(), self.NONE, "left a Trial member behind on close")
        g, z = self.groups()
        self.assertEqual(g["claude-opus-5-5"], ["claude/claude-opus-5-5", "kiro/claude-opus-5.5"])
        self.assertEqual(g["frontier"], FRONTIER)
        self.assertTrue(z.get("off"))
        self.assertIn("已自动关上", Fake.messages[-1][0]["content"].splitlines()[0])

    def test_closed_takes_out_a_trial_member_added_by_hand(self):
        self.providers(zcode_off=False, extra=["zcode/GLM-5.3-Trial"])
        self.state(open=False, since=0)
        Fake.cards[:] = [self.seat("a@x.com", 30, 120), self.seat("b@x.com", 5, 200), self.seat("c@x.com", 20, 60)]
        self.run_guard()
        g, _ = self.groups()
        self.assertEqual(g["claude-opus-5-5"], ["claude/claude-opus-5-5", "kiro/claude-opus-5.5"])
        self.assertEqual(Fake.messages, [])

    def test_gift_not_started_is_not_room(self):
        # 卡片上的 Trial 只是一行字（赠送套餐还没生效）：不算余量；Max 周额度也用完 → 兜底已空
        self.trial_on()
        self.providers(zcode_off=False)
        self.state(open=False, since=0)
        self.all_low()
        Fake.cards.append(self.zcard(week=100, trial_text=True))
        self.run_guard()
        self.assertEqual(self.zcode_members(), self.NONE, "a gift row that is only text was counted as room")
        self.assertIn("兜底已空", Fake.messages[0][0]["content"].splitlines()[0])

    # ---- 复审第一轮 A：读不到、读数不全、看不懂，都算不知道 ----
    def test_no_zcode_reading_adds_nothing(self):
        # 卡片和历史里都没有 ZCode：不加 GLM-5.3，也不开 zcode、不动别的组，消息说读不到
        self.all_low()
        self.assertEqual(self.run_guard(), 0)
        self.assertEqual(self.calls(), [], "unknown ZCode allowance read as room")
        msg = Fake.messages[0][0]["content"]
        self.assertIn("读不到 ZCode 余量", msg.splitlines()[0])
        self.assertEqual(Fake.unrests, [])

    def test_weekly_missing_is_not_max(self):
        # 只有 5 hours 有读数（Weekly 缺，插件改名也是这样）：不算 Max 有余量，改用有读数的 Trial
        self.trial_on()
        h = self.zhist(week=0, stale=False)
        del h["zcode|otmrzlm7"]["Weekly"]
        self.history(h)
        self.all_low()
        self.run_guard()
        self.assertEqual(self.zcode_members(), self.TRIALS, "a missing Weekly reading read as room")

    def test_card_window_without_used_is_no_reading(self):
        # 卡片上 Weekly 没有 used：不是读数（不是 100% 剩余）；Trial 桶也用完 → 什么都不加
        self.providers(zcode_off=False)
        self.state(open=False, since=0)
        self.all_low()
        z = self.zcard(week=100, trial=100, flash=100)
        next(w for w in z["windows"] if w["name"] == "Weekly").pop("used")
        Fake.cards.append(z)
        self.run_guard()
        self.assertEqual(self.zcode_members(), self.NONE, "a Weekly window with no 'used' read as 100% left")

    def test_unparseable_reading_is_no_reading(self):
        # 历史点 left 不是数：不让整轮崩掉（不然既开不了也关不了）；那个窗口算没读数，用 Trial
        self.trial_on()
        h = self.zhist(week=0, stale=False)
        h["zcode|otmrzlm7"]["Weekly"][0]["left"] = "n/a"
        self.history(h)
        self.all_low()
        self.assertEqual(self.run_guard(), 0)
        self.assertEqual(self.zcode_members(), self.TRIALS)
        with open(self.tmp + "/var/log") as f:
            self.assertIn("closed -> open", f.read())

    def test_history_uses_the_newest_point(self):
        # 真实历史一个窗口几百个点：最旧的是周初（剩 100%），最新的是 0%。要按最新的判，用 Trial
        self.trial_on()
        h = self.zhist(stale=False)
        h["zcode|otmrzlm7"]["Weekly"] = [
            {"at": iso(self.t - 50 * 3600), "left": 100, "resetsAt": iso(self.t + 100 * 3600)},
            {"at": iso(self.t - 20 * 3600), "left": 40, "resetsAt": iso(self.t + 100 * 3600)},
            {"at": iso(self.t - 2 * 60), "left": 0, "resetsAt": iso(self.t + 100 * 3600)}]
        self.history(h)
        self.all_low()
        self.run_guard()
        self.assertEqual(self.zcode_members(), self.TRIALS, "judged by an old point, not the newest")

    def test_swap_read_back_sees_the_old_member_still_there(self):
        # 开着、组里是 Max；周额度用完要换 Trial，可「models-= Max」退出 0 却没生效：读回要抓到，记失败
        self.trial_on()
        self.history(self.zhist(week=60, ago_min=30, stale=False))
        self.opened(20)
        self.all_low()
        Fake.cards.append(self.zcard(week=100))
        self.flag("noop", "group set claude-opus-5-5 models-=")
        self.assertEqual(self.run_guard(), 1, "a swap that left the Max member in was counted as done")
        with open(self.tmp + "/var/log") as f:
            self.assertIn("providers.json not as expected", f.read())

    # ---- 复审第一轮 B：magpie 把整个 ZCode 账号歇掉，Trial 一起挡住 ----
    def routing(self, *recs):
        """routing 日志：recs 是 (几分钟前, rest 或 None)；每条一个 claude-opus-5-5 请求，order 里有 ZCode 账号那一项"""
        day = datetime.fromtimestamp(self.t, TZ).strftime("%Y-%m-%d")
        with open(os.path.join(gg.ROUTING, day + ".jsonl"), "a") as f:
            for ago, rest in recs:
                o = {"id": "zcode", "provider": "zcode", "who": "otmrzlm7", "model": "GLM-5.3-Trial", "used": 0}
                if rest:
                    o["rest"] = rest
                f.write(json.dumps({"time": iso(self.t - ago * 60), "model": "claude-opus-5-5", "status": 429,
                                    "order": [{"id": "claude", "provider": "claude"}, o],
                                    "tries": [{"id": "claude@a@x.com · DuoCode", "status": 429}]}) + "\n")

    def cap_rest(self, hours=100):
        return {"why": "rate", "status": 429, "until": iso(self.t + hours * 3600), "by": "resets", "failures": 1,
                "key": "zcode@otmrzlm7",
                "error": "ZCode: [1310][您已达到每周/每月使用上限，您的限额将在 2026-11-06 13:13:55 重置。][x]"}

    def test_cap_rest_is_lifted_after_trial_goes_in(self):
        # 11-02 01:10 的样子：Max 周额度用完，账号因 1310 歇到 11-06；Trial 桶满。加 Trial，组对齐之后解除账号休息
        self.trial_on()
        self.history(self.zhist(week=0, stale=False))
        self.routing((30, self.cap_rest()))
        Fake.unrest_reply = (200, {"lifted": True})
        self.all_low()
        self.assertEqual(self.run_guard(), 0)
        self.assertEqual(self.zcode_members(), self.TRIALS)
        self.assertEqual([k for k, _ in Fake.unrests], ["zcode@otmrzlm7"], "the account rest was left in place")
        self.assertEqual(Fake.unrests[0][1], len(self.calls()), "lifted before the groups were aligned")
        msg = Fake.messages[0][0]["content"]
        self.assertIn("已解除", msg)
        self.assertIn("1310", msg)
        with open(self.tmp + "/var/log") as f:
            log = f.read()
        self.assertIn("unrest zcode@otmrzlm7: lifted (was rate until", log)
        self.assertIn("[1310]", log)

    def test_no_lift_without_a_rest_in_the_log(self):
        # 日志里没有这个账号歇着的记录：不知道为什么歇、歇没歇，就不解除（只解除确认是 Max 周额度上限造成的）
        self.trial_on()
        self.history(self.zhist(week=0, stale=False))
        self.all_low()
        self.run_guard()
        self.assertEqual(self.zcode_members(), self.TRIALS)
        self.t += 300
        self.all_low()
        self.run_guard()
        self.assertEqual(Fake.unrests, [], "lifted a rest the log never showed")

    def test_steady_round_lifts_when_the_log_says_rested_again(self):
        # 开着、组里已是 Trial；之后有请求让账号又歇了（日志里看得到）：这一轮解除，只写日志、不发消息
        self.trial_on()
        self.history(self.zhist(week=0, stale=False))
        self.all_low()
        self.run_guard()
        n = len(Fake.messages)
        self.t += 300
        self.routing((1, self.cap_rest()))
        Fake.unrest_reply = (200, {"lifted": True})
        self.all_low()
        self.assertEqual(self.run_guard(), 0)
        self.assertEqual(len(Fake.unrests), 1)
        self.assertEqual(len(Fake.messages), n)
        with open(self.tmp + "/var/log") as f:
            self.assertIn("unrest zcode@otmrzlm7: lifted", f.read().splitlines()[-1])

    def test_later_record_without_rest_means_not_resting(self):
        # 先歇过、后来又答过（最新一条没有 rest）：不在歇，稳定的一轮不去解除
        self.trial_on()
        self.history(self.zhist(week=0, stale=False))
        self.all_low()
        self.run_guard()
        self.t += 300
        self.routing((20, self.cap_rest()), (2, None))
        self.all_low()
        self.run_guard()
        self.assertEqual(Fake.unrests, [], "an old rest, cleared by a later answer, was lifted")

    def test_restricted_account_is_neither_lifted_nor_used(self):
        # 风控（3012，why=restricted）：守护不解除（只有 ZCode 客服能解），也不加它的成员，消息说清楚
        self.trial_on()
        self.history(self.zhist(week=0, stale=False))
        self.routing((10, {"why": "restricted", "status": 405, "until": iso(self.t + 6 * 3600), "by": "restricted",
                           "key": "zcode@otmrzlm7", "error": "ZCode: [3012] request has been blocked due to unusual activity"}))
        self.all_low()
        self.assertEqual(self.run_guard(), 0)
        self.assertEqual(self.calls(), [], "used a ZCode account under risk control")
        self.assertEqual(Fake.unrests, [], "lifted a risk-control rest")
        msg = Fake.messages[0][0]["content"]
        self.assertIn("兜底已空", msg.splitlines()[0])
        self.assertIn("风控", msg)

    def test_risk_control_keeps_the_whole_account_out_wherever_it_is_filed(self):
        # magpie 把 3012 记在账号上；万一记在某个条目上（key 带 /模型），守护照样整个账号都不用：读数说 Max 有余量也不加
        self.history(self.zhist(stale=False))
        self.routing((10, {"why": "restricted", "status": 405, "until": iso(self.t + 6 * 3600), "by": "restricted",
                           "key": "zcode@otmrzlm7/GLM-5.3-Trial",
                           "error": "ZCode: [3012] request has been blocked due to unusual activity"}))
        self.all_low()
        self.run_guard()
        self.assertEqual(self.calls(), [], "used a ZCode account under risk control")
        self.assertIn("风控", Fake.messages[0][0]["content"])

    def test_cap_rest_skips_max_even_when_readings_say_room(self):
        # 读数说 Max 有余量，可账号刚因上限被歇：Max 显然被拒过，用 Trial（解除后 Max 会再被拒、又把账号歇掉）
        self.trial_on()
        self.history(self.zhist(stale=False))
        self.routing((5, self.cap_rest()))
        self.all_low()
        self.run_guard()
        self.assertEqual(self.zcode_members(), self.TRIALS, "added the Max member of an account resting for its cap")

    def test_max_never_lifts_a_rest(self):
        self.trial_on()
        self.zroom()
        self.all_low()
        self.run_guard()
        self.assertEqual(self.zcode_members(), self.MAXES)
        self.assertEqual(Fake.unrests, [])

    def test_failed_lift_is_reported_not_fatal(self):
        # 解除失败（网页 key 不对 → 401）：这一轮照样算成功、Trial 留在组里，消息说 Trial 暂时到不了
        self.trial_on()
        os.environ["MAGPIE_WEB_KEY"] = "wrong"
        self.history(self.zhist(week=0, stale=False))
        self.routing((30, self.cap_rest()))
        self.all_low()
        self.assertEqual(self.run_guard(), 0)
        self.assertEqual(self.zcode_members(), self.TRIALS)
        self.assertEqual(Fake.unrests, [])
        self.assertIn("解除失败", Fake.messages[0][0]["content"])
        with open(self.tmp + "/var/log") as f:
            self.assertIn("unrest zcode@otmrzlm7: FAILED", f.read())


    # ---- Trial 开关（默认关）、只解除 Max 周额度上限造成的账号休息、限频 ----
    def test_trial_is_off_by_default(self):
        # 开关不在：Max 用完、Trial 桶满、账号因 1310 歇着，也什么都不加、不解除，消息说兜底已空、Trial 没开、怎么打开
        self.history(self.zhist(week=0, stale=False))
        self.routing((30, self.cap_rest()))
        self.all_low()
        self.assertEqual(self.run_guard(), 0)
        self.assertEqual(self.calls(), [], "used Trial with the switch off")
        self.assertEqual(Fake.unrests, [], "lifted a rest with the switch off")
        msg = Fake.messages[0][0]["content"]
        self.assertIn("兜底已空", msg.splitlines()[0])
        self.assertIn("开关没开", msg)
        self.assertIn("use-trial", msg)
        with open(self.tmp + "/var/log") as f:
            self.assertIn("trial=off", f.read())

    def test_switching_trial_off_takes_trial_out(self):
        self.trial_on()
        self.history(self.zhist(week=0, stale=False))
        self.all_low()
        self.run_guard()
        self.assertEqual(self.zcode_members(), self.TRIALS)
        os.remove(os.path.join(self.tmp, "etc", "use-trial"))
        self.t += 300
        self.history(self.zhist(week=0, stale=False))
        self.all_low()
        self.assertEqual(self.run_guard(), 0)
        self.assertEqual(self.zcode_members(), self.NONE, "Trial left in after the switch went off")
        g, z = self.groups()
        self.assertTrue(z.get("off"))
        self.assertEqual(g["frontier"], FRONTIER)
        self.assertTrue(self.read_state()["open"])
        self.assertIn("兜底已空", Fake.messages[-1][0]["content"].splitlines()[0])

    def test_account_rest_counts_as_no_room(self):
        # 读数说 Max 有余量，可账号在 magpie 里歇着（Max 被拒过）：不加 Max（开关关着也不加 Trial），消息说账号歇到什么时候
        self.history(self.zhist(stale=False))
        self.routing((5, self.cap_rest()))
        self.all_low()
        self.run_guard()
        self.assertEqual(self.calls(), [], "added members of a resting account")
        msg = Fake.messages[0][0]["content"]
        self.assertIn("兜底已空", msg.splitlines()[0])
        self.assertIn("歇到", msg)

    def test_trial_entry_rest_is_not_lifted(self):
        # 歇的是 GLM-5.3-Trial 条目自己（key 带 /模型）：不解除，哪怕错误和时间像周额度上限；opus、sonnet 不加它，haiku 的
        # Flash-Trial 照样加
        self.trial_on()
        for rest in ({"why": "quota", "status": 429, "until": iso(self.t + 10 * 3600), "by": "resets",
                      "key": "zcode@otmrzlm7/GLM-5.3-Trial",
                      "error": "ZCode's limited quota for glm-5.3 is exhausted or temporarily unavailable"},
                     dict(self.cap_rest(), key="zcode@otmrzlm7/GLM-5.3-Trial")):
            Fake.unrests[:] = []
            self.state(open=False, since=0)
            self.providers(zcode_off=True)
            self.history(self.zhist(week=0, stale=False))
            self.routing((1, rest))
            self.all_low()
            self.run_guard()
            self.assertEqual(Fake.unrests, [], "lifted a Trial entry's own rest: %s" % rest["error"])
            self.assertEqual(self.zcode_members(), dict(self.NONE, **{"claude-haiku-5-5": ["zcode/GLM-5.3-Flash-Trial"]}))
            self.t += 300

    def test_other_account_rests_are_not_lifted(self):
        # 账号级、但不是 Max 周额度上限：认证错，或 1310 的 until 对不上周额度的重置（月上限）。不解除，Trial 到不了就不加
        self.trial_on()
        for rest in (dict(self.cap_rest(), why="auth", status=401, error="ZCode: token expired"),
                     # 请求 id 里碰巧有 1310（13:10:05 的请求）的余额错误：不是周额度上限
                     dict(self.cap_rest(), why="quota", error="ZCode: [1113][余额不足][20261101131005a1b2c3d4e5f6a7b8]"),
                     dict(self.cap_rest(), until=iso(self.t + 30 * 24 * 3600))):
            Fake.unrests[:], Fake.messages[:] = [], []
            self.state(open=False, since=0)
            self.providers(zcode_off=True)
            self.history(self.zhist(week=0, stale=False))
            self.routing((1, rest))
            self.all_low()
            self.run_guard()
            self.assertEqual(Fake.unrests, [], "lifted %s" % rest["error"])
            self.assertEqual(self.zcode_members(), self.NONE, "added Trial on an account it can't reach: %s" % rest)
            self.assertIn("守护只解除", Fake.messages[0][0]["content"])
            self.t += 300

    def test_lift_is_rate_limited(self):
        # 每次打开一次，之后同一次打开里最多每小时一次（只算真解除了的）；关上再打开又能解一次
        self.trial_on()
        Fake.unrest_reply = (200, {"lifted": True})

        def round_(ago=1):
            self.history(self.zhist(week=0, stale=False))
            self.routing((ago, self.cap_rest()))
            self.all_low()
            self.assertEqual(self.run_guard(), 0)
        round_(30)
        self.assertEqual(len(Fake.unrests), 1)
        self.t += 300
        round_()
        self.assertEqual(len(Fake.unrests), 1, "lifted twice within the hour")
        with open(self.tmp + "/var/log") as f:
            self.assertIn("unrest zcode@otmrzlm7: deferred to", f.read().splitlines()[-1])
        self.t += 3300
        round_()
        self.assertEqual(len(Fake.unrests), 2, "not lifted again after an hour")
        self.t += 300
        self.history(self.zhist(week=0, stale=False))
        self.a_reset()
        self.run_guard()
        self.assertFalse(self.read_state()["open"])
        self.t += 16 * 60
        round_()
        self.assertTrue(self.read_state()["open"])
        self.assertEqual(len(Fake.unrests), 3, "a new opening didn't get its lift")


    # ---- 复审增量：错误码按词认、过期的休息、web key 不上命令行、昨天的压缩日志 ----
    def test_request_id_digits_are_not_an_error_code(self):
        # 复审 v8：周额度上限（1310）的休息，请求 id 里碰巧连着 3012（11-03 01:25:12 的请求）：不是风控。开关关时消息不说
        # 「风控挡住」；开关开时照样加 Trial、解除一次
        rest = dict(self.cap_rest(), error="ZCode: [1310][您已达到每周/每月使用上限，您的限额将在 2026-11-06 13:13:55 重置。]"
                                           "[20261103012512a1b2c3d4e5f6a7b8]")
        Fake.unrest_reply = (200, {"lifted": True})
        for on in (False, True):
            Fake.unrests[:], Fake.messages[:] = [], []
            self.state(open=False, since=0)
            self.providers(zcode_off=True)
            if on:
                self.trial_on()
            self.history(self.zhist(week=0, stale=False))
            self.routing((5, rest))
            self.all_low()
            self.assertEqual(self.run_guard(), 0)
            msg = Fake.messages[0][0]["content"]
            self.assertNotIn("风控挡住", msg, "a 1310 rest was reported as risk control (switch %s)" % on)
            if on:
                self.assertEqual(self.zcode_members(), self.TRIALS)
                self.assertEqual([k for k, _ in Fake.unrests], ["zcode@otmrzlm7"])
            else:
                self.assertEqual(self.calls(), [])
            self.t += 300

    def test_expired_rest_is_not_a_rest(self):
        # 复审 v9：最新一条记录还带着 rest，可 until 已经过了（周额度已重置、之后没人问过）：不算在歇，Max 有余量就用
        self.history(self.zhist(stale=False))
        self.routing((30, dict(self.cap_rest(), until=iso(self.t - 60))))
        self.all_low()
        self.run_guard()
        self.assertEqual(self.zcode_members(), self.MAXES, "an expired rest kept Max out")

    def test_web_key_never_on_a_command_line_or_in_the_log(self):
        # 复审 v10：真解除一次时，所有子进程的参数里都没有 MAGPIE_WEB_KEY 的值（同机别的用户 ps 看得见），日志和消息里也没有
        self.trial_on()
        argvs, real = [], gg.subprocess.run

        def spy(cmd, *a, **kw):
            argvs.append(list(cmd))
            return real(cmd, *a, **kw)
        self.history(self.zhist(week=0, stale=False))
        self.routing((5, self.cap_rest()))
        Fake.unrest_reply = (200, {"lifted": True})
        self.all_low()
        gg.subprocess.run = spy
        try:
            self.assertEqual(self.run_guard(), 0)
        finally:
            gg.subprocess.run = real
        self.assertEqual(len(Fake.unrests), 1)
        self.assertTrue(argvs)
        for c in argvs:
            self.assertFalse(any(WEBKEY in x for x in c), "MAGPIE_WEB_KEY on a command line: %s" % c[:3])
        with open(self.tmp + "/var/log") as f:
            self.assertNotIn(WEBKEY, f.read())
        self.assertFalse(any(WEBKEY in m[0]["content"] for m in Fake.messages))

    def test_yesterdays_gzipped_log_is_read(self):
        # 过了午夜 magpie 把昨天的日志压成 .jsonl.gz；今天还没有含 ZCode 的记录时，账号歇着要从昨天那份里读出来
        at = self.t - 20 * 3600
        day = datetime.fromtimestamp(at, TZ).strftime("%Y-%m-%d")
        self.assertNotEqual(day, datetime.fromtimestamp(self.t, TZ).strftime("%Y-%m-%d"))
        o = {"id": "zcode", "provider": "zcode", "who": "otmrzlm7", "model": "GLM-5.3", "used": 100, "rest": self.cap_rest()}
        with gzip.open(os.path.join(gg.ROUTING, day + ".jsonl.gz"), "wt") as f:
            f.write(json.dumps({"time": iso(at), "model": "claude-opus-5-5", "status": 429, "order": [o],
                                "tries": [{"id": "zcode", "model": "GLM-5.3", "status": 429}]}) + "\n")
        self.history(self.zhist(stale=False))
        self.all_low()
        self.run_guard()
        self.assertEqual(self.calls(), [], "yesterday's gzipped log wasn't read: Max added to a resting account")
        self.assertIn("歇到", Fake.messages[0][0]["content"])


if __name__ == "__main__":
    unittest.main()
