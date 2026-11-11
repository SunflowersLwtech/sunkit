//! A device saved and started again carries on where it was.

use hm_seal::*;

fn restart(m: &Member) -> Member {
    Member::load(&m.save().unwrap()).unwrap()
}

struct Pair {
    phone: Member,
    room: Member,
}

fn pair() -> Pair {
    let mut phone = Member::new(b"phone").unwrap();
    let mut room = Member::new(b"room").unwrap();
    phone.create_group(b"account-1").unwrap();
    let added = phone.add(&room.key_package().unwrap()).unwrap();
    room.join(&added.welcome).unwrap();
    Pair { phone, room }
}

#[test]
fn a_device_restarted_from_its_save_goes_on_in_the_group() {
    let mut p = pair();
    let mut room = restart(&p.room);
    assert_eq!(room.epoch().unwrap(), p.room.epoch().unwrap());
    assert_eq!(room.signature_key(), p.room.signature_key());

    let msg = p.phone.seal(b"video off").unwrap();
    assert!(matches!(room.handle(&msg).unwrap(), Incoming::Application { bytes, .. } if bytes == b"video off"));
    let back = room.seal(b"switched").unwrap();
    assert!(matches!(p.phone.handle(&back).unwrap(), Incoming::Application { bytes, .. } if bytes == b"switched"));

    let mut opener = FrameOpener::default();
    p.phone.update_opener(&mut opener).unwrap();
    let frame = room.frame_sealer().unwrap().seal(b"jpeg", b"").unwrap();
    assert_eq!(opener.open(&frame, b"").unwrap(), b"jpeg");
}

#[test]
fn a_key_package_survives_a_restart_until_its_welcome_arrives() {
    let mut p = pair();
    let tablet = Member::new(b"tablet").unwrap();
    let kp = tablet.key_package().unwrap();
    let mut tablet = restart(&tablet);
    let added = p.phone.add(&kp).unwrap();
    p.room.handle(&added.commit).unwrap();
    tablet.join(&added.welcome).unwrap();
    let msg = p.phone.seal(b"hello tablet").unwrap();
    assert!(matches!(tablet.handle(&msg).unwrap(), Incoming::Application { .. }));
}

#[test]
fn a_removed_device_started_again_still_reads_nothing_new() {
    let mut p = pair();
    let leaf = p.room.leaf_index().unwrap();
    let commit = p.phone.remove(leaf).unwrap();
    let _ = p.room.handle(&commit);
    let mut room = restart(&p.room);
    let after = p.phone.seal(b"after the removal").unwrap();
    assert!(room.handle(&after).is_err(), "a removed device read a new message after a restart");
}

#[test]
fn a_damaged_save_is_refused() {
    let p = pair();
    let saved = p.room.save().unwrap();
    assert!(Member::load(&saved[..saved.len() - 1]).is_err(), "a truncated save loaded");
    let mut longer = saved.clone();
    longer.push(0);
    assert!(Member::load(&longer).is_err(), "a save with trailing bytes loaded");
    let mut other = saved.clone();
    other[0] ^= 1;
    assert!(Member::load(&other).is_err(), "a save with another format tag loaded");
    assert!(Member::load(b"").is_err());
}
