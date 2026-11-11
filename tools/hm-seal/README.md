# hm-seal

End-to-end encryption among one person's own devices (phones, browsers, a room camera), built only from published standards and their existing implementations:

| piece | standard | implementation |
|---|---|---|
| the owner's device group | MLS, RFC 9420 | [OpenMLS](https://github.com/openmls/openmls) 0.9.2 (audited by SRLabs, 2026; advisory GHSA-94v4 fixed in 0.9.2) |
| live video frames | SFrame, RFC 9605 (keys from MLS as in §5.2) | [sframe-rs](https://github.com/TobTheRock/sframe-rs) 2.1.0 |
| stored data and its recovery wrap | XChaCha20-Poly1305, HKDF-SHA256 (RFC 5869) | RustCrypto |

`cargo test` runs the promises as tests: every device reads the others and knows who sent; a removed device reads nothing sent after its removal and opens no frame of the next epoch; tampered messages and frames, frames under other metadata, replayed frames and messages from outside the group are refused; frames match RFC 9605 Appendix C; stored data opens only with its key and purpose; a device added later reads stored history through the data key, not old messages.

State is kept in memory. Persistence and the Python, WebAssembly, Swift and Kotlin bindings come next.
