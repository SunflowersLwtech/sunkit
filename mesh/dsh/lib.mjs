// Pure helpers for the DSH bridge. Kept free of I/O so they can be tested
// without a relay, a peer process or the network.
import { join } from "node:path";
import { homedir } from "node:os";
import { fileURLToPath } from "node:url";
import { dirname } from "node:path";

export const REPO_PEER = join(dirname(fileURLToPath(import.meta.url)), "..", "plugins", "mesh", "server", "mesh-peer.mjs");

export function meshHome(env = process.env) {
  return env.MESH_HOME ?? join(homedir(), ".claude-mesh");
}

/** A session name the relay accepts: lower-case, 1-32 chars of [a-z0-9_-]. */
export function sanitizeName(raw) {
  const s = String(raw ?? "").toLowerCase().replace(/[^a-z0-9_-]/g, "-").replace(/-+/g, "-").replace(/^-|-$/g, "");
  return s.slice(0, 32);
}

/** 1s, 2s, 5s, 10s, then 30s for every further attempt. */
export function backoffMs(attempt) {
  const table = [1000, 2000, 5000, 10000];
  return attempt < table.length ? table[attempt] : 30000;
}

/**
 * Read complete JSON lines from `text` starting at `offset` (a byte offset into
 * the file the text was read from, assumed UTF-8). A trailing fragment without
 * a newline is left for the next read; `nextOffset` points at it so nothing is
 * half-parsed and nothing is delivered twice.
 */
export function parseOutbox(text, offset = 0) {
  if (offset > text.length) offset = 0; // file was truncated or replaced: start over
  const chunk = text.slice(offset);
  const records = [];
  let consumed = 0;
  let bad = 0;
  for (const line of chunk.split("\n")) {
    const len = line.length + 1;
    if (consumed + len > chunk.length) break; // last line has no newline yet
    consumed += len;
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      const o = JSON.parse(trimmed);
      if (o && typeof o.to === "string" && typeof o.message === "string" && o.to && o.message) {
        records.push({ to: o.to, message: o.message, in_reply_to: typeof o.in_reply_to === "string" ? o.in_reply_to : undefined });
      } else bad++;
    } catch {
      bad++;
    }
  }
  return { records, nextOffset: offset + consumed, bad };
}

/** Turn an MCP channel notification into the line written to inbox.jsonl. */
export function inboxRecord(params, now = new Date()) {
  const meta = params?.meta ?? {};
  return {
    ts: now.toISOString(),
    from: meta.from ?? "",
    msg_id: meta.msg_id ?? "",
    content: typeof params?.content === "string" ? params.content : "",
  };
}

/**
 * Inbox lines from `cursor` (a count of lines already read) onward. The cursor
 * only ever counts complete lines, so a torn write is read on the next call
 * instead of half-parsed; a shrink (rotated file) restarts at 0.
 */
export function readInbox(text, cursor = 0) {
  const lines = text.split("\n");
  const complete = lines.slice(0, -1); // last element is "" or a torn fragment
  const start = cursor > complete.length ? 0 : cursor;
  const messages = [];
  let bad = 0;
  for (const line of complete.slice(start)) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      messages.push(JSON.parse(trimmed));
    } catch {
      bad++;
    }
  }
  return { messages, nextCursor: complete.length, bad, restarted: start === 0 && cursor > 0 };
}

/** Where the next inbox read starts, kept beside the inbox. */
export function cursorFrom(raw) {
  const n = Number(String(raw ?? "").trim());
  return Number.isFinite(n) && n >= 0 ? Math.floor(n) : 0;
}

/** Rotate a file to `<file>.1` once it grows past `maxBytes`; true when rotated. */
export function shouldRotate(size, maxBytes) {
  return Number.isFinite(size) && size > maxBytes;
}

/** Parse `join --name x --dir y` style flags, rejecting unknown ones. */
export function parseFlags(argv, known) {
  const out = {};
  const rest = [];
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--") { rest.push(...argv.slice(i + 1)); break; }
    if (!a.startsWith("--")) { rest.push(a); continue; }
    const [k, inline] = a.includes("=") ? [a.slice(0, a.indexOf("=")), a.slice(a.indexOf("=") + 1)] : [a, undefined];
    const name = k.slice(2);
    if (!known.includes(name)) throw new Error(`unknown option ${k}`);
    if (inline !== undefined) out[name] = inline;
    else if (i + 1 < argv.length && !argv[i + 1].startsWith("--")) out[name] = argv[++i];
    else out[name] = true;
  }
  return { flags: out, rest };
}
