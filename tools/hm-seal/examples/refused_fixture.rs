//! Commits that break the admin rule, for the bindings' tests: a binding cannot
//! make one (the helpers for it are test-only Rust). They are written fresh for
//! each run rather than checked in, because OpenMLS refuses an added device's
//! key package once its lifetime is over (84 days by default), and checks that
//! when it reads the commit.
//!
//! cargo run --example refused_fixture --features test-support --locked -- <dir>
//!
//! `<dir>` gets the phone's save at epoch 2 (`phone.save`); two commits the
//! room device made for epoch 2 although it is not an admin, an add of a
//! listener (`add.commit`) and a removal of the laptop (`remove.commit`); and
//! the room's, the listener's and the laptop's signature keys (`*.key`). A
//! phone loaded from the save refuses each commit; this checks that before
//! writing anything.

use hm_seal::*;

fn main() {
    let dir = std::path::PathBuf::from(std::env::args_os().nth(1).expect("usage: refused_fixture <dir>"));
    let mut phone = Member::new(b"phone").unwrap();
    let mut room = Member::new(b"room").unwrap();
    let mut laptop = Member::new(b"laptop").unwrap();
    phone.create_group(b"account-1").unwrap();
    let added = phone.add(&room.key_package().unwrap(), &room.signature_key()).unwrap();
    room.join(&added.welcome, &phone.signature_key()).unwrap();
    let added = phone.add(&laptop.key_package().unwrap(), &laptop.signature_key()).unwrap();
    room.handle(&added.commit).unwrap();
    laptop.join(&added.welcome, &phone.signature_key()).unwrap();

    // Both from the room at epoch 2: the removal is made by the room as it
    // was before its add.
    let room_at_2 = room.save().unwrap();
    let listener = Member::new(b"listener").unwrap();
    let add = room.add_ignoring_admins_for_test(&listener.key_package().unwrap()).unwrap().commit;
    let mut room = Member::load(&room_at_2).unwrap();
    let laptop_leaf = room.members().unwrap().into_iter().find(|(_, name)| name == b"laptop").unwrap().0;
    let remove = room.remove_ignoring_admins_for_test(laptop_leaf).unwrap();

    let save = phone.save().unwrap();
    for (commit, added, removed) in [
        (&add, vec![listener.signature_key()], vec![]),
        (&remove, vec![], vec![laptop.signature_key()]),
    ] {
        let mut copy = Member::load(&save).unwrap();
        let want = Incoming::Refused { epoch: 2, by: room.signature_key(), added, removed };
        assert_eq!(copy.handle(commit).unwrap(), want);
        assert_eq!(copy.epoch().unwrap(), 2);
    }

    std::fs::create_dir_all(&dir).unwrap();
    for (name, bytes) in [
        ("phone.save", save),
        ("add.commit", add),
        ("remove.commit", remove),
        ("room.key", room.signature_key()),
        ("listener.key", listener.signature_key()),
        ("laptop.key", laptop.signature_key()),
    ] {
        std::fs::write(dir.join(name), bytes).unwrap();
    }
}
