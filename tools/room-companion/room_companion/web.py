"""Tailnet web page + local API.

Who may connect:
- 127.0.0.1 (other services on this machine): no key needed,
  unless the request came through a reverse proxy (X-Forwarded-For set): then it is a browser and needs the key.
- tailnet / home LAN addresses: need the key (link with ?k=..., then a cookie).
- anything else: refused.

On top of that, for every caller (this machine included):
- the Host header must be 127.0.0.1, localhost, [::1] or a name in `allowed_hosts`, and a browser request
  marked `Sec-Fetch-Site: cross-site` is refused (except opening the page itself from a link). This stops a
  web page in a browser on the same machine from reading the API, also through DNS rebinding.
- a POST needs `X-Room-AI: 1` and `Content-Type: application/json`, and a browser Origin, when sent, must be
  an allowed host. A cross-site form cannot set either header, so it cannot flip a switch.
"""
from __future__ import annotations

import hmac
import ipaddress
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .camera.catalog import UNOFFICIAL_WARNINGS
from .switches import SwitchWriteError

COOKIE = "room_k"
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


def host_name(value: str) -> str:
    """The name part of a Host header or an Origin: lower case, no port, no brackets, no trailing dot."""
    h = (value or "").strip().lower()
    if "://" in h:
        h = h.split("://", 1)[1].split("/", 1)[0]
    if h.startswith("["):
        end = h.find("]")
        return h[1:end] if end > 0 else ""
    if h.count(":") == 1:
        h = h.split(":", 1)[0]
    return h.rstrip(".")


def host_allowed(value: str, extra=()) -> bool:
    name = host_name(value)
    return bool(name) and (name in LOOPBACK_HOSTS or name in {host_name(x) for x in extra})


def cross_site(headers, method: str, path: str) -> bool:
    if headers.get("Sec-Fetch-Site", "").lower() != "cross-site":
        return False
    # Following a link to the page from elsewhere is fine; everything the page then loads is same-origin.
    return not (method == "GET" and path == "/" and headers.get("Sec-Fetch-Mode") == "navigate"
                and headers.get("Sec-Fetch-Dest", "document") == "document")


def classify(ip: str, allowed_cidrs, trust_loopback: bool = True) -> str:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return "deny"
    if getattr(a, "ipv4_mapped", None):
        a = a.ipv4_mapped
    if a.is_loopback and trust_loopback:
        return "local"
    for c in allowed_cidrs:
        try:
            if a in ipaddress.ip_network(c, strict=False):
                return "remote"
        except ValueError:
            continue
    return "deny"


def make_handler(app):
    allowed = app.cfg.get("allowed_cidrs", [])
    trust_loopback = app.cfg.get("trust_loopback", True)
    extra_hosts = list(app.cfg.get("allowed_hosts", []))
    # a remote caller cannot name its own source; addresses that are known services get a name here
    source_names = dict(app.cfg.get("source_names", {}))
    stream_slots = threading.BoundedSemaphore(app.cfg.get("max_streams", 4))

    class H(BaseHTTPRequestHandler):
        server_version = "room-companion"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # keep logs quiet; no URLs (they may hold the key)
            pass

        # ---- auth ----
        def _guard(self, method, path):
            """Host / cross-site / header checks that apply to every caller, before the key is looked at."""
            if not host_allowed(self.headers.get("Host", ""), extra_hosts):
                self._send(403, "text/plain; charset=utf-8", "host not allowed".encode())
                return False
            if cross_site(self.headers, method, path):
                self._send(403, "text/plain; charset=utf-8", "cross-site request refused".encode())
                return False
            if method == "POST":
                origin = self.headers.get("Origin")
                if origin is not None and not host_allowed(origin, extra_hosts):
                    self._send(403, "text/plain; charset=utf-8", "origin not allowed".encode())
                    return False
                if self.headers.get("X-Room-AI") != "1":  # a custom header: cross-site forms cannot send it
                    self._send(403, "text/plain; charset=utf-8", "missing X-Room-AI header".encode())
                    return False
                ctype = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if ctype != "application/json":
                    self._send(415, "text/plain; charset=utf-8", "Content-Type must be application/json".encode())
                    return False
            return True

        def _who(self):
            who = classify(self.client_address[0], allowed, trust_loopback)
            if who == "local" and (self.headers.get("X-Forwarded-For") or self.headers.get("X-Forwarded-Host")):
                # came in through a reverse proxy: a browser somewhere, not a service on this box
                return "remote"
            return who

        def _token_ok(self, qs):
            tok = app.web_token
            if not tok:
                return False
            cands = []
            cands += qs.get("k", [])
            auth = self.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                cands.append(auth[7:])
            for part in self.headers.get("Cookie", "").split(";"):
                k, _, v = part.strip().partition("=")
                if k == COOKIE:
                    cands.append(v)
            return any(hmac.compare_digest(c.encode(), tok.encode()) for c in cands)

        def _authorize(self, qs):
            who = self._who()
            if who == "local":
                return True
            if who == "deny":
                self._send(403, "text/plain; charset=utf-8", "forbidden".encode())
                return False
            if not self._token_ok(qs):
                self._send(401, "text/html; charset=utf-8", NEED_KEY.encode())
                return False
            return True

        def _source(self, body=None):
            if self._who() == "local":
                return (body or {}).get("source") or "本机"
            if self.headers.get("X-Forwarded-For"):
                return "网页（经反向代理）"
            # the address is not named in confirmations, which leave the machine
            return source_names.get(self.client_address[0]) or "网页（另一台设备）"

        # ---- helpers ----
        def _unread_body(self) -> bool:
            if self.headers.get("Transfer-Encoding"):
                return True
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return True
            return n > 0 and not self._body_done

        def _send(self, code, ctype, data: bytes, extra=None):
            if self._unread_body():
                # Refused before the body was read: close, or the body would be parsed as the next request
                # on this connection (and could carry the headers the refused request lacked).
                self.close_connection = True
                extra = {**(extra or {}), "Connection": "close"}
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _json(self, code, obj):
            self._send(code, "application/json; charset=utf-8", json.dumps(obj, ensure_ascii=False).encode())

        def _body(self, limit=10000):
            if self.headers.get("Transfer-Encoding"):
                raise ValueError("chunked bodies are not accepted")
            n = int(self.headers.get("Content-Length") or 0)
            if n > limit:
                raise ValueError("body too large")
            raw = self.rfile.read(n) if n else b"{}"
            self._body_done = True
            obj = json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(obj, dict):
                raise ValueError("body must be an object")
            return obj

        # ---- routes ----
        def do_GET(self):
            self._body_done = False
            u = urllib.parse.urlsplit(self.path)
            qs = urllib.parse.parse_qs(u.query)
            if not self._guard("GET", u.path):
                return
            if u.path == "/healthz" and self._who() == "local":
                return self._json(200, {"ok": True})
            if not self._authorize(qs):
                return
            if u.path == "/" and "k" in qs and self._who() != "local":
                # turn the key link into a cookie, then drop the key from the address bar
                cookie = f"{COOKIE}={qs['k'][0]}; Path=/; HttpOnly; SameSite=Strict; Max-Age=31536000"
                return self._send(302, "text/plain", b"", {"Location": "/", "Set-Cookie": cookie})
            if u.path == "/":
                return self._send(200, "text/html; charset=utf-8", PAGE.encode())
            if u.path == "/api/status":
                st = app.status()
                st["events"] = app.events.latest(30)
                st["transcripts"] = app.audio.recent_transcripts(app.cfg.get("transcript_ttl_seconds", 600))
                return self._json(200, st)
            if u.path == "/snapshot.jpg":
                frame, _ = app.video.latest()
                if frame is None:
                    return self._send(404, "text/plain; charset=utf-8", "视频关着或没有画面".encode())
                return self._send(200, "image/jpeg", frame)
            if u.path == "/stream.mjpg":
                return self._stream()
            if u.path.startswith("/api/broadcast/"):
                r = app.broadcast_result(urllib.parse.unquote(u.path.rsplit("/", 1)[-1]))
                return self._json(200, r) if r else self._json(404, {"ok": False, "message": "没有这一条"})
            if u.path == "/api/camera":
                return self._json(200, {"status": app.camera_status(), "detail": app.camera.detail_status(),
                                        "drivers": app.camera_drivers(),
                                        "unofficial_warning": UNOFFICIAL_WARNINGS.get(getattr(app, "language", "zh"), UNOFFICIAL_WARNINGS["zh"])})
            return self._send(404, "text/plain", b"not found")

        def do_POST(self):
            self._body_done = False
            u = urllib.parse.urlsplit(self.path)
            qs = urllib.parse.parse_qs(u.query)
            if not self._guard("POST", u.path) or not self._authorize(qs):
                return
            big = u.path == "/api/selftest/inject" and self._who() == "local"
            try:
                body = self._body(2_000_000 if big else 10000)
            except ValueError as e:
                return self._json(400, {"ok": False, "message": str(e)})
            if u.path == "/api/switch":
                changes = {k: v for k, v in body.items() if k in ("video", "audio", "ai")}
                try:
                    diff = app.set_switches(changes, self._source(body))
                except ValueError as e:
                    return self._json(400, {"ok": False, "message": str(e)})
                except SwitchWriteError as e:
                    return self._json(500, {"ok": False, "message": str(e)})
                app.wait_settled()
                return self._json(200, {"ok": True, "changes": {k: n for k, (o, n) in diff.items()},
                                        "summary": app.plain_status()})
            if u.path == "/api/command":
                r = app.run_command(str(body.get("text", "")), self._source(body))
                return self._json(200 if r.get("ok") else 400, r)
            if u.path == "/api/broadcast":
                r = app.broadcast(str(body.get("text", "")), self._source(body), request_id=body.get("id"))
                code = 200 if r.get("ok") else {"rate_limited": 429, "busy": 503, "no_output": 503}.get(r.get("code"), 400)
                return self._json(code, r)
            if u.path == "/api/output":
                try:
                    return self._json(200, app.set_output(str(body.get("choice", "auto")), self._source(body)))
                except ValueError as e:
                    return self._json(400, {"ok": False, "message": str(e)})
            if u.path == "/api/camera":
                ok, err = app.set_camera_config(body.get("camera", body))
                if not ok:
                    return self._json(400, {"ok": False, "error": err})
                return self._json(200, {"ok": True, "status": app.camera_status()})
            if u.path == "/api/camera/action":
                ok, detail = app.camera_action(str(body.get("action", "")))
                return self._json(200 if ok else 409, {"ok": ok, "detail": detail, "status": app.camera_status()})
            if u.path == "/api/selftest/unplug" and self._who() == "local":
                app.hide_devices(body.get("names", []), body.get("seconds", 60))
                return self._json(200, {"ok": True})
            if u.path == "/api/selftest/inject" and self._who() == "local":
                # self-test only: 16 kHz mono s16le PCM, base64, fed into the mic path as if heard
                import base64
                n = app.audio.inject(base64.b64decode(str(body.get("pcm_b64", ""))))
                return self._json(200, {"ok": True, "segments": n})
            if u.path == "/api/speak" and self._who() == "local":
                # self-test only (this machine): play a sentence; hear=true lets the mic transcribe it
                if app.speaker is None:
                    return self._json(400, {"ok": False, "message": "没有配置出声"})
                ok = app.speaker.say(str(body.get("text", ""))[:200], hear=bool(body.get("hear")))
                return self._json(200 if ok else 503, {"ok": ok})
            return self._send(404, "text/plain", b"not found")

        def _stream(self):
            if not app.switches.get("video"):
                return self._send(409, "text/plain; charset=utf-8", "视频关着".encode())
            if not stream_slots.acquire(blocking=False):
                return self._send(429, "text/plain; charset=utf-8", "看的人太多".encode())
            try:
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                seq = -1
                while app.switches.get("video"):
                    frame, seq = app.video.wait_frame(seq, 2.0)
                    if frame is None:
                        continue
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                     + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n")
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                pass
            finally:
                stream_slots.release()

    return H


def serve(app):
    srv = ThreadingHTTPServer((app.cfg["listen"], app.cfg["port"]), make_handler(app))
    srv.daemon_threads = True
    return srv


NEED_KEY = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>房间AI</title><body style="font-family:system-ui;padding:24px">
<p>需要带钥匙的链接才能打开（地址后面加 ?k=钥匙，打开一次后会记住）。</p></body>"""

PAGE = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>房间AI</title>
<style>
:root{--bg:#f6f6f4;--card:#fff;--fg:#1d1d1f;--muted:#6b6b70;--on:#1f8f4e;--off:#9a9aa0;--warn:#b5651d;--line:#e3e3e0}
@media (prefers-color-scheme: dark){:root{--bg:#141416;--card:#1e1e21;--fg:#f2f2f2;--muted:#a0a0a6;--on:#3cc47a;--off:#6b6b70;--warn:#e0a060;--line:#2c2c30}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,-apple-system,"PingFang SC",sans-serif}
main{max-width:860px;margin:0 auto;padding:16px}
h1{font-size:20px;margin:4px 0 12px}
.sw{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:12px}
.sw button{border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:14px;padding:14px 8px;font-size:17px;cursor:pointer}
.sw button b{display:block;font-size:22px;margin-top:2px}
.sw button.on b{color:var(--on)}.sw button.off b{color:var(--off)}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px 14px;margin-bottom:12px}
#live{width:100%;border-radius:10px;background:#000;display:none;aspect-ratio:16/9;object-fit:contain}
#nolive{color:var(--muted);padding:28px 0;text-align:center}
.muted{color:var(--muted);font-size:14px}.warn{color:var(--warn)}
ul{margin:4px 0;padding-left:18px}li{margin:2px 0}
.bar{height:8px;background:var(--line);border-radius:4px;overflow:hidden}.bar i{display:block;height:100%;background:var(--on);width:0}
textarea,select{width:100%;font:inherit;font-size:16px;color:var(--fg);background:var(--bg);border:1px solid var(--line);border-radius:10px;padding:10px}
textarea{resize:vertical;min-height:64px;margin:6px 0}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.big{border:0;border-radius:12px;background:var(--on);color:#fff;font-size:17px;padding:12px 22px;min-height:48px;cursor:pointer}
.big:disabled{opacity:.5}
.drv{display:flex;gap:10px;align-items:flex-start;padding:8px 0;border-top:1px solid var(--line)}.drv input{margin-top:5px}
.drv b{font-weight:600}.drv.dis{opacity:.5}.opt{display:block;margin:8px 0}
#camcard .row button{border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:10px;padding:8px 12px;font-size:15px;cursor:pointer}
</style></head><body><main>
<h1>房间AI</h1>
<div class="sw">
 <button id="b-video" data-k="video">视频<b>…</b></button>
 <button id="b-audio" data-k="audio">声音<b>…</b></button>
 <button id="b-ai" data-k="ai">AI<b>…</b></button>
</div>
<div class="card"><div id="summary">读取中…</div><div id="remote" class="warn"></div><div id="err" class="warn"></div></div>
<div class="card"><div id="scene">AI 看到的：还不知道</div><div class="muted" id="pinfo"></div></div>
<div class="card"><img id="live" alt="实时画面"><div id="nolive">视频关着，摄像头没有在用。</div>
 <div class="muted" id="vinfo"></div></div>
<div class="card"><div>声音电平</div><div class="bar"><i id="lv"></i></div>
 <div class="muted" id="ainfo"></div>
 <div id="tr"></div></div>
<div class="card"><div>念出来</div>
 <textarea id="say" maxlength="300" placeholder="打一句话，点「念出来」，房间里就会念（最多 300 字，中英文都行）"></textarea>
 <div class="row"><button class="big" id="b-say">念出来</button><span class="muted" id="saymsg"></span></div>
 <div style="margin-top:10px">从哪出声</div><select id="outsel" aria-label="从哪出声"></select>
 <div class="muted" id="outinfo"></div><div id="bc"></div></div>
<div class="card"><div>最近发生的事（只记摘要，不存画面和录音）</div><ul id="ev"></ul></div>
<div class="card" id="camcard"><div>相机怎么接</div><div class="muted" id="camnow"></div>
 <div id="camlist"></div>
 <label class="opt"><input type="checkbox" id="camunoff"> 允许用社区逆向的协议 <span class="muted" id="camwarn"></span></label>
 <div class="row"><button id="campair">配对蓝牙</button><button id="camrecover">现在切回网络摄像头</button></div>
 <div class="muted" id="cammsg"></div></div>
<p class="muted">语音口令：先说「房间助手」，再说「关视频」「关声音」「关AI」「隐私模式」（三个全关），或「安静模式」（只发通知不出声）、「平衡模式」、「主动模式」。听到提醒后说「不用」今天不再提这类，说「别再提醒这个」以后都不提。声音关着时听不到口令，要用这里或你配置的消息渠道打开。上面「念出来」框里打的字会在房间里念出来；文字命令「播报：要念的话」也一样。念的时候不用开视频或声音，房间里念的话也不会被当成口令。听写交给别的机器（自选服务器或 HipiMind 云）时，语音口令只能关、不能开。</p>
</main>
<script>
const $=id=>document.getElementById(id);
let cur=null, liveOn=false;
const KIND={switch:"开关",video_on:"摄像头开始用",video_off:"摄像头已释放",audio_on:"麦克风开始用",audio_off:"麦克风已释放",
 motion_start:"画面开始有动静",motion_end:"画面安静了",speech:"有人说话",voice_command:"语音命令",voice_command_unparsed:"没听懂的语音命令",
 service_start:"服务启动",state_load:"开关状态读取",scene:"AI 判断场景",reminder:"说了一条提醒",reminder_queued:"有一条提醒在等时机",
 reminder_off:"关掉了一类提醒",model_on:"本地模型启动",model_ready:"本地模型就绪",model_off:"本地模型已停",mic_change:"换了麦克风",
 spoke:"念了一句",summary:"早报",camera_missing_reminder:"提醒点相机",reminder_setting:"提醒设置",
 broadcast:"播报了一句",output_choice:"换了出声设备",interop:"和 Windows 的连接",
 models_changed:"换了模型",voice_command_refused:"远端听写的打开口令，没执行",
 camera_recover:"自动切回网络摄像头",camera_config:"换了相机驱动",camera_back:"相机回来了"};
const SCN={laundry:"洗衣服",cooking:"做饭",coding:"写代码",router:"配置路由器",yoga:"瑜伽",sofa_phone:"沙发上玩手机",sleeping:"睡觉",other:"其他",empty:"没人"};
function fmtEv(e){let t=e.ts.slice(11,16)+" "+(KIND[e.kind]||e.kind);
 if(e.kind==="switch"){t+=" · "+e.source+"："+Object.entries(e.changes).map(([k,v])=>({video:"视频",audio:"声音",ai:"AI"}[k])+(v?"开":"关")).join("、")}
 if(e.kind==="speech")t+=(e.n>1?" "+e.n+" 段，共 ":" ")+Math.round(e.seconds*10)/10+" 秒"; if(e.kind==="motion_end")t+="（持续 "+e.seconds+" 秒）";
 if(e.kind==="scene")t+="："+(SCN[e.scene]||e.scene); if(e.category)t+="："+e.category;
 if(e.kind==="broadcast")t+="（"+e.chars+" 字，来自"+e.source+"）"; if(e.kind==="spoke"&&e.output)t+="（"+e.output+"）";
 if(e.kind==="output_choice")t+="："+e.choice; return t}
function groupEv(list){const out=[];for(const e of list){const last=out[out.length-1];
 if(e.kind==="speech"&&last&&last.kind==="speech"){last.n=(last.n||1)+1;last.seconds+=e.seconds;last.ts=e.ts}else out.push({...e})}return out}
const ASR={ready:"本地识别就绪",loading:"识别模型加载中",idle:"识别未启动"};
async function refresh(){
 try{const r=await fetch("/api/status",{cache:"no-store"}); if(!r.ok){$("summary").textContent="打不开（"+r.status+"）";return}
 const s=await r.json(); cur=s.switches;
 for(const k of ["video","audio","ai"]){const b=$("b-"+k); b.className=s.switches[k]?"on":"off"; b.querySelector("b").textContent=s.switches[k]?"开":"关"}
 const p=s.policy||{}; $("scene").textContent="AI 看到的："+(s.switches.ai?(p.scene_text||"还不知道")+(p.scene_minutes!=null?"（约 "+p.scene_minutes+" 分钟）":"")+(p.note?" · "+p.note:""):"AI 关着，不看画面");
 $("pinfo").textContent=s.switches.ai?("提醒：今天 "+p.delivered_today+"/"+p.max_per_day+" 条 · "+p.mode_text+(p.pending&&p.pending.length?" · 等时机："+p.pending.join("、")+(p.blocked_now?"（"+p.blocked_now+"）":""):"")):"";
 $("summary").textContent=s.summary; $("remote").textContent=s.remote_text||""; $("err").textContent=s.state_load_error&&s.state_load_error!=="no state file yet"?("开关状态文件有问题，已按全关处理："+s.state_load_error):"";
 const v=s.video; const want=s.switches.video&&v.state==="running";
 if(want&&!liveOn){$("live").src="/stream.mjpg?t="+Date.now();$("live").style.display="block";$("nolive").style.display="none";liveOn=true}
 if(!want&&liveOn){$("live").removeAttribute("src");$("live").style.display="none";$("nolive").style.display="block";liveOn=false}
 $("nolive").textContent=s.switches.video?(v.detail||"正在连接摄像头…"):"视频关着，摄像头没有在用。";
 $("vinfo").textContent=v.state==="running"?(v.device_name+" · "+v.format+" · 实际 "+v.fps+" 帧/秒 · 画面变化 "+v.motion+(v.moving?"（有动静）":"")):"";
 const a=s.audio; const pct=Math.max(0,Math.min(100,(a.level_db+70)/70*100)); $("lv").style.width=(a.state==="running"?pct:0)+"%";
 $("ainfo").textContent=s.switches.audio?(a.state==="running"?(a.device+" · "+(ASR[a.asr]||"识别不可用")+" · 已切出 "+a.segments+" 段话"):(a.detail||"正在连接麦克风…")):"声音关着，麦克风没有在用。";
 $("tr").innerHTML=(s.transcripts||[]).slice(-6).reverse().map(t=>"<div class='muted'>"+new Date(t.t*1000).toTimeString().slice(0,5)+" "+t.text.replace(/[<&]/g,c=>({"<":"&lt;","&":"&amp;"}[c]))+"</div>").join("");
 renderOut(s.speaker,s.broadcast);
 $("ev").innerHTML=groupEv((s.events||[]).filter(e=>e.kind!=="camera_step")).slice(-12).reverse().map(e=>"<li>"+fmtEv(e).replace(/[<&]/g,c=>({"<":"&lt;","&":"&amp;"}[c]))+"</li>").join("");
 }catch(e){$("summary").textContent="连不上："+e}
}
const esc=t=>String(t).replace(/[<&]/g,c=>({"<":"&lt;","&":"&amp;"}[c]));
let outKey="";
function renderOut(sp,bc){
 if(!sp){$("outinfo").textContent="这台电脑没有配置出声";$("b-say").disabled=true;return}
 const key=sp.choice+"|"+sp.outputs.map(o=>o.name).join("|");
 if(key!==outKey&&document.activeElement!==$("outsel")){outKey=key;
  $("outsel").innerHTML="<option value='auto'>自动（按设置的顺序，没有就用 Windows 默认的）</option>"+sp.outputs.map(o=>"<option value='"+esc(o.name).replace(/'/g,"&#39;")+"'>"+esc(o.label)+(o.label!==o.name?" · "+esc(o.name):"")+"</option>").join("");
  $("outsel").value=sp.choice}
 const o=sp.output; $("outinfo").textContent=(o?"现在从「"+o.label+"」出声"+(sp.speaking?"，正在念":""):"没有能出声的设备")+(sp.notes.length?" · "+sp.notes.join(" · "):"")+(sp.error?" · 出错："+sp.error:"");
 $("bc").innerHTML=bc&&bc.recent.length?"<div class='muted'>今天念过 "+bc.today+"/"+bc.max_per_day+" 次（文字只留在今天，不存盘）：</div>"+bc.recent.slice().reverse().map(b=>"<div class='muted'>"+new Date(b.t*1000).toTimeString().slice(0,5)+" "+esc(b.text)+"</div>").join(""):""}
async function post(path,body){const r=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json","X-Room-AI":"1"},body:JSON.stringify(body)});
 let j={};try{j=await r.json()}catch(e){j={message:"出错了（"+r.status+"）"}} return j}
$("b-say").onclick=async()=>{const t=$("say").value.trim(); if(!t){$("saymsg").textContent="先打一句话";return}
 $("b-say").disabled=true; try{const j=await post("/api/broadcast",{text:t}); $("saymsg").textContent=j.message||""; if(j.ok)$("say").value=""}
 finally{$("b-say").disabled=false} refresh()};
$("say").addEventListener("keydown",e=>{if(e.key==="Enter"&&(e.ctrlKey||e.metaKey))$("b-say").click()});
$("outsel").onchange=async()=>{const j=await post("/api/output",{choice:$("outsel").value}); $("saymsg").textContent=j.message||""; outKey=""; refresh()};
for(const k of ["video","audio","ai"]){$("b-"+k).onclick=async()=>{if(!cur)return;
 const b=$("b-"+k); b.disabled=true;
 try{await fetch("/api/switch",{method:"POST",headers:{"Content-Type":"application/json","X-Room-AI":"1"},body:JSON.stringify({[k]:!cur[k]})})}finally{b.disabled=false}
 refresh()}}
let camCfg=null;
function esc(t){return String(t==null?"":t).replace(/[<&"]/g,c=>({"<":"&lt;","&":"&amp;",'"':"&quot;"}[c]))}
async function camRefresh(){
 try{const r=await fetch("/api/camera",{cache:"no-store"}); if(!r.ok)return; const c=await r.json();
 camCfg=c.detail.config; const st=c.status; const allow=camCfg.allow_unofficial;
 $("camunoff").checked=allow; $("camwarn").textContent=c.unofficial_warning;
 const now={running:"现在：画面走 USB 网络摄像头",waiting_device:"现在：没找到网络摄像头",off:"现在：视频关着",error:"现在：出错了"}[st.state]||st.state;
 $("camnow").textContent=now+(st.control?"；自动恢复用的是"+(c.drivers.find(d=>d.id===st.control)||{}).label:"")+(st.detail?"。"+st.detail:"")+(st.fallback?"（"+st.fallback+"）":"");
 $("camlist").innerHTML=c.drivers.map(d=>{const av=d.id==="auto"||(st.drivers[d.id]||{}).available;const lock=d.unofficial&&!allow;
  const err=(st.drivers[d.id]||{}).last_error; return "<label class='drv"+(av&&!lock?"":" dis")+"'><input type=radio name=camdrv value='"+d.id+"'"+(camCfg.driver===d.id?" checked":"")+(av&&!lock?"":" disabled")+"><span><b>"+esc(d.label)+"</b><br><span class=muted>"+esc(d.does)+"。需要："+esc(d.needs)+(d.unofficial?"。"+esc(c.unofficial_warning):"")+(err?"<br>上次："+esc(err):"")+(av?"":"<br>这台电脑上用不了")+"</span></span></label>"}).join("");
 for(const el of document.querySelectorAll("input[name=camdrv]"))el.onchange=()=>camSave({driver:el.value});
 }catch(e){}
}
async function camSave(ch){const body=Object.assign({},camCfg,ch);
 const r=await fetch("/api/camera",{method:"POST",headers:{"Content-Type":"application/json","X-Room-AI":"1"},body:JSON.stringify(body)});
 const j=await r.json(); $("cammsg").textContent=j.ok?"已保存":"没保存："+(j.error&&j.error.message||r.status); camRefresh()}
$("camunoff").onchange=()=>{const on=$("camunoff").checked; camSave(on?{allow_unofficial:true}:{allow_unofficial:false,driver:camCfg.driver==="dji-duml"?"auto":camCfg.driver})};
async function camAct(a,btn){btn.disabled=true;$("cammsg").textContent=a==="pair"?"正在配对：相机屏幕弹出请求时点允许（每个协议等 25 秒，勾了社区协议会弹两次）":"正在让相机切回网络摄像头…";
 try{const r=await fetch("/api/camera/action",{method:"POST",headers:{"Content-Type":"application/json","X-Room-AI":"1"},body:JSON.stringify({action:a})});
 const j=await r.json(); $("cammsg").textContent=j.detail||""}finally{btn.disabled=false;camRefresh()}}
$("campair").onclick=()=>camAct("pair",$("campair")); $("camrecover").onclick=()=>camAct("recover",$("camrecover"));
refresh(); setInterval(refresh,2000); camRefresh(); setInterval(camRefresh,10000);
</script></body></html>"""
