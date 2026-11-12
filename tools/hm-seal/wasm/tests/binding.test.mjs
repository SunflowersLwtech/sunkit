// What the WebAssembly binding promises, run with `node --test` against the
// wasm-bindgen output for Node (HM_SEAL_WASM_PKG, default ../pkg-node). The
// interop test also needs HM_SEAL_PYTHON: a Python with the hm_seal binding.

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const pkg = process.env.HM_SEAL_WASM_PKG ?? join(here, "..", "pkg-node", "hm_seal.js");
const s = createRequire(import.meta.url)(pkg);
const enc = (t) => new TextEncoder().encode(t);
const dec = (b) => new TextDecoder().decode(b);

/** The phone starts the group, then adds the room device and the browser. */
function trio() {
  const phone = new s.Member(enc("phone"));
  const room = new s.Member(enc("room"));
  const web = new s.Member(enc("web"));
  phone.createGroup(enc("account-1"));
  let added = phone.add(room.keyPackage(), room.signatureKey());
  room.join(added.welcome, phone.signatureKey());
  added = phone.add(web.keyPackage(), web.signatureKey());
  assert.deepEqual(room.handle(added.commit), {
    kind: "commit",
    epoch: 2,
    by: phone.signatureKey(),
    added: [web.signatureKey()],
    removed: [],
  });
  web.join(added.welcome, phone.signatureKey());
  return { phone, room, web };
}

const leafOf = (m, name) => m.members().find((x) => dec(x.name) === name).leaf;

function refusal(fn, name = "SealError") {
  assert.throws(fn, (e) => e instanceof Error && e.name === name, `expected a ${name}`);
}

test("every device reads the others and knows who sent", () => {
  const t = trio();
  const msg = t.phone.seal(enc("video off"));
  for (const other of [t.room, t.web]) {
    const got = other.handle(msg);
    assert.equal(got.kind, "application");
    assert.equal(got.sender, t.phone.leafIndex());
    assert.deepEqual(got.senderKey, t.phone.signatureKey());
    assert.equal(dec(got.bytes), "video off");
  }
  // The phone is leaf 0: a sender from another leaf tells a real sender from a constant.
  const fromRoom = t.web.handle(t.room.seal(enc("motion")));
  assert.notEqual(t.room.leafIndex(), 0);
  assert.equal(fromRoom.sender, t.room.leafIndex());
  assert.deepEqual(fromRoom.senderKey, t.room.signatureKey());
  assert.equal(typeof t.web.epoch(), "number");
  assert.deepEqual(t.web.members().map((m) => dec(m.name)).sort(), ["phone", "room", "web"]);
});

test("a removed device is told so and reads nothing sent after", () => {
  const t = trio();
  const commit = t.phone.remove(leafOf(t.phone, "web"));
  assert.equal(t.room.handle(commit).kind, "commit");
  refusal(() => t.web.handle(commit), "Removed");
  const after = t.phone.seal(enc("the camera is back on"));
  assert.equal(dec(t.room.handle(after).bytes), "the camera is back on");
  assert.throws(() => t.web.handle(after), "a removed device read a message sent after its removal");
});

test("frames open only under their metadata, only once, and not from a removed device", () => {
  const t = trio();
  const opener = new s.FrameOpener();
  t.phone.updateOpener(opener);
  const room = t.room.frameSealer();
  const frame = room.seal(enc("jpeg"), enc("device-1"));
  refusal(() => opener.open(frame, enc("device-2")));
  refusal(() => opener.open(frame));
  assert.equal(dec(opener.open(frame, enc("device-1"))), "jpeg");
  refusal(() => opener.open(frame, enc("device-1")));
  const plain = room.seal(enc("no metadata"));
  assert.equal(dec(opener.open(plain)), "no metadata");

  const webStream = t.web.frameSealer();
  const commit = t.phone.remove(leafOf(t.phone, "web"));
  t.room.handle(commit);
  t.phone.updateOpener(opener);
  refusal(() => opener.open(webStream.seal(enc("forged"))));
  assert.equal(dec(opener.open(t.room.frameSealer().seal(enc("real")))), "real");
});

test("stored data opens only with its key and purpose; the recovery secret unwraps the key", () => {
  const key = s.DataKey.generate();
  const blob = key.seal(enc("room-event"), enc("sat on the sofa"));
  assert.equal(dec(key.open(enc("room-event"), blob)), "sat on the sofa");
  refusal(() => key.open(enc("vlog-edit"), blob));
  refusal(() => s.DataKey.generate().open(enc("room-event"), blob));

  const secret = new Uint8Array(32).fill(7);
  const wrapped = key.wrapForRecovery(secret);
  assert.deepEqual(s.DataKey.unwrapFromRecovery(secret, wrapped).toBytes(), key.toBytes());
  refusal(() => s.DataKey.unwrapFromRecovery(new Uint8Array(32).fill(8), wrapped));
  refusal(() => key.wrapForRecovery(new Uint8Array(31)));
  // Not cut to 32: the first 32 bytes here are the real secret.
  refusal(() => key.wrapForRecovery(new Uint8Array(33).fill(7)));
  refusal(() => s.DataKey.unwrapFromRecovery(new Uint8Array(33).fill(7), wrapped));
  assert.deepEqual(s.DataKey.fromBytes(key.toBytes()).toBytes(), key.toBytes());
});

test("members name each device by its leaf, also after one leaves from the middle", () => {
  // MLS keeps a removed device's leaf empty: after the room (leaf 1) leaves,
  // the web is still leaf 2, the second member listed.
  const t = trio();
  const commit = t.phone.remove(leafOf(t.phone, "room"));
  t.web.handle(commit);
  const leaves = Object.fromEntries(t.phone.members().map((m) => [dec(m.name), m.leaf]));
  assert.deepEqual(leaves, { phone: t.phone.leafIndex(), web: t.web.leafIndex() });
  const second = t.phone.remove(leafOf(t.phone, "web"));
  refusal(() => t.web.handle(second), "Removed");
  assert.deepEqual(t.phone.members().map((m) => dec(m.name)), ["phone"]);
});

test("bytes are taken only from a Uint8Array, never from a string or an array", () => {
  // wasm-bindgen's glue would copy a string character by character (most to 0),
  // so a frame sealed with the metadata "camera-a" opened with "camera-b".
  const t = trio();
  const opener = new s.FrameOpener();
  t.phone.updateOpener(opener);
  const frame = t.room.frameSealer().seal(enc("jpeg"), enc("camera-a"));
  for (const bad of ["camera-b", [99, 97], 42, {}]) {
    refusal(() => t.room.frameSealer().seal(enc("jpeg"), bad));
    refusal(() => opener.open(frame, bad));
  }
  refusal(() => t.room.frameSealer().seal("jpeg"));
  refusal(() => t.phone.seal("video off"));
  refusal(() => new s.Member("phone"));
  const key = s.DataKey.generate();
  refusal(() => key.seal("room-event", enc("x")));
  refusal(() => key.wrapForRecovery("7".repeat(32)));
  assert.throws(() => t.phone.seal("x"), /must be a Uint8Array/);
  // A Node Buffer is a Uint8Array.
  assert.equal(dec(opener.open(frame, Buffer.from("camera-a"))), "jpeg");
});

test("remove() refuses a leaf that is not a whole number in range, and removes nobody", () => {
  // wasm-bindgen's own glue turned undefined, null and NaN into leaf 0 (the phone) and 1.5 into leaf 1.
  // undefined is what members().find(...)?.leaf gives for a device that has just left.
  const removed = [];
  for (const leaf of [undefined, null, NaN, 1.5, -1, 2 ** 32, Infinity, "2", 2n, [2], {}]) {
    const t = trio();
    const label = typeof leaf === "string" ? JSON.stringify(leaf) : typeof leaf === "bigint" ? `${leaf}n` : String(leaf);
    let commit = null;
    try {
      commit = t.phone.remove(leaf);
    } catch (e) {
      // Refused by the leaf check itself, not by whatever leaf a conversion
      // happened to land on (-1 saturated to 0 is the phone's own leaf).
      assert.equal(e.name, "SealError", `remove(${label}) threw ${e.name}: ${e.message}`);
      assert.match(e.message, /a leaf is a whole number/, `remove(${label}) was refused for another reason`);
    }
    if (commit) removed.push(`${label} -> a commit; the phone now lists ${JSON.stringify(t.phone.members().map((m) => dec(m.name)).sort())}`);
    assert.deepEqual(t.phone.members().map((m) => dec(m.name)).sort(), ["phone", "room", "web"], `remove(${label})`);
  }
  assert.deepEqual(removed, [], "remove() took a leaf that is not a whole number in range");
  // Control: a whole number still removes that device.
  const t = trio();
  t.room.handle(t.phone.remove(leafOf(t.phone, "web")));
  assert.deepEqual(t.room.members().map((m) => dec(m.name)).sort(), ["phone", "room"]);
});

test("a device saved and loaded goes on in the group; a damaged save is refused", () => {
  const t = trio();
  const saved = t.web.save();
  const web = s.Member.load(saved);
  assert.equal(web.leafIndex(), t.web.leafIndex());
  assert.equal(dec(web.handle(t.phone.seal(enc("after the reload"))).bytes), "after the reload");
  const cut = saved.slice(0, saved.length - 1);
  refusal(() => s.Member.load(cut));
});

test("pairing refuses another device on either side", () => {
  const t = trio();
  const tablet = new s.Member(enc("tablet"));
  const relay = new s.Member(enc("tablet"));
  refusal(() => t.phone.add(relay.keyPackage(), tablet.signatureKey()), "WrongDevice");
  // The phone's Welcome, but the device was told to expect the room's key.
  const byPhone = t.phone.add(tablet.keyPackage(), tablet.signatureKey());
  refusal(() => tablet.join(byPhone.welcome, t.room.signatureKey()), "WrongDevice");
  refusal(() => tablet.epoch());
});

test("a commit names who made it and which devices it added and removed", () => {
  const t = trio();
  const stranger = new s.Member(enc("stranger"));
  const byPhone = t.phone.add(stranger.keyPackage(), stranger.signatureKey());
  const seen = t.room.handle(byPhone.commit);
  assert.deepEqual([seen.kind, seen.by, seen.added, seen.removed], ["commit", t.phone.signatureKey(), [stranger.signatureKey()], []]);
  t.web.handle(byPhone.commit);
  const removal = t.room.handle(t.phone.remove(leafOf(t.phone, "stranger")));
  assert.deepEqual([removal.by, removal.added, removal.removed], [t.phone.signatureKey(), [], [stranger.signatureKey()]]);
});

test("only the admin device adds or removes devices", () => {
  const t = trio();
  for (const m of [t.phone, t.room, t.web]) assert.deepEqual(m.admins(), [t.phone.signatureKey()]);
  const tablet = new s.Member(enc("tablet"));
  refusal(() => t.room.add(tablet.keyPackage(), tablet.signatureKey()), "NotAdmin");
  refusal(() => t.room.remove(leafOf(t.room, "phone")), "NotAdmin");
  refusal(() => t.room.remove(leafOf(t.room, "web")), "NotAdmin");
  assert.equal(t.room.epoch(), 2);
  refusal(() => t.room.makeAdmin(t.room.signatureKey()), "NotAdmin");
  const promote = t.phone.makeAdmin(t.web.signatureKey());
  assert.equal(t.room.handle(promote).kind, "commit");
  t.web.handle(promote);
  const hex = (keys) => keys.map((k) => Buffer.from(k).toString("hex")).sort();
  assert.deepEqual(hex(t.room.admins()), hex([t.phone.signatureKey(), t.web.signatureKey()]));
});

test("a commit that breaks the admin rule is reported as refused", () => {
  // The room's own add and removal. The binding cannot make either, so they
  // are made in Rust: cargo run --example refused_fixture --features test-support -- <dir>
  const d = process.env.HM_SEAL_REFUSED_FIXTURE;
  assert.ok(d, "set HM_SEAL_REFUSED_FIXTURE to a directory the refused_fixture example wrote");
  const read = (name) => new Uint8Array(readFileSync(join(d, name)));
  for (const [commit, added, removed] of [
    ["add.commit", [read("listener.key")], []],
    ["remove.commit", [], [read("laptop.key")]],
  ]) {
    const phone = s.Member.load(read("phone.save"));
    const want = { kind: "refused", epoch: 2, by: read("room.key"), added, removed };
    assert.deepEqual(phone.handle(read(commit)), want, `the room's ${commit} was not reported as refused`);
    assert.equal(phone.epoch(), 2);
  }
});

test("pairing refuses an empty confirmed key on either side", () => {
  const t = trio();
  const tablet = new s.Member(enc("tablet"));
  refusal(() => t.phone.add(tablet.keyPackage(), new Uint8Array(0)), "WrongDevice");
  const added = t.phone.add(tablet.keyPackage(), tablet.signatureKey());
  refusal(() => tablet.join(added.welcome, new Uint8Array(0)), "WrongDevice");
});

test("a Python device and a browser talk to each other", () => {
  const py = process.env.HM_SEAL_PYTHON;
  assert.ok(py, "set HM_SEAL_PYTHON to a Python that has the hm_seal binding");
  const d = mkdtempSync(join(tmpdir(), "hm-seal-interop-"));
  try {
    const peer = (step) => execFileSync(py, ["-I", join(here, "py_peer.py"), step, d], { encoding: "utf8" });
    const web = new s.Member(enc("web"));
    writeFileSync(join(d, "web.kp"), web.keyPackage());
    writeFileSync(join(d, "web.sigkey"), web.signatureKey());
    peer("start");
    web.join(readFileSync(join(d, "py.welcome")), readFileSync(join(d, "py.sigkey")));
    const got = web.handle(readFileSync(join(d, "py.msg")));
    assert.equal(dec(got.bytes), "from python");
    assert.equal(got.sender, leafOf(web, "phone"));
    assert.ok(Buffer.from(got.senderKey).equals(readFileSync(join(d, "py.sigkey"))), "the sender key is not the phone's");
    const opener = new s.FrameOpener();
    web.updateOpener(opener);
    assert.equal(dec(opener.open(readFileSync(join(d, "py.frame")), enc("meta"))), "frame from python");

    writeFileSync(join(d, "web.msg"), web.seal(enc("from the browser")));
    writeFileSync(join(d, "web.frame"), web.frameSealer().seal(enc("frame from the browser"), enc("meta")));
    assert.equal(
      peer("reply").trim(),
      `application ${web.leafIndex()} ${Buffer.from(web.signatureKey()).toString("hex")} from the browser | frame from the browser`,
    );
  } finally {
    rmSync(d, { recursive: true, force: true });
  }
});
