"""Which model does each job: vision, speech-to-text, text-to-speech, each chosen on its own.

Every slot has a source:
- "engine": the engine built into room-companion (llama-server for vision, sherpa-onnx SenseVoice
  for speech-to-text, sherpa-onnx MeloTTS for text-to-speech) — the default, and what the app did
  before this module existed;
- "openai": any OpenAI-compatible server this machine can reach (localhost, the LAN, a server you
  host, or a provider with your key): chat/completions with an image, audio/transcriptions,
  audio/speech;
- "cloud": HipiMind's cloud models, through the HipiMind connector;
- "off": nobody.

The choice comes from the config file's "models" section, and can be changed at run time (from the
HipiMind page); run-time choices are kept in <data_dir>/state/models.json, keys in
<data_dir>/state/model_keys.json, both readable only by this user. Keys are never logged.
"""
from __future__ import annotations

import base64
import io
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
import uuid
import wave

SLOTS = ("vision", "stt", "tts")
SOURCES = ("engine", "openai", "cloud", "off")
TEST_TIMEOUT_S = 15

# 64x64 grey JPEG, so the vision test needs no image library
TEST_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDABALDA4MChAODQ4SERATGCgaGBYWGDEjJR0oOjM9PDkzODdASFxOQERXRTc4UG1R"
    "V19iZ2hnPk1xeXBkeFxlZ2P/2wBDARESEhgVGC8aGi9jQjhCY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2Nj"
    "Y2NjY2NjY2NjY2NjY2P/wAARCABAAEADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAA"
    "AgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6"
    "Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXG"
    "x8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREA"
    "AgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5"
    "OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPE"
    "xcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwAooooAKKKKACiiigAooooAKKKKACiiigAo"
    "oooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooA/9k=")


def normalize_slot(d) -> dict:
    """A ModelSlot with only the fields this module reads; an unknown source reads as "engine"."""
    d = d if isinstance(d, dict) else {}
    src = d.get("source") if d.get("source") in SOURCES else "engine"
    out = {"source": src}
    if src == "openai":
        for k in ("base_url", "model", "voice", "api_key_file", "language"):
            v = d.get(k)
            if isinstance(v, str) and v.strip():
                out[k] = v.strip().rstrip("/") if k == "base_url" else v.strip()
    return out


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_private_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, json.dumps(obj, ensure_ascii=False).encode("utf-8"))
    finally:
        os.close(fd)
    os.replace(tmp, path)


class ModelSettings:
    """The effective slot for each job: run-time choice, else the config file, else "engine"."""

    def __init__(self, cfg: dict, state_dir: str):
        self.static = cfg.get("models") if isinstance(cfg.get("models"), dict) else {}
        self.path = os.path.join(state_dir, "models.json")
        self.keys_path = os.path.join(state_dir, "model_keys.json")
        self._lock = threading.Lock()
        self.runtime = _read_json(self.path)
        self._keys = {k: v for k, v in _read_json(self.keys_path).items() if isinstance(v, str)}

    def slot(self, name: str) -> dict:
        with self._lock:
            if name in self.runtime:
                return normalize_slot(self.runtime[name])
            return normalize_slot(self.static.get(name))

    def preset(self):
        with self._lock:
            p = self.runtime.get("preset", self.static.get("preset"))
            return p if isinstance(p, str) else None

    def key(self, name: str):
        with self._lock:
            k = self._keys.get(name)
        if k:
            return k
        f = self.slot(name).get("api_key_file")
        if f:
            try:
                with open(os.path.expanduser(f), "r", encoding="utf-8") as fh:
                    return fh.read().strip() or None
            except OSError:
                return None
        return None

    def has_key(self, name: str) -> bool:
        return bool(self.key(name))

    def set(self, models: dict, keys: dict | None = None) -> list[str]:
        """Apply a run-time choice; returns the slots that changed. Keys: "" clears one."""
        changed = []
        with self._lock:
            for name in SLOTS:
                if name in (models or {}):
                    new = normalize_slot(models[name])
                    new.pop("api_key_file", None)  # a path on this machine is the config file's business
                    old = normalize_slot(self.runtime[name]) if name in self.runtime else normalize_slot(self.static.get(name))
                    if new != old:
                        changed.append(name)
                    self.runtime[name] = new
            if isinstance((models or {}).get("preset"), str):
                self.runtime["preset"] = models["preset"][:40]
            _write_private_json(self.path, self.runtime)
            if keys:
                for name, v in keys.items():
                    if name in SLOTS and isinstance(v, str):
                        if v:
                            self._keys[name] = v
                        else:
                            self._keys.pop(name, None)
                        if name not in changed:
                            changed.append(name)
                _write_private_json(self.keys_path, self._keys)
        return changed


# ---------------------------------------------------------------- HTTP to OpenAI-compatible servers

class ModelCallError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code, self.message = code, message


def _host_of(url: str) -> str:
    try:
        from urllib.parse import urlsplit
        u = urlsplit(url)
        return u.netloc or url
    except ValueError:
        return url


def http_call(url: str, data: bytes, headers: dict, timeout: float, urlopen=urllib.request.urlopen,
              model: str | None = None):
    """POST and return (status, content-type, body); errors become ModelCallError with a protocol code."""
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    try:
        with urlopen(req, timeout=timeout) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            body = ""
        if e.code in (401, 403):
            raise ModelCallError("unauthorized", f"HTTP {e.code} from {_host_of(url)}: wrong or missing key") from None
        if e.code == 404:
            if "model" in body.lower() and model:
                raise ModelCallError("model_not_found", f"{_host_of(url)} does not know the model {model!r}") from None
            raise ModelCallError("not_found", f"HTTP 404 from {url} (does the base URL end in /v1?)") from None
        if "model" in body.lower() and ("not found" in body.lower() or "does not exist" in body.lower()) and model:
            raise ModelCallError("model_not_found", f"{_host_of(url)} does not know the model {model!r}") from None
        raise ModelCallError("bad_response", f"HTTP {e.code} from {_host_of(url)}") from None
    except (socket.timeout, TimeoutError):
        raise ModelCallError("timeout", f"{_host_of(url)} did not answer within {int(timeout)} s") from None
    except urllib.error.URLError as e:
        reason = e.reason
        if isinstance(reason, (socket.timeout, TimeoutError)):
            raise ModelCallError("timeout", f"{_host_of(url)} did not answer within {int(timeout)} s") from None
        why = getattr(reason, "strerror", None) or str(reason)
        raise ModelCallError("connect_failed", f"Could not connect to {_host_of(url)} ({why})") from None
    except OSError as e:
        raise ModelCallError("connect_failed", f"Could not connect to {_host_of(url)} ({type(e).__name__})") from None


def _auth(key: str | None) -> dict:
    return {"Authorization": "Bearer " + key} if key else {}


def extract_json(content):
    """The first JSON object in a model's reply (servers without schema support wrap it in prose)."""
    if not isinstance(content, str):
        return None
    try:
        return json.loads(content)
    except ValueError:
        pass
    start = content.find("{")
    end = content.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(content[start:end + 1])
        except ValueError:
            return None
    return None


def chat_image(base_url, model, key, jpeg: bytes, prompt: str, timeout, urlopen=urllib.request.urlopen,
               schema: dict | None = None) -> tuple[str, dict]:
    """One chat/completions call with a JPEG; returns (content, full response)."""
    body = {"messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()}},
        {"type": "text", "text": prompt}]}], "temperature": 0.1}
    if model:
        body["model"] = model
    if schema:
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": "observation", "schema": schema}}
    url = base_url.rstrip("/") + "/chat/completions"
    try:
        _, _, raw = http_call(url, json.dumps(body).encode(), {"Content-Type": "application/json", **_auth(key)},
                              timeout, urlopen, model)
    except ModelCallError as e:
        if schema and e.code == "bad_response":
            body.pop("response_format")  # a server without structured output: ask again, parse the prose
            _, _, raw = http_call(url, json.dumps(body).encode(), {"Content-Type": "application/json", **_auth(key)},
                                  timeout, urlopen, model)
        else:
            raise
    try:
        resp = json.loads(raw.decode("utf-8"))
        return resp["choices"][0]["message"]["content"] or "", resp
    except (ValueError, KeyError, IndexError, TypeError):
        raise ModelCallError("bad_response", "the answer is not an OpenAI chat completion") from None


def pcm16_wav(samples, rate=16000) -> bytes:
    """WAV bytes from float samples (-1..1) or from raw 16-bit little-endian PCM bytes."""
    import array
    if isinstance(samples, (bytes, bytearray)):
        pcm = bytes(samples)
    else:
        pcm = array.array("h", (max(-32768, min(32767, int(float(x) * 32767))) for x in samples)).tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def transcribe_wav(base_url, model, key, wav: bytes, timeout, urlopen=urllib.request.urlopen,
                   language: str | None = None) -> str:
    boundary = "----room-companion-" + uuid.uuid4().hex
    parts = []
    fields = {"model": model or "whisper-1", "response_format": "json"}
    if language:
        fields["language"] = language
    for k, v in fields.items():
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"audio.wav\"\r\n"
                 f"Content-Type: audio/wav\r\n\r\n".encode() + wav + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    _, _, raw = http_call(base_url.rstrip("/") + "/audio/transcriptions", b"".join(parts),
                          {"Content-Type": f"multipart/form-data; boundary={boundary}", **_auth(key)},
                          timeout, urlopen, model)
    try:
        d = json.loads(raw.decode("utf-8"))
        if isinstance(d, dict) and isinstance(d.get("text"), str):
            return d["text"].strip()
    except ValueError:
        pass
    raise ModelCallError("bad_response", "the answer has no transcription text")


def speech_wav(base_url, model, key, text: str, voice: str | None, timeout, urlopen=urllib.request.urlopen) -> bytes:
    body = {"model": model or "tts-1", "input": text, "voice": voice or "alloy", "response_format": "wav"}
    _, ctype, raw = http_call(base_url.rstrip("/") + "/audio/speech", json.dumps(body).encode(),
                              {"Content-Type": "application/json", **_auth(key)}, timeout, urlopen, model)
    if not raw or ctype.startswith("application/json"):
        raise ModelCallError("bad_response", "the answer is not audio")
    return raw


class WavAudio:
    """What sherpa's OfflineTts.generate returns, built from WAV bytes: .samples (floats) and .sample_rate."""

    def __init__(self, wav: bytes):
        import array
        with wave.open(io.BytesIO(wav), "rb") as w:
            if w.getsampwidth() != 2:
                raise ModelCallError("bad_response", "only 16-bit WAV speech is supported")
            ch, rate, frames = w.getnchannels(), w.getframerate(), w.readframes(w.getnframes())
        a = array.array("h")
        a.frombytes(frames[: len(frames) - len(frames) % 2])
        if ch > 1:
            a = a[::ch]
        self.samples = [x / 32768.0 for x in a]
        self.sample_rate = rate


# ---------------------------------------------------------------- slot clients

class OpenAIVision:
    """AI gate client for an OpenAI-compatible vision server: one frame in, one scene observation out."""

    def __init__(self, slot: dict, key_fn, urlopen=urllib.request.urlopen, timeout=90):
        self.slot, self.key_fn, self.urlopen, self.timeout = slot, key_fn, urlopen, timeout
        self.last_seconds, self.errors, self.last_error, self.ok = None, 0, None, None

    def send(self, kind, payload):
        return False  # transcripts are not forwarded to the model in this version

    def ask(self, kind, payload):
        from .vision import PROMPT, SCHEMA, parse_observation
        if kind != "frame":
            return None
        t = time.time()
        try:
            content, _ = chat_image(self.slot["base_url"], self.slot.get("model"), self.key_fn(), payload["jpeg"],
                                    PROMPT, self.timeout, self.urlopen, SCHEMA)
        except (ModelCallError, KeyError) as e:
            self.errors += 1
            self.ok = False
            self.last_error = getattr(e, "message", str(e))[:200]
            return None
        self.last_seconds = round(time.time() - t, 2)
        obs = parse_observation(json.dumps(extract_json(content)) if extract_json(content) is not None else content)
        self.ok = obs is not None
        if obs is None:
            self.errors += 1
            self.last_error = "unparseable answer"
        return obs


class CloudVision:
    """AI gate client that asks HipiMind's cloud vision model through the connector."""

    def __init__(self, cloud):
        self.cloud = cloud
        self.errors, self.last_error, self.ok = 0, None, None

    def send(self, kind, payload):
        return False

    def ask(self, kind, payload):
        from .vision import PROMPT, SCENES, parse_observation
        if kind != "frame" or self.cloud is None:
            return None
        prompt = PROMPT + " 只输出一个 JSON 对象，字段：person, scene（" + "/".join(SCENES) + "）, hot_oil, on_phone_call, note。"
        res = self.cloud("infer", prompt=prompt, images=[base64.b64encode(payload["jpeg"]).decode()], kind="scene")
        if not res.get("ok"):
            self.errors += 1
            self.ok = False
            self.last_error = ((res.get("error") or {}).get("code") or "unavailable")[:60]
            return None
        d = extract_json(res.get("text"))
        obs = parse_observation(json.dumps(d)) if d is not None else None
        self.ok = obs is not None
        return obs


class RemoteSpeech:
    """Speech-to-text on a server: the local VAD still cuts utterances; only the cut segment is sent.

    Sent only while `allowed()` is true (the AI switch): with AI off, speech leaves the machine for nobody.
    """

    def __init__(self, vad, transcribe, allowed):
        self.vad, self._transcribe, self.allowed = vad, transcribe, allowed
        self.ready = True
        self.errors, self.last_error, self.dropped = 0, None, 0

    def accept(self, pcm):
        return self.vad.accept(pcm)

    def reset(self):
        self.vad.reset()

    def seconds(self, seg):
        return self.vad.seconds(seg)

    def transcribe(self, seg) -> str:
        if not self.allowed():
            self.dropped += 1
            return ""
        try:
            return self._transcribe(pcm16_wav(seg))
        except ModelCallError as e:
            self.errors += 1
            self.last_error = e.message[:200]
            return ""


class RemoteTTS:
    """Looks like sherpa's OfflineTts to the Speaker: generate(text) -> .samples/.sample_rate."""

    def __init__(self, synth):
        self.synth = synth

    def generate(self, text, sid=0, speed=1.0):
        return WavAudio(self.synth(text))


def cloud_transcriber(cloud, language=None):
    def go(wav: bytes) -> str:
        res = cloud("transcribe", audio=base64.b64encode(wav).decode(), language=language)
        if not res.get("ok"):
            raise ModelCallError((res.get("error") or {}).get("code") or "unavailable", "cloud speech-to-text refused")
        return str(res.get("text") or "").strip()
    return go


def cloud_synth(cloud, language=None):
    def go(text: str) -> bytes:
        res = cloud("speak", text=text[:300], language=language)
        if not res.get("ok"):
            raise ModelCallError((res.get("error") or {}).get("code") or "unavailable", "cloud speech refused")
        return base64.b64decode(res.get("audio") or "")
    return go


# ---------------------------------------------------------------- "Test connection"

def test_slot(slot_name: str, slot: dict, key: str | None, cloud=None, engine_check=None,
              urlopen=urllib.request.urlopen, timeout=TEST_TIMEOUT_S) -> dict:
    """One small real request with exactly this setting. Returns {"ok", "result"|"error"}; never raises."""
    slot = normalize_slot(slot)
    src = slot["source"]
    t0 = time.time()
    try:
        if src == "off":
            return {"ok": False, "error": {"code": "unsupported", "message": "this slot is off"}}
        if src == "engine":
            if engine_check is None:
                raise ModelCallError("engine_unavailable", "this device has no built-in engine for " + slot_name)
            detail = engine_check(slot_name)
            return {"ok": True, "result": {"model": detail.get("model"), "latency_ms": int((time.time() - t0) * 1000),
                                           "detail": detail.get("detail", "")}}
        if src == "cloud":
            if cloud is None:
                raise ModelCallError("connect_failed", "not connected to HipiMind")
            if slot_name == "vision":
                res = cloud("infer", prompt="Reply with OK", images=[base64.b64encode(TEST_JPEG).decode()], kind="test")
            elif slot_name == "stt":
                res = cloud("transcribe", audio=base64.b64encode(pcm16_wav(b"\x00\x00" * 16000)).decode())
            else:
                res = cloud("speak", text="test")
            if not res.get("ok"):
                err = res.get("error") or {}
                raise ModelCallError(err.get("code") or "unavailable", err.get("message") or "HipiMind cloud refused")
            return {"ok": True, "result": {"model": "hipimind-cloud", "latency_ms": int((time.time() - t0) * 1000),
                                           "detail": "HipiMind cloud answered"}}
        base, model = slot.get("base_url"), slot.get("model")
        if not base:
            raise ModelCallError("bad_request", "a base URL is needed")
        if slot_name == "vision":
            content, resp = chat_image(base, model, key, TEST_JPEG, "Reply with OK", timeout, urlopen)
            usage = (resp.get("usage") or {}).get("completion_tokens")
            detail = "HTTP 200" + (f", {usage} tokens" if isinstance(usage, int) else "")
            name = resp.get("model") or model
        elif slot_name == "stt":
            transcribe_wav(base, model, key, pcm16_wav(b"\x00\x00" * 16000), timeout, urlopen, slot.get("language"))
            detail, name = "HTTP 200, transcription returned", model
        else:
            wav = speech_wav(base, model, key, "test", slot.get("voice"), timeout, urlopen)
            detail, name = f"HTTP 200, {len(wav)} bytes of audio", model
        return {"ok": True, "result": {"model": name, "latency_ms": int((time.time() - t0) * 1000), "detail": detail}}
    except ModelCallError as e:
        return {"ok": False, "error": {"code": e.code, "message": e.message[:300]}}
    except Exception as e:  # a test must never take the device down
        return {"ok": False, "error": {"code": "bad_response", "message": type(e).__name__}}
