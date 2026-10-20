import { execFileSync } from 'node:child_process'
import { accessSync, constants, copyFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { delimiter, dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { HookReply, HookRequest } from '../hook-socket.ts'
import { askHostPeer, forgetHostPeer, readStdin } from './host-hook.ts'

export const DEVIN_EVENTS = ['SessionStart', 'UserPromptSubmit', 'PostToolUse', 'Stop', 'SessionEnd'] as const

export const DEVIN_USAGE = 'usage: mesh devin install [--scope user|project|local] [--name mesh] [--node <path>] [--peer <path to mesh-peer.mjs>] [--cli <path to mesh-cli.mjs>] [--config <path to Devin config.json>] [--write]\n'
  + `       mesh devin hook <${DEVIN_EVENTS.join('|')}>   (run by Devin CLI)`

export interface DevinInstallOpts {
  /** Absolute path of the node binary Devin should run (Devin may not share the shell's PATH). */
  node: string
  /** Absolute path of the bundled peer, mesh-peer.mjs. */
  peer: string
  /** Absolute path of the bundled CLI, mesh-cli.mjs, which runs the hooks. */
  cli: string
  scope: 'user' | 'project' | 'local'
  name: string
  /** Devin's user config, whose "hooks" key holds user-level hooks. */
  config: string
}

/**
 * argv for `devin mcp add`: the peer in pull mode, named after the host, so Devin reads messages
 * with read_messages. MESH_SESSION_NAME is not set here: one config serves every session.
 */
export function devinAddArgs(o: DevinInstallOpts): string[] {
  return ['mcp', 'add', '-s', o.scope, o.name, '-e', 'MESH_JOIN=pull', '-e', 'MESH_HOST=devin', '--', o.node, o.peer]
}

export function shellQuote(s: string): string {
  return /^[A-Za-z0-9_./:=@%+-]+$/.test(s) ? s : `'${s.replace(/'/g, `'\\''`)}'`
}

function isExecutable(p: string): boolean {
  try { accessSync(p, constants.X_OK); return true } catch { return false }
}

/**
 * The node Devin should run: the first one on PATH, which is usually a link that
 * survives upgrades (/opt/homebrew/bin/node), rather than process.execPath, which
 * resolves to a versioned binary (…/Cellar/node/26.0.0/bin/node) that an upgrade
 * deletes. fnm's per-shell directories are skipped: they vanish with the shell.
 */
export function stableNode(path: string | undefined, fallback: string, exists: (p: string) => boolean = isExecutable): string {
  for (const dir of (path ?? '').split(delimiter)) {
    if (!dir || dir.includes('fnm_multishells')) continue
    const candidate = join(dir, process.platform === 'win32' ? 'node.exe' : 'node')
    if (exists(candidate)) return candidate
  }
  return fallback
}

/**
 * Devin runs a hook command with `sh -c`, and on Windows with Git Bash's `bash -c`. There a
 * path is double-quoted with forward slashes, which bash and cmd both read the same way.
 */
function hookCommand(o: DevinInstallOpts, event: string, platform: NodeJS.Platform): string {
  const q = platform === 'win32' ? (s: string) => `"${s.replace(/\\/g, '/')}"` : shellQuote
  return `${q(o.node)} ${q(o.cli)} devin hook ${event}`
}

/**
 * The hooks: SessionStart reports idle (so a fresh session can be woken), a prompt marks the
 * session busy, a tool result carries a notice when mail arrived, a stop is kept going once per
 * new arrival, and SessionEnd forgets the session. SessionStart may wait a little for the peer,
 * which Devin starts at about the same time.
 */
export function devinHooks(o: DevinInstallOpts, platform: NodeJS.Platform = process.platform): Record<string, unknown[]> {
  return Object.fromEntries(DEVIN_EVENTS.map(e => [e, [{ hooks: [{ type: 'command', command: hookCommand(o, e, platform), timeout: e === 'SessionStart' ? 10 : 5 }] }]]))
}

/** A mesh hook, whatever the path to the CLI: the command ends in `devin hook <event>`. */
const OURS = /\sdevin hook [A-Za-z]+\s*$/

function isOurs(group: unknown): boolean {
  const hooks = (group as { hooks?: unknown } | null)?.hooks
  return Array.isArray(hooks) && hooks.some(h => typeof (h as { command?: unknown })?.command === 'string' && OURS.test((h as { command: string }).command))
}

/**
 * Devin's config.json with our hooks in it. Every other setting and every other hook group is kept;
 * an earlier mesh group (another checkout, an event no longer installed) is replaced or dropped.
 */
export function mergeDevinHooks(existing: string | undefined, ours: Record<string, unknown[]>): string {
  const text = (existing ?? '').replace(/^﻿/, '').trim()
  const parsed: unknown = text ? JSON.parse(text) : {}
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('Devin config.json is not a JSON object; fix or move it first')
  const cfg = parsed as Record<string, unknown>
  const hooks = cfg.hooks ?? {}
  if (!hooks || typeof hooks !== 'object' || Array.isArray(hooks)) throw new Error('Devin config.json: "hooks" is not an object; fix or move it first')
  const next: Record<string, unknown> = {}
  for (const [event, groups] of Object.entries(hooks as Record<string, unknown>)) {
    if (!Array.isArray(groups)) { next[event] = groups; continue }
    const kept = groups.filter(g => !isOurs(g))
    if (kept.length > 0 || groups.length === 0) next[event] = kept
  }
  for (const [event, groups] of Object.entries(ours)) {
    next[event] = [...(Array.isArray(next[event]) ? next[event] as unknown[] : []), ...groups]
  }
  return JSON.stringify({ ...cfg, hooks: next }, null, 2) + '\n'
}

function flag(args: string[], name: string): string | undefined {
  const i = args.indexOf(name)
  return i >= 0 && i + 1 < args.length ? args[i + 1] : undefined
}

export function parseDevinInstall(args: string[], defaults: { node: string; peer: string; cli: string; config: string }): DevinInstallOpts {
  const scope = flag(args, '--scope') ?? 'user'
  if (scope !== 'user' && scope !== 'project' && scope !== 'local') throw new Error(DEVIN_USAGE)
  return {
    node: flag(args, '--node') ?? defaults.node,
    peer: flag(args, '--peer') ?? defaults.peer,
    cli: flag(args, '--cli') ?? defaults.cli,
    config: flag(args, '--config') ?? defaults.config,
    scope,
    name: flag(args, '--name') ?? 'mesh',
  }
}

/** Devin's user config: ~/.config/devin/config.json, %APPDATA%\devin\config.json on Windows. */
function defaultConfig(): string {
  if (process.platform === 'win32') return join(process.env.APPDATA || join(homedir(), 'AppData', 'Roaming'), 'devin', 'config.json')
  return join(homedir(), '.config', 'devin', 'config.json')
}

function stamp(d = new Date()): string {
  return d.toISOString().replace(/[-:]/g, '').replace(/\..*$/, '').replace('T', '-')
}

export function runDevinInstall(args: string[], io: { log?: (s: string) => void; run?: (file: string, argv: string[]) => void } = {}): number {
  const log = io.log ?? console.log
  // In the bundle this file is mesh-cli.mjs, next to mesh-peer.mjs.
  const o = parseDevinInstall(args, {
    node: stableNode(process.env.PATH, process.execPath),
    peer: fileURLToPath(new URL('./mesh-peer.mjs', import.meta.url)),
    cli: fileURLToPath(import.meta.url),
    config: defaultConfig(),
  })
  const argv = devinAddArgs(o)
  log(`devin ${argv.map(shellQuote).join(' ')}`)
  log(`${o.config}: hooks ${DEVIN_EVENTS.join(', ')} run ${hookCommand(o, '<event>', process.platform)}`)
  log('Name each Devin session before starting it: export MESH_SESSION_NAME=<name>; devin. Unnamed sessions are devin-<Herdr tab label> or devin-<directory>.')
  log('Messages wait in an inbox read with read_messages; while the agent works, a tool result tells it when one arrives, and a turn that ends with mail unread runs once more. With MESH_WAKE=herdr set before starting devin in a Herdr pane, a message to an idle session also prompts it to read. devin -p only sends.')
  if (!args.includes('--write')) return 0
  const run = io.run ?? ((file: string, a: string[]) => { execFileSync(file, a, { stdio: 'inherit' }) })
  // `devin mcp add` refuses a name that exists; a reinstall replaces it.
  try { run('devin', ['mcp', 'remove', '-s', o.scope, o.name]) } catch { log(`(no "${o.name}" server in ${o.scope} scope yet)`) }
  run('devin', argv)
  const before = existsSync(o.config) ? readFileSync(o.config, 'utf8') : undefined
  const after = mergeDevinHooks(before, devinHooks(o))
  if (before !== after) {
    mkdirSync(dirname(o.config), { recursive: true })
    if (before !== undefined) copyFileSync(o.config, `${o.config}.bak-mesh-${stamp()}`)
    writeFileSync(o.config, after)
  }
  log('written')
  return 0
}

const plural = (n: number, one: string, many: string) => (n === 1 ? one : many)

/** What a hook prints for Devin CLI: a note on a tool result, or a blocked stop; {} for nothing. */
export function devinHookOutput(event: string, r: HookReply | undefined): Record<string, unknown> {
  if (!r || r.unread <= 0) return {}
  const n = r.unread
  const who = r.from.join(', ')
  if (event === 'PostToolUse' && r.notify) {
    return { hookSpecificOutput: { hookEventName: event, additionalContext: `[mesh] ${n} unread ${plural(n, 'message', 'messages')} from ${who} ${plural(n, 'is', 'are')} waiting. Call the mesh read_messages tool to read ${plural(n, 'it', 'them')}.` } }
  }
  if (event === 'Stop' && r.continue) {
    return { decision: 'block', reason: `[mesh] ${n} ${plural(n, 'message', 'messages')} from ${who} arrived and ${plural(n, 'is', 'are')} still unread. Call the mesh read_messages tool and deal with ${plural(n, 'it', 'them')} before you finish.` }
  }
  return {}
}

/**
 * Devin CLI fires Stop only when the agent ends its turn itself: an interrupt (Esc) fires none,
 * so every Stop may be kept going. A stop the hook already kept going has stop_hook_active set;
 * the peer still allows only one extra turn per new arrival.
 */
export function devinHookRequest(event: string, _payload: unknown): HookRequest | undefined {
  if (event === 'SessionStart') return { op: 'idle' }
  if (event === 'UserPromptSubmit') return { op: 'turn' }
  if (event === 'PostToolUse') return { op: 'tool' }
  if (event === 'Stop') return { op: 'stop', natural: true }
  return undefined
}

/** The hook command itself. Prints a JSON object and exits 0 whatever happens: a failing hook must never get in the agent's way. */
export async function runDevinHook(args: string[], io: { stdin?: () => Promise<string>; write?: (s: string) => void; ppid?: number; waitMs?: number } = {}): Promise<number> {
  const write = io.write ?? (s => process.stdout.write(s))
  try {
    const event = args[0] ?? ''
    const raw = await (io.stdin ?? readStdin)()
    let payload: unknown = undefined
    try { payload = raw.trim() ? JSON.parse(raw) : undefined } catch { /* not JSON */ }
    const sid = (payload as { session_id?: unknown } | null | undefined)?.session_id
    const cacheKey = typeof sid === 'string' ? `devin-${sid}` : undefined
    if (event === 'SessionEnd') {
      forgetHostPeer(cacheKey)
      write('{}\n')
      return 0
    }
    const req = devinHookRequest(event, payload)
    const reply = req ? await askHostPeer(req, io.ppid ?? process.ppid, { cacheKey, waitMs: event === 'SessionStart' ? (io.waitMs ?? 3_000) : 0 }) : undefined
    write(JSON.stringify(devinHookOutput(event, reply)) + '\n')
  } catch {
    write('{}\n')
  }
  return 0
}

export async function runDevin(args: string[], io: { log?: (s: string) => void; run?: (file: string, argv: string[]) => void } = {}): Promise<number> {
  const [sub, ...rest] = args
  if (sub === 'install') return runDevinInstall(rest, io)
  if (sub === 'hook') return runDevinHook(rest)
  console.error(DEVIN_USAGE)
  return 2
}
