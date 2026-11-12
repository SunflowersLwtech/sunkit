# End-to-end encryption between room-companion and the owner's pages

HipiMind relays a device that declares `e2ee` without being able to read it
(HipiMind's protocol v2, <https://hipimind.com/room/connect> §9). This page is
the other half: what room-companion and the owner's pages (the HipiMind web page
or app) put inside the bodies HipiMind relays. Both ends implement it; the keys
are [hm-seal](../../hm-seal)'s. `room_companion/e2ee.py` is the device's side,
and the reference for the page's checks.

The owner's devices and pages are one MLS group (RFC 9420). Only an **admin**
device adds or removes devices or changes who the admins are (hm-seal); the page
that starts the group is the first admin. The room device is never an admin and
never makes a commit.

Base64 below is standard base64 with padding (RFC 4648 §4), except in the
pairing code, which is base64url without padding (§5). JSON is UTF-8.

## Pairing: the code the page shows

An admin page starts pairing by showing a QR code whose text is

```
hmroom1.<base64url, no padding, of 48 bytes>
```

The 48 bytes are a 16-byte one-time secret, then the admin device's 32-byte
signature key (Ed25519). The page makes a new secret for every code, keeps it
until the device has joined or the code is dismissed, and never sends it
anywhere. The device refuses any other text: another prefix, another length,
characters outside the base64url alphabet.

What each part protects:

- The **admin's signature key** is what the device's `join` checks the Welcome
  against. A Welcome from any other device (one HipiMind made, say) is refused.
- The **secret** proves to the page that the key package it is about to add came
  from the device that scanned its code (below). HipiMind relays the key package,
  and without this it could put in its own.

The device's account is already known: it is paired to the account with
HipiMind's 8-character code before any of this.

## The group log

Every body the device or a page appends to HipiMind's group log (§9.6) is
base64 of a JSON object with `"v": 1` and a type `"t"`. A reader ignores a body
that is not such an object, has another `v`, or has a `t` it does not know.

### `join`: the device asks to be added

```json
{"v": 1, "t": "join", "id": "<16 bytes>", "key": "<32 bytes>", "kp": "<key package>", "mac": "<32 bytes>"}
```

- `id` = SHA-256(`"hm-room pairing id v1"` ‖ secret), first 16 bytes. It tells
  the page which of its codes this answers, without showing the secret.
- `key` = the device's signature key; `kp` = its MLS key package.
- `mac` = HMAC-SHA256 with the secret as key, over `"hm-room join v1"` ‖
  len(key) ‖ key ‖ len(kp) ‖ kp, each length a 4-byte big-endian integer.

The page finds its code by `id`, checks `mac` in constant time and refuses the
request if it does not match. Then it adds the device with `add(kp, key)`
(hm-seal checks that the key package is signed by `key`). A code answers one
request: once a device has joined with it, the page drops the secret.

### `welcome`: the page's answer, for the new device

```json
{"v": 1, "t": "welcome", "to": "<the device's signature key>", "after": 41, "welcome": "<MLS Welcome>"}
```

The admin appends the commit that adds the device first (an `mls` body), then
this. `after` is the last number of the log the admin had processed when it made
that commit.

The device joins with the Welcome addressed to its key, checking that it came
from the admin key in the code it scanned. Then it goes back and reads the log
from `after + 1` (but not past the Welcome itself). That reading skips the
commit that added it, which is for an earlier epoch, and applies any commit for
its new epoch that another admin appended before the Welcome. A Welcome from any
other device ends the pairing: its key package is used up, so the owner scans a
new code.

### `mls`: a commit or an application message

```json
{"v": 1, "t": "mls", "msg": "<MLS message>"}
```

Commits are applied in the log's order and nowhere else. The application
messages that travel in the log are the ones every member must get, even one
that is offline:

- the account's **data key**, sent by an admin after it adds a device and
  whenever it makes a new one: `{"t": "datakey", "id": "<8 bytes>", "key": "<32 bytes>"}`.
  The device keeps every data key it gets, and seals with the newest. It takes a
  data key only from an admin.

A message that cannot be read (from an earlier epoch, a commit that lost to
another one for the same epoch, a device that has left the group) is skipped.

## Sealed messages: commands and answers

`{"type": "sealed", "body": …}` (§9.2) carries base64 of one MLS application
message, never a commit. The device reads it with hm-seal's
`handle_application`, which refuses a commit before decrypting it. A commit read
there would move the device ahead of the log, or split it from the others.

A command from a page:

```json
{"t": "cmd", "req": "<at most 64 characters>", "cmd": {"type": "set", …}}
```

`cmd` is one of the plaintext commands of §3, §4b, §4c and §5, unchanged. **The
device acts only on a command from an admin device** (by its signature key, never
its leaf index, which MLS gives to the next device added). A command from any
other member is refused. So a second room device can't operate this one, and a
second browser has to be made an admin first.

## Sealed with the data key: events and the last state

A sealed event's `body` (§9.3), and the state the device sends with `keep`
(§9.2), are base64 of

```
data key id (8 bytes) ‖ hm-seal DataKey.seal(purpose, JSON)
```

with purpose `"hm-room event v1"` ‖ 0x00 ‖ device id, or `"hm-room state v1"` ‖
0x00 ‖ device id. The device id is HipiMind's id for the device, as ASCII. Binding
it in means a body cannot be shown as another device's. The JSON is the plaintext
event of §2 (`kind`, `text`, `data`, `at`), or the state of §2.

Sealed under the data key rather than as an MLS message, so a page that opens
later, or opens the same history twice, can read it. The cost: any member could
seal such a body. A page shows it as the device's because of the purpose, not
because of a signature.

Until the device has a data key it sends no state and keeps its events; it
sends them once one arrives.

## Frames

A live frame (§9.1) is `0x01` ‖ the output of hm-seal's `FrameSealer.seal(jpeg,
meta)`, with `meta` = `"hm-room frame v1"` ‖ 0x00 ‖ device id. `meta` is
authenticated, not sent: a page opens the frame with the same `meta` and a
`FrameOpener` it updates after every commit.

## What this does not protect against

- **HipiMind can stop a pairing.** It sees the device's join request, and can
  send the device a Welcome of its own. The device refuses that Welcome, but its
  key package is then used up, and the owner scans again. HipiMind can't make the
  device join anything other than the owner's group.
- **Any admin can operate the device.** Making a device an admin trusts it with
  that.
- **Events and the kept state carry no sender signature** (above).
- What HipiMind still sees is listed in §9.5 of its protocol.
