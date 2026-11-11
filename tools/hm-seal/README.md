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

State is kept in memory. Persistence and the Python, WebAssembly, Swift and Kotlin bindings come next.

## Dependencies

`cargo deny check` (in CI) checks advisories, licenses, sources and wildcard versions of the shipped tree; `deny.toml` records the two ignored advisories and why. Licenses are MIT, Apache-2.0, BSD, ISC and Unicode, plus MPL-2.0 for hpke-rs, hpke-rs-crypto and hpke-rs-rust-crypto (pulled in by openmls_rust_crypto): file-level copyleft, compatible with Apache-2.0 and with closed apps. An app that ships this has to say where those crates' source is (https://github.com/celabshq/libcrux).
