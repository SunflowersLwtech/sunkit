# hm-seal

End-to-end encryption among one person's own devices (phones, browsers, a room camera), built only from published standards and their existing implementations:

| piece | standard | implementation |
|---|---|---|
| the owner's device group | MLS, RFC 9420 | [OpenMLS](https://github.com/openmls/openmls) 0.9.2 (SRLabs audited commit a3402f2 of 2025-10-22, before 0.8.0, without the crypto and storage providers; 0.9.2 itself is not audited and fixes every advisory published since, including GHSA-94v4) |
| live video frames | SFrame, RFC 9605 (keys from MLS as in §5.2) | [sframe-rs](https://github.com/TobTheRock/sframe-rs) 2.1.0 |
| stored data and its recovery wrap | XChaCha20-Poly1305, HKDF-SHA256 (RFC 5869) | RustCrypto |

`cargo test` runs the promises as tests: every device reads the others and knows who sent; a removed device reads nothing sent after its removal, opens no frame of the next epoch, and can no longer inject frames under the epoch it knew; a frame in flight across an add still opens; an opener refuses its own device's frames; tampered messages and frames, frames under other metadata, replayed frames and messages from outside the group are refused; frames match RFC 9605 Appendix C, their KID has the RFC's layout, and their key is the MLS exporter called with the label copied from the RFC text, an empty context and Nk; stored data opens only with its key and purpose; a device added later reads stored history through the data key, not old messages; a received message prints its length, not its bytes. The raw-key and raw-exporter entry points those tests use exist only with the `test-support` feature.

Frames authenticate the group, not the member: SFrame "does not provide per-sender authentication of media data" (RFC 9605 §7.2), so any device in the group can seal a frame under another device's KID. A removed device still knows the previous epoch's key, so as soon as a device leaves, the opener drops the previous epoch (devices are compared by signature key, because MLS gives a removed device's leaf index to the next device added); after an add it keeps the previous epoch for frames in flight. Call `update_opener` after every commit: until then an opener accepts frames of the epochs it knows. Commands and anything else that must come from a particular device travel as MLS application messages, which carry their sender. That sender is a leaf index, which MLS reuses after a removal, so a caller that authorizes commands has to check the sender's signature key; this crate has no command path, the room device's code enforces it.

Pairing is not checked yet: `add()` cannot compare a key package's signature key with the one the owner scanned, and `join()` does not check who added the device. Both land before any binding is used to pair devices.

## Saving a device

A `Member` lives in memory; `save()` writes everything it needs after a restart, private keys included, and `load()` reads it back. `tests/persist.rs` holds these promises.

- **Damage is refused, never a crash.** A save ends with the SHA-256 of everything before it, and `load()` checks it before reading anything, so a partial write or a bad sector gives `BadSave`. A save that matches its digest but holds values OpenMLS cannot read (written wrong, or forged) is refused too: OpenMLS's storage unwraps what it reads and panics, and `load()` turns that into `BadSave`. Some such saves load and only panic later, when OpenMLS reads more of its storage; every call that reaches that storage turns the panic into `Damaged`, and the device then refuses every call that reads or changes the group or its keys, `save()` included, so a half-changed state is never written over a good save; only `signature_key()`, which is public, still answers. A panic caught this way is printed as where it happened only, not with its message, which can quote stored bytes; panics anywhere else still reach whatever hook was set before. A seeded test damages 4,000 saves and checks for both. (On WebAssembly a panic stops the module; the digest still refuses accidental damage.)
- **The save is the device.** Keep it where only the device's user can read it (a file of mode 600, the Keychain), or seal it under a platform key store where there is one. Anyone holding a copy, together with the ciphertexts the relay forwards, can process later commits exactly as the device does after a restart, and keeps reading until the device is removed from the group: hm-seal has no self-update of a device's own keys yet.
- **An old save is a key.** A save taken before a message still decrypts that message after it has been handled. So replace the save atomically (write a temporary file, fsync, rename over the old one) and keep no backups or older copies.
- **Save after every call that changes the group or its keys** (`key_package`, `create_group`, `join`, `add`, `remove`, `seal`, `handle`). A device restarted from an older save reuses a generation the others already consumed, and they refuse its next message (`SecretReuseError`).
- A `FrameOpener` is not saved: after a restart it starts with an empty replay window for the current epoch.
- The format depends on how `openmls_memory_storage` lays out its keys. Upgrading OpenMLS needs a test that loads a save written by the previous version.

## Python

`python/` is the binding (PyO3, abi3, Python 3.10 and later): `Member`, `FrameSealer`, `FrameOpener`, `DataKey`, and the exceptions `SealError` (a `ValueError`) and `Removed`. Bytes go in and come out as `bytes`; each object can be used from any thread. `handle()` gives a sender only as a leaf index for now. A leaf index is reused after a removal, so the room device must not act on commands until the binding also gives the sender's signature key (the pairing change).

```
python -m venv .venv && .venv/bin/pip install maturin pytest
VIRTUAL_ENV=$PWD/.venv PATH=$PWD/.venv/bin:$PATH maturin develop -m python/Cargo.toml --locked
.venv/bin/python -m pytest python/tests
```

The WebAssembly, Swift and Kotlin bindings come next.

## Dependencies

`cargo deny check` (in CI) checks advisories, licenses, sources and wildcard versions of the shipped tree (every crate of the workspace, bindings included); `deny.toml` records the two ignored advisories and why. Licenses are MIT, Apache-2.0, BSD, ISC and Unicode, plus MPL-2.0 for hpke-rs, hpke-rs-crypto and hpke-rs-rust-crypto (pulled in by openmls_rust_crypto): file-level copyleft, compatible with Apache-2.0 and with closed apps. An app that ships this has to say where those crates' source is (https://github.com/celabshq/libcrux).
