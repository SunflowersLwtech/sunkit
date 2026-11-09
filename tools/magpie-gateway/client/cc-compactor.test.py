#!/usr/bin/env python3
"""Tests for cc-compactor.py: seat readings, the wait / compact / handoff scoring, config, compaction."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
import os
import tempfile
import time
import tomllib
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parent / "cc-compactor.py"
TOML_PATH = Path(__file__).resolve().parent / "cc-compactor.toml"
spec = importlib.util.spec_from_file_location("cc_compactor", MODULE_PATH)
assert spec and spec.loader
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)

NOW = cc.parse_iso_ts("2026-11-03T10:40:00Z")  # 18:40 in Asia/Shanghai
GW_ENV = ("ANTHROPIC_BASE_URL", "ANTHROPIC_CUSTOM_HEADERS", "ANTHROPIC_API_KEY")


def at(offset_sec: float) -> str:
    return cc.iso(NOW + offset_sec)


def card(user, plan="team", five=None, five_reset=None, week=None, week_reset=None, fable_first=True, **extra):
    windows = []
    if five is not None:
        windows.append({"name": "5 hours", "used": five, "remaining": 100 - five, "resetsAt": at(five_reset) if five_reset else None})
    fable = {"name": "7 days · Fable", "used": 0, "remaining": 100, "resetsAt": at(4 * 86400)}
    if fable_first:
        windows.append(fable)
    if week is not None:
        windows.append({"name": "7 days", "used": week, "remaining": 100 - week, "resetsAt": at(week_reset or 4 * 86400)})
    if not fable_first:
        windows.append(fable)
    return {"provider": "claude", "kind": "subscription", "plan": plan, "user": user, "windows": windows, **extra}


def pool_card(provider, used, reset=None):
    return {"provider": provider, "kind": "subscription", "user": f"{provider}-acct",
            "windows": [{"name": "7 days", "used": used, "resetsAt": at(reset) if reset else None}]}


POOLS = [pool_card("zcode", 90), pool_card("devin", 92), pool_card("grok", 90), pool_card("copilot", 0)]
QUOTAS = {
    "room": [
        card("seat1@x.com · DuoCode", five=14, five_reset=3 * 3600, week=34),
        card("seat2@x.com · DuoCode", five=98, five_reset=40 * 60, week=33),
        card("seat3@x.com · DuoCode", five=97, five_reset=3 * 3600 + 3000, week=41),
        card("seat2@x.com", plan="max", week=100, week_reset=6 * 86400),
        *POOLS,
    ],
    "full": [
        card("seat1@x.com · DuoCode", five=96, five_reset=25 * 60, week=34),
        card("seat2@x.com · DuoCode", five=50, five_reset=2 * 3600, week=100, week_reset=2 * 86400),
        card("seat3@x.com · DuoCode", five=100, five_reset=3 * 3600, week=41),
        card("seat2@x.com", plan="max", week=100, week_reset=6 * 86400),
        *POOLS,
    ],
}

GW_STOP = "API Error: Request rejected (429) · Claude Code: You've hit your session limit · resets 9:50pm (Asia/Shanghai)"
DEVIN_STOP = "API Error: Request rejected (429) · Devin: usage limit reached: Your weekly usage quota has been exhausted."


def rec(kind, uuid_, ts, content, usage=None, **extra):
    msg = {"role": kind, "content": content}
    if usage:
        msg["usage"] = usage
    return {"type": kind, "uuid": uuid_, "timestamp": cc.iso(ts), "sessionId": "s", "cwd": extra.pop("cwd", "/tmp/demo"),
            "version": "2.1.316", "gitBranch": "feat/x", "slug": "demo", "message": msg, **extra}


def usage_for(tokens):
    return {"input_tokens": 100, "cache_creation_input_tokens": 2000, "cache_read_input_tokens": tokens - 2900, "output_tokens": 800}


def write_session(path: Path, tokens: int, stop_text: str | None, stop_at: float, cache_at: float, cwd: str = "/tmp/demo",
                  tail_chars: int = 0) -> Path:
    """A session with every kind of record the digest, the excerpts and the tail read: a Read result, a
    passing and a failing test log, a todo list; then `tail_chars`-long turns; then the limit message."""
    t0 = stop_at - 3600
    r = [
        rec("user", "u0", t0, "Make the router pick a seat by remaining allowance.", cwd=cwd),
        rec("assistant", "a0", t0 + 60, [
            {"type": "tool_use", "id": "t_read", "name": "Read", "input": {"file_path": "/tmp/demo/src/router.py"}},
            {"type": "tool_use", "id": "t_todo", "name": "TodoWrite", "input": {"todos": [
                {"content": "rewrite pick_seat", "status": "in_progress"}, {"content": "add tests", "status": "pending"}]}},
        ], usage_for(tokens // 2), cwd=cwd),
        rec("user", "u1", t0 + 61, [
            {"type": "tool_result", "tool_use_id": "t_read", "content": "def pick_seat():\n    SECRETFILEBODY\n" * 40},
            {"type": "tool_result", "tool_use_id": "t_todo", "content": "Todos updated"},
        ], cwd=cwd),
        rec("assistant", "a1", t0 + 120, [
            {"type": "tool_use", "id": "t_edit", "name": "Edit", "input": {"file_path": "/tmp/demo/src/router.py", "old_string": "a", "new_string": "b"}},
            {"type": "tool_use", "id": "t_ok", "name": "Bash", "input": {"command": "pytest tests/test_ok.py -q"}},
            {"type": "tool_use", "id": "t_bad", "name": "Bash", "input": {"command": "pytest tests/test_router.py -q"}},
        ], usage_for(tokens - 20000), cwd=cwd),
        rec("user", "u2", t0 + 121, [
            {"type": "tool_result", "tool_use_id": "t_edit", "content": "Updated /tmp/demo/src/router.py"},
            {"type": "tool_result", "tool_use_id": "t_ok", "content": "collected 12 items\nPASSINGLOGBODY\n12 passed in 0.31s"},
            {"type": "tool_result", "tool_use_id": "t_bad", "is_error": True,
             "content": "FAILED tests/test_router.py::test_cap\nAssertionError: expected cap 95 in tests/test_router.py:42"},
        ], cwd=cwd),
        rec("assistant", "a2", t0 + 180, [{"type": "text", "text": "Decided: the cap follows accountCaps."}], cwd=cwd),
    ]
    for i in range(12):
        r.append(rec("user" if i % 2 == 0 else "assistant", f"m{i}", t0 + 200 + i, [{"type": "text", "text": f"middle turn {i} " + "x" * 200}], cwd=cwd))
    for i in range(10):
        kind = "user" if i % 2 == 0 else "assistant"
        u = usage_for(tokens) if (kind == "assistant" and i == 9) else None
        r.append(rec(kind, f"tail{i}", cache_at if i == 9 else t0 + 400 + i, [{"type": "text", "text": f"tail {i} " + "y" * tail_chars}], u, cwd=cwd))
    if stop_text:
        r.append(rec("assistant", "stop", stop_at, [{"type": "text", "text": stop_text}], {"input_tokens": 0, "output_tokens": 0},
                     isApiErrorMessage=True, error="rate_limit", apiErrorStatus=429, cwd=cwd))
    path.write_text("\n".join(json.dumps(x) for x in r) + "\n", encoding="utf-8")
    last = stop_at if stop_text else NOW - 30
    os.utime(path, (last, last))
    return path


def quotas(cfg, name):
    return cc.fetch_magpie_quotas(cfg, now_ts=NOW, mock_payload={"data": QUOTAS[name]})


def leaves(d, path=()):
    for k, v in d.items():
        if isinstance(v, dict) and v:
            yield from leaves(v, path + (k,))
        elif not isinstance(v, dict):
            yield path + (k,), v


def get_in(d, path):
    for k in path:
        d = d[k]
    return d


def set_in(d, path, value):
    for k in path[:-1]:
        d = d[k]
    d[path[-1]] = value


def perturb(v):
    if isinstance(v, bool):
        return not v
    if isinstance(v, (int, float)):
        return v * 3 + 1
    if isinstance(v, str):
        return v + "_x"
    if isinstance(v, list):
        return v[:-1]
    raise TypeError(v)


class Rig:
    """Everything the config reaches, in one temporary directory: sessions, settings, sign-in, state."""

    def __init__(self, tmp: str):
        self.tmp = Path(tmp)
        (self.tmp / "repo").mkdir()
        self.settings = self.tmp / "magpie-settings.json"
        self.settings.write_text(json.dumps({"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:9"}}), encoding="utf-8")
        self.claude_json = self.tmp / "claude.json"
        self.claude_json.write_text(json.dumps({"oauthAccount": {"emailAddress": "seat3@x.com"}}), encoding="utf-8")
        cwd = str(self.tmp / "repo")
        self.sessions = {
            "big": write_session(self.tmp / "big.jsonl", 600000, GW_STOP, NOW - 300, NOW - 300, cwd, tail_chars=21000),
            "huge": write_session(self.tmp / "huge.jsonl", 1200000, DEVIN_STOP, NOW - 7200, NOW - 7200, cwd),
            "small": write_session(self.tmp / "small.jsonl", 50000, None, NOW - 1200, NOW - 1200, cwd),
        }

    def base_cfg(self):
        return cc.deep_merge(cc.load_config(str(TOML_PATH)), {"general": {
            "magpie_settings_path": str(self.settings),
            "claude_json_path": str(self.claude_json),
            "state_dir": str(self.tmp / "state"),
        }})

    def observe(self, cfg) -> dict:
        out: dict = {}

        def score(tag, t, q, c, **kw):
            try:
                d = cc.evaluate_actions(t, q, c, now_ts=NOW, login="seat3@x.com", **kw)
                out[tag] = [(r["action"], r["score"], r["dims"], r["minutes"], r["spend_pct"]) for r in d["ranked_actions"]]
            except SystemExit as e:
                out[tag] = f"exit: {e}"

        t_states = {n: cc.analyze_transcript(p, now_ts=NOW, cfg=cfg) for n, p in self.sessions.items()}
        qs = {n: quotas(cfg, n) for n in QUOTAS}
        qs["unreachable"] = cc.read_quotas(cfg, NOW, None, "test")
        out["seats"] = {n: (q["healthy"], q["counted"], [(s["user"], s["healthy"], s["headroom_5h"], s["headroom_7d"]) for s in q["seats"]])
                        for n, q in qs.items()}
        for sn, t in t_states.items():
            for qn, q in qs.items():
                for route in ("auto", "gateway", "seat"):
                    score(f"{sn}/{qn}/{route}", t, q, cfg, route=route)
                for urg in ("high", "normal", "low"):
                    score(f"{sn}/{qn}/urgency={urg}", t, q, cfg, urgency=urg)
            for prof in (cfg.get("profiles") or {}):
                score(f"{sn}/full/profile={prof}", t, qs["full"], cfg, profile_name=prof)
            for only in cfg["pools"]:
                c2 = copy.deepcopy(cfg)
                for name in c2["pools"]:
                    c2["pools"][name]["usable"] = name == only
                score(f"{sn}/full/only={only}", t, quotas(c2, "full"), c2, route="gateway")

        big = t_states["big"]
        comp = cfg["compaction"]
        out["digest"] = cc.build_deterministic_digest(big, {"status_short": "M src/router.py", "diff_stat": ""}, comp["preserve_buckets"])
        out["tail"] = [r["uuid"] for r in cc.select_safe_tail_records(big["conversation_records"], int(comp["preserve_tail_messages"]), cc.tail_token_cap(cfg))]
        asked = []

        def fail(req, timeout=None):
            body = json.loads(req.data)
            asked.append((body["model"], body["max_tokens"], timeout, hashlib.sha256(body["messages"][0]["content"].encode()).hexdigest()[:12]))
            raise urllib.error.HTTPError(req.full_url, 429, "x", {}, io.BytesIO(b""))

        with mock.patch.dict(os.environ, {k: v for k, v in os.environ.items() if k not in GW_ENV}, clear=True), \
                mock.patch.object(cc.urllib.request, "urlopen", side_effect=fail):
            out["conn"] = cc.load_magpie_connection(cfg)["base_url"]
            out["distill"] = cc.distill_with_byok_llm(out["digest"], big, cfg)
        out["asked"] = asked
        out["login"] = cc.signed_in_seat(cfg)

        state = self.tmp / "state"  # where base_cfg keeps it: another state_dir must not see this history
        state.mkdir(parents=True, exist_ok=True)
        now = time.time()
        (state / "rate_guard.json").write_text(json.dumps({"timestamps": [now - 3000, now - 2500, now - 2000, now - 1500, now - 1000, now - 200]}))
        out["rate"] = cc.check_and_record_rate_limit(cfg, dry_run=True)
        live = self.tmp / "live.jsonl"
        live.write_text("{}\n")
        os.utime(live, (now - 200, now - 200))
        out["live"] = cc.session_is_live(live, cfg)
        d = cc.evaluate_actions(big, qs["full"], cfg, now_ts=NOW) if not isinstance(out.get("big/full/auto"), str) else {"recommended_action": "?", "recommended_score": 0}
        out["handoff"] = str(cc.write_handoff_document(big, qs["full"], d, cfg).relative_to(self.tmp))
        return out


class TestSeats(unittest.TestCase):
    def setUp(self):
        self.cfg = cc.load_config(str(TOML_PATH))

    def test_only_team_seats_are_counted(self):
        q = quotas(self.cfg, "room")
        self.assertEqual(q["counted"], 3, [s["user"] for s in q["seats"]])
        self.assertNotIn("seat2@x.com", [s["user"] for s in q["seats"]])
        self.assertEqual([(s["user"], s["plan"]) for s in q["skipped"]], [("seat2@x.com", "max")])

    def test_a_seat_is_full_at_the_gateway_cap(self):
        def healthy(five, user="a@x.com · DuoCode", cfg=None):
            q = cc.fetch_magpie_quotas(cfg or self.cfg, now_ts=NOW, mock_payload=[card(user, five=five, five_reset=3600, week=10)])
            return q["seats"][0]["healthy"]

        self.assertTrue(healthy(94.9))
        self.assertFalse(healthy(95), "a seat at the 95% cap counted as having room")
        self.assertFalse(healthy(95.5))
        s3 = "seat3@x.com · DuoCode"
        own = cc.deep_merge(self.cfg, {"seats": {"seat_caps": {s3.lower(): {"5 hours": 100}}}})
        self.assertFalse(healthy(97, s3), "a per-seat cap applied with no seats.seat_caps")
        self.assertTrue(healthy(97, s3, cfg=own), "seats.seat_caps not read")
        self.assertFalse(healthy(100, s3, cfg=own))
        lower = cc.deep_merge(self.cfg, {"seats": {"caps": {"5 hours": 90}}})
        self.assertFalse(healthy(92, cfg=lower), "seats.caps not read")

    def test_week_is_the_seats_own_window_not_a_model_window(self):
        for fable_first in (True, False):
            q = cc.fetch_magpie_quotas(self.cfg, now_ts=NOW, mock_payload=[
                card("a@x.com · DuoCode", five=10, five_reset=3600, week=41, fable_first=fable_first)])
            self.assertEqual(q["seats"][0]["used_7d"], 41.0, f"fable_first={fable_first}: read the Fable window as the week")
        q = cc.fetch_magpie_quotas(self.cfg, now_ts=NOW, mock_payload=[
            card("a@x.com · DuoCode", five=10, five_reset=3600, week=100, week_reset=86400)])
        s = q["seats"][0]
        self.assertFalse(s["healthy"])
        self.assertEqual(s["usable_at_ts"], NOW + 86400, "a full week should make the seat usable at the week's reset")

    def test_a_window_past_its_reset_starts_over(self):
        q = cc.fetch_magpie_quotas(self.cfg, now_ts=NOW, mock_payload=[card("a@x.com · DuoCode", five=99, five_reset=-60, week=10)])
        self.assertTrue(q["seats"][0]["healthy"])
        self.assertEqual(q["seats"][0]["used_5h"], 0.0)

    def test_a_seat_with_no_5_hour_reading_has_no_room(self):
        q = cc.fetch_magpie_quotas(self.cfg, now_ts=NOW, mock_payload=[card("a@x.com · DuoCode", week=10)])
        self.assertFalse(q["seats"][0]["healthy"])
        self.assertEqual(q["healthy"], 0)


class TestStopMessage(unittest.TestCase):
    def test_reset_times(self):
        self.assertEqual(cc.parse_reset_text("resets 9:50pm (Asia/Shanghai)", NOW), cc.parse_iso_ts("2026-11-03T13:50:00Z"))
        self.assertEqual(cc.parse_reset_text("resets 6:20am (Asia/Shanghai)", NOW), cc.parse_iso_ts("2026-11-03T22:20:00Z"))
        self.assertEqual(cc.parse_reset_text("resets 11am (UTC)", NOW), cc.parse_iso_ts("2026-11-03T11:00:00Z"))
        self.assertEqual(cc.parse_reset_text("resets Oct 29, 3pm (Asia/Kuala_Lumpur)", cc.parse_iso_ts("2026-10-27T00:00:00Z")),
                         cc.parse_iso_ts("2026-10-29T07:00:00Z"))
        self.assertEqual(cc.parse_reset_text("[1308][已达到 5 小时的使用上限。您的限额将在 2026-11-01 12:00:00 重置。]", NOW),
                         cc.parse_iso_ts("2026-11-01T04:00:00Z"))
        self.assertIsNone(cc.parse_reset_text("Grok Build usage balance exhausted", NOW))

    def test_stop_on_the_gateway_and_on_a_direct_sign_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write_session(Path(tmp) / "s.jsonl", 300000, GW_STOP, NOW - 300, NOW - 300)
            stop = cc.analyze_transcript(p, now_ts=NOW)["stop"]
            self.assertEqual((stop["kind"], stop["provider"], stop["via_gateway"]), ("session_limit", "Claude Code", True))
            self.assertEqual(stop["reset_ts"], cc.parse_iso_ts("2026-11-03T13:50:00Z"))
            p = write_session(Path(tmp) / "d.jsonl", 300000, "You've hit your session limit · resets 3pm (Asia/Shanghai)", NOW - 300, NOW - 300)
            stop = cc.analyze_transcript(p, now_ts=NOW)["stop"]
            self.assertEqual((stop["kind"], stop["provider"], stop["via_gateway"]), ("session_limit", None, False))
            p = write_session(Path(tmp) / "g.jsonl", 300000, "API Error: 402 Grok (SuperGrok): Grok Build usage balance exhausted", NOW - 300, NOW - 300)
            stop = cc.analyze_transcript(p, now_ts=NOW)["stop"]
            self.assertEqual((stop["kind"], stop["provider"], stop["via_gateway"]), ("usage_limit", "Grok (SuperGrok)", True))
            p = write_session(Path(tmp) / "n.jsonl", 300000, None, NOW - 300, NOW - 300)
            self.assertIsNone(cc.analyze_transcript(p, now_ts=NOW)["stop"])

    def test_what_a_session_did_after_it_stopped(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write_session(Path(tmp) / "s.jsonl", 300000, GW_STOP, NOW - 300, NOW - 300)
            self.assertEqual(cc.activity_after(p, NOW - 300), {"turns": 0, "first": None})
            with p.open("a") as f:
                f.write(json.dumps(rec("assistant", "r1", NOW + 600, [{"type": "text", "text": "back"}],
                                       {"input_tokens": 5, "cache_creation_input_tokens": 9000, "cache_read_input_tokens": 0, "output_tokens": 50})) + "\n")
            a = cc.activity_after(p, NOW - 300)
            self.assertEqual(a["turns"], 1)
            self.assertEqual((a["first"]["after_min"], a["first"]["cache_write"], a["first"]["cache_read"]), (15.0, 9000, 0))


class TestDecision(unittest.TestCase):
    def setUp(self):
        self.cfg = cc.load_config(str(TOML_PATH))
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def decide(self, tokens, stopped_sec, payload, cache_sec=None, urgency=None, stop=GW_STOP, cfg=None):
        p = write_session(self.dir / f"s{tokens}-{stopped_sec}.jsonl", tokens, stop, NOW - stopped_sec, NOW - (cache_sec if cache_sec is not None else stopped_sec))
        cfg = cfg or self.cfg
        t = cc.analyze_transcript(p, now_ts=NOW, cfg=cfg)
        q = cc.fetch_magpie_quotas(cfg, now_ts=NOW, mock_payload=payload)
        return cc.evaluate_actions(t, q, cfg, urgency=urgency, now_ts=NOW)

    def test_wait_when_a_seat_comes_back_before_the_cache_goes_cold(self):
        d = self.decide(400000, 300, [card("a@x.com · DuoCode", five=99, five_reset=10 * 60, week=30)])
        self.assertEqual(d["recommended_action"], "wait", d["summary_zh"])
        self.assertTrue(d["signals"]["cache_warm_at_wait"])
        self.assertEqual(next(r for r in d["ranked_actions"] if r["action"] == "wait")["minutes"], 10.0)

    def test_compact_a_large_cold_session_rather_than_rewrite_it_whole(self):
        d = self.decide(600000, 2 * 3600, [card("a@x.com · DuoCode", five=20, five_reset=3 * 3600, week=30)])
        self.assertEqual(d["recommended_action"], "compact", d["summary_zh"])

    def test_hand_off_urgent_work_when_every_seat_is_out_for_hours(self):
        payload = [card("a@x.com · DuoCode", five=99, five_reset=4 * 3600, week=30),
                   card("b@x.com · DuoCode", five=50, five_reset=3600, week=100, week_reset=3 * 86400)]
        d = self.decide(300000, 600, payload, urgency="high")
        self.assertEqual(d["recommended_action"], "handoff", d["summary_zh"])

    def test_wait_out_a_short_gap_when_the_work_is_not_urgent(self):
        payload = [card("a@x.com · DuoCode", five=99, five_reset=40 * 60, week=30)]
        d = self.decide(300000, 600, payload, urgency="low")
        self.assertEqual(d["recommended_action"], "wait", d["summary_zh"])
        d = self.decide(300000, 600, [card("a@x.com · DuoCode", five=99, five_reset=6 * 3600, week=30)], urgency="low")
        self.assertNotEqual(d["recommended_action"], "wait", "waited six hours: " + d["summary_zh"])

    def test_a_usable_pool_is_room_and_its_window_decides_who_fits(self):
        payload = [card("a@x.com · DuoCode", five=99, five_reset=5 * 3600, week=30), pool_card("grok", 40)]
        grok = cc.deep_merge(self.cfg, {"pools": {"grok": {"usable": True}}})
        d = self.decide(600000, 2 * 3600, payload, cfg=grok)
        by = {r["action"]: r for r in d["ranked_actions"]}
        self.assertEqual(by["compact"]["source"], "pool grok", "the compacted session fits Grok's 256K window")
        self.assertTrue(by["wait"]["source"].startswith("seat a@x.com"), "the raw 600K session does not fit Grok")
        d = self.decide(600000, 2 * 3600, payload)
        self.assertTrue({r["action"]: r for r in d["ranked_actions"]}["compact"]["source"].startswith("seat"), "an unusable pool counted as room")

    def test_a_longer_wait_always_costs_more_time(self):
        """No flat top: past the tolerable wait, four hours must still look worse than one."""
        timing = []
        for hours in (0.5, 1, 4, 8):
            d = self.decide(300000, 600, [card("a@x.com · DuoCode", five=99, five_reset=int(hours * 3600), week=30)], urgency="high")
            timing.append(next(r for r in d["ranked_actions"] if r["action"] == "wait")["dims"]["timing"])
        self.assertEqual(timing, sorted(set(timing)), timing)

    def test_scores_are_the_weighted_mean_of_the_four_dimensions(self):
        d = self.decide(600000, 2 * 3600, QUOTAS["full"])
        w = d["weights"]
        for r in d["ranked_actions"]:
            self.assertAlmostEqual(r["score"], sum(w[k] * r["dims"][k] for k in cc.DIMENSIONS) / sum(w.values()), places=3)
            self.assertEqual(set(r["dims"]), {"timing", "session", "cost", "account"})
        self.assertIn("时机/会话/成本/账号", d["summary_zh"])


class TestConfig(unittest.TestCase):
    def test_every_config_key_changes_something(self):
        """No setting is decoration: changing any one of them changes what cc-compactor does."""
        with tempfile.TemporaryDirectory() as tmp:
            rig = Rig(tmp)
            base_cfg = rig.base_cfg()
            base = rig.observe(base_cfg)
            dead = []
            for path, value in leaves(cc.DEFAULT_CONFIG):
                cfg = copy.deepcopy(base_cfg)
                set_in(cfg, path, perturb(get_in(cfg, path)))
                if rig.observe(cfg) == base:
                    dead.append(".".join(path))
            self.assertEqual(dead, [], "settings that change nothing")

    def test_shipped_toml_is_the_defaults_and_nothing_else(self):
        raw = tomllib.loads(TOML_PATH.read_text(encoding="utf-8"))
        self.assertEqual(cc.config_problems(raw), [])
        self.assertEqual(dict(leaves(raw)), dict(leaves(cc.DEFAULT_CONFIG)))

    def test_unknown_keys_and_buckets_are_reported(self):
        raw = {
            "weights": {"timimg": 0.3},
            "pools": {"zcode": {"usabel": True}},
            "seats": {"caps": {"5hours": 90}, "seat_caps": {"a@x.com": {"5 hour": 90}}},
            "compaction": {"preserve_buckets": ["file_paths_and_line_ranges"]},
            "profiles": {"p": {"limits": {"live_guard_sec": 0}, "weights": {"tming": 1}}},
            "keep_warm": {"enabled": True},
        }
        problems = "\n".join(cc.config_problems(raw))
        for needle in ("weights.timimg", "pools.zcode.usabel", "seats.caps.5hours", "'5 hour'", "'file_paths_and_line_ranges'",
                       "profiles.p.limits", "profiles.p.weights.tming", "unknown key keep_warm"):
            self.assertIn(needle, problems)

    def test_a_pool_named_only_in_the_config_gets_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "c.toml"
            p.write_text("[pools.kimi]\nusable = true\n", encoding="utf-8")
            cfg = cc.load_config(str(p))
            self.assertEqual(cfg["pools"]["kimi"], {**cc.POOL_DEFAULT, "usable": True})
            self.assertEqual(cfg["_problems"], [])

    def test_compact_refuses_unknown_buckets(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = write_session(Path(tmp) / "s.jsonl", 300000, GW_STOP, NOW - 3600, NOW - 3600)
            before = s.read_text()
            c = Path(tmp) / "c.toml"
            c.write_text(f'[general]\nstate_dir = "{tmp}/state"\n[compaction]\nevict_buckets = ["old_base64_images"]\n', encoding="utf-8")
            out = io.StringIO()
            with mock.patch("sys.stdout", out):
                rc = cc.main(["--config", str(c), "--session", str(s), "compact", "--deterministic-only"])
            self.assertEqual(rc, 2)
            self.assertEqual(json.loads(out.getvalue())["status"], "config_error")
            self.assertEqual(s.read_text(), before)

    def test_no_hook_or_keep_warm_subcommand(self):
        for sub in ("hook", "keep-warm"):
            with self.assertRaises(SystemExit), mock.patch("sys.stderr", io.StringIO()):
                cc.build_arg_parser().parse_args([sub])


class TestCompaction(unittest.TestCase):
    def setUp(self):
        self.cfg = cc.load_config(str(TOML_PATH))
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.path = write_session(self.dir / "s.jsonl", 600000, GW_STOP, NOW - 3600, NOW - 3600, tail_chars=21000)
        self.t = cc.analyze_transcript(self.path, now_ts=NOW)

    def tearDown(self):
        self.tmp.cleanup()

    def test_analyze_reads_files_errors_todos_and_size(self):
        t = self.t
        self.assertGreaterEqual(t["context_tokens"], 600000)
        self.assertEqual(t["touched_files"].get("/tmp/demo/src/router.py"), "MODIFIED")
        self.assertTrue(any("pytest tests/test_router.py" in c for c in t["commands_run"]))
        self.assertTrue(any("AssertionError" in e for e in t["errors_and_failures"]))
        self.assertEqual([td["content"] for td in t["latest_todos"]], ["rewrite pick_seat", "add tests"])
        self.assertEqual(t["stopped_min"], 60.0)

    def test_preserve_buckets_pick_the_digest_sections(self):
        git = {"status_short": "M src/router.py", "diff_stat": ""}
        full = cc.build_deterministic_digest(self.t, git, cc.PRESERVE_BUCKETS)
        for section in ("Primary User Request", "Todo List", "Touched Files", "Live Git", "Recent Commands", "Diagnostic Errors"):
            self.assertIn(section, full)
        some = cc.build_deterministic_digest(self.t, git, ["errors"])
        self.assertIn("Diagnostic Errors", some)
        self.assertNotIn("Live Git", some)
        self.assertNotIn("Todo List", some)

    def test_evict_buckets_keep_file_bodies_and_passing_logs_out_of_the_excerpts(self):
        text = "\n".join(cc.middle_excerpts(self.t, self.cfg, 100000))
        self.assertNotIn("SECRETFILEBODY", text)
        self.assertNotIn("PASSINGLOGBODY", text)
        self.assertIn("AssertionError: expected cap 95", text, "a failing log was evicted")
        kept = cc.deep_merge(self.cfg, {"compaction": {"evict_buckets": []}})
        text = "\n".join(cc.middle_excerpts(self.t, kept, 100000))
        self.assertIn("SECRETFILEBODY", text)
        self.assertIn("PASSINGLOGBODY", text)

    def test_tail_is_capped_by_target_post_compact_tokens(self):
        conv = self.t["conversation_records"]
        uncapped = cc.select_safe_tail_records(conv, 10)
        capped = cc.select_safe_tail_records(conv, 10, cc.tail_token_cap(self.cfg))
        self.assertGreater(len(uncapped), len(capped))
        self.assertGreaterEqual(len(capped), 2)
        self.assertLessEqual(sum(cc.record_tokens(r) for r in capped), cc.tail_token_cap(self.cfg))
        self.assertEqual(capped[-1]["uuid"], conv[-1]["uuid"])

    def test_preserved_tail_never_starts_on_a_tool_result(self):
        recs = [
            {"uuid": "u0", "message": {"role": "user", "content": "task"}},
            {"uuid": "a1", "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}]}},
            {"uuid": "u1", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}},
            {"uuid": "a2", "message": {"role": "assistant", "content": [{"type": "text", "text": "done"}]}},
        ]
        self.assertEqual([r["uuid"] for r in cc.select_safe_tail_records(recs, 2)], ["a1", "u1", "a2"])

    def test_splice_writes_a_compact_boundary_and_resets_the_active_segment(self):
        cfg = cc.deep_merge(self.cfg, {"general": {"state_dir": str(self.dir / "state")}})
        digest = cc.build_deterministic_digest(self.t, {}, cc.PRESERVE_BUCKETS)
        res = cc.splice_compact_boundary(self.path, self.t, digest, "deterministic_test", cfg, 120)
        self.assertTrue(Path(res["backup_path"]).is_file())
        self.assertLessEqual(res["post_tokens"], int(self.cfg["compaction"]["target_post_compact_tokens"]))
        after = cc.analyze_transcript(self.path, now_ts=NOW)
        self.assertEqual(after["compactions"], 1)
        self.assertEqual(after["active_records_count"], 1)
        self.assertLess(after["context_tokens"], 5000)

    def test_byok_chain_falls_through_to_next_model_then_to_deterministic(self):
        settings = self.dir / "ms.json"
        settings.write_text(json.dumps({"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:9"}}), encoding="utf-8")
        cfg = cc.deep_merge(self.cfg, {"general": {"magpie_settings_path": str(settings)},
                                       "compaction": {"byok_chain": ["first-model", "second-model"]}})
        asked: list[str] = []
        good = json.dumps({"content": [{"type": "text", "text": "S" * 200}]}).encode()

        def first_fails(req, timeout=None):
            model = json.loads(req.data)["model"]
            asked.append(model)
            if model == "first-model":
                raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, io.BytesIO(b""))
            return io.BytesIO(good)

        env = {k: v for k, v in os.environ.items() if k not in GW_ENV}
        with mock.patch.dict(os.environ, env, clear=True):
            tried: list[str] = []
            with mock.patch.object(cc.urllib.request, "urlopen", side_effect=first_fails):
                text, source = cc.distill_with_byok_llm("digest", {"conversation_records": []}, cfg, tried)
            self.assertEqual((asked, source, text, tried), (["first-model", "second-model"], "byok:second-model", "S" * 200, ["first-model: HTTP 429"]))
            tried = []
            with mock.patch.object(cc.urllib.request, "urlopen", side_effect=TimeoutError()):
                text, source = cc.distill_with_byok_llm("digest", {"conversation_records": []}, cfg, tried)
            self.assertEqual((text, source, tried), (None, "deterministic_fallback", ["first-model: TimeoutError", "second-model: TimeoutError"]))

    def test_default_chain_starts_on_litellm_api_then_seat_haiku_without_glm(self):
        chain = cc.DEFAULT_CONFIG["compaction"]["byok_chain"]
        self.assertTrue(chain[0].startswith("litellm-claude-api/"), chain)
        self.assertLess(chain.index("claude-haiku-5-5"), chain.index("always-up"), chain)
        self.assertTrue(all(m.startswith("litellm-claude-api/") for m in chain[:chain.index("claude-haiku-5-5")]), chain)
        self.assertFalse([m for m in chain if "glm" in m.lower()], chain)

    def test_rate_limit_cooldown_and_hourly_cap_and_force_still_counts(self):
        cfg = cc.deep_merge(self.cfg, {"general": {"state_dir": str(self.dir / "state")},
                                       "limits": {"min_compaction_cooldown_sec": 180, "max_compactions_per_hour": 3}})
        self.assertEqual(cc.check_and_record_rate_limit(cfg), (True, "ok"))
        ok, why = cc.check_and_record_rate_limit(cfg)
        self.assertFalse(ok, "second compaction inside the cooldown was allowed")
        self.assertTrue(why.startswith("cooldown_active"), why)
        rate = self.dir / "state" / "rate_guard.json"
        now = time.time()
        rate.write_text(json.dumps({"timestamps": [now - 3000, now - 2000, now - 1000]}), encoding="utf-8")
        ok, why = cc.check_and_record_rate_limit(cfg)
        self.assertFalse(ok, "a 4th compaction in the hour was allowed")
        self.assertTrue(why.startswith("hourly_cap_reached"), why)
        ok, _ = cc.check_and_record_rate_limit(cfg, force=True)
        self.assertTrue(ok)
        self.assertEqual(len(json.loads(rate.read_text())["timestamps"]), 4)

    def test_compact_refuses_a_live_transcript_unless_allowed(self):
        env = {k: v for k, v in os.environ.items() if k not in GW_ENV}
        with mock.patch.dict(os.environ, env, clear=True):
            p = self.dir / "live-session.jsonl"
            write_session(p, 300000, GW_STOP, NOW - 300, NOW - 300)
            os.utime(p, None)  # just written
            cfg_path = self.dir / "cfg.toml"
            cfg_path.write_text(f'[general]\nstate_dir = "{self.dir / "state"}"\nmagpie_settings_path = "{self.dir / "none.json"}"\n', encoding="utf-8")
            before = p.read_text(encoding="utf-8")
            out = io.StringIO()
            with mock.patch("sys.stdout", out):
                cc.main(["--config", str(cfg_path), "--session", str(p), "compact", "--deterministic-only"])
            self.assertEqual(json.loads(out.getvalue()), {"status": "skipped", "reason": "session_live", "session_path": str(p)})
            self.assertEqual(p.read_text(encoding="utf-8"), before)
            out = io.StringIO()
            with mock.patch("sys.stdout", out):
                cc.main(["--config", str(cfg_path), "--session", str(p), "compact", "--deterministic-only", "--allow-live"])
            self.assertEqual(json.loads(out.getvalue())["status"], "compacted")
            self.assertIn('"subtype": "compact_boundary"', p.read_text(encoding="utf-8"))
            old = time.time() - 3600
            os.utime(p, (old, old))
            self.assertFalse(cc.session_is_live(p, cc.load_config(str(cfg_path))))


if __name__ == "__main__":
    unittest.main()
