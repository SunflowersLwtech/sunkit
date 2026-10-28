import { test } from "node:test";
import assert from "node:assert/strict";
import { sanitizeName, backoffMs, parseOutbox, inboxRecord, shouldRotate, parseFlags } from "./lib.mjs";

test("sanitizeName keeps a relay-safe name", () => {
  assert.equal(sanitizeName("M4-DSH"), "m4-dsh");
  assert.equal(sanitizeName(" my agent "), "my-agent");
  assert.equal(sanitizeName("a//b"), "a-b");
  assert.equal(sanitizeName("-x-"), "x");
  assert.equal(sanitizeName("x".repeat(40)).length, 32);
  assert.equal(sanitizeName(""), "");
});

test("backoffMs grows then caps", () => {
  assert.deepEqual([0, 1, 2, 3, 4, 9].map(backoffMs), [1000, 2000, 5000, 10000, 30000, 30000]);
});

test("parseOutbox reads complete lines only", () => {
  const text = '{"to":"a","message":"one"}\n{"to":"b","message":"two"}\n{"to":"c","mess';
  const { records, nextOffset } = parseOutbox(text, 0);
  assert.equal(records.length, 2);
  assert.deepEqual(records.map((r) => r.to), ["a", "b"]);
  assert.equal(nextOffset, text.indexOf('{"to":"c"'));
});

test("parseOutbox resumes at an offset and never repeats", () => {
  const first = '{"to":"a","message":"one"}\n';
  const text = first + '{"to":"b","message":"two"}\n';
  const { records } = parseOutbox(text, first.length);
  assert.equal(records.length, 1);
  assert.equal(records[0].to, "b");
});

test("parseOutbox restarts when the file shrank", () => {
  const text = '{"to":"a","message":"one"}\n';
  const { records, nextOffset } = parseOutbox(text, 9999);
  assert.equal(records.length, 1);
  assert.equal(nextOffset, text.length);
});

test("parseOutbox counts bad lines and drops incomplete records", () => {
  const text = ['not json', '{"to":"a"}', '{"to":"b","message":"ok"}', ""].join("\n");
  const { records, bad } = parseOutbox(text, 0);
  assert.equal(records.length, 1);
  assert.equal(bad, 2);
});

test("parseOutbox passes in_reply_to through", () => {
  const { records } = parseOutbox('{"to":"a","message":"m","in_reply_to":"msg_1"}\n', 0);
  assert.equal(records[0].in_reply_to, "msg_1");
});

test("inboxRecord maps the channel notification", () => {
  const rec = inboxRecord({ meta: { from: "feishu-assistant", msg_id: "m1" }, content: "hi" }, new Date("2026-10-28T10:00:00Z"));
  assert.deepEqual(rec, { ts: "2026-10-28T10:00:00.000Z", from: "feishu-assistant", msg_id: "m1", content: "hi" });
  assert.equal(inboxRecord({ content: 42 }).content, "");
});

test("shouldRotate compares against the cap", () => {
  assert.equal(shouldRotate(5, 10), false);
  assert.equal(shouldRotate(11, 10), true);
  assert.equal(shouldRotate(NaN, 10), false);
});

test("parseFlags accepts both forms and rejects unknown flags", () => {
  const { flags, rest } = parseFlags(["--name", "x", "--dir=/tmp/d", "to", "hello"], ["name", "dir"]);
  assert.deepEqual(flags, { name: "x", dir: "/tmp/d" });
  assert.deepEqual(rest, ["to", "hello"]);
  assert.throws(() => parseFlags(["--nope"], ["name"]), /unknown option/);
});
