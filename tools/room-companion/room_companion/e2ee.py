"""End-to-end encryption on the Room device: its place in the owner's MLS group, and what it seals for
HipiMind to relay without reading (HipiMind's protocol v2, §9). The formats it shares with the owner's
pages are in docs/e2ee.md; the keys are hm-seal's (sunkit tools/hm-seal, Python binding `hm_seal`).

`DeviceGroup` keeps everything in one directory, readable only by this user: the hm-seal save (the
device's private keys), the account's data keys, and where the device is in the group log. It never
makes a commit: an admin page adds and removes it, and it applies commits only from the group log, in
the log's order.

Without the `hm_seal` binding, `available()` is False and the device stays on protocol v1.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import os
import re
from dataclasses import dataclass

try:
    import hm_seal
except ImportError:  # pragma: no cover - the binding is optional
    hm_seal = None

log = logging.getLogger("room_companion.e2ee")

PAIRING_PREFIX = "hmroom1."
SECRET_BYTES = 16
SIGNATURE_KEY_BYTES = 32
PAIRING_ID_BYTES = 16
DATA_KEY_ID_BYTES = 8
DATA_KEY_BYTES = 32
#: HipiMind's limits for group bodies and sealed messages (§9.2, §9.6) and sealed events (§9.3).
GROUP_MAX_CHARS = 60_000
SEALED_MAX_CHARS = 60_000
SEALED_EVENT_MIN_CHARS = 56
SEALED_EVENT_MAX_CHARS = 16_384
REQ_MAX_CHARS = 64
FRAME_VERSION = 0x01

_PAIRING_ID_LABEL = b"hm-room pairing id v1"
_JOIN_LABEL = b"hm-room join v1"
_PAIRING_BODY = re.compile(r"[A-Za-z0-9_-]{64}")
_BASE64 = re.compile(r"(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?")

SAVE_FILE = "member.save"
KEYS_FILE = "keys.json"
GROUP_FILE = "group.json"


def available() -> bool:
    return hm_seal is not None


class PairingRefused(ValueError):
    """A pairing code this device will not use, or pairing that cannot start now."""


@dataclass(frozen=True)
class PairingCode:
    secret: bytes
    admin_key: bytes

    @property
    def pairing_id(self) -> bytes:
        return pairing_id(self.secret)


@dataclass(frozen=True)
class Command:
    """A command a page sent, opened and from an admin device."""
    sender_key: bytes
    req: str
    cmd: dict


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def unb64(text, length: int | None = None) -> bytes | None:
    """Standard base64 with padding, or None. With `length`, only exactly that many bytes."""
    if not isinstance(text, str) or not _BASE64.fullmatch(text):
        return None
    try:
        raw = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        return None
    if length is not None and len(raw) != length:
        return None
    return raw


def parse_pairing_code(text) -> PairingCode:
    """The code an admin page shows as a QR code (docs/e2ee.md). Anything else is refused."""
    if not isinstance(text, str):
        raise PairingRefused("not a pairing code")
    text = text.strip()
    if not text.startswith(PAIRING_PREFIX):
        raise PairingRefused("not a HipiMind Room pairing code")
    body = text[len(PAIRING_PREFIX):]
    if not _PAIRING_BODY.fullmatch(body):
        raise PairingRefused("the pairing code is damaged")
    raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
    if len(raw) != SECRET_BYTES + SIGNATURE_KEY_BYTES:  # pragma: no cover - 64 characters are 48 bytes
        raise PairingRefused("the pairing code is damaged")
    return PairingCode(secret=raw[:SECRET_BYTES], admin_key=raw[SECRET_BYTES:])


def pairing_code(secret: bytes, admin_key: bytes) -> str:
    """The text of a pairing code: what an admin page shows (the tests' page uses it)."""
    raw = secret + admin_key
    return PAIRING_PREFIX + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def pairing_id(secret: bytes) -> bytes:
    return hashlib.sha256(_PAIRING_ID_LABEL + secret).digest()[:PAIRING_ID_BYTES]


def join_mac(secret: bytes, signature_key: bytes, key_package: bytes) -> bytes:
    msg = (_JOIN_LABEL + len(signature_key).to_bytes(4, "big") + signature_key
           + len(key_package).to_bytes(4, "big") + key_package)
    return hmac.new(secret, msg, hashlib.sha256).digest()


def check_join(secret: bytes, envelope: dict) -> tuple[bytes, bytes]:
    """The admin's check of a join request (docs/e2ee.md): (signature key, key package) to add, or
    PairingRefused. Here as the reference for the page, and for the tests' page."""
    if not isinstance(envelope, dict) or envelope.get("t") != "join":
        raise PairingRefused("not a join request")
    pid = unb64(envelope.get("id"), PAIRING_ID_BYTES)
    key = unb64(envelope.get("key"), SIGNATURE_KEY_BYTES)
    kp = unb64(envelope.get("kp"))
    mac = unb64(envelope.get("mac"), 32)
    if pid is None or key is None or not kp or mac is None:
        raise PairingRefused("a malformed join request")
    if not hmac.compare_digest(pid, pairing_id(secret)):
        raise PairingRefused("a join request for another code")
    if not hmac.compare_digest(mac, join_mac(secret, key, kp)):
        raise PairingRefused("a join request that does not match the code")
    return key, kp


def encode_body(envelope: dict) -> str:
    """A group log body: base64 of the JSON object, with "v": 1."""
    return b64(json.dumps({"v": 1, **envelope}, separators=(",", ":"), sort_keys=True).encode("utf-8"))


def decode_body(body) -> dict | None:
    raw = unb64(body)
    if raw is None:
        return None
    try:
        envelope = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(envelope, dict) or type(envelope.get("v")) is not int or envelope["v"] != 1 \
            or not isinstance(envelope.get("t"), str):
        return None
    return envelope


def _purpose(kind: str, device_id: str) -> bytes:
    return f"hm-room {kind} v1".encode("ascii") + b"\x00" + device_id.encode("ascii")


def event_purpose(device_id: str) -> bytes:
    return _purpose("event", device_id)


def state_purpose(device_id: str) -> bytes:
    return _purpose("state", device_id)


def frame_meta(device_id: str) -> bytes:
    return _purpose("frame", device_id)


def _write_private(path: str, data: bytes):
    """Replace `path` atomically with `data`, readable only by this user: a temporary file, fsync,
    rename. An old save still decrypts what came after it, so no copy is left behind."""
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    dfd = os.open(os.path.dirname(path) or ".", os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


def _short(e: BaseException) -> str:
    return str(e)[:200]


class DeviceGroup:
    """This device's place in its owner's group. Not thread-safe: one connection drives it.

    status: "unpaired", "joining" (a join request is out), "joined", "removed" (an admin removed this
    device), or "broken" (its save could not be read or written; pair again).
    """

    def __init__(self, directory: str, device_id: str, name: str = "room", hm=None):
        self._hm = hm if hm is not None else hm_seal
        if self._hm is None:
            raise RuntimeError("the hm_seal binding is not installed")
        if not isinstance(device_id, str) or not device_id or not device_id.isascii():
            raise ValueError("the device id must be HipiMind's id for this device")
        self.directory = os.path.expanduser(directory)
        self.device_id = device_id
        self.name = name
        os.makedirs(self.directory, mode=0o700, exist_ok=True)
        os.chmod(self.directory, 0o700)
        self._member = None
        self._sealer = None
        self._keys: list[tuple[bytes, bytes]] = []
        self.status = "unpaired"
        self.reason: str | None = None
        self._admin_key: bytes | None = None
        self._last: int | None = None
        self._join_body: str | None = None
        self.skipped = 0
        #: How the last `open_command` went: "ok", "later" (for an epoch this device has not reached
        #: yet: try again once the log has been read further) or "refused".
        self.open_outcome: str | None = None
        self._load()

    # --- persistence -------------------------------------------------------------------------------

    def _path(self, name: str) -> str:
        return os.path.join(self.directory, name)

    def _load(self):
        try:
            with open(self._path(GROUP_FILE), "r", encoding="utf-8") as f:
                state = json.load(f)
        except FileNotFoundError:
            return
        except (OSError, ValueError):
            self._break("the group state could not be read")
            return
        if not isinstance(state, dict):
            self._break("the group state could not be read")
            return
        status = state.get("status")
        self.reason = state.get("reason") if isinstance(state.get("reason"), str) else None
        if status in ("unpaired", "removed"):
            self.status = status
            return
        if status not in ("joining", "joined"):
            self._break("the group state could not be read")
            return
        last = state.get("last_seq")
        admin = unb64(state.get("admin_key"), SIGNATURE_KEY_BYTES) if state.get("admin_key") else None
        if (last is not None and (not isinstance(last, int) or isinstance(last, bool) or last < 0)) or \
                (status == "joining" and admin is None):
            self._break("the group state could not be read")
            return
        if state.get("device_id") != self.device_id:
            # Paired to HipiMind again (a new device id, perhaps another account): the old account's
            # group and keys do not go to the new one.
            self._end("unpaired", "this device was paired to HipiMind again; scan a new code")
            return
        try:
            with open(self._path(SAVE_FILE), "rb") as f:
                self._member = self._hm.Member.load(f.read())
        except (OSError, self._hm.SealError):
            self._member = None
            self._break("this device's keys could not be read")
            return
        try:
            with open(self._path(KEYS_FILE), "r", encoding="utf-8") as f:
                stored = json.load(f)
            self._keys = [(unb64(k["id"], DATA_KEY_ID_BYTES), unb64(k["key"], DATA_KEY_BYTES)) for k in stored["keys"]]
            if any(i is None or k is None for i, k in self._keys):
                raise ValueError("a data key is damaged")
        except FileNotFoundError:
            self._keys = []
        except (OSError, ValueError, KeyError, TypeError):
            self._member = None
            self._keys = []
            self._break("the data keys could not be read")
            return
        self.status = status
        self._admin_key = admin
        self._last = last
        join = state.get("join")
        self._join_body = join if status == "joining" and last is None and isinstance(join, str) else None
        self.skipped = state.get("skipped") if isinstance(state.get("skipped"), int) else 0

    def _save_state(self):
        state = {"status": self.status, "device_id": self.device_id, "last_seq": self._last, "skipped": self.skipped}
        if self.reason:
            state["reason"] = self.reason
        if self._admin_key is not None and self.status == "joining":
            state["admin_key"] = b64(self._admin_key)
        if self._join_body is not None and self.status == "joining":
            state["join"] = self._join_body
        _write_private(self._path(GROUP_FILE), json.dumps(state).encode("utf-8"))

    def _save_member(self) -> bool:
        """Save after every call that changes the group or its keys (hm-seal's README). False, and
        the device is broken, when the member refuses to save (hm-seal: a damaged state)."""
        try:
            data = self._member.save()
        except self._hm.SealError as e:
            self._break(f"this device's keys are damaged ({_short(e)})")
            return False
        _write_private(self._path(SAVE_FILE), data)
        return True

    def _save_keys(self):
        stored = {"keys": [{"id": b64(i), "key": b64(k)} for i, k in self._keys]}
        _write_private(self._path(KEYS_FILE), json.dumps(stored).encode("utf-8"))

    def _wipe(self):
        for name in (SAVE_FILE, KEYS_FILE):
            try:
                os.remove(self._path(name))
            except FileNotFoundError:
                pass
        self._member = None
        self._sealer = None
        self._keys = []
        self._admin_key = None
        self._last = None
        self._join_body = None

    def _end(self, status: str, reason: str | None):
        self._wipe()
        self.status = status
        self.reason = reason
        self.skipped = 0
        self._save_state()

    def _break(self, reason: str):
        self._member = None
        self._sealer = None
        self.status = "broken"
        self.reason = reason
        log.warning("end-to-end encryption is off: %s; pair the device again", reason)

    # --- pairing -----------------------------------------------------------------------------------

    def start_pairing(self, code) -> str:
        """Start joining the group of the admin whose code was scanned: the body to append to the
        group log (a `join` request). Then call `join_sent` with the number HipiMind gave it."""
        parsed = parse_pairing_code(code)
        if self.status == "joined":
            raise PairingRefused("this device is already in a group; an admin removes it first")
        self._wipe()
        member = self._hm.Member(self.name.encode("utf-8"))
        key = member.signature_key()
        kp = member.key_package()
        self._member = member
        if not self._save_member():
            raise PairingRefused(self.reason or "this device's keys could not be saved")
        body = encode_body({"t": "join", "id": b64(parsed.pairing_id), "key": b64(key), "kp": b64(kp),
                            "mac": b64(join_mac(parsed.secret, key, kp))})
        if len(body) > GROUP_MAX_CHARS:  # pragma: no cover - a key package is a few hundred bytes
            raise PairingRefused("the join request is too large")
        self.status = "joining"
        self.reason = None
        self._admin_key = parsed.admin_key
        self._last = None
        self._join_body = body
        self.skipped = 0
        self._save_state()
        return body

    def pending_join(self) -> str | None:
        """A join request HipiMind has not numbered yet (the connection dropped, or the device restarted
        before `join_sent`): append it again. It holds no secret: only the MAC the code's secret made."""
        return self._join_body if self.status == "joining" and self._last is None else None

    def join_sent(self, seq: int):
        """HipiMind numbered this device's join request `seq`: the Welcome comes after it."""
        if self.status == "joining" and _is_seq(seq):
            self._last = seq
            self._join_body = None
            self._save_state()

    def fell_behind(self):
        """The log no longer has the next number this device needs (it was away for longer than the log
        keeps messages, 30 days): it can never catch up, and an admin has to add it again."""
        self._end("unpaired", "the group log no longer has what this device missed; pair it again")

    @property
    def last_seq(self) -> int | None:
        """The last number of the group log this device has dealt with: ask for everything after it."""
        return self._last

    def signature_key(self) -> bytes | None:
        return self._member.signature_key() if self._member is not None else None

    def epoch(self) -> int | None:
        if self.status != "joined":
            return None
        try:
            return self._member.epoch()
        except self._hm.SealError:  # pragma: no cover - a damaged member refuses every call
            return None

    # --- the group log -----------------------------------------------------------------------------

    def process(self, seq: int, body) -> list[tuple]:
        """Deal with group log message `seq`, strictly in order. What happened, for the caller:

        ("gap", n)        — ask for everything after n first; this one was not processed
        ("joined", epoch) — then ("rewind", n): ask for everything after n again
        ("pairing_failed", reason)
        ("commit", epoch, by, added, removed) / ("refused", epoch, by, added, removed)
        ("datakey", id)   — a new data key: send the events and state that were waiting
        ("removed",)      — an admin removed this device; everything was wiped
        ("skipped", seq, why) / ("ignored", seq, why)
        ("broken", reason)
        """
        if not _is_seq(seq):
            raise ValueError("a group log number is a positive integer")
        if self.status not in ("joining", "joined") or self._last is None or seq <= self._last:
            return []
        if seq != self._last + 1:
            return [("gap", self._last)]
        envelope = decode_body(body)
        if self.status == "joining":
            out = self._process_joining(seq, envelope)
        else:
            out = self._process_joined(seq, envelope)
        if self.status in ("joining", "joined") and not any(o[0] == "rewind" for o in out):
            self._last = seq
            self._save_state()
        return out

    def _process_joining(self, seq: int, envelope: dict | None) -> list[tuple]:
        if envelope is None or envelope.get("t") != "welcome":
            return []
        to = unb64(envelope.get("to"), SIGNATURE_KEY_BYTES)
        if to is None or to != self._member.signature_key():
            return []
        welcome = unb64(envelope.get("welcome"))
        after = envelope.get("after")
        if not welcome or not _is_count(after):
            return [("ignored", seq, "a malformed Welcome")]
        try:
            self._member.join(welcome, self._admin_key)
        except self._hm.WrongDevice:
            # Not from the device whose code was scanned. hm-seal has used up the key package, so
            # pairing starts again with a new code.
            reason = "a Welcome from a device other than the one whose code was scanned"
            self._end("unpaired", reason)
            return [("pairing_failed", reason)]
        except self._hm.SealError as e:
            reason = f"the Welcome could not be read ({_short(e)})"
            self._end("unpaired", reason)
            return [("pairing_failed", reason)]
        if not self._save_member():
            return [("broken", self.reason)]
        self.status = "joined"
        self._admin_key = None
        # Read the log again from just after what the admin had seen: the commit that added this
        # device is for an earlier epoch and is skipped; a commit for this epoch that another admin
        # appended before the Welcome is applied. Never past the Welcome itself.
        self._last = min(after, seq - 1)
        self._save_state()
        return [("joined", self._member.epoch()), ("rewind", self._last)]

    def _process_joined(self, seq: int, envelope: dict | None) -> list[tuple]:
        if envelope is None:
            return [("ignored", seq, "not a group message")]
        if envelope.get("t") != "mls":
            return []
        message = unb64(envelope.get("msg"))
        if not message:
            return [("ignored", seq, "a malformed MLS message")]
        try:
            got = self._member.handle(message)
        except self._hm.Removed:
            self._end("removed", "an admin removed this device")
            return [("removed",)]
        except self._hm.SealError as e:
            if not self._save_member():
                return [("broken", self.reason)]
            self.skipped += 1
            return [("skipped", seq, _short(e))]
        if not self._save_member():
            return [("broken", self.reason)]
        kind = got[0]
        if kind == "commit":
            self._sealer = None
            return [("commit", *got[1:])]
        if kind == "refused":
            return [("refused", *got[1:])]
        return self._log_application(seq, got[3], got[2])

    def _log_application(self, seq: int, sender_key: bytes, payload: bytes) -> list[tuple]:
        message = _json_object(payload)
        if message is None or message.get("t") != "datakey":
            return [("ignored", seq, "an application message this device does not use")]
        if sender_key not in self._member.admins():
            return [("ignored", seq, "a data key from a device that is not an admin")]
        key_id = unb64(message.get("id"), DATA_KEY_ID_BYTES)
        key = unb64(message.get("key"), DATA_KEY_BYTES)
        if key_id is None or key is None:
            return [("ignored", seq, "a malformed data key")]
        if any(i == key_id for i, _ in self._keys):
            return [("ignored", seq, "a data key id seen before")]
        self._keys.append((key_id, key))
        self._save_keys()
        return [("datakey", key_id.hex())]

    # --- sealed messages ---------------------------------------------------------------------------

    def open_command(self, body) -> Command | None:
        """A command a page sent as a sealed message (docs/e2ee.md), or None. Only an application
        message is read (a commit is refused before it is decrypted and still applies from the log),
        and only a command from an admin device is returned."""
        self.open_outcome = "refused"
        if self.status != "joined":
            return None
        message = unb64(body)
        if not message:
            return None
        try:
            got = self._member.handle_application(message)
        except self._hm.Removed:
            self._end("removed", "an admin removed this device")
            return None
        except self._hm.SealError as e:
            # OpenMLS refuses a message for a later epoch before decrypting it, so it opens once this
            # device has applied that epoch's commit from the log.
            if "WrongEpoch" in str(e):
                self.open_outcome = "later"
            else:
                log.info("a sealed message did not open: %s", _short(e))
            self._save_member()
            return None
        if not self._save_member():
            return None
        sender_key, payload = got[3], got[2]
        if sender_key not in self._member.admins():
            log.warning("refused a command from a device that is not an admin")
            return None
        command = _json_object(payload)
        if command is None or command.get("t") != "cmd":
            return None
        req, cmd = command.get("req"), command.get("cmd")
        if not isinstance(req, str) or not req or len(req) > REQ_MAX_CHARS or not isinstance(cmd, dict) \
                or not isinstance(cmd.get("type"), str):
            return None
        self.open_outcome = "ok"
        return Command(sender_key=sender_key, req=req, cmd=cmd)

    def seal_message(self, message: dict) -> str | None:
        """An answer for the owner's pages, as an MLS application message (sealed `body`)."""
        if self.status != "joined":
            return None
        try:
            sealed = self._member.seal(json.dumps(message, separators=(",", ":")).encode("utf-8"))
        except self._hm.SealError as e:
            log.warning("could not seal a message: %s", _short(e))
            return None
        if not self._save_member():
            return None
        body = b64(sealed)
        return body if len(body) <= SEALED_MAX_CHARS else None

    def has_data_key(self) -> bool:
        return self.status == "joined" and bool(self._keys)

    def _seal_with_data_key(self, purpose: bytes, obj: dict, limit: int, minimum: int = 4) -> str | None:
        if not self.has_data_key():
            return None
        key_id, raw = self._keys[-1]
        blob = self._hm.DataKey.from_bytes(raw).seal(purpose, json.dumps(obj, separators=(",", ":"),
                                                                          ensure_ascii=False).encode("utf-8"))
        body = b64(key_id + blob)
        return body if minimum <= len(body) <= limit else None

    def seal_event(self, event: dict) -> str | None:
        """A sealed event's body (§9.3), or None: no data key yet, or too large."""
        return self._seal_with_data_key(event_purpose(self.device_id), event, SEALED_EVENT_MAX_CHARS,
                                        SEALED_EVENT_MIN_CHARS)

    def seal_state(self, state: dict) -> str | None:
        """The state to send with `keep` (§9.2), or None: no data key yet, or too large."""
        return self._seal_with_data_key(state_purpose(self.device_id), state, SEALED_MAX_CHARS)

    def seal_frame(self, jpeg: bytes) -> bytes | None:
        """A live frame (§9.1): 0x01, then the SFrame. None when not in a group."""
        if self.status != "joined":
            return None
        try:
            if self._sealer is None:
                self._sealer = self._member.frame_sealer()
            return bytes([FRAME_VERSION]) + self._sealer.seal(jpeg, frame_meta(self.device_id))
        except self._hm.SealError as e:
            log.warning("could not seal a frame: %s", _short(e))
            self._sealer = None
            return None

    def forget(self):
        """Leave encryption on this device: the keys and the place in the group are deleted."""
        self._end("unpaired", None)


def _is_seq(n) -> bool:
    return isinstance(n, int) and not isinstance(n, bool) and n >= 1


def _is_count(n) -> bool:
    return isinstance(n, int) and not isinstance(n, bool) and n >= 0


def _json_object(payload: bytes) -> dict | None:
    try:
        message = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return message if isinstance(message, dict) else None
