//! A panic hm-seal catches is printed without its message, which can quote the
//! stored bytes; a panic anywhere else still reaches the hook set before. Its own
//! test binary, because a panic hook is global to the process.

use std::sync::{Arc, Mutex};

use hm_seal::*;
use sha2::{Digest, Sha256};

#[test]
fn a_caught_panic_keeps_its_message_to_itself_and_others_still_reach_the_hook() {
    let seen: Arc<Mutex<Vec<String>>> = Arc::default();
    let record = seen.clone();
    std::panic::set_hook(Box::new(move |info| {
        let payload = info.payload();
        let text = payload
            .downcast_ref::<String>()
            .cloned()
            .or_else(|| payload.downcast_ref::<&str>().map(|s| s.to_string()))
            .unwrap_or_default();
        record.lock().unwrap().push(text);
    }));

    let mut phone = Member::new(b"phone").unwrap();
    let mut room = Member::new(b"room").unwrap();
    phone.create_group(b"account-1").unwrap();
    let added = phone.add(&room.key_package().unwrap(), &room.signature_key()).unwrap();
    room.join(&added.welcome, &phone.signature_key()).unwrap();

    // A save OpenMLS cannot read, under a matching digest: its storage panics inside load().
    let saved = room.save().unwrap();
    let mut body = saved[..saved.len() - 32].to_vec();
    let at = body.windows(11).position(|w| w == b"\"mac_value\"").expect("no mac_value in the save");
    body[at + 1] ^= 0x20;
    let digest = Sha256::digest(&body);
    body.extend_from_slice(&digest);
    let before = caught_panics_for_test();
    let loaded = Member::load(&body).map(|_| ());
    let caught = caught_panics_for_test() - before;
    let after_load = seen.lock().unwrap().clone();

    // A panic outside hm-seal still reaches the hook set before.
    let _ = std::panic::catch_unwind(|| panic!("outside hm-seal"));
    let at_the_end = seen.lock().unwrap().clone();

    // Back to the default hook, so a failing assertion below is printed.
    let _ = std::panic::take_hook();
    assert!(matches!(loaded, Err(SealError::BadSave)), "the damaged save gave {loaded:?}");
    assert_eq!(caught, 1, "load() did not panic inside OpenMLS once: this test checked nothing");
    assert!(after_load.is_empty(), "the caught panic reached the hook with its message: {after_load:?}");
    assert_eq!(at_the_end, ["outside hm-seal"], "a panic outside hm-seal did not reach the hook set before");
}
