//! A device saved and started again carries on where it was.

use hm_seal::*;
use sha2::{Digest, Sha256};

fn restart(m: &Member) -> Member {
    Member::load(&m.save().unwrap()).unwrap()
}

/// A save without its trailing SHA-256.
fn body(saved: &[u8]) -> &[u8] {
    &saved[..saved.len() - 32]
}

/// `body` with a matching digest, so what is checked is what comes after the digest check.
fn resealed(body: &[u8]) -> Vec<u8> {
    let mut v = body.to_vec();
    v.extend_from_slice(&Sha256::digest(body));
    v
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
    let got = room.handle(&after);
    assert!(matches!(got, Err(SealError::Removed)), "a removed device restarted from its save: {got:?}");
}

#[test]
fn a_damaged_save_is_refused() {
    let p = pair();
    let saved = p.room.save().unwrap();
    let b = body(&saved);
    let refused = |bytes: &[u8]| matches!(Member::load(bytes), Err(SealError::BadSave));
    // Each under a matching digest, so the checks behind the digest are what refuses.
    assert!(refused(&resealed(&b[..b.len() - 1])), "a truncated save loaded");
    let mut longer = b.to_vec();
    longer.push(0);
    assert!(refused(&resealed(&longer)), "a save with trailing bytes loaded");
    let mut other = b.to_vec();
    other[0] ^= 1;
    assert!(refused(&resealed(&other)), "a save with another format tag loaded");
    assert!(refused(&saved[..saved.len() - 1]), "a save without its last byte loaded");
    assert!(refused(b""));
}

#[test]
fn a_save_damaged_anywhere_is_refused() {
    let p = pair();
    let saved = p.room.save().unwrap();
    let mut not_refused = vec![];
    for pos in 0..saved.len() {
        let mut bad = saved.clone();
        bad[pos] ^= 0x20;
        match std::panic::catch_unwind(|| Member::load(&bad).map(|_| ())) {
            Ok(Err(SealError::BadSave)) => {}
            other => not_refused.push((pos, format!("{:?}", other.map_err(|_| "a panic")))),
        }
    }
    assert!(
        not_refused.is_empty(),
        "{} of {} damaged positions were not refused, first: {:?}",
        not_refused.len(),
        saved.len(),
        &not_refused[..not_refused.len().min(5)]
    );
}

#[test]
fn a_save_that_matches_its_digest_but_that_openmls_cannot_read_is_refused_not_a_panic() {
    // As if written wrong or edited by hand: OpenMLS's storage unwraps what it reads.
    let p = pair();
    let saved = p.room.save().unwrap();
    let mut b = body(&saved).to_vec();
    let at = b.windows(11).position(|w| w == b"\"mac_value\"").expect("no mac_value in the save");
    b[at + 1] ^= 0x20;
    let got = std::panic::catch_unwind(|| Member::load(&resealed(&b)).map(|_| ()));
    assert!(matches!(got, Ok(Err(SealError::BadSave))), "a save OpenMLS cannot read gave {:?}", got.map_err(|_| "a panic"));
}

/// xorshift64*. The seed fixes the damage done; the save itself has fresh keys on every run.
struct Rng(u64);

impl Rng {
    fn next(&mut self) -> u64 {
        self.0 ^= self.0 >> 12;
        self.0 ^= self.0 << 25;
        self.0 ^= self.0 >> 27;
        self.0.wrapping_mul(0x2545_f491_4f6c_dd1d)
    }
    fn below(&mut self, n: usize) -> usize {
        (self.next() % n as u64) as usize
    }
}

/// One random change: a bit flipped, a byte set, a cut, a range dropped, bytes inserted or a range repeated.
fn damage(rng: &mut Rng, b: &mut Vec<u8>) {
    if b.is_empty() {
        b.push(rng.next() as u8);
        return;
    }
    let at = rng.below(b.len());
    match rng.below(6) {
        0 => b[at] ^= 1 << rng.below(8),
        1 => b[at] = rng.next() as u8,
        2 => b.truncate(at),
        3 => {
            let end = (at + 1 + rng.below(16)).min(b.len());
            b.drain(at..end);
        }
        4 => {
            for _ in 0..1 + rng.below(16) {
                b.insert(at, rng.next() as u8);
            }
        }
        _ => {
            let end = (at + 1 + rng.below(64)).min(b.len());
            let piece = b[at..end].to_vec();
            b.splice(at..at, piece);
        }
    }
}

#[test]
fn thousands_of_damaged_saves_never_crash_the_device() {
    // Damage under a matching digest reaches the parser and OpenMLS, as a save
    // written wrong or forged would; every tenth case keeps the old digest.
    let mut p = pair();
    let saved = p.room.save().unwrap();
    let msg = p.phone.seal(b"after the save").unwrap();
    let tablet = Member::new(b"tablet").unwrap();
    let commit = p.phone.add(&tablet.key_package().unwrap()).unwrap().commit;
    let seed = 0x9e37_79b9_7f4a_7c15;
    let mut rng = Rng(seed);
    let (mut refused, mut loaded, mut damaged, mut crashed) = (0, 0, 0, vec![]);
    for case in 0..4000 {
        let mut b = body(&saved).to_vec();
        for _ in 0..1 + rng.below(3) {
            damage(&mut rng, &mut b);
        }
        let input = if case % 10 == 0 { [b.as_slice(), &saved[saved.len() - 32..]].concat() } else { resealed(&b) };
        let run = std::panic::catch_unwind(|| match Member::load(&input) {
            Err(SealError::BadSave) => Ok("refused"),
            Err(e) => Err(format!("load gave {e:?}, not BadSave")),
            Ok(mut m) => {
                let results = [m.handle(&msg).map(|_| ()), m.handle(&commit).map(|_| ()), m.seal(b"x").map(|_| ())];
                if !results.iter().any(|r| matches!(r, Err(SealError::Damaged))) {
                    return Ok("loaded");
                }
                // Once damaged, nothing more is done and nothing is written.
                let after = [
                    ("save", m.save().map(|_| ())),
                    ("seal", m.seal(b"y").map(|_| ())),
                    ("epoch", m.epoch().map(|_| ())),
                    ("key_package", m.key_package().map(|_| ())),
                    ("frame_sealer", m.frame_sealer().map(|_| ())),
                ];
                match after.iter().find(|(_, r)| !matches!(r, Err(SealError::Damaged))) {
                    None => Ok("damaged"),
                    Some((call, r)) => Err(format!("after Damaged: {call} gave {r:?}")),
                }
            }
        });
        match run {
            Ok(Ok("refused")) => refused += 1,
            Ok(Ok("loaded")) => loaded += 1,
            Ok(Ok(_)) => damaged += 1,
            Ok(Err(e)) => crashed.push((case, e)),
            Err(_) => crashed.push((case, "a panic".to_string())),
        }
    }
    eprintln!("damaged saves: {refused} refused, {loaded} loaded and used, {damaged} became Damaged, {} crashed", crashed.len());
    assert!(
        crashed.is_empty(),
        "{} of 4000 damaged saves crashed (seed {seed:#x}, a save of {} bytes), first (case, what): {:?}",
        crashed.len(),
        saved.len(),
        &crashed[..crashed.len().min(5)]
    );
    // Without this the guard might never have been reached at this seed.
    assert!(damaged > 0, "no damaged save loaded and then reached the panic guard at this seed");
}
