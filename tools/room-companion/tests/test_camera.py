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
    def test_official_frame_matches_dji_example(self):
        # DJI's published example: switch to Hyperlapse, sequence 5
        want = bytes.fromhex("aa1b00010000000005" "0057ee1d04000033ff0a01473936f4fae1d0")
        self.assertEqual(rsdk.Frame(0x01, 5, 0x1D, 0x04, rsdk.mode_switch(0x0A)).encode(), want)
        f = rsdk.decode(want)
        self.assertEqual((f.cmd_set, f.cmd_id, f.seq), (0x1D, 0x04, 5))
        with self.assertRaises(ValueError):
            rsdk.decode(want[:-1] + b"\x00")

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
        ids = [d["id"] for d in catalog.CATALOG]
        self.assertEqual(ids, list(catalog.DRIVER_IDS))
        for d in catalog.CATALOG:
            for k in ("label", "does", "needs"):
                self.assertLessEqual(len(d[k]), 120, (d["id"], k))
        self.assertEqual([d["id"] for d in catalog.CATALOG if d["unofficial"]], ["dji-duml"])


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


if __name__ == "__main__":
    unittest.main()
