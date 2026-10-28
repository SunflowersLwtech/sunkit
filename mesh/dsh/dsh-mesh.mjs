#!/usr/bin/env node
// dsh-mesh — put a DeepSeek Harness session on a claude-mesh, without channels.
//
//   join    run the bridge: a real (push) mesh session whose inbound mail is
//           spooled to inbox.jsonl and whose outbox.jsonl is sent as written.
//   say     one-shot send as a send-only identity.
//   read    one-shot pull-mode read (read_messages) for hosts that prefer polling.
//   status  what the running bridge is doing.
//
// Exit codes: 0 ok · 2 usage · 3 peer failed · 4 timeout · 5 already running.
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { REPO_PEER, meshHome, sanitizeName, backoffMs, parseOutbox, inboxRecord, shouldRotate, parseFlags } from "./lib.mjs";

const EXIT = { ok: 0, usage: 2, peer: 3, timeout: 4, lock: 5 };
const INBOX_MAX = 5 * 1024 * 1024;
const REQUEST_TIMEOUT = 30_000;

const USAGE = `usage:
  dsh-mesh join   [--name NAME] [--dir DIR] [--peer FILE]
  dsh-mesh say    <to> <message...> [--reply-to MSG_ID] [--as NAME]
  dsh-mesh read   [--name NAME]
  dsh-mesh status [--dir DIR]

join keeps a push session alive next to the agent and spools mail to
<dir>/inbox.jsonl; append {"to":"session","message":"…"} lines to
<dir>/outbox.jsonl to send. Defaults: --name $MESH_AS or m4-dsh,
--dir ~/.mesh-names/<name>, --peer <this repo>/plugins/mesh/server/mesh-peer.mjs.

Identity (relay URL, token, handle) is read by the peer from ~/.claude-mesh
(MESH_HOME). Run \`mesh pair\` first, exactly as for any other host.`;

function log(...a) {
  process.stderr.write(`${new Date().toISOString()} dsh-mesh ${a.join(" ")}\n`);
}

function fail(code, msg) {
  log(msg);
  process.exit(code);
}

/** A peer process behind a tiny MCP client: init, request/response, notifications. */
function startPeer({ peerPath, joinMode, name, dir, onNotification, onExit }) {
  const child = spawn(process.execPath, [peerPath], {
    cwd: dir,
    env: { ...process.env, MESH_JOIN: joinMode, MESH_SESSION_NAME: name },
    stdio: ["pipe", "pipe", "pipe"],
  });
  const pending = new Map();
  let nextId = 1;
  let buf = "";

  child.stdout.setEncoding("utf8");
  child.stdout.on("data", (d) => {
    buf += d;
    let i;
    while ((i = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, i);
      buf = buf.slice(i + 1);
      let m;
      try {
        m = JSON.parse(line);
      } catch {
        continue;
      }
      if (m.id && pending.has(m.id)) {
        const { resolve, timer } = pending.get(m.id);
        clearTimeout(timer);
        pending.delete(m.id);
        resolve(m);
      } else if (m.method && onNotification) {
        onNotification(m);
      }
    }
  });
  child.stderr.setEncoding("utf8");
  child.stderr.on("data", (d) => process.stderr.write(d));
  child.on("exit", (code, signal) => onExit?.(code, signal));

  const write = (o) => child.stdin.write(JSON.stringify(o) + "\n");
  const request = (method, params) =>
    new Promise((resolve, reject) => {
      const id = nextId++;
      const timer = setTimeout(() => {
        pending.delete(id);
        reject(new Error(`${method} timed out`));
      }, REQUEST_TIMEOUT);
      pending.set(id, { resolve, timer });
      write({ jsonrpc: "2.0", id, method, params });
    });

  return {
    request,
    init: async () => {
      await request("initialize", { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "dsh-mesh", version: "0.2" } });
      write({ jsonrpc: "2.0", method: "notifications/initialized" });
    },
    kill: () => {
      try {
        child.kill("SIGTERM");
      } catch {}
    },
  };
}

function toolText(res) {
  const text = (res?.result?.content ?? []).map((c) => c.text).filter(Boolean).join("\n");
  if (res?.error) throw new Error(res.error.message ?? JSON.stringify(res.error));
  if (res?.result?.isError) throw new Error(text || "tool failed");
  return text;
}

async function oneShot({ peerPath, name, joinMode, dir, tool, args }) {
  const peer = startPeer({ peerPath, joinMode, name, dir, onExit: () => {} });
  try {
    await peer.init();
    return toolText(await peer.request("tools/call", { name: tool, arguments: args }));
  } finally {
    peer.kill();
  }
}

function pidAlive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function acquireLock(pidFile) {
  try {
    const pid = Number(fs.readFileSync(pidFile, "utf8").trim());
    if (pid && pidAlive(pid)) return false;
  } catch {}
  fs.writeFileSync(pidFile, String(process.pid), { mode: 0o600 });
  return true;
}

function appendInbox(file, record) {
  try {
    if (shouldRotate(fs.statSync(file).size, INBOX_MAX)) fs.renameSync(file, `${file}.1`);
  } catch {}
  fs.appendFileSync(file, JSON.stringify(record) + "\n", { mode: 0o600 });
}

async function cmdJoin(argv) {
  const { flags } = parseFlags(argv, ["name", "dir", "peer", "help"]);
  if (flags.help) return console.log(USAGE);
  const name = sanitizeName(flags.name ?? process.env.MESH_AS ?? "m4-dsh");
  if (!name) fail(EXIT.usage, "a session name is required");
  const peerPath = String(flags.peer ?? REPO_PEER);
  if (!fs.existsSync(peerPath)) fail(EXIT.peer, `peer not found: ${peerPath}`);
  if (!fs.existsSync(path.join(meshHome(), "config.json"))) fail(EXIT.peer, `not paired: ${path.join(meshHome(), "config.json")} is missing (run \`mesh pair\`)`);

  const dir = path.resolve(String(flags.dir ?? path.join(process.env.HOME ?? ".", ".mesh-names", name)));
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
  const inbox = path.join(dir, "inbox.jsonl");
  const outbox = path.join(dir, "outbox.jsonl");
  const failed = path.join(dir, "outbox.failed.jsonl");
  const stateFile = path.join(dir, "outbox.offset");
  const pidFile = path.join(dir, "bridge.pid");
  if (!acquireLock(pidFile)) fail(EXIT.lock, `already running (${pidFile})`);

  let stopping = false;
  let offset = 0;
  try {
    offset = Number(fs.readFileSync(stateFile, "utf8").trim() || 0) || 0;
  } catch {}
  const cleanup = () => {
    try {
      if (Number(fs.readFileSync(pidFile, "utf8").trim()) === process.pid) fs.unlinkSync(pidFile);
    } catch {}
  };
  process.on("exit", cleanup);
  for (const sig of ["SIGINT", "SIGTERM"]) {
    process.on(sig, () => {
      stopping = true;
      peer?.kill();
      setTimeout(() => process.exit(EXIT.ok), 300).unref();
    });
  }

  let peer;
  let attempt = 0;
  const pump = setInterval(async () => {
    let text;
    try {
      text = fs.readFileSync(outbox, "utf8");
    } catch {
      return;
    }
    const { records, nextOffset, bad } = parseOutbox(text, offset);
    if (bad) log(`skipped ${bad} malformed outbox line(s)`);
    if (nextOffset !== offset) {
      offset = nextOffset;
      fs.writeFileSync(stateFile, String(offset), { mode: 0o600 });
    }
    for (const r of records) {
      try {
        const res = await peer.request("tools/call", { name: "send_message", arguments: r });
        log(`sent -> ${r.to}: ${toolText(res).slice(0, 120)}`);
      } catch (err) {
        fs.appendFileSync(failed, JSON.stringify({ ...r, error: String(err.message ?? err) }) + "\n", { mode: 0o600 });
        log(`send failed -> ${r.to}: ${err.message ?? err}`);
      }
    }
  }, 500);
  pump.unref();

  const run = async () => {
    peer = startPeer({
      peerPath,
      joinMode: "always",
      name,
      dir,
      onNotification: (m) => {
        if (m.method !== "notifications/claude/channel") return;
        const rec = inboxRecord(m.params);
        appendInbox(inbox, rec);
        log(`inbox <- ${rec.from}: ${JSON.stringify(rec.content.slice(0, 80))}`);
      },
      onExit: (code) => {
        if (stopping) return;
        log(`peer exited (${code}); reconnecting in ${backoffMs(attempt)}ms`);
        setTimeout(() => {
          attempt++;
          run().catch((e) => log(`reconnect failed: ${e.message}`));
        }, backoffMs(attempt)).unref();
      },
    });
    await peer.init();
    attempt = 0;
    log(`joined as ${name} · inbox ${inbox} · outbox ${outbox}`);
  };
  await run();
}

function cmdSay(argv) {
  const { flags, rest } = parseFlags(argv, ["reply-to", "as", "help"]);
  if (flags.help) return console.log(USAGE);
  const [to, ...words] = rest;
  const message = words.join(" ");
  if (!to || !message) fail(EXIT.usage, "usage: dsh-mesh say <to> <message...>");
  const name = sanitizeName(flags.as ?? process.env.MESH_AS ?? "m4-dsh");
  const args = { to, message };
  if (flags["reply-to"]) args.in_reply_to = String(flags["reply-to"]);
  const dir = path.join(process.env.HOME ?? ".", ".mesh-names", name);
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
  oneShot({ peerPath: REPO_PEER, name, joinMode: "never", dir, tool: "send_message", args })
    .then((t) => console.log(t))
    .catch((e) => fail(EXIT.peer, e.message));
}

async function cmdRead(argv) {
  const { flags } = parseFlags(argv, ["name", "as", "help"]);
  if (flags.help) return console.log(USAGE);
  const name = sanitizeName(flags.name ?? flags.as ?? process.env.MESH_AS ?? "m4-dsh");
  const dir = path.join(process.env.HOME ?? ".", ".mesh-names", name);
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
  try {
    const t = await oneShot({ peerPath: REPO_PEER, name, joinMode: "pull", dir, tool: "read_messages", args: {} });
    console.log(t || "(no unread messages)");
  } catch (e) {
    fail(EXIT.peer, e.message);
  }
}

function cmdStatus(argv) {
  const { flags } = parseFlags(argv, ["dir", "name", "help"]);
  if (flags.help) return console.log(USAGE);
  const name = sanitizeName(flags.name ?? process.env.MESH_AS ?? "m4-dsh");
  const dir = path.resolve(String(flags.dir ?? path.join(process.env.HOME ?? ".", ".mesh-names", name)));
  const read = (f) => {
    try {
      return fs.readFileSync(path.join(dir, f), "utf8");
    } catch {
      return "";
    }
  };
  const pid = Number(read("bridge.pid").trim() || 0);
  const inbox = read("inbox.jsonl").trim().split("\n").filter(Boolean);
  let last = null;
  try {
    last = inbox.length ? JSON.parse(inbox[inbox.length - 1]) : null;
  } catch {}
  console.log(JSON.stringify({ dir, running: pid ? pidAlive(pid) : false, pid: pid || null, inbox_lines: inbox.length, last, outbox_offset: Number(read("outbox.offset").trim() || 0) }, null, 2));
}

const [cmd, ...rest] = process.argv.slice(2);
try {
  if (!cmd || cmd === "help" || cmd === "--help" || cmd === "-h") console.log(USAGE);
  else if (cmd === "join") await cmdJoin(rest);
  else if (cmd === "say") cmdSay(rest);
  else if (cmd === "read") await cmdRead(rest);
  else if (cmd === "status") cmdStatus(rest);
  else fail(EXIT.usage, `unknown command: ${cmd}\n${USAGE}`);
} catch (e) {
  fail(EXIT.peer, e.message ?? String(e));
}
