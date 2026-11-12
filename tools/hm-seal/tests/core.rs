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

    let added = phone.add(&room.key_package().unwrap(), &room.signature_key()).unwrap();
    room.join(&added.welcome, &phone.signature_key()).unwrap();

    let added = phone.add(&laptop.key_package().unwrap(), &laptop.signature_key()).unwrap();
    assert_eq!(
        room.handle(&added.commit).unwrap(),
        Incoming::Commit { epoch: 2, by: phone.signature_key(), added: vec![laptop.signature_key()], removed: vec![] }
    );
    laptop.join(&added.welcome, &phone.signature_key()).unwrap();
    Trio { phone, room, laptop }
}

fn leaf_of(m: &Member, name: &[u8]) -> u32 {
    m.members().unwrap().into_iter().find(|(_, n)| n == name).unwrap().0
}

#[test]
fn every_device_reads_the_others_and_knows_who_sent() {
    let mut t = trio();
    let phone_leaf = t.phone.leaf_index().unwrap();
    let phone_key = t.phone.signature_key();
    let msg = t.phone.seal(b"video off").unwrap();
    for other in [&mut t.room, &mut t.laptop] {
        assert_eq!(
            other.handle(&msg).unwrap(),
            Incoming::Application { sender: phone_leaf, sender_key: phone_key.clone(), bytes: b"video off".to_vec() }
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
    let added = t.phone.add(&tablet.key_package().unwrap(), &tablet.signature_key()).unwrap();
    t.room.handle(&added.commit).unwrap();
    t.laptop.handle(&added.commit).unwrap();
    tablet.join(&added.welcome, &t.phone.signature_key()).unwrap();

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

/// RFC 9605 §5.2, copied from the RFC text: the frame key's exporter call.
const RFC_9605_EXPORTER_LINE: &str = r#"base_key = MLS-Exporter("SFrame 1.0 Base Key", "", AEAD.Nk)"#;
/// RFC 9605 Table 1: Nk of AES_128_GCM_SHA256_128.
const RFC_9605_NK: usize = 16;

fn rfc_exporter_label() -> &'static str {
    RFC_9605_EXPORTER_LINE.split('"').nth(1).unwrap()
}

fn kid_and_counter(frame: &[u8], meta: &[u8]) -> (u64, u64) {
    let enc = sframe::frame::EncryptedFrame::try_with_meta_data(frame, meta).unwrap();
    (enc.header().key_id(), enc.header().counter())
}

#[test]
fn a_removed_device_cannot_inject_frames_after_its_removal() {
    // The removed laptop knows the old epoch's base key. Its own stream goes on
    // sealing under it, and it can seal under any member's KID (RFC 9605 §7.2).
    let mut t = trio();
    let mut laptop_stream = t.laptop.frame_sealer().unwrap();
    let old_base = t.laptop.export_secret_for_test(rfc_exporter_label(), b"", RFC_9605_NK).unwrap();
    let old_epoch = t.laptop.epoch().unwrap();
    let room_leaf = u64::from(leaf_of(&t.phone, b"room"));
    let as_room = |context: u64| (context << 12) | (room_leaf << 4) | (old_epoch % 16);
    let mut phone_opener = FrameOpener::default();
    t.phone.update_opener(&mut phone_opener).unwrap();
    // While the laptop is a member this works: frames prove the group, not the sender.
    let before = seal_frame_with_base_key(&old_base, as_room(1), 0, b"under the room's KID", b"").unwrap();
    assert_eq!(phone_opener.open(&before, b"").unwrap(), b"under the room's KID");

    let laptop = leaf_of(&t.phone, b"laptop");
    let commit = t.phone.remove(laptop).unwrap();
    t.room.handle(&commit).unwrap();
    let _ = t.laptop.handle(&commit);
    t.phone.update_opener(&mut phone_opener).unwrap();

    let real = t.room.frame_sealer().unwrap().seal(b"real picture", b"").unwrap();
    assert_eq!(phone_opener.open(&real, b"").unwrap(), b"real picture");
    for i in 0..3 {
        let forged = laptop_stream.seal(format!("forged picture {i}").as_bytes(), b"").unwrap();
        let got = phone_opener.open(&forged, b"");
        assert!(
            got.is_err(),
            "the owner's opener accepted frame {i} sealed by the removed laptop after its removal: {:?}",
            got.map(|p| String::from_utf8_lossy(&p).into_owned())
        );
    }
    let forged = seal_frame_with_base_key(&old_base, as_room(2), 0, b"forged as the room", b"").unwrap();
    let got = phone_opener.open(&forged, b"");
    assert!(
        got.is_err(),
        "the owner's opener accepted a frame the removed laptop sealed under the room's KID: {:?}",
        got.map(|p| String::from_utf8_lossy(&p).into_owned())
    );
}

#[test]
fn a_frame_sealed_before_an_add_still_opens_after_it() {
    // Adding a device keeps everyone who knew the old epoch's key in the group,
    // so frames in flight across the commit are still read.
    let mut t = trio();
    let mut phone_opener = FrameOpener::default();
    t.phone.update_opener(&mut phone_opener).unwrap();
    let mut room_stream = t.room.frame_sealer().unwrap();
    let first = room_stream.seal(b"before the add", b"").unwrap();
    let in_flight = room_stream.seal(b"in flight across the add", b"").unwrap();
    assert_eq!(phone_opener.open(&first, b"").unwrap(), b"before the add");

    let mut tablet = Member::new(b"tablet").unwrap();
    let added = t.phone.add(&tablet.key_package().unwrap(), &tablet.signature_key()).unwrap();
    t.room.handle(&added.commit).unwrap();
    t.laptop.handle(&added.commit).unwrap();
    tablet.join(&added.welcome, &t.phone.signature_key()).unwrap();
    t.phone.update_opener(&mut phone_opener).unwrap();

    assert_eq!(
        phone_opener.open(&in_flight, b"").unwrap(),
        b"in flight across the add",
        "a frame of the previous epoch was refused after an add"
    );
    assert!(phone_opener.open(&first, b"").is_err(), "a frame opened twice across the add");
    let after = t.room.frame_sealer().unwrap().seal(b"after the add", b"").unwrap();
    assert_eq!(phone_opener.open(&after, b"").unwrap(), b"after the add");
}

#[test]
fn a_frame_kid_carries_4_epoch_bits_then_an_8_bit_leaf() {
    // RFC 9605 §5.2 (Figure 9): KID = context || member index (S bits) || epoch (E bits); here E = 4, S = 8.
    let t = trio();
    for m in [&t.phone, &t.room, &t.laptop] {
        let frame = m.frame_sealer().unwrap().seal(b"x", b"").unwrap();
        let (kid, ctr) = kid_and_counter(&frame, b"");
        assert_eq!(kid & 0xf, m.epoch().unwrap() % 16, "kid {kid:#x}: epoch bits");
        assert_eq!((kid >> 4) & 0xff, u64::from(m.leaf_index().unwrap()), "kid {kid:#x}: leaf bits");
        assert_eq!(ctr, 0);
    }
}

#[test]
fn an_opener_refuses_its_own_devices_frames() {
    // A relay reflecting a device's own frames back to it.
    let t = trio();
    let mut opener = FrameOpener::default();
    t.phone.update_opener(&mut opener).unwrap();
    let own = t.phone.frame_sealer().unwrap().seal(b"mine", b"").unwrap();
    assert!(opener.open(&own, b"").is_err(), "the phone's opener accepted the phone's own frame");
}

#[test]
fn the_frame_key_is_the_mls_exporter_with_the_rfc_9605_label_empty_context_and_nk() {
    // Both ends deriving with the same wrong label, context or length would still
    // round-trip; compare with the exporter called as the RFC text says instead.
    let t = trio();
    let base = t.room.export_secret_for_test(rfc_exporter_label(), b"", RFC_9605_NK).unwrap();
    let frame = t.room.frame_sealer().unwrap().seal(b"payload", b"meta").unwrap();
    let (kid, ctr) = kid_and_counter(&frame, b"meta");
    let want = seal_frame_with_base_key(&base, kid, ctr, b"payload", b"meta").unwrap();
    assert_eq!(frame, want, "the frame was not sealed under MLS-Exporter(RFC label, \"\", 16)");
}

#[test]
fn a_received_message_prints_its_length_not_its_bytes() {
    let secret = b"canary-5f3a".to_vec();
    let text = format!("{:?}", Incoming::Application { sender: 1, sender_key: vec![7; 32], bytes: secret.clone() });
    let as_list = format!("{secret:?}");
    assert!(
        !text.contains("canary") && !text.contains(&as_list[1..as_list.len() - 1]),
        "the plaintext is in the Debug text: {text}"
    );
    assert!(text.contains("11 bytes"), "{text}");
}

#[test]
fn adding_refuses_a_key_package_from_any_device_but_the_confirmed_one() {
    // The owner confirmed the new room device's key; the relay hands over a key package of its own.
    let mut t = trio();
    let epoch = t.phone.epoch().unwrap();
    let new_room = Member::new(b"room 2").unwrap();
    let relay = Member::new(b"room 2").unwrap();
    let got = t.phone.add(&relay.key_package().unwrap(), &new_room.signature_key());
    assert!(
        matches!(got, Err(SealError::WrongDevice)),
        "a key package from another device was added: {:?}",
        got.map(|_| ())
    );
    assert_eq!(t.phone.epoch().unwrap(), epoch);
    assert_eq!(t.phone.members().unwrap().len(), 3);
    t.phone.add(&new_room.key_package().unwrap(), &new_room.signature_key()).unwrap();
    assert_eq!(t.phone.members().unwrap().len(), 4);
}

#[test]
fn joining_refuses_a_welcome_from_any_device_but_the_expected_one() {
    let mut t = trio();
    let phone_key = t.phone.signature_key();

    // The relay has the new device's key package and adds it to a group of its own.
    let mut tablet = Member::new(b"tablet").unwrap();
    let mut relay = Member::new(b"phone").unwrap();
    relay.create_group(b"account-1").unwrap();
    let fake = relay.add(&tablet.key_package().unwrap(), &tablet.signature_key()).unwrap();
    let got = tablet.join(&fake.welcome, &phone_key);
    assert!(matches!(got, Err(SealError::WrongDevice)), "the device joined the relay's group: {got:?}");
    assert!(matches!(tablet.epoch(), Err(SealError::NoGroup)));

    // A member that is not the device the owner paired with does not count either:
    // the Welcome is the phone's, and the device was told to expect the room's key.
    let by_phone = t.phone.add(&tablet.key_package().unwrap(), &tablet.signature_key()).unwrap();
    let got = tablet.join(&by_phone.welcome, &t.room.signature_key());
    assert!(matches!(got, Err(SealError::WrongDevice)), "a Welcome from the phone passed as the room's: {got:?}");

    // After the refusals the device pairs with a new key package.
    let mut other = trio();
    let real = other.phone.add(&tablet.key_package().unwrap(), &tablet.signature_key()).unwrap();
    tablet.join(&real.welcome, &other.phone.signature_key()).unwrap();
    assert_eq!(tablet.members().unwrap().len(), 4);
}

#[test]
fn a_received_message_names_its_senders_key_even_when_a_leaf_is_reused() {
    let mut t = trio();
    let laptop_leaf = leaf_of(&t.phone, b"laptop");
    let laptop_key = t.laptop.signature_key();
    let msg = t.laptop.seal(b"from the laptop").unwrap();
    let Incoming::Application { sender, sender_key, .. } = t.room.handle(&msg).unwrap() else { panic!() };
    assert_eq!((sender, &sender_key), (laptop_leaf, &laptop_key));

    let commit = t.phone.remove(laptop_leaf).unwrap();
    t.room.handle(&commit).unwrap();
    let mut tablet = Member::new(b"tablet").unwrap();
    let added = t.phone.add(&tablet.key_package().unwrap(), &tablet.signature_key()).unwrap();
    t.room.handle(&added.commit).unwrap();
    tablet.join(&added.welcome, &t.phone.signature_key()).unwrap();
    assert_eq!(tablet.leaf_index().unwrap(), laptop_leaf, "the tablet did not take the laptop's leaf");

    let msg = tablet.seal(b"from the tablet").unwrap();
    let Incoming::Application { sender, sender_key, .. } = t.room.handle(&msg).unwrap() else { panic!() };
    assert_eq!(sender, laptop_leaf);
    assert_eq!(sender_key, tablet.signature_key());
    assert_ne!(sender_key, laptop_key, "the tablet's message was put down to the removed laptop");
}

#[test]
fn a_remove_and_an_add_in_one_commit_still_drop_the_previous_epoch() {
    // One commit removes the laptop and adds a tablet, which takes the laptop's
    // leaf: the leaf indices before and after are the same, the devices are not.
    let mut t = trio();
    let mut laptop_stream = t.laptop.frame_sealer().unwrap();
    let mut room_opener = FrameOpener::default();
    t.room.update_opener(&mut room_opener).unwrap();
    let laptop = leaf_of(&t.phone, b"laptop");
    let tablet = Member::new(b"tablet").unwrap();
    let commit = t.phone.remove_and_add_in_one_commit_for_test(laptop, &tablet.key_package().unwrap()).unwrap();
    assert!(matches!(t.room.handle(&commit).unwrap(), Incoming::Commit { .. }));
    assert_eq!(leaf_of(&t.room, b"tablet"), laptop, "the tablet did not get the laptop's leaf");
    t.room.update_opener(&mut room_opener).unwrap();
    let forged = laptop_stream.seal(b"forged after remove+add", b"").unwrap();
    let got = room_opener.open(&forged, b"");
    assert!(
        got.is_err(),
        "after one commit that removed the laptop and gave its leaf to a tablet, the opener accepted the laptop's frame: {:?}",
        got.map(|p| String::from_utf8_lossy(&p).into_owned())
    );
}

#[test]
fn members_name_each_device_by_its_leaf_after_one_leaves_from_the_middle() {
    // MLS keeps a removed device's leaf empty: after the room (leaf 1) leaves,
    // the laptop is still leaf 2, the second member listed.
    let mut t = trio();
    let commit = t.phone.remove(leaf_of(&t.phone, b"room")).unwrap();
    t.laptop.handle(&commit).unwrap();
    let listed: Vec<(Vec<u8>, u32)> = t.phone.members().unwrap().into_iter().map(|(leaf, name)| (name, leaf)).collect();
    let own = vec![
        (b"phone".to_vec(), t.phone.leaf_index().unwrap()),
        (b"laptop".to_vec(), t.laptop.leaf_index().unwrap()),
    ];
    assert_eq!(listed, own);
    let second = t.phone.remove(leaf_of(&t.phone, b"laptop")).unwrap();
    assert!(matches!(t.laptop.handle(&second), Err(SealError::Removed)));
}

#[test]
fn pairing_refuses_an_empty_confirmed_key_on_either_side() {
    // A pairing screen that failed to read the scanned key and passed no bytes.
    let mut t = trio();
    let tablet = Member::new(b"tablet").unwrap();
    let got = t.phone.add(&tablet.key_package().unwrap(), &[]);
    assert!(matches!(got, Err(SealError::WrongDevice)), "add with an empty key: {:?}", got.map(|_| ()));
    assert_eq!(t.phone.members().unwrap().len(), 3);

    let mut tablet = Member::new(b"tablet").unwrap();
    let added = t.phone.add(&tablet.key_package().unwrap(), &tablet.signature_key()).unwrap();
    let got = tablet.join(&added.welcome, &[]);
    assert!(matches!(got, Err(SealError::WrongDevice)), "join with an empty key: {got:?}");
    assert!(matches!(tablet.epoch(), Err(SealError::NoGroup)));
}

#[test]
fn a_commit_names_who_made_it_and_which_devices_it_added_and_removed() {
    let mut t = trio();
    let stranger = Member::new(b"stranger").unwrap();
    let by_phone = t.phone.add(&stranger.key_package().unwrap(), &stranger.signature_key()).unwrap();
    let Incoming::Commit { by, added, removed, .. } = t.room.handle(&by_phone.commit).unwrap() else { panic!() };
    assert_eq!(by, t.phone.signature_key(), "the room was not told the phone made the commit");
    assert_eq!(added, vec![stranger.signature_key()]);
    assert!(removed.is_empty());

    t.laptop.handle(&by_phone.commit).unwrap();
    let commit = t.phone.remove(leaf_of(&t.phone, b"stranger")).unwrap();
    let Incoming::Commit { by, added, removed, .. } = t.room.handle(&commit).unwrap() else { panic!() };
    assert_eq!((by, added), (t.phone.signature_key(), vec![]));
    assert_eq!(removed, vec![stranger.signature_key()], "the room was not told which device was removed");

    // One commit that removes the laptop and adds a tablet in its leaf names both.
    t.laptop.handle(&commit).unwrap();
    let tablet = Member::new(b"tablet").unwrap();
    let laptop_key = t.laptop.signature_key();
    let swap = t.phone.remove_and_add_in_one_commit_for_test(leaf_of(&t.phone, b"laptop"), &tablet.key_package().unwrap()).unwrap();
    let Incoming::Commit { added, removed, .. } = t.room.handle(&swap).unwrap() else { panic!() };
    assert_eq!((added, removed), (vec![tablet.signature_key()], vec![laptop_key]));
}

#[test]
fn the_device_that_starts_the_group_is_its_admin_and_every_device_knows_it() {
    let mut t = trio();
    let phone = vec![t.phone.signature_key()];
    for m in [&t.phone, &t.room, &t.laptop] {
        assert_eq!(m.admins().unwrap(), phone);
    }
    // Only an admin adds: the room is refused before anything is made.
    let tablet = Member::new(b"tablet").unwrap();
    let got = t.room.add(&tablet.key_package().unwrap(), &tablet.signature_key());
    assert!(matches!(got, Err(SealError::NotAdmin)), "the room added a device: {:?}", got.map(|_| ()));
    assert_eq!(t.room.epoch().unwrap(), 2);
    // ...nor removes an admin.
    let got = t.room.remove(leaf_of(&t.room, b"phone"));
    assert!(matches!(got, Err(SealError::NotAdmin)), "the room removed the phone: {got:?}");
}

#[test]
fn a_compromised_device_adding_a_listener_is_refused_by_every_other_device() {
    // A room camera running someone else's code commits an add anyway.
    let mut t = trio();
    let room_key = t.room.signature_key();
    let mut listener = Member::new(b"listener").unwrap();
    let added = t.room.add_ignoring_admins_for_test(&listener.key_package().unwrap()).unwrap();
    for m in [&mut t.phone, &mut t.laptop] {
        assert_eq!(
            m.handle(&added.commit).unwrap(),
            Incoming::Refused { epoch: 2, by: room_key.clone(), added: vec![listener.signature_key()], removed: vec![] },
            "a device applied an add the room made"
        );
        assert_eq!(m.epoch().unwrap(), 2);
    }
    listener.join(&added.welcome, &room_key).unwrap();

    // The phone removes the room; the laptop follows; the listener reads nothing.
    let commit = t.phone.remove(leaf_of(&t.phone, b"room")).unwrap();
    assert!(matches!(t.laptop.handle(&commit).unwrap(), Incoming::Commit { .. }));
    let msg = t.phone.seal(b"for my devices").unwrap();
    let Incoming::Application { bytes, .. } = t.laptop.handle(&msg).unwrap() else { panic!() };
    assert_eq!(bytes, b"for my devices");
    let got = listener.handle(&msg);
    assert!(got.is_err(), "the listener read the phone's message: {got:?}");
}

#[test]
fn a_device_that_is_not_an_admin_cannot_remove_a_device_or_rewrite_the_list() {
    let mut t = trio();
    let (phone_key, room_key) = (t.phone.signature_key(), t.room.signature_key());
    let rewrite = t.room.set_admins_ignoring_rules_for_test(std::slice::from_ref(&room_key)).unwrap();
    let got = t.laptop.handle(&rewrite).unwrap();
    assert!(matches!(&got, Incoming::Refused { by, .. } if *by == room_key), "the laptop took a new admin list from the room: {got:?}");
    assert_eq!(t.laptop.admins().unwrap(), vec![phone_key]);

    let mut t = trio();
    let kick = t.room.remove_ignoring_admins_for_test(leaf_of(&t.room, b"phone")).unwrap();
    let got = t.laptop.handle(&kick).unwrap();
    assert_eq!(
        got,
        Incoming::Refused { epoch: 2, by: t.room.signature_key(), added: vec![], removed: vec![t.phone.signature_key()] }
    );

    // Nor any other device: only an admin removes devices.
    let mut t = trio();
    let got = t.room.remove(leaf_of(&t.room, b"laptop"));
    assert!(matches!(got, Err(SealError::NotAdmin)), "the room removed the laptop: {:?}", got.map(|_| ()));
    let kick = t.room.remove_ignoring_admins_for_test(leaf_of(&t.room, b"laptop")).unwrap();
    let got = t.phone.handle(&kick).unwrap();
    assert!(matches!(&got, Incoming::Refused { removed, .. } if *removed == vec![t.laptop.signature_key()]), "{got:?}");
    assert_eq!(t.phone.members().unwrap().len(), 3);
}

#[test]
fn an_admin_hands_over_to_a_new_phone() {
    // The new phone joins, is made an admin, removes the old one and adds a device.
    let mut t = trio();
    let mut new_phone = Member::new(b"new phone").unwrap();
    let added = t.phone.add(&new_phone.key_package().unwrap(), &new_phone.signature_key()).unwrap();
    for m in [&mut t.room, &mut t.laptop] {
        m.handle(&added.commit).unwrap();
    }
    new_phone.join(&added.welcome, &t.phone.signature_key()).unwrap();

    assert!(matches!(t.room.make_admin(&t.room.signature_key()), Err(SealError::NotAdmin)));
    assert!(matches!(t.phone.make_admin(&Member::new(b"x").unwrap().signature_key()), Err(SealError::WrongDevice)));
    let promote = t.phone.make_admin(&new_phone.signature_key()).unwrap();
    for m in [&mut t.room, &mut t.laptop, &mut new_phone] {
        assert!(matches!(m.handle(&promote).unwrap(), Incoming::Commit { .. }));
    }

    let commit = new_phone.remove(leaf_of(&new_phone, b"phone")).unwrap();
    for m in [&mut t.room, &mut t.laptop] {
        assert!(matches!(m.handle(&commit).unwrap(), Incoming::Commit { .. }), "the new phone could not remove the old one");
    }
    let tablet = Member::new(b"tablet").unwrap();
    let added = new_phone.add(&tablet.key_package().unwrap(), &tablet.signature_key()).unwrap();
    assert!(matches!(t.room.handle(&added.commit).unwrap(), Incoming::Commit { .. }), "the new phone could not add a device");
    for m in [&t.room, &new_phone] {
        assert_eq!(m.admins().unwrap(), vec![new_phone.signature_key()], "a removed admin still counted");
    }
}

#[test]
fn a_removed_admin_paired_again_with_its_old_keys_is_an_ordinary_device() {
    // The phone's keys as they were before it started the group: a removed
    // device cannot join the same group again, but a copy of its keys can.
    let mut phone = Member::new(b"phone").unwrap();
    let keys_only = phone.save().unwrap();
    let mut room = Member::new(b"room").unwrap();
    let mut laptop = Member::new(b"laptop").unwrap();
    phone.create_group(b"account-1").unwrap();
    let added = phone.add(&room.key_package().unwrap(), &room.signature_key()).unwrap();
    room.join(&added.welcome, &phone.signature_key()).unwrap();
    let added = phone.add(&laptop.key_package().unwrap(), &laptop.signature_key()).unwrap();
    room.handle(&added.commit).unwrap();
    laptop.join(&added.welcome, &phone.signature_key()).unwrap();
    let promote = phone.make_admin(&laptop.signature_key()).unwrap();
    room.handle(&promote).unwrap();
    laptop.handle(&promote).unwrap();
    let out = laptop.remove(leaf_of(&laptop, b"phone")).unwrap();
    room.handle(&out).unwrap();

    // The laptop pairs the phone's keys again.
    let mut again = Member::load(&keys_only).unwrap();
    assert_eq!(again.signature_key(), phone.signature_key(), "control: the same keys");
    let back = laptop.add(&again.key_package().unwrap(), &again.signature_key()).unwrap();
    assert!(matches!(room.handle(&back.commit).unwrap(), Incoming::Commit { .. }));
    again.join(&back.welcome, &laptop.signature_key()).unwrap();
    for m in [&laptop, &room, &again] {
        assert_eq!(m.admins().unwrap(), vec![laptop.signature_key()], "a device paired again with its old keys came back as an admin");
    }
    let tablet = Member::new(b"tablet").unwrap();
    let got = again.add(&tablet.key_package().unwrap(), &tablet.signature_key());
    assert!(matches!(got, Err(SealError::NotAdmin)), "the phone paired again added a device: {:?}", got.map(|_| ()));

    // An admin makes it one again; its add then keeps both admins.
    let promote = laptop.make_admin(&again.signature_key()).unwrap();
    room.handle(&promote).unwrap();
    again.handle(&promote).unwrap();
    let added = again.add(&tablet.key_package().unwrap(), &tablet.signature_key()).unwrap();
    for m in [&mut room, &mut laptop] {
        assert!(matches!(m.handle(&added.commit).unwrap(), Incoming::Commit { .. }));
    }
    let mut both = vec![laptop.signature_key(), again.signature_key()];
    both.sort();
    for m in [&laptop, &room, &again] {
        let mut got = m.admins().unwrap();
        got.sort();
        assert_eq!(got, both, "an add dropped an admin that is still in the group");
    }
}

#[test]
fn a_removed_device_cannot_commit_an_add() {
    // The public add stops a removed admin at the admin rule; the test-only add,
    // which skips that rule, reaches commit_add, whose own check is then all that
    // stands between it and OpenMLS (which panics on a removed member's commit).
    let mut phone = Member::new(b"phone").unwrap();
    let mut laptop = Member::new(b"laptop").unwrap();
    phone.create_group(b"account-1").unwrap();
    let added = phone.add(&laptop.key_package().unwrap(), &laptop.signature_key()).unwrap();
    laptop.join(&added.welcome, &phone.signature_key()).unwrap();
    let promote = phone.make_admin(&laptop.signature_key()).unwrap();
    laptop.handle(&promote).unwrap();
    let out = laptop.remove(leaf_of(&laptop, b"phone")).unwrap();
    assert!(matches!(phone.handle(&out), Err(SealError::Removed)), "control: the phone was removed");

    let tablet = Member::new(b"tablet").unwrap();
    let got = phone.add(&tablet.key_package().unwrap(), &tablet.signature_key());
    assert!(matches!(got, Err(SealError::NotAdmin)), "the removed admin's add: {:?}", got.map(|_| ()));
    let kp = tablet.key_package().unwrap();
    let got = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| phone.add_ignoring_admins_for_test(&kp).map(|_| ())));
    assert!(
        matches!(&got, Ok(Err(SealError::Mls(m))) if m == "the group cannot take a commit now"),
        "a removed device's add reached OpenMLS: {got:?}"
    );
}

#[test]
fn a_commit_read_as_an_application_message_is_refused_and_still_applies_from_the_log() {
    let mut t = trio();
    let tablet = Member::new(b"tablet").unwrap();
    let added = t.phone.add(&tablet.key_package().unwrap(), &tablet.signature_key()).unwrap();
    // Outside the log (a command channel, say): refused before it is decrypted.
    let got = t.room.handle_application(&added.commit);
    assert!(
        matches!(&got, Err(SealError::BadMessage(m)) if m == "not an application message"),
        "a commit read as an application message: {:?}",
        got.map(|i| format!("{i:?}"))
    );
    assert_eq!(t.room.epoch().unwrap(), 2, "a commit read as an application message was applied");
    // From the log it still applies: nothing of it was used up.
    let got = t.room.handle(&added.commit);
    assert!(
        matches!(&got, Ok(Incoming::Commit { epoch: 3, .. })),
        "the commit no longer applied from the log: {:?}",
        got.map(|i| format!("{i:?}"))
    );
    // An application message reads the same either way, its sender included.
    let msg = t.phone.seal(b"video off").unwrap();
    assert_eq!(
        t.room.handle_application(&msg).unwrap(),
        Incoming::Application { sender: t.phone.leaf_index().unwrap(), sender_key: t.phone.signature_key(), bytes: b"video off".to_vec() }
    );
}
