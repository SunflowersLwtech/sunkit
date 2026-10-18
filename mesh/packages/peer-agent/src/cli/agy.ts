import { execFileSync } from 'node:child_process'
import { copyFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { askHookSocket, hookSocketPath, type HookReply, type HookRequest } from '../hook-socket.ts'
import { shellQuote, stableNode } from './devin.ts'

export const AGY_USAGE = 'usage: mesh agy install [--name mesh] [--node <path>] [--peer <path to mesh-peer.mjs>] [--cli <path to mesh-cli.mjs>] [--hooks <path to hooks.json>] [--write]\n       mesh agy hook <PreInvocation|Stop>   (run by Antigravity CLI)'

export interface AgyInstallOpts {
  /** Absolute path of the node binary agy should run. */
  node: string
  /** Absolute path of the bundled peer, mesh-peer.mjs. */
  peer: string
  /** Absolute path of the bundled CLI, mesh-cli.mjs, which runs the hooks. */
  cli: string
  name: string
  /** agy's global hooks file. */
  hooks: string
}

/**
 * argv for `agy mcp add`: the peer in pull mode, named after the host. MESH_SESSION_NAME is
 * deliberately not set here: agy lets a server's configured env override the session's, so a
 * name set in the config would name every session the same.
 */
export function agyAddArgs(o: AgyInstallOpts): string[] {
  return ['mcp', 'add', '-e', 'MESH_JOIN=pull', '-e', 'MESH_HOST=agy', o.name, '--', o.node, o.peer]
}

/** The hooks that tell a busy agent about new messages and report busy/idle to the mesh. */
export function agyHookEntry(o: AgyInstallOpts): Record<string, unknown> {
  const handler = (event: string) => ({ type: 'command', command: `${shellQuote(o.node)} ${shellQuote(o.cli)} agy hook ${event}`, timeout: 5 })
  return { PreInvocation: [handler('PreInvocation')], Stop: [handler('Stop')] }
}

/** hooks.json with our entry set under `name`; every other named hook is kept as it was. */
export function mergeHooks(existing: string | undefined, name: string, entry: Record<string, unknown>): string {
  const text = (existing ?? '').replace(/^﻿/, '').trim()
  const parsed: unknown = text ? JSON.parse(text) : {}
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('hooks.json is not a JSON object; fix or move it first')
  return JSON.stringify({ ...(parsed as Record<string, unknown>), [name]: entry }, null, 2) + '\n'
}

function flag(args: string[], name: string): string | undefined {
  const i = args.indexOf(name)
  return i >= 0 && i + 1 < args.length ? args[i + 1] : undefined
}

export function parseAgyInstall(args: string[], defaults: { node: string; peer: string; cli: string; hooks: string }): AgyInstallOpts {
  return {
    node: flag(args, '--node') ?? defaults.node,
    peer: flag(args, '--peer') ?? defaults.peer,
    cli: flag(args, '--cli') ?? defaults.cli,
    hooks: flag(args, '--hooks') ?? defaults.hooks,
    name: flag(args, '--name') ?? 'mesh',
  }
}

function stamp(d = new Date()): string {
  return d.toISOString().replace(/[-:]/g, '').replace(/\..*$/, '').replace('T', '-')
}

export function runAgyInstall(args: string[], io: { log?: (s: string) => void; run?: (file: string, argv: string[]) => void } = {}): number {
  const log = io.log ?? console.log
  // In the bundle this file is mesh-cli.mjs, next to mesh-peer.mjs.
  const cli = fileURLToPath(import.meta.url)
  const o = parseAgyInstall(args, {
    node: stableNode(process.env.PATH, process.execPath),
    peer: fileURLToPath(new URL('./mesh-peer.mjs', import.meta.url)),
    cli,
    hooks: join(homedir(), '.gemini', 'config', 'hooks.json'),
  })
  const argv = agyAddArgs(o)
  log(`agy ${argv.map(shellQuote).join(' ')}`)
  log(`${o.hooks}: set "${o.name}" to ${JSON.stringify(agyHookEntry(o))}`)
  log('Name each session before starting it: export MESH_SESSION_NAME=<name>; agy. Unnamed sessions are agy-<Herdr tab label> or agy-<directory>.')
  log('Messages wait in an inbox read with read_messages; while the agent works, the hooks tell it when one arrives. With MESH_WAKE=herdr set before starting agy in a Herdr pane, a message to an idle session also prompts it to read.')
  if (!args.includes('--write')) return 0
  const run = io.run ?? ((file: string, a: string[]) => { execFileSync(file, a, { stdio: 'inherit' }) })
  run('agy', argv)
  const before = existsSync(o.hooks) ? readFileSync(o.hooks, 'utf8') : undefined
  const after = mergeHooks(before, o.name, agyHookEntry(o))
  if (before !== after) {
    mkdirSync(dirname(o.hooks), { recursive: true })
    if (before !== undefined) copyFileSync(o.hooks, `${o.hooks}.bak-mesh-${stamp()}`)
    writeFileSync(o.hooks, after)
  }
  log('written')
  return 0
}

const plural = (n: number, one: string, many: string) => (n === 1 ? one : many)

/** What a hook prints for agy: inject a notice into the turn, or keep the agent going; {} for nothing. */
export function agyHookOutput(event: string, r: HookReply | undefined): Record<string, unknown> {
  if (!r || r.unread <= 0) return {}
  const n = r.unread
  const who = r.from.join(', ')
  if (event === 'PreInvocation') {
    return { injectSteps: [{ ephemeralMessage: `[mesh] ${n} unread ${plural(n, 'message', 'messages')} from ${who} ${plural(n, 'is', 'are')} waiting. Call the mesh read_messages tool to read ${plural(n, 'it', 'them')}.` }] }
  }
  if (event === 'Stop' && r.continue) {
    return { decision: 'continue', reason: `[mesh] ${n} ${plural(n, 'message', 'messages')} from ${who} arrived and ${plural(n, 'is', 'are')} still unread. Call the mesh read_messages tool and deal with ${plural(n, 'it', 'them')} before you finish.` }
  }
  return {}
}

export function hookRequest(event: string, payload: unknown): HookRequest | undefined {
  if (event === 'PreInvocation') return { op: 'turn' }
  if (event === 'Stop') {
    const reason = (payload as { terminationReason?: unknown } | null)?.terminationReason
    return typeof reason === 'string' ? { op: 'stop', reason } : { op: 'stop' }
  }
  return undefined
}

function parentOf(pid: number): number | undefined {
  try {
    if (process.platform === 'linux') return Number(readFileSync(`/proc/${pid}/stat`, 'utf8').replace(/^.*\) /s, '').split(' ')[1]) || undefined
    if (process.platform === 'win32') return undefined
    return Number(execFileSync('ps', ['-o', 'ppid=', '-p', String(pid)], { encoding: 'utf8', timeout: 2_000 }).trim()) || undefined
  } catch {
    return undefined
  }
}

/**
 * The hook command itself. agy runs it with `sh -c`, which usually execs it, so the host is
 * our parent; if the shell stayed around, it is our grandparent. Prints a JSON object and
 * exits 0 whatever happens: a failing hook must never get in the agent's way.
 */
export async function runAgyHook(args: string[], io: { stdin?: () => Promise<string>; write?: (s: string) => void; ppid?: number } = {}): Promise<number> {
  const write = io.write ?? (s => process.stdout.write(s))
  try {
    const event = args[0] ?? ''
    const raw = await (io.stdin ?? readStdin)()
    let payload: unknown = undefined
    try { payload = raw.trim() ? JSON.parse(raw) : undefined } catch { /* not JSON */ }
    const req = hookRequest(event, payload)
    let reply: HookReply | undefined
    if (req) {
      const ppid = io.ppid ?? process.ppid
      for (const pid of [ppid, parentOf(ppid)]) {
        if (!pid) continue
        const path = hookSocketPath(pid)
        if (process.platform !== 'win32' && !existsSync(path)) continue
        reply = await askHookSocket(path, req)
        if (reply) break
      }
    }
    write(JSON.stringify(agyHookOutput(event, reply)) + '\n')
  } catch {
    write('{}\n')
  }
  return 0
}

function readStdin(): Promise<string> {
  return new Promise(resolve => {
    if (process.stdin.isTTY) { resolve(''); return }
    let buf = ''
    const timer = setTimeout(() => resolve(buf), 2_000)
    process.stdin.setEncoding('utf8')
    process.stdin.on('data', d => { buf += d; if (buf.length > 1_000_000) { clearTimeout(timer); resolve(buf) } })
    process.stdin.on('end', () => { clearTimeout(timer); resolve(buf) })
    process.stdin.on('error', () => { clearTimeout(timer); resolve(buf) })
  })
}

export async function runAgy(args: string[]): Promise<number> {
  const [sub, ...rest] = args
  if (sub === 'install') return runAgyInstall(rest)
  if (sub === 'hook') return runAgyHook(rest)
  console.error(AGY_USAGE)
  return 2
}
