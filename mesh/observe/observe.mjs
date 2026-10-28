#!/usr/bin/env node
// mesh-observe — one snapshot of who is on the mesh, where, and what state they
// are in, rendered as a self-contained page (no deps, no build step).
//
//   node mesh/observe/observe.mjs                # JSON to stdout
//   node mesh/observe/observe.mjs --html OUT     # the page
//
// Reads the relay with the same token the peers use (~/.claude-mesh/token,
// MESH_HOME honoured). READ-ONLY: only GETs /v1/sessions and /v1/machines.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const home = process.env.MESH_HOME ?? path.join(os.homedir(), ".claude-mesh");
const cfg = JSON.parse(fs.readFileSync(path.join(home, "config.json"), "utf8"));
const token = fs.readFileSync(cfg.token_path ?? path.join(home, "token"), "utf8").trim();
const relay = (process.env.MESH_RELAY ?? cfg.relay_url).replace(/\/$/, "");

async function get(p) {
  const r = await fetch(relay + p, { headers: { authorization: `Bearer ${token}` } });
  if (!r.ok) throw new Error(`${p}: HTTP ${r.status}`);
  return r.json();
}

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const short = (s, n) => (String(s ?? "").length > n ? String(s).slice(0, n - 1) + "…" : String(s ?? ""));

function age(sec) {
  if (sec == null) return "—";
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.round(sec / 60)}m`;
  return `${(sec / 3600).toFixed(1)}h`;
}

const [sessions, machines] = await Promise.all([get("/v1/sessions"), get("/v1/machines")]);
const now = new Date();

const byStatus = sessions.reduce((a, s) => ((a[s.status] = (a[s.status] ?? 0) + 1), a), {});
const byAgent = sessions.reduce((a, s) => ((a[s.agent ?? "?"] = (a[s.agent ?? "?"] ?? 0) + 1), a), {});
const byAccount = sessions.reduce((a, s) => ((a[s.account ?? "?"] = (a[s.account ?? "?"] ?? 0) + 1), a), {});

// A bridge is observable through its own files; report what is there, if anything.
function bridgeState(name) {
  const dir = path.join(os.homedir(), ".mesh-names", name);
  try {
    const st = JSON.parse(fs.readFileSync(path.join(dir, "bridge.state.json"), "utf8"));
    const lines = fs.readFileSync(path.join(dir, "inbox.jsonl"), "utf8").trim().split("\n").filter(Boolean);
    const inbox = lines.length;
    const recent = lines.slice(-2).map((l) => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);
    const cursor = Number(fs.readFileSync(path.join(dir, "inbox.cursor"), "utf8").trim() || 0);
    let failed = 0;
    try {
      failed = fs.readFileSync(path.join(dir, "outbox.failed.jsonl"), "utf8").trim().split("\n").filter(Boolean).length;
    } catch {}
    return { name, ...st, inbox, cursor, unread: Math.max(0, inbox - cursor), failed, recent };
  } catch {
    return null;
  }
}

const snapshot = {
  at: now.toISOString(),
  relay,
  sessions: sessions.map((s) => ({
    name: s.name, ref: s.ref, account: s.account, device: s.device, status: s.status,
    agent: s.agent, model: s.model, repo: s.repo, branch: s.branch, cwd: s.cwd,
    machine: s.herdr?.machine ?? s.device, tab: s.herdr?.tab, age_s: s.age_s,
  })),
  machines: machines.map((m) => ({
    machine: m.machine, connected: m.connected, stale: m.stale, age_s: m.age_s,
    load1: m.report?.load?.load1, cpus: m.report?.load?.cpus, mem_pct: m.report?.load?.mem_used_pct,
    herdr: m.report?.herdr?.version, kinds: (m.report?.kinds ?? []).map((k) => k.kind),
  })),
  summary: { sessions: sessions.length, byStatus, byAgent, byAccount, machines: machines.length },
  bridge: bridgeState("m4-dsh"),
};

if (!process.argv.includes("--html")) {
  console.log(JSON.stringify(snapshot, null, 2));
  process.exit(0);
}
const out = process.argv[process.argv.indexOf("--html") + 1];

// ------------------------------------------------------------------ page
const STATUS_ORDER = ["busy", "idle", "unknown", "offline"];
const statusRows = STATUS_ORDER.filter((s) => byStatus[s]).map((s) => ({
  s, n: byStatus[s], pct: Math.round((byStatus[s] / sessions.length) * 100),
}));
const top = [...snapshot.sessions].sort((a, b) => (a.age_s ?? 1e9) - (b.age_s ?? 1e9)).slice(0, 12);
const machineRows = [...snapshot.machines].sort((a, b) => (a.machine > b.machine ? 1 : -1));

const page = `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>mesh 观测台</title>
<style>
:root{--paper:#faf9f6;--ink:#1d2025;--muted:#555c69;--soft:#8a90a0;--line:rgba(29,32,37,.14);--card:#fff;
--accent:#b4551f;--accent-tint:rgba(180,85,31,.08);--link:#2f5aa0;--ok:#1c6b46;--chip:rgba(29,32,37,.05);
--sans:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Noto Sans CJK SC","Segoe UI",sans-serif;
--mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;--serif:"Songti SC","Noto Serif CJK SC",Georgia,serif}
@media (prefers-color-scheme:dark){:root{--paper:#1b1e24;--ink:#eceef2;--muted:#b9bfcc;--soft:#828a9b;
--line:rgba(236,238,242,.15);--card:#242832;--accent:#e08a5a;--accent-tint:rgba(224,138,90,.12);
--link:#7ea3e0;--ok:#69c39a;--chip:rgba(236,238,242,.06)}}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{background:var(--paper);color:var(--ink);font:15px/1.65 var(--sans);padding:24px 16px 48px}
main{max-width:820px;margin:0 auto}
.eyebrow{font:11px/1.4 var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--soft)}
h1{font-family:var(--serif);font-size:clamp(24px,6vw,34px);line-height:1.2;margin:8px 0 6px;font-weight:600}
.at{font:12px/1.6 var(--mono);color:var(--soft);margin-bottom:22px}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:26px}
@media(max-width:560px){.stats{grid-template-columns:repeat(2,1fr)}}
.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.stat b{display:block;font-size:22px;line-height:1.2;font-variant-numeric:tabular-nums}
.stat span{font-size:11.5px;color:var(--soft)}
h2{font-size:15px;margin:26px 0 8px}
.bars{display:grid;gap:6px;margin:8px 0 4px}
.bar{display:grid;grid-template-columns:64px 1fr 44px;align-items:center;gap:8px;font-size:12.5px}
.track{display:block;height:8px;border-radius:5px;background:var(--chip);overflow:hidden}
.fill{display:block;height:100%;background:var(--accent);border-radius:5px}
.bar em{font-style:normal;color:var(--soft);text-align:right;font-family:var(--mono);font-size:11px}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th,td{text-align:left;padding:7px 6px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:11px;color:var(--soft);font-weight:500;text-transform:uppercase;letter-spacing:.04em}
td.n{font-family:var(--mono);font-variant-numeric:tabular-nums}
.pill{font-size:10.5px;padding:0 6px;border-radius:9px;border:1px solid var(--line);white-space:nowrap}
.pill.busy{color:var(--accent);border-color:var(--accent)}
.pill.idle{color:var(--ok);border-color:var(--ok)}
.muted{color:var(--soft)}
code{font-family:var(--mono);font-size:.92em}
pre{background:var(--chip);border:1px solid var(--line);border-radius:9px;padding:10px 12px;overflow-x:auto;font:11.5px/1.6 var(--mono)}
@media(max-width:560px){table,thead,tbody,tr,td,th{display:block}thead{display:none}
tr{border:1px solid var(--line);border-radius:9px;margin-bottom:8px;padding:4px 10px;background:var(--card)}
td{border:0;padding:2px 0}td:first-child{font-weight:600;margin-top:4px}}
footer{font-size:12px;color:var(--soft);border-top:1px solid var(--line);margin-top:26px;padding-top:10px}
</style></head><body><main>
<p class="eyebrow">mesh observe · 只读快照</p>
<h1>${sessions.length} 个会话，在 ${machines.length} 台机器上</h1>
<p class="at">${now.toLocaleString("zh-CN", { hour12: false })} · ${esc(relay)}</p>
<div class="stats">
<div class="stat"><b>${sessions.length}</b><span>在线会话</span></div>
<div class="stat"><b>${byStatus.busy ?? 0}</b><span>正在干活</span></div>
<div class="stat"><b>${machines.filter((m) => m.connected).length}/${machines.length}</b><span>机器在线</span></div>
<div class="stat"><b>${snapshot.bridge ? snapshot.bridge.unread : "—"}</b><span>DSH 未读</span></div>
</div>

<h2>谁在干什么</h2>
<div class="bars">${statusRows.map((r) => `<div class="bar"><span>${esc(r.s)}</span><span class="track"><span class="fill" style="width:${r.pct}%"></span></span><em>${r.n}</em></div>`).join("")}</div>

<h2>最近活跃的 12 个</h2>
<table><thead><tr><th>会话</th><th>状态</th><th>agent / model</th><th>仓库</th><th>机器</th><th>最后</th></tr></thead><tbody>
${top.map((s) => `<tr><td>${esc(s.name)} <span class="muted">${esc(s.ref)}</span></td>
<td><span class="pill ${esc(s.status)}">${esc(s.status)}</span></td>
<td>${esc(s.agent ?? "?")}<span class="muted"> · ${esc(short(s.model, 22))}</span></td>
<td>${esc(short(s.repo ?? "—", 18))}<span class="muted"> ${esc(short(s.branch ?? "", 14))}</span></td>
<td>${esc(short(s.machine ?? "—", 18))}</td><td class="n">${age(s.age_s)}</td></tr>`).join("")}
</tbody></table>

${snapshot.bridge?.recent?.length ? `<h2>最近投递（DSH 桥）</h2><table><tbody>${snapshot.bridge.recent.map((m) => `<tr><td>${esc(short(m.from, 20))}</td><td class="muted">${esc(short(String(m.content ?? "").replace(/\n/g, " "), 60))}</td><td class="n">${esc((m.ts ?? "").slice(11, 19))}</td></tr>`).join("")}</tbody></table>` : ""}

<h2>机器</h2>
<table><thead><tr><th>机器</th><th>连接</th><th>负载</th><th>内存</th><th>herdr</th><th>上报</th></tr></thead><tbody>
${machineRows.map((m) => `<tr><td>${esc(m.machine)}</td><td>${m.connected ? "✓" : "✗"}${m.stale ? " 陈旧" : ""}</td>
<td class="n">${m.load1 ?? "—"}${m.cpus ? ` / ${m.cpus}` : ""}</td><td class="n">${m.mem_pct ?? "—"}%</td>
<td class="n">${esc(m.herdr ?? "—")}</td><td class="n">${age(m.age_s)}</td></tr>`).join("")}
</tbody></table>

<h2>观测契约（想成为共识的那部分）</h2>
<p class="muted" style="font-size:13px">任何 agent 消息系统只要能回答这四个问题，就能填进同一张表：谁发给谁、到没到、多久、谁在读。mesh 这边由 relay 的 <code>/v1/sessions</code>（谁在哪）加投递方的游标/失败文件（到没到）拼出来。</p>
<pre>{
  "ts": "2026-10-28T13:20:00Z",
  "system": "mesh",                  // mesh | dsh-team | any
  "from": { "session": "m4-dsh", "account": "duocode", "device": "duocode-m4" },
  "to":   { "session": "feishu-assistant", "ref": "s7kexj" },
  "msg_id": "msg_01M6…",
  "bytes": 412,
  "state": "delivered",              // sent | delivered | read | failed
  "latency_ms": 180
}</pre>
<p class="muted" style="font-size:12.5px">DSH bridge 的 <code>inbox.cursor</code> 就是 <code>read</code> 的证据；<code>outbox.failed.jsonl</code> 是 <code>failed</code> 的证据。</p>

<footer>只读：GET /v1/sessions, /v1/machines；桥接状态读本地 <code>~/.mesh-names/m4-dsh</code>。由 <code>mesh/observe/observe.mjs</code> 生成。</footer>
</main></body></html>`;

fs.writeFileSync(out, page);
console.error(`wrote ${out} (${sessions.length} sessions, ${machines.length} machines)`);
