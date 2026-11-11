//! What hm-seal promises, each in a test that fails when the promise breaks.

use hm_seal::*;

struct Trio {
    phone: Member,
    room: Member,
    laptop: Member,
}

/// The phone starts the owner's group, then adds the room device and the laptop.
fn trio() -> Trio {
    let mut phone = Member::new(b"phone").unwrap();
    let mut room = Member::new(b"room").unwrap();
    let mut laptop = Member::new(b"laptop").unwrap();
    phone.create_group(b"account-1").unwrap();

    let added = phone.add(&room.key_package().unwrap()).unwrap();
    room.join(&added.welcome).unwrap();

    let added = phone.add(&laptop.key_package().unwrap()).unwrap();
    assert_eq!(room.handle(&added.commit).unwrap(), Incoming::Commit { epoch: 2 });
    laptop.join(&added.welcome).unwrap();
    Trio { phone, room, laptop }
}

fn leaf_of(m: &Member, name: &[u8]) -> u32 {
    m.members().unwrap().into_iter().find(|(_, n)| n == name).unwrap().0
}

#[test]
fn every_device_reads_the_others_and_knows_who_sent() {
    let mut t = trio();
    let phone_leaf = t.phone.leaf_index().unwrap();
    let msg = t.phone.seal(b"video off").unwrap();
    for other in [&mut t.room, &mut t.laptop] {
        assert_eq!(
            other.handle(&msg).unwrap(),
            Incoming::Application { sender: phone_leaf, bytes: b"video off".to_vec() }
        );
    }
    let names: Vec<Vec<u8>> = t.phone.members().unwrap().into_iter().map(|(_, n)| n).collect();
    assert_eq!(names.len(), 3);
}

#[test]
fn a_removed_device_cannot_read_what_is_sent_after_it() {
    let mut t = trio();
    let laptop = leaf_of(&t.phone, b"laptop");
    let commit = t.phone.remove(laptop).unwrap();
    assert!(matches!(t.room.handle(&commit).unwrap(), Incoming::Commit { .. }));
    assert!(matches!(t.laptop.handle(&commit), Err(SealError::Removed)));

    let after = t.phone.seal(b"the camera is back on").unwrap();
    assert!(matches!(t.room.handle(&after).unwrap(), Incoming::Application { .. }));
    assert!(t.laptop.handle(&after).is_err(), "a removed device read a message sent after its removal");
    assert_eq!(t.phone.members().unwrap().len(), 2);
}

#[test]
fn a_removed_device_cannot_open_frames_of_the_next_epoch() {
    let mut t = trio();
    let mut laptop_opener = FrameOpener::default();
    t.laptop.update_opener(&mut laptop_opener).unwrap();
    let mut before = t.room.frame_sealer().unwrap();
    let frame = before.seal(b"jpeg-before", b"").unwrap();
    assert_eq!(laptop_opener.open(&frame, b"").unwrap(), b"jpeg-before");

    let laptop = leaf_of(&t.phone, b"laptop");
    let commit = t.phone.remove(laptop).unwrap();
    t.room.handle(&commit).unwrap();
    let _ = t.laptop.handle(&commit);

    let mut phone_opener = FrameOpener::default();
    t.phone.update_opener(&mut phone_opener).unwrap();
    let frame = t.room.frame_sealer().unwrap().seal(b"jpeg-after", b"").unwrap();
    assert_eq!(phone_opener.open(&frame, b"").unwrap(), b"jpeg-after");
    assert!(laptop_opener.open(&frame, b"").is_err(), "a removed device opened a frame of the next epoch");
}

#[test]
fn a_tampered_message_or_frame_is_refused() {
    let mut t = trio();
    let mut msg = t.phone.seal(b"announce: dinner").unwrap();
    let last = msg.len() - 1;
    msg[last] ^= 1;
    assert!(t.room.handle(&msg).is_err());

    let mut opener = FrameOpener::default();
    t.phone.update_opener(&mut opener).unwrap();
    let mut sealer = t.room.frame_sealer().unwrap();
    let mut frame = sealer.seal(b"jpeg", b"device-1").unwrap();
    assert!(opener.open(&frame, b"device-2").is_err(), "a frame opened under other metadata");
    let n = frame.len() - 1;
    frame[n] ^= 1;
    assert!(opener.open(&frame, b"device-1").is_err());
}

#[test]
fn a_replayed_frame_is_refused() {
    let t = trio();
    let mut opener = FrameOpener::default();
    t.phone.update_opener(&mut opener).unwrap();
    let mut sealer = t.room.frame_sealer().unwrap();
    let frame = sealer.seal(b"jpeg", b"").unwrap();
    assert_eq!(opener.open(&frame, b"").unwrap(), b"jpeg");
    assert!(opener.open(&frame, b"").is_err(), "the same frame was accepted twice");
}

#[test]
fn a_message_from_outside_the_group_is_refused() {
    let mut t = trio();
    // Someone who knows the group's id but not its keys (the relay, say).
    let mut outsider = Member::new(b"phone").unwrap();
    outsider.create_group(b"account-1").unwrap();
    let forged = outsider.seal(b"video on").unwrap();
    assert!(t.room.handle(&forged).is_err(), "a message from outside the group was accepted");
}

#[test]
fn frames_follow_the_rfc_9605_test_vectors() {
    // tests/rfc9605-test-vectors.json: RFC 9605 Appendix C (each value also
    // appears in the RFC's text); AES_128_GCM_SHA256_128 is suite 4.
    let raw: serde_json::Value =
        serde_json::from_str(include_str!("rfc9605-test-vectors.json")).unwrap();
    let v = raw["sframe"].as_array().unwrap().iter().find(|v| v["cipher_suite"] == 4).unwrap();
    let h = |k: &str| hex::decode(v[k].as_str().unwrap()).unwrap();
    let ct = seal_frame_with_base_key(
        &h("base_key"),
        v["kid"].as_u64().unwrap(),
        v["ctr"].as_u64().unwrap(),
        &h("pt"),
        &h("metadata"),
    )
    .unwrap();
    assert_eq!(hex::encode(ct), v["ct"].as_str().unwrap());
}

#[test]
fn stored_data_opens_only_with_its_key_and_purpose() {
    let key = DataKey::generate();
    let blob = key.seal(b"room-event", b"sat on the sofa for 90 minutes").unwrap();
    assert_eq!(key.open(b"room-event", &blob).unwrap(), b"sat on the sofa for 90 minutes");
    assert!(key.open(b"vlog-edit", &blob).is_err(), "a blob opened under another purpose");
    assert!(DataKey::generate().open(b"room-event", &blob).is_err());
    let mut bad = blob.clone();
    let n = bad.len() - 1;
    bad[n] ^= 1;
    assert!(key.open(b"room-event", &bad).is_err());
    assert_ne!(key.seal(b"room-event", b"x").unwrap(), key.seal(b"room-event", b"x").unwrap());
}

#[test]
fn the_recovery_secret_and_only_it_unwraps_the_data_key() {
    let key = DataKey::generate();
    let secret = [7u8; 32];
    let wrapped = key.wrap_for_recovery(&secret).unwrap();
    let back = DataKey::unwrap_from_recovery(&secret, &wrapped).unwrap();
    assert_eq!(back.to_bytes(), key.to_bytes());
    assert!(DataKey::unwrap_from_recovery(&[8u8; 32], &wrapped).is_err());
}

#[test]
fn a_device_added_later_reads_the_history_through_the_data_key_not_through_old_messages() {
    let mut t = trio();
    let key = DataKey::generate();
    let stored = key.seal(b"room-event", b"reminder before the tablet joined").unwrap();
    let old = t.phone.seal(b"an old live message").unwrap();
    t.room.handle(&old).unwrap();

    let mut tablet = Member::new(b"tablet").unwrap();
    let added = t.phone.add(&tablet.key_package().unwrap()).unwrap();
    t.room.handle(&added.commit).unwrap();
    t.laptop.handle(&added.commit).unwrap();
    tablet.join(&added.welcome).unwrap();

    assert!(tablet.handle(&old).is_err(), "a new device read a message from before it joined");
    let handover = t.phone.seal(&key.to_bytes()).unwrap();
    let Incoming::Application { bytes, .. } = tablet.handle(&handover).unwrap() else { panic!() };
    let got = DataKey::from_bytes(&bytes).unwrap();
    assert_eq!(got.open(b"room-event", &stored).unwrap(), b"reminder before the tablet joined");
}

#[test]
fn two_sealers_in_one_epoch_never_share_a_key() {
    // A second sealer in the same epoch: a second stream, or the same device
    // after a restart. Each counts its frames from 0, so a shared key would mean
    // a repeated AES-GCM nonce: the same frame would come out byte for byte.
    let t = trio();
    let mut opener = FrameOpener::default();
    t.phone.update_opener(&mut opener).unwrap();
    let a = t.room.frame_sealer().unwrap().seal(b"jpeg", b"").unwrap();
    let b = t.room.frame_sealer().unwrap().seal(b"jpeg", b"").unwrap();
    assert_ne!(a, b, "two sealers of one epoch encrypted under the same key and counter");
    assert_eq!(opener.open(&a, b"").unwrap(), b"jpeg");
    assert_eq!(opener.open(&b, b"").unwrap(), b"jpeg");
}
