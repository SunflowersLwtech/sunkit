"""The Python binding hands each promise of hm-seal through unchanged."""

import hashlib
import os
import pathlib
import threading

import pytest

import hm_seal


def trio():
    phone, room, laptop = hm_seal.Member(b"phone"), hm_seal.Member(b"room"), hm_seal.Member(b"laptop")
    phone.create_group(b"account-1")
    commit, welcome = phone.add(room.key_package(), room.signature_key())
    room.join(welcome, phone.signature_key())
    commit, welcome = phone.add(laptop.key_package(), laptop.signature_key())
    assert room.handle(commit) == ("commit", 2, phone.signature_key(), [laptop.signature_key()], [])
    laptop.join(welcome, phone.signature_key())
    return phone, room, laptop


def leaf_of(member, name):
    return next(leaf for leaf, n in member.members() if n == name)


def test_every_device_reads_the_others_and_knows_who_sent():
    phone, room, laptop = trio()
    msg = phone.seal(b"video off")
    assert isinstance(msg, bytes)
    for other in (room, laptop):
        assert other.handle(msg) == ("application", phone.leaf_index(), b"video off", phone.signature_key())
    back = room.seal(b"done")
    assert phone.handle(back) == ("application", room.leaf_index(), b"done", room.signature_key())
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
    assert room2.handle(phone.seal(b"after restart")) == ("application", phone.leaf_index(), b"after restart", phone.signature_key())
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
    with pytest.raises((ValueError, TypeError)):
        key.wrap_for_recovery(bytes(range(33)))


def test_a_member_can_be_used_from_another_thread():
    phone, room, _ = trio()
    out = []
    t = threading.Thread(target=lambda: out.append(room.handle(phone.seal(b"from a thread"))))
    t.start()
    t.join()
    assert out == [("application", phone.leaf_index(), b"from a thread", phone.signature_key())]


def test_pairing_refuses_another_device_on_either_side():
    phone, room, _ = trio()
    tablet, relay = hm_seal.Member(b"tablet"), hm_seal.Member(b"tablet")
    with pytest.raises(hm_seal.WrongDevice):
        phone.add(relay.key_package(), tablet.signature_key())
    assert issubclass(hm_seal.WrongDevice, hm_seal.SealError)
    # The phone's Welcome, but the device was told to expect the room's key.
    _, welcome = phone.add(tablet.key_package(), tablet.signature_key())
    with pytest.raises(hm_seal.WrongDevice):
        tablet.join(welcome, room.signature_key())
    with pytest.raises(hm_seal.SealError):
        tablet.epoch()


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


def test_members_name_each_device_by_its_leaf_after_one_leaves_from_the_middle():
    phone, room, laptop = trio()
    commit = phone.remove(leaf_of(phone, b"room"))
    laptop.handle(commit)
    assert {name: leaf for leaf, name in phone.members()} == {
        b"phone": phone.leaf_index(),
        b"laptop": laptop.leaf_index(),
    }
    second = phone.remove(leaf_of(phone, b"laptop"))
    with pytest.raises(hm_seal.Removed):
        laptop.handle(second)
    assert [name for _, name in phone.members()] == [b"phone"]


def test_pairing_refuses_an_empty_confirmed_key_on_either_side():
    phone, _, _ = trio()
    tablet = hm_seal.Member(b"tablet")
    with pytest.raises(hm_seal.WrongDevice):
        phone.add(tablet.key_package(), b"")
    _, welcome = phone.add(tablet.key_package(), tablet.signature_key())
    with pytest.raises(hm_seal.WrongDevice):
        tablet.join(welcome, b"")


def test_a_commit_names_who_made_it_and_which_devices_it_added_and_removed():
    phone, room, laptop = trio()
    stranger = hm_seal.Member(b"stranger")
    commit, _ = phone.add(stranger.key_package(), stranger.signature_key())
    assert room.handle(commit) == ("commit", 3, phone.signature_key(), [stranger.signature_key()], [])
    laptop.handle(commit)
    removal = phone.remove(leaf_of(phone, b"stranger"))
    assert room.handle(removal) == ("commit", 4, phone.signature_key(), [], [stranger.signature_key()])


def test_only_the_admin_device_adds_or_removes_devices():
    phone, room, laptop = trio()
    for m in (phone, room, laptop):
        assert m.admins() == [phone.signature_key()]
    tablet = hm_seal.Member(b"tablet")
    with pytest.raises(hm_seal.NotAdmin):
        room.add(tablet.key_package(), tablet.signature_key())
    assert issubclass(hm_seal.NotAdmin, hm_seal.SealError)
    with pytest.raises(hm_seal.NotAdmin):
        room.remove(leaf_of(room, b"phone"))
    with pytest.raises(hm_seal.NotAdmin):
        room.remove(leaf_of(room, b"laptop"))
    assert room.epoch() == 2
    with pytest.raises(hm_seal.NotAdmin):
        room.make_admin(room.signature_key())
    promote = phone.make_admin(laptop.signature_key())
    assert room.handle(promote)[0] == "commit"
    laptop.handle(promote)
    assert sorted(room.admins()) == sorted([phone.signature_key(), laptop.signature_key()])


def test_a_commit_that_breaks_the_admin_rule_is_reported_as_refused():
    # The room's own add and removal. The binding cannot make either, so they
    # are made in Rust: cargo run --example refused_fixture --features test-support -- <dir>
    d = os.environ.get("HM_SEAL_REFUSED_FIXTURE")
    assert d, "set HM_SEAL_REFUSED_FIXTURE to a directory the refused_fixture example wrote"

    def read(name):
        return (pathlib.Path(d) / name).read_bytes()

    room = read("room.key")
    for commit, added, removed in (("add.commit", [read("listener.key")], []), ("remove.commit", [], [read("laptop.key")])):
        phone = hm_seal.Member.load(read("phone.save"))
        assert phone.handle(read(commit)) == ("refused", 2, room, added, removed), f"the room's {commit} was not reported as refused"
        assert phone.epoch() == 2


def test_a_commit_read_as_an_application_message_is_refused_and_still_applies_from_the_log():
    phone, room, laptop = trio()
    tablet = hm_seal.Member(b"tablet")
    commit, _ = phone.add(tablet.key_package(), tablet.signature_key())
    with pytest.raises(hm_seal.SealError, match="not an application message"):
        room.handle_application(commit)
    assert room.epoch() == 2, "a commit read as an application message was applied"
    assert room.handle(commit) == ("commit", 3, phone.signature_key(), [tablet.signature_key()], []), "the commit no longer applied from the log"
    msg = phone.seal(b"video off")
    assert room.handle_application(msg) == ("application", phone.leaf_index(), b"video off", phone.signature_key())
