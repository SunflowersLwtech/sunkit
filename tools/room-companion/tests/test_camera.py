"""Camera drivers: protocol codecs, config rules, and recovery through the real Bluetooth helper process
talking to a fake camera (tests/fake_dji.py). No radio, no network."""
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import time
import unittest

from room_companion.camera import catalog, duml, rsdk
from room_companion.camera.bridge import BleBridge
from room_companion.camera.manager import CameraManager

HERE = os.path.dirname(os.path.abspath(__file__))
FAKE = os.path.join(HERE, "fake_dji.py")
FAKE_ADDR = "11:22:33:44:55:66"


class Events:
    def __init__(self):
        self.items = []

    def add(self, kind, **kw):
        self.items.append({"kind": kind, **kw})

    def kinds(self):
        return [e["kind"] for e in self.items]


class FakeVideo:
    """The webcam shows up when the fake camera is in webcam mode (0x23)."""

    def __init__(self, state_path):
        self.state_path = state_path
        self.state = "waiting_device"
        self.waiting_since = time.time() - 3600
        self.detail = ""
        self.device = None

    def find_device(self):
        try:
            with open(self.state_path) as f:
                mode = json.load(f)["mode"]
        except (OSError, ValueError, KeyError):
            return None
        return object() if mode == 0x23 else None


class CodecTest(unittest.TestCase):
    def test_official_frames_match_published_vectors(self):
        # vectors from RB14/dji-vcam docs/camera-controls.md (MIT): switch to Video, subscribe status
        want = bytes.fromhex("aa1b000100000000110058ee1d04000033ff0101473936fce45f4e")
        self.assertEqual(rsdk.Frame(0x01, 0x11, 0x1D, 0x04, rsdk.mode_switch(0x01)).encode(), want)
        self.assertEqual(rsdk.Frame(0x01, 0x10, 0x1D, 0x05, rsdk.status_subscribe(3)).encode().hex(),
                         "aa1800010000000010004d8e1d05031400000000d2a49342")
        f = rsdk.decode(want)
        self.assertEqual((f.cmd_set, f.cmd_id, f.seq), (0x1D, 0x04, 0x11))
        with self.assertRaises(ValueError):
            rsdk.decode(want[:-1] + b"\x00")

    def test_stray_aa_byte_does_not_hold_back_frames(self):
        good = duml.Frame(2, 1, 7, 0xC0, 2, 0xE1, b"\x00").encode()
        d = duml.Demux()
        got = d.feed(b"\xaa\xff\x03" + bytes(12) + good)
        self.assertEqual([k for k, _ in got], ["duml"])

    def test_helper_output_is_ascii(self):
        import io
        from room_companion.camera.ble_helper import Out
        buf = io.StringIO()
        Out(buf).send({"detail": "相机拒绝了"})
        self.assertTrue(buf.getvalue().isascii())
        self.assertEqual(json.loads(buf.getvalue())["detail"], "相机拒绝了")

    def test_duml_frames_match_captures(self):
        for hx, args in {
            "550f04a202f01bcb40002b04009ab9": (0x02, 0xF0, 0xCB1B, 0x40, 0x00, 0x2B, b"\x04\x00"),
            "55110492021c1dcb40531000000000894a": (0x02, 0x1C, 0xCB1D, 0x40, 0x53, 0x10, bytes(4)),
            "550e0466020134124002e1014df2": (0x02, 0x01, 0x1234, 0x40, 0x02, 0xE1, b"\x01"),
        }.items():
            self.assertEqual(duml.Frame(*args).encode().hex(), hx)
            self.assertEqual(duml.decode(bytes.fromhex(hx)).payload, args[-1])

    def test_demux_splits_both_framings_across_notifications(self):
        a = duml.Frame(2, 1, 7, 0x40, 2, 0xE1, b"\x23").encode()
        b = rsdk.Frame(0x02, 9, 0x1D, 0x04, rsdk.mode_switch(0x23)).encode()
        d = duml.Demux()
        got = d.feed(b"\x00" + a[:4]) + d.feed(a[4:] + b[:7]) + d.feed(b[7:])
        self.assertEqual([k for k, _ in got], ["duml", "rsdk"])
        self.assertEqual(rsdk.decode(got[1][1]).payload[4], 0x23)

    def test_status_push_and_wake_broadcast(self):
        st = bytearray(38)
        st[0], st[28], st[30], st[37] = 0x23, 3, 1, 64
        s = rsdk.parse_status(bytes(st))
        self.assertEqual((s["mode"], s["power_mode"], s["temperature"], s["battery"]),
                         ("uvc_webcam", "sleep", "warm", 64))
        cid, data = rsdk.wake_advertisement("11:22:33:44:55:66")
        self.assertEqual(cid.to_bytes(2, "little") + data, b"WKP" + bytes([0x66, 0x55, 0x44, 0x33, 0x22, 0x11]))


class ConfigTest(unittest.TestCase):
    def test_new_user_default_is_auto_without_unofficial(self):
        c = catalog.normalize(None)
        self.assertEqual((c["driver"], c["allow_unofficial"]), ("auto", False))
        self.assertEqual(catalog.control_chain(c), ["dji-ble-official"])

    def test_unofficial_needs_opt_in(self):
        with self.assertRaises(catalog.ConfigError) as cm:
            catalog.normalize({"driver": "dji-duml"})
        self.assertEqual(cm.exception.code, "unofficial_not_allowed")
        c = catalog.normalize({"driver": "dji-duml", "allow_unofficial": True})
        self.assertEqual(catalog.control_chain(c), ["dji-duml"])
        self.assertEqual(catalog.control_chain(catalog.normalize({"allow_unofficial": True})),
                         ["dji-ble-official", "dji-duml"])
        self.assertEqual(catalog.control_chain(catalog.normalize({"driver": "uvc", "allow_unofficial": True})), [])

    def test_unknown_keys_dropped_and_options_bounded(self):
        c = catalog.normalize({"driver": "uvc", "secret": "x", "ble": {"device": "Osmo", "addr": "x"},
                               "options": {"fps": 30}})
        self.assertNotIn("secret", c)
        self.assertEqual(c["ble"], {"device": "Osmo"})
        with self.assertRaises(catalog.ConfigError):
            catalog.normalize({"options": {"nested": {"a": 1}}})
        with self.assertRaises(catalog.ConfigError):
            catalog.normalize({"driver": "rtsp"})

    def test_catalog_texts_fit_the_shared_limits(self):
        for lang in ("zh", "en"):
            cat = catalog.catalog_for(lang)
            self.assertEqual([d["id"] for d in cat], list(catalog.DRIVER_IDS))
            for d in cat:
                for k in ("label", "does", "needs"):
                    self.assertLessEqual(len(d[k]), 120, (lang, d["id"], k))
            self.assertEqual([d["id"] for d in cat if d["unofficial"]], ["dji-duml"])

    def test_only_a_real_true_allows_the_unofficial_driver(self):
        for v in ("false", "true", 1, "yes", None):
            with self.assertRaises(catalog.ConfigError, msg=repr(v)):
                catalog.normalize({"driver": "dji-duml", "allow_unofficial": v})
            self.assertFalse(catalog.normalize({"allow_unofficial": v})["allow_unofficial"], repr(v))


class RecoveryTest(unittest.TestCase):
    """CameraManager -> BleBridge -> ble_helper.py (a real subprocess) -> fake camera."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.conf_path = os.path.join(self.dir, "fake.json")
        self.state_path = os.path.join(self.dir, "fake_state.json")
        self.old_env = {k: os.environ.get(k) for k in ("FAKE_DJI_CONF", "FAKE_DJI_STATE")}
        os.environ["FAKE_DJI_CONF"] = self.conf_path
        os.environ["FAKE_DJI_STATE"] = self.state_path
        self.managers = []

    def tearDown(self):
        for m in self.managers:
            m.shutdown()
        for k, v in self.old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def make(self, fake: dict, camera: dict | None = None, notes=None):
        with open(self.conf_path, "w") as f:
            json.dump(fake, f)
        with open(self.state_path, "w") as f:
            json.dump({"mode": fake.get("mode", 1)}, f)
        cfg = {"data_dir": os.path.join(self.dir, "data"), "camera": camera,
               "camera_host": {"uvc_wait_s": 3, "recover_after_s": 0}}
        events = Events()
        sent = notes if notes is not None else []
        bridge = BleBridge(python=sys.executable, extra_args=["--fake", FAKE])
        m = CameraManager(cfg, FakeVideo(self.state_path), events, notify=sent.append, bridge=bridge)
        self.managers.append(m)
        self.assertTrue(m.ble_available())
        return m, events, sent

    def fake_mode(self):
        with open(self.state_path) as f:
            return json.load(f)["mode"]

    def test_official_brings_the_webcam_back(self):
        m, events, sent = self.make({"rsdk_paired": True, "mode": 0x01})
        ok, detail = m.recover()
        self.assertTrue(ok, detail)
        self.assertEqual(self.fake_mode(), 0x23)
        st = m.status()
        self.assertEqual((st["control"], st["fallback"]), ("dji-ble-official", None))
        self.assertTrue(any("切回来" in s for s in sent))

    def test_falls_back_to_community_protocol_when_allowed(self):
        m, events, sent = self.make({"rsdk_paired": True, "duml_paired": True, "rsdk_uvc_ret": 2, "mode": 0x01},
                                    camera={"driver": "auto", "allow_unofficial": True})
        ok, detail = m.recover()
        self.assertTrue(ok, detail)
        self.assertEqual(self.fake_mode(), 0x23)
        st = m.status()
        self.assertEqual(st["control"], "dji-duml")
        self.assertIn("返回 2", st["fallback"])
        self.assertIn("社区逆向协议", st["fallback"])
        self.assertIn("返回 2", st["drivers"]["dji-ble-official"]["last_error"])

    def test_community_protocol_stays_out_unless_allowed(self):
        # same camera, same failure of the official command, but the user did not tick "allow"
        m, events, sent = self.make({"rsdk_paired": True, "duml_paired": True, "rsdk_uvc_ret": 2, "mode": 0x01})
        ok, detail = m.recover()
        self.assertFalse(ok)
        self.assertEqual(self.fake_mode(), 0x01, "the community protocol must not have switched the camera")
        self.assertNotIn("dji-duml", [e.get("driver") for e in events.items])
        self.assertTrue(m.gave_up)
        self.assertIn("返回 2", m.last_failure)

    def test_unpaired_camera_needs_a_tap_and_says_so(self):
        m, events, sent = self.make({"mode": 0x01})  # nobody taps
        ok, detail = m.recover()
        self.assertFalse(ok)
        self.assertIn("点一次允许", detail)
        self.assertEqual(self.fake_mode(), 0x01)
        # pairing from the settings page, with someone tapping the prompt
        with open(self.conf_path, "w") as f:
            json.dump({"tap": True, "mode": 0x01}, f)
        m.bridge.stop()  # the fake camera re-reads its conf on start
        ok, detail = m.action("pair")
        self.assertTrue(ok, detail)
        self.assertTrue(m.detail_status()["paired"]["dji-ble-official"])
        ok, detail = m.action("recover")
        self.assertTrue(ok, detail)

    def test_asleep_camera_is_woken_first(self):
        m, events, sent = self.make({"rsdk_paired": True, "sleeping": True, "mode": 0x01})
        m.remember(addr=FAKE_ADDR)
        ok, detail = m.recover()
        self.assertTrue(ok, detail)
        self.assertIn("wake", [e.get("step") for e in events.items])

    def test_unpaired_community_protocol_needs_a_tap_too(self):
        m, events, sent = self.make({"rsdk_paired": True, "rsdk_uvc_ret": 2, "mode": 0x01},
                                    camera={"allow_unofficial": True})
        ok, detail = m.recover()
        self.assertFalse(ok)
        self.assertEqual(m.errors["dji-duml"].key, "duml_need_tap")
        self.assertEqual(self.fake_mode(), 0x01)

    def test_a_late_answer_from_another_module_is_not_taken(self):
        m, events, sent = self.make({"rsdk_paired": True, "rsdk_uvc_ret": 2, "duml_paired": True,
                                     "duml_late_01": True, "mode": 0x01}, camera={"allow_unofficial": True})
        ok, detail = m.recover()
        self.assertFalse(ok)
        self.assertEqual(m.errors["dji-duml"].key, "duml_uvc_refused")

    def test_failures_never_carry_the_address(self):
        m, events, sent = self.make({"found": False, "mode": 0x01})
        m.remember(addr=FAKE_ADDR)
        ok, detail = m.recover()
        self.assertFalse(ok)
        self.assertIn("wake", [e.get("step") for e in events.items])
        text = json.dumps([m.status(), m.detail_status(), events.items, detail], ensure_ascii=False)
        self.assertNotIn(FAKE_ADDR, text)
        self.assertEqual(m.errors["dji-ble-official"].key, "not_found")

    def test_the_helper_refuses_to_guess_between_cameras(self):
        m, events, sent = self.make({"rsdk_paired": True, "extra_cameras": 1, "mode": 0x01})
        ok, detail = m.recover()
        self.assertFalse(ok)
        self.assertEqual(m.errors["dji-ble-official"].key, "several_cameras")
        self.assertIsNone(m.ble_state.get("addr"))
        self.assertEqual(self.fake_mode(), 0x01)

    def test_choice_is_saved_private_and_validated(self):
        m, events, sent = self.make({"rsdk_paired": True})
        ok, code, msg = m.set_config({"driver": "dji-duml"})
        self.assertEqual((ok, code), (False, "unofficial_not_allowed"))
        ok, code, msg = m.set_config({"driver": "dji-duml", "allow_unofficial": True})
        self.assertTrue(ok, msg)
        mode = stat.S_IMODE(os.stat(m.choice_path).st_mode)
        self.assertEqual(mode, 0o600)
        m2, _, _ = self.make({"rsdk_paired": True})
        self.assertEqual(m2.config["driver"], "dji-duml")

    def test_status_never_carries_the_address(self):
        m, events, sent = self.make({"rsdk_paired": True, "mode": 0x01})
        m.recover()
        self.assertEqual(m.ble_state.get("addr"), FAKE_ADDR)
        text = json.dumps([m.status(), m.detail_status(), events.items], ensure_ascii=False)
        self.assertNotIn(FAKE_ADDR, text)
        self.assertNotIn(m.ble_state["sender_mac"], text)


class StubBridge:
    def __init__(self, check=(True,), raise_on=None):
        self.checks = list(check)
        self.raise_on = raise_on
        self.calls = []

    def call(self, cmd, timeout=30, **kw):
        self.calls.append(cmd)
        if cmd == self.raise_on:
            from room_companion.camera.bridge import BridgeError
            raise BridgeError("cannot start the Bluetooth helper: /mnt/c/Users/SOMEONE/room/python.exe")
        if cmd == "check":
            return {"ok": self.checks.pop(0) if len(self.checks) > 1 else self.checks[0]}
        return {"ok": False, "error": "not_found"}

    def stop(self):
        pass


class ManagerRulesTest(unittest.TestCase):
    def make(self, bridge, camera=None, clock=None):
        d = tempfile.mkdtemp()
        video = FakeVideo(os.path.join(d, "none.json"))
        kw = {"monotonic": clock} if clock else {}
        return CameraManager({"data_dir": d, "camera": camera, "camera_host": {"uvc_wait_s": 0}}, video, Events(),
                             bridge=bridge, sleep=lambda s: None, **kw)

    def test_withdrawn_permission_stops_the_community_protocol_mid_recovery(self):
        m = self.make(StubBridge(), camera={"allow_unofficial": True})
        self.assertTrue(m.ble_available())
        ran = []

        def official():
            ran.append("official")
            ok, code, msg = m.set_config({"allow_unofficial": False})  # the user unticks it meanwhile
            ran.append(("set", ok))
            raise __import__("room_companion.camera.manager", fromlist=["x"]).StepFailed("rsdk_uvc_refused", ret=2)
        m.drivers["dji-ble-official"].recover = official
        m.drivers["dji-duml"].recover = lambda: ran.append("duml RAN")
        ok, detail = m.recover()
        self.assertFalse(ok)
        self.assertEqual(ran, ["official", ("set", True)])

    def test_a_failed_helper_check_is_retried_and_its_text_stays_local(self):
        now = [1000.0]
        b = StubBridge(raise_on="check")
        m = self.make(b, clock=lambda: now[0])
        self.assertFalse(m.ble_available())
        st = json.dumps(m.status(), ensure_ascii=False)
        self.assertNotIn("SOMEONE", st)
        self.assertNotIn("{", m.status()["drivers"]["dji-ble-official"]["last_error"])
        self.assertIn("SOMEONE", json.dumps(m.events.items))  # the local event log keeps the detail
        b.raise_on = None
        self.assertFalse(m.ble_available())   # within a minute: not asked again
        now[0] += 61
        self.assertTrue(m.ble_available())
        self.assertEqual(b.calls.count("check"), 1 + 1)  # the raising call is recorded before it raises

    def test_a_choice_is_accepted_while_the_check_is_still_unknown(self):
        m = self.make(StubBridge(check=(False,)))
        ok, code, msg = m.set_config({"driver": "dji-ble-official"})
        self.assertTrue(ok, msg)
        m._ble_ok, m._ble_checked_at = False, m.monotonic()
        ok, code, msg = m.set_config({"driver": "dji-ble-official"})
        self.assertEqual(code, "driver_unavailable")

    def test_tick_does_not_start_a_second_job(self):
        m = self.make(StubBridge())
        self.assertTrue(m.ble_available())
        m.video.waiting_since = 1.0
        started = []
        m._recover_bg = lambda: started.append(1)
        m.busy = "pair"
        m.tick(10_000.0)
        self.assertEqual((started, m.busy), ([], "pair"))
        m.busy = None
        m.tick(10_000.0)
        time.sleep(0.2)
        self.assertEqual(started, [1])


class TickTest(unittest.TestCase):
    def test_waits_for_the_webcam_to_be_missing_then_backs_off(self):
        class StubBridge:
            def call(self, cmd, timeout=30, **kw):
                return {"ok": cmd == "check"} if cmd == "check" else {"ok": False, "error": "not_found"}

            def stop(self):
                pass

        d = tempfile.mkdtemp()
        video = FakeVideo(os.path.join(d, "none.json"))
        video.waiting_since = 1000.0
        m = CameraManager({"data_dir": d, "camera_host": {"recover_after_s": 20, "uvc_wait_s": 0}}, video, Events(),
                          bridge=StubBridge(), sleep=lambda s: None)
        self.assertTrue(m.ble_available())
        m.tick(1010.0)
        self.assertIsNone(m.busy)             # missing for only 10 s
        m.recover()                           # what the background thread would run
        self.assertTrue(m.gave_up)
        self.assertGreater(m.next_try_at, 0)
        first_backoff = m.backoff
        m.recover()
        self.assertGreater(m.backoff, first_backoff)
        video.state = "running"
        m.tick(5000.0)
        self.assertFalse(m.gave_up)
        self.assertEqual(m.backoff, 60.0)



class SharedSchemaTest(unittest.TestCase):
    """What a remote settings page gets: hello.device.camera_drivers and state.camera."""

    def test_state_camera_is_whitelisted(self):
        from room_companion import hipimind as hm
        cam = {"driver": "auto", "active": "uvc", "control": "dji-ble-official", "fallback": "x" * 500,
               "state": "running", "name": "Osmo Action 5 Pro", "detail": None, "addr": FAKE_ADDR,
               "drivers": {"uvc": {"available": True, "last_error": None, "addr": FAKE_ADDR},
                           "dji-duml": {"available": "yes", "last_error": 7}, "evil": {"available": True}}}
        out = hm.map_state({"switches": {}, "camera": cam})["camera"]
        self.assertNotIn(FAKE_ADDR, json.dumps(out))
        self.assertEqual(set(out), {"driver", "active", "control", "fallback", "state", "name", "detail", "drivers"})
        self.assertEqual(len(out["fallback"]), 200)
        self.assertEqual(set(out["drivers"]), {"uvc", "dji-duml"})
        self.assertEqual(out["drivers"]["dji-duml"], {"available": False, "last_error": None})
        bad = hm.map_state({"switches": {}, "camera": {"driver": "rtsp", "state": "weird", "control": "x"}})["camera"]
        self.assertEqual((bad["driver"], bad["state"], bad["control"]), ("auto", "error", None))

    def test_hello_driver_list(self):
        from room_companion import hipimind as hm

        class Dev:
            def camera_drivers(self):
                return catalog.catalog_for("en") + [{"id": "bogus", "label": "x"}]
        got = hm.camera_drivers(Dev())
        self.assertEqual([d["id"] for d in got], ["auto", "uvc", "dji-ble-official", "dji-duml"])
        self.assertTrue(all(len(d[k]) <= 120 for d in got for k in ("label", "does", "needs")))
        self.assertEqual([d["id"] for d in got if d["unofficial"]], ["dji-duml"])

    def test_status_in_english_and_never_capture_output(self):
        d = tempfile.mkdtemp()
        video = FakeVideo(os.path.join(d, "none.json"))
        video.state, video.detail = "error", "SENTINEL ffmpeg: Could not run graph"
        video.device = type("D", (), {"name": "SENTINEL-CAM"})()
        m = CameraManager({"data_dir": d}, video, Events(), bridge=type("B", (), {"call": lambda *a, **k: {"ok": False}, "stop": lambda s: None})())
        m.lang = lambda: "en"
        st = m.status()
        self.assertNotIn("SENTINEL", json.dumps(st))
        self.assertIn("failed", st["detail"])
        ok, code, msg = m.set_config({"driver": "dji-duml"})
        self.assertEqual(code, "unofficial_not_allowed")
        self.assertIn("not supported by DJI", msg)


class TapReminderTest(unittest.TestCase):
    """The "please tap Webcam" message waits until the Bluetooth drivers have had their go."""

    def test_reminder_waits_for_the_drivers_then_says_what_was_tried(self):
        from room_companion.app import App
        from tests.test_pipelines import FakeNotifier
        from room_companion.app import DEFAULTS
        d = tempfile.mkdtemp()
        notifier = FakeNotifier()
        video = FakeVideo(os.path.join(d, "none.json"))
        video.waiting_since = 1000.0
        cam = CameraManager({"data_dir": d}, video, Events(), bridge=StubBridge(), sleep=lambda s: None)
        app = App(dict(DEFAULTS, data_dir=d, port=0), video=video, audio=object(), notifier=notifier, camera=cam)
        app.switches.set({"video": True}, "t")
        self.assertTrue(cam.ble_available())
        app._camera_tap_check(1000.0 + 600)
        self.assertEqual([m for m in notifier.messages if "网络摄像头" in m], [], "asked a person before the drivers tried")
        cam.recover()  # the official driver cannot find the camera
        self.assertTrue(cam.gave_up)
        app._camera_tap_check(1000.0 + 600)
        msgs = [m for m in notifier.messages if "网络摄像头" in m]
        self.assertEqual(len(msgs), 1)
        self.assertIn("已经试过自动切回", msgs[0])
        self.assertIn("蓝牙找不到相机", msgs[0])


class ActionBudgetTest(unittest.TestCase):
    """A remote page waits 95 s for an action; the device must answer well inside that."""

    def make(self, camera=None):
        now = [0.0]
        d = tempfile.mkdtemp()
        video = FakeVideo(os.path.join(d, "none.json"))
        m = CameraManager({"data_dir": d, "camera": camera}, video, Events(), bridge=StubBridge(),
                          sleep=lambda s: now.__setitem__(0, now[0] + s), monotonic=lambda: now[0])
        self.assertTrue(m.ble_available())
        return m, now

    def test_recover_stops_before_the_page_gives_up(self):
        m, now = self.make(camera={"allow_unofficial": True})
        from room_companion.camera.manager import StepFailed

        def slow():
            now[0] += 60  # a slow official attempt: scan, wake, scan again
            raise StepFailed("rsdk_uvc_refused", ret=2)
        ran = []
        m.drivers["dji-ble-official"].recover = slow
        m.drivers["dji-duml"].recover = lambda: ran.append("duml")
        ok, detail = m.action("recover")
        self.assertFalse(ok)
        self.assertEqual(ran, [])
        self.assertLess(now[0], 90)
        self.assertIn("没时间", detail)

    def test_pair_wait_shrinks_to_fit(self):
        m, now = self.make(camera={"allow_unofficial": True})
        waits = []

        def pair(wait):
            waits.append(wait)
            now[0] += 22 + wait  # nobody taps
            from room_companion.camera.manager import StepFailed
            if len(waits) == 1:
                return  # the official one got its tap
            raise StepFailed("duml_need_tap")
        m.drivers["dji-ble-official"].pair = pair
        m.drivers["dji-duml"].pair = pair
        ok, detail = m.action("pair")
        self.assertEqual(waits[0], 25.0)
        self.assertLessEqual(waits[1], 85 - 47 - 22)
        self.assertLess(now[0], 90)

    def test_a_second_action_while_busy_is_refused(self):
        m, now = self.make()
        m.busy = "recover"
        ok, detail = m.action("pair")
        self.assertFalse(ok)
        self.assertIn("正在忙", detail)
        self.assertEqual(m.busy, "recover")

    def hung(self, check_s=0.0, addr=True):
        now = [0.0]
        d = tempfile.mkdtemp()
        b = HungHelper(now, check_s)
        m = CameraManager({"data_dir": d, "camera": {"allow_unofficial": True}}, FakeVideo(os.path.join(d, "x")),
                          Events(), bridge=b, sleep=lambda s: now.__setitem__(0, now[0] + s), monotonic=lambda: now[0])
        if addr:
            m.remember(addr=FAKE_ADDR)
        return m, b, now

    def test_a_hanging_helper_cannot_hold_an_action_past_the_budget(self):
        # the real drivers this time: a slow helper check, then every request hangs until its timeout
        for addr in (True, False):
            for action in ("recover", "pair"):
                m, b, now = self.hung(check_s=40, addr=addr)
                ok, detail = m.action(action)
                self.assertFalse(ok)
                self.assertLessEqual(now[0], 85, (addr, action, b.calls))
                self.assertIsNone(m.deadline)

    def test_a_helper_stopped_inside_an_action_is_not_started_again_there(self):
        m, b, now = self.hung()
        m.action("recover")                   # the first connect hangs and the helper is stopped
        self.assertNotIn("start", b.calls)
        self.assertLessEqual(now[0], 85)

    def test_the_next_action_starts_a_stopped_helper_in_its_check(self):
        m, b, now = self.hung()
        m.action("pair")
        self.assertFalse(b.running)
        b.answers = True                      # the camera is back
        ok, detail = m.action("pair")
        self.assertTrue(ok, detail)
        self.assertEqual(b.calls.count("start"), 1)


class HungHelper:
    """Like BleBridge over a Bluetooth stack that hangs: each request runs into its timeout, which stops the
    helper, and the next request starts it again (up to 20 s). With `answers` the camera answers."""

    def __init__(self, now, check_s=0.0):
        self.now, self.check_s, self.answers = now, check_s, False
        self.running, self.calls = True, []

    def call(self, cmd, timeout=30, **kw):
        if not self.running:
            self.now[0] += 20
            self.running = True
            self.calls.append("start")
        self.calls.append(cmd)
        if cmd == "check":
            self.now[0] += min(timeout, self.check_s)
            return {"ok": True}
        if self.answers:
            return {"ok": True, "addr": kw.get("addr") or FAKE_ADDR, "model": "Osmo Action 5 Pro"}
        self.now[0] += timeout
        self.running = False
        return {"ok": False, "error": "timeout"}

    def stop(self):
        self.running = False


class RecordingBridge(StubBridge):
    def __init__(self, connect_ok=False, addr=None, handshake_ok=False, count=1):
        super().__init__()
        self.kw = []
        self.connect_ok, self.addr, self.handshake_ok, self.count = connect_ok, addr, handshake_ok, count

    def call(self, cmd, timeout=30, **kw):
        self.kw.append((cmd, kw))
        if cmd == "connect" and self.connect_ok:
            if kw.get("unique") and self.count > 1:
                return {"ok": False, "error": "several", "count": self.count}
            return {"ok": True, "addr": kw.get("addr") or self.addr}
        if cmd == "rsdk_connect":
            return {"ok": True, "model": "Osmo Action 5 Pro"} if self.handshake_ok else {"ok": False, "error": "no_tap"}
        if cmd in ("disconnect", "wake_adv"):
            return {"ok": True}
        return super().call(cmd, timeout, **kw)


class CameraIdentityTest(unittest.TestCase):
    """Which camera is ours: never one that merely answered a scan."""

    def make(self, bridge, clock=time.time, camera=None):
        d = tempfile.mkdtemp()
        video = FakeVideo(os.path.join(d, "none.json"))
        video.waiting_since = 1.0
        m = CameraManager({"data_dir": d, "camera": camera, "camera_host": {"uvc_wait_s": 0}}, video, Events(),
                          bridge=bridge, clock=clock, sleep=lambda s: None)
        self.assertTrue(m.ble_available())
        return m

    def test_tick_waits_out_the_back_off_after_a_failed_round(self):
        now = [10_000.0]
        m = self.make(StubBridge(), clock=lambda: now[0])
        started = []
        m._recover_bg = lambda: (started.append(1), setattr(m, "busy", None))
        ok, _ = m.recover()                # every allowed driver fails: next round in 60 s
        self.assertFalse(ok)
        m.tick(now[0] + 30)
        time.sleep(0.2)
        self.assertEqual(started, [], "a new round started inside the back-off")
        m.tick(now[0] + 61)
        time.sleep(0.2)
        self.assertEqual(started, [1])

    def test_a_remembered_camera_is_connected_by_its_address(self):
        b = RecordingBridge()
        m = self.make(b)
        m.remember(addr=FAKE_ADDR)
        m.recover()
        connects = [kw for cmd, kw in b.kw if cmd == "connect"]
        self.assertEqual(connects[0].get("addr"), FAKE_ADDR, "scanned instead of using the remembered camera")
        # asleep: after the wake broadcast it reconnects to that same camera, never by a scan
        self.assertEqual([c.get("addr") for c in connects], [FAKE_ADDR, FAKE_ADDR])

    def test_a_failed_handshake_leaves_the_saved_camera_alone(self):
        other = "aa:bb:cc:dd:ee:ff"
        b = RecordingBridge(connect_ok=True, addr=other, handshake_ok=False)
        m = self.make(b)
        ok, _ = m.recover()              # a new camera answers the scan but refuses the handshake
        self.assertFalse(ok)
        self.assertIsNone(m.ble_state.get("addr"))
        b.handshake_ok = True
        m.recover()
        self.assertEqual(m.ble_state.get("addr"), other)  # saved once it answered the handshake

    def test_several_cameras_nearby_are_not_guessed_between(self):
        b = RecordingBridge(connect_ok=True, addr="aa:bb:cc:dd:ee:ff", handshake_ok=True, count=2)
        m = self.make(b)
        ok, detail = m.recover()
        self.assertFalse(ok)
        self.assertIn("2 台", detail)
        self.assertNotIn("rsdk_connect", [c for c, _ in b.kw])
        self.assertIsNone(m.ble_state.get("addr"))
        # naming the camera in the settings picks it
        m2 = self.make(b, camera={"ble": {"device": "OsmoAction5ProFAKE"}})
        m2.recover()
        named = [kw for cmd, kw in b.kw if cmd == "connect"][-1]
        self.assertEqual((named.get("name"), named.get("unique")), ("OsmoAction5ProFAKE", False))

    def test_pointing_at_another_camera_forgets_the_old_one(self):
        m = self.make(StubBridge())
        m.remember(addr=FAKE_ADDR)
        ok, code, msg = m.set_config({"ble": {"device": "OsmoAction5ProOTHER"}})
        self.assertTrue(ok, msg)
        self.assertIsNone(m.ble_state.get("addr"))

    def test_the_action_budget_includes_the_helper_check(self):
        now = [0.0]

        class SlowCheck(StubBridge):
            def call(self, cmd, timeout=30, **kw):
                if cmd == "check":
                    now[0] += min(timeout, 40)
                return super().call(cmd, timeout, **kw)
        d = tempfile.mkdtemp()
        m = CameraManager({"data_dir": d, "camera": {"allow_unofficial": True}}, FakeVideo(os.path.join(d, "x")),
                          Events(), bridge=SlowCheck(), sleep=lambda s: now.__setitem__(0, now[0] + s),
                          monotonic=lambda: now[0])
        from room_companion.camera.manager import StepFailed

        def slow():
            now[0] += 60
            raise StepFailed("rsdk_uvc_refused", ret=2)
        m.drivers["dji-ble-official"].recover = slow
        m.drivers["dji-duml"].recover = lambda: None
        m.action("recover")
        self.assertLess(now[0], 90)


class CameraWebTest(unittest.TestCase):
    """The camera routes behind the web server's own checks (Host, Origin, Sec-Fetch-Site, header, JSON)."""
    from tests.test_pipelines import WebTest as _W
    setUp, tearDown, req, raw = _W.setUp, _W.tearDown, _W.req, _W.raw

    def use_camera(self):
        self.bridge = RecordingBridge()
        d = self.app.cfg["data_dir"]
        self.app.camera = CameraManager(dict(self.app.cfg), FakeVideo(os.path.join(d, "none.json")), Events(),
                                        bridge=self.bridge, sleep=lambda s: None)
        self.assertTrue(self.app.camera.ble_available())
        self.bridge.kw.clear()

    def test_cross_site_post_cannot_turn_on_the_community_protocol(self):
        self.use_camera()
        form = {"Content-Type": "text/plain", "Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"}
        code, _ = self.raw("/api/camera", b'{"driver":"dji-duml","allow_unofficial":true,"x":"="}', form)
        self.assertEqual(code, 403)
        self.assertEqual((self.app.camera.config["driver"], self.app.camera.config["allow_unofficial"]), ("auto", False))
        self.assertFalse(os.path.exists(self.app.camera.choice_path))

    def test_cross_site_post_cannot_start_pairing(self):
        self.use_camera()
        form = {"Content-Type": "text/plain", "Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"}
        self.assertEqual(self.raw("/api/camera/action", b'{"action":"pair","x":"="}', form)[0], 403)
        self.assertEqual(self.bridge.kw, [], "the Bluetooth helper was called")

    def test_rebinding_cannot_read_the_camera_settings(self):
        self.use_camera()
        self.assertEqual(self.req("/api/camera", headers={"Host": "evil.example:8790"})[0], 403)
        code, body = self.req("/api/camera", headers={"Host": f"127.0.0.1:{self.port}"})
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["status"]["driver"], "auto")

    def test_own_page_can_still_choose_and_act(self):
        self.use_camera()
        own = {"X-Room-AI": "1", "Origin": f"http://127.0.0.1:{self.port}"}
        code, body = self.req("/api/camera", {"driver": "dji-duml", "allow_unofficial": True}, headers=own)
        self.assertEqual(code, 200, body)
        self.assertEqual(self.app.camera.config["driver"], "dji-duml")
        code, body = self.req("/api/camera/action", {"action": "pair"}, headers=own)
        self.assertIn("connect", [c for c, _ in self.bridge.kw])


class BridgeInteropTest(unittest.TestCase):
    def test_windows_python_retries_on_another_interop_channel(self):
        from room_companion.camera.bridge import BleBridge, BridgeError
        d = tempfile.mkdtemp()

        class Interop:
            calls = []

            def ensure(self, force=False):
                self.calls.append(force)
                return True
        tries = []

        def popen(cmd, **kw):
            tries.append(cmd[0])
            if len(tries) == 1:
                raise OSError(22, "Invalid argument")  # what a broken channel looks like
            return __import__("subprocess").Popen([sys.executable, "-u", os.path.join(HERE, "..", "room_companion", "camera", "ble_helper.py"),
                                                   "--fake", FAKE], stdin=-1, stdout=-1, stderr=-1)
        conf = os.path.join(d, "c.json")
        with open(conf, "w") as f:
            json.dump({}, f)
        old = os.environ.get("FAKE_DJI_CONF")
        os.environ["FAKE_DJI_CONF"] = conf
        try:
            ip = Interop()
            b = BleBridge(python="/mnt/c/x/python.exe", helper_dir=os.path.join(d, "mnt", "c", "h"), popen=popen, interop=ip)
            b._script = lambda: "C:\\h\\ble_helper.py"
            self.assertEqual(b.start().get("ev"), "ready")
            self.assertEqual(ip.calls, [False, True])
            self.assertEqual(len(tries), 2)
            b.stop()
        finally:
            if old is None:
                os.environ.pop("FAKE_DJI_CONF", None)
            else:
                os.environ["FAKE_DJI_CONF"] = old


if __name__ == "__main__":
    unittest.main()
