"""The Python binding hands each promise of hm-seal through unchanged."""

import hashlib
import threading

import pytest

import hm_seal


def trio():
    phone, room, laptop = hm_seal.Member(b"phone"), hm_seal.Member(b"room"), hm_seal.Member(b"laptop")
    phone.create_group(b"account-1")
    commit, welcome = phone.add(room.key_package())
    room.join(welcome)
    commit, welcome = phone.add(laptop.key_package())
    assert room.handle(commit) == ("commit", 2, b"")
    laptop.join(welcome)
    return phone, room, laptop


def leaf_of(member, name):
    return next(leaf for leaf, n in member.members() if n == name)


def test_every_device_reads_the_others_and_knows_who_sent():
    phone, room, laptop = trio()
    msg = phone.seal(b"video off")
    assert isinstance(msg, bytes)
    for other in (room, laptop):
        assert other.handle(msg) == ("application", phone.leaf_index(), b"video off")
    back = room.seal(b"done")
    assert phone.handle(back) == ("application", room.leaf_index(), b"done")
    assert sorted(n for _, n in phone.members()) == [b"laptop", b"phone", b"room"]


def test_a_removed_device_is_told_so_and_reads_nothing_after():
    phone, room, laptop = trio()
    commit = phone.remove(leaf_of(phone, b"laptop"))
    assert room.handle(commit)[0] == "commit"
    with pytest.raises(hm_seal.Removed):
        laptop.handle(commit)
    assert issubclass(hm_seal.Removed, hm_seal.SealError) and issubclass(hm_seal.SealError, ValueError)
    after = phone.seal(b"camera back on")
    assert room.handle(after)[2] == b"camera back on"
    with pytest.raises(hm_seal.SealError):
        laptop.handle(after)


def test_frames_open_only_under_their_metadata_and_only_once():
    phone, room, _ = trio()
    opener = hm_seal.FrameOpener()
    phone.update_opener(opener)
    sealer = room.frame_sealer()
    frame = sealer.seal(b"jpeg", b"device-1")
    with pytest.raises(hm_seal.SealError):
        opener.open(frame, b"device-2")
    assert opener.open(frame, b"device-1") == b"jpeg"
    with pytest.raises(hm_seal.SealError):
        opener.open(frame, b"device-1")
    plain = sealer.seal(b"jpeg2")
    assert opener.open(plain) == b"jpeg2"
    assert room.frame_sealer().seal(b"x") != room.frame_sealer().seal(b"x")


def test_a_device_saved_and_loaded_goes_on():
    phone, room, _ = trio()
    saved = room.save()
    assert isinstance(saved, bytes)
    room2 = hm_seal.Member.load(saved)
    assert room2.signature_key() == room.signature_key() and room2.epoch() == room.epoch()
    assert room2.handle(phone.seal(b"after restart")) == ("application", phone.leaf_index(), b"after restart")
    with pytest.raises(hm_seal.SealError):
        hm_seal.Member.load(saved[:-1])


def test_stored_data_opens_only_with_its_key_and_purpose_and_recovers():
    key = hm_seal.DataKey.generate()
    blob = key.seal(b"room-event", b"sat for 90 minutes")
    assert key.open(b"room-event", blob) == b"sat for 90 minutes"
    with pytest.raises(hm_seal.SealError):
        key.open(b"vlog-edit", blob)
    raw = key.to_bytes()
    assert len(raw) == 32 and hm_seal.DataKey.from_bytes(raw).open(b"room-event", blob) == b"sat for 90 minutes"
    secret = bytes(range(32))
    wrapped = key.wrap_for_recovery(secret)
    assert hm_seal.DataKey.unwrap_from_recovery(secret, wrapped).to_bytes() == raw
    with pytest.raises(hm_seal.SealError):
        hm_seal.DataKey.unwrap_from_recovery(bytes(32), wrapped)
    with pytest.raises((ValueError, TypeError)):
        key.wrap_for_recovery(b"too short")


def test_a_member_can_be_used_from_another_thread():
    phone, room, _ = trio()
    out = []
    t = threading.Thread(target=lambda: out.append(room.handle(phone.seal(b"from a thread"))))
    t.start()
    t.join()
    assert out == [("application", phone.leaf_index(), b"from a thread")]


def test_a_damaged_save_raises_seal_error_not_a_panic():
    _, room, _ = trio()
    saved = bytearray(room.save())
    saved[bytes(saved).index(b'"mac_value"') + 1] ^= 0x20
    with pytest.raises(hm_seal.SealError):
        hm_seal.Member.load(bytes(saved))
    # Under a matching digest the damage reaches OpenMLS, which unwraps what it reads.
    body = saved[:-32]
    with pytest.raises(hm_seal.SealError):
        hm_seal.Member.load(bytes(body) + hashlib.sha256(body).digest())
