#!/usr/bin/env node
// dsh-mesh — join the claude-mesh as a non-Claude (DSH) peer.
//
//   join  run a persistent peer: inbound messages land in <dir>/inbox.jsonl,
//         lines written to <dir>/outbox.jsonl are sent ({to, message}).
//   say   one-shot send (send-only identity), same as mesh-say.
//
// The relay + wire format come from sunkit/mesh (claude-mesh). This file only
// adapts it: DSH has no channels, so the peer is kept alive here and inbound
// notifications are spooled to a file the agent can read between turns.
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const PEER = path.join(os.homedir(), "Developer/opensource/sunkit/mesh/plugins/mesh/server/mesh-peer.mjs");
const [mode, ...rest] = process.argv.slice(2);

if (mode === "say") {
  const [to, ...words] = rest;
  const text = words.join(" ");
  if (!to || !text) { console.error("usage: dsh-mesh say <to> <message...>"); process.exit(2); }
  const name = (process.env.MESH_AS || "m4-dsh").toLowerCase().replace(/[^a-z0-9_-]/g, "-").slice(0, 32);
  const dir = path.join(os.homedir(), ".mesh-names", name);
  fs.mkdirSync(dir, { recursive: true });
  const p = spawn(process.execPath, [PEER], { cwd: dir, env: { ...process.env, MESH_JOIN: "never" }, stdio: ["pipe", "pipe", "inherit"] });
  const send = (o) => p.stdin.write(JSON.stringify(o) + "\n");
  let buf = "";
  p.stdout.on("data", (d) => {
    buf += d;
    let i;
    while ((i = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, i); buf = buf.slice(i + 1);
      let m; try { m = JSON.parse(line); } catch { continue; }
      if (m.id === 1) {
        send({ jsonrpc: "2.0", method: "notifications/initialized" });
        send({ jsonrpc: "2.0", id: 2, method: "tools/call", params: { name: "send_message", arguments: { to, message: text } } });
      } else if (m.id === 2) {
        const t = (m.result?.content || []).map((c) => c.text).join("\n") || JSON.stringify(m.error || m.result);
        console.log(t);
        p.kill(); process.exit(m.error ? 1 : 0);
      }
    }
  });
  send({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "dsh-mesh", version: "0.1" } } });
  setTimeout(() => { console.error("timeout"); p.kill(); process.exit(3); }, 30000);
  process.exit(0);
}

if (mode !== "join") { console.error("usage: dsh-mesh join [--name N] [--dir D]  |  dsh-mesh say <to> <msg...>"); process.exit(2); }

const arg = (k, d) => { const i = rest.indexOf(k); return i >= 0 ? rest[i + 1] : d; };
const name = (arg("--name", process.env.MESH_AS || "m4-dsh")).toLowerCase().replace(/[^a-z0-9_-]/g, "-").slice(0, 32);
const dir = arg("--dir", path.join(os.homedir(), ".mesh-names", name));
fs.mkdirSync(dir, { recursive: true });
const inbox = path.join(dir, "inbox.jsonl");
const outbox = path.join(dir, "outbox.jsonl");
fs.writeFileSync(outbox, "");

const log = (...a) => console.log(new Date().toISOString(), ...a);
const p = spawn(process.execPath, [PEER], {
  cwd: dir,
  env: { ...process.env, MESH_JOIN: "always", MESH_SESSION_NAME: name },
  stdio: ["pipe", "pipe", "inherit"],
});
const send = (o) => p.stdin.write(JSON.stringify(o) + "\n");
let nextId = 10;
const pending = new Map();

let buf = "";
p.stdout.on("data", (d) => {
  buf += d;
  let i;
  while ((i = buf.indexOf("\n")) >= 0) {
    const line = buf.slice(0, i); buf = buf.slice(i + 1);
    let m; try { m = JSON.parse(line); } catch { continue; }
    if (m.id === 1) {
      send({ jsonrpc: "2.0", method: "notifications/initialized" });
      send({ jsonrpc: "2.0", method: "tools/list" });
      log("joined as", name);
    } else if (m.id && pending.has(m.id)) {
      pending.get(m.id)(m); pending.delete(m.id);
    } else if (m.method === "notifications/claude/channel") {
      const meta = m.params?.meta || {};
      const rec = { ts: new Date().toISOString(), from: meta.from, msg_id: meta.msg_id, content: m.params?.content || "" };
      fs.appendFileSync(inbox, JSON.stringify(rec) + "\n");
      log("inbox <-", meta.from, JSON.stringify(rec.content).slice(0, 80));
    }
  }
});

// outbox: {to, message} one per line
let sent = 0;
setInterval(() => {
  let body;
  try { body = fs.readFileSync(outbox, "utf8"); } catch { return; }
  const lines = body.split("\n").filter(Boolean);
  if (lines.length <= sent) return;
  for (const line of lines.slice(sent)) {
    let o; try { o = JSON.parse(line); } catch { continue; }
    const id = nextId++;
    pending.set(id, (m) => log("sent ->", o.to, JSON.stringify(m.result?.content?.[0]?.text || m.error || "").slice(0, 120)));
    send({ jsonrpc: "2.0", id, method: "tools/call", params: { name: "send_message", arguments: { to: o.to, message: o.message } } });
  }
  sent = lines.length;
}, 500);

send({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "dsh-mesh", version: "0.1" } } });
p.on("exit", (c) => { log("peer exited", c); process.exit(c ?? 0); });
process.on("SIGTERM", () => { try { p.kill(); } catch {} process.exit(0); });
