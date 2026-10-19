import { execFileSync } from 'node:child_process'
import { copyFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { HookReply, HookRequest } from '../hook-socket.ts'
import { shellQuote, stableNode } from './devin.ts'
import { askHostPeer, readStdin } from './host-hook.ts'

export const GROK_EVENTS = ['SessionStart', 'UserPromptSubmit', 'PostToolUse', 'PostToolUseFailure', 'Stop', 'StopCancelled', 'StopFailure'] as const

export const GROK_USAGE = 'usage: mesh grok install [--name mesh] [--node <path>] [--peer <path to mesh-peer.mjs>] [--cli <path to mesh-cli.mjs>] [--hooks <path to hooks file>] [--write]\n'
  + `       mesh grok hook <${GROK_EVENTS.join('|')}>   (run by Grok Build)`

export interface GrokInstallOpts {
  /** Absolute path of the node binary Grok Build should run. */
  node: string
  /** Absolute path of the bundled peer, mesh-peer.mjs. */
  peer: string
  /** Absolute path of the bundled CLI, mesh-cli.mjs, which runs the hooks. */
  cli: string
  name: string
  /** Our own file in Grok Build's global hooks directory (every *.json there is loaded). */
  hooks: string
}

/**
 * argv for `grok mcp add`: the peer in pull mode, named after the host. MESH_SESSION_NAME is
 * deliberately not set here: Grok Build lets a server's configured env override the session's
 * (measured), so a name set in the config would name every session the same.
 */
export function grokAddArgs(o: GrokInstallOpts): string[] {
  return ['mcp', 'add', '-e', 'MESH_JOIN=pull', '-e', 'MESH_HOST=grok', o.name, '--', o.node, o.peer]
}

/**
 * The hooks file: SessionStart reports idle (so a fresh session can be woken), a prompt marks
 * the session busy, a tool result carries a notice when mail arrived, and a stop that ended the
 * turn on its own is kept going once per new arrival. Grok Build reads only matcher groups.
 */
export function grokHooksFile(o: GrokInstallOpts): Record<string, unknown> {
  const group = (event: string) => [{ hooks: [{ type: 'command', command: `${shellQuote(o.node)} ${shellQuote(o.cli)} grok hook ${event}`, timeout: 5 }] }]
  return { hooks: Object.fromEntries(GROK_EVENTS.map(e => [e, group(e)])) }
}

function flag(args: string[], name: string): string | undefined {
  const i = args.indexOf(name)
  return i >= 0 && i + 1 < args.length ? args[i + 1] : undefined
}

export function parseGrokInstall(args: string[], defaults: { node: string; peer: string; cli: string; hooks: string }): GrokInstallOpts {
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

export function runGrokInstall(args: string[], io: { log?: (s: string) => void; run?: (file: string, argv: string[]) => void } = {}): number {
  const log = io.log ?? console.log
  // In the bundle this file is mesh-cli.mjs, next to mesh-peer.mjs.
  const cli = fileURLToPath(import.meta.url)
  const grokHome = process.env.GROK_HOME || join(homedir(), '.grok')
  const o = parseGrokInstall(args, {
    node: stableNode(process.env.PATH, process.execPath),
    peer: fileURLToPath(new URL('./mesh-peer.mjs', import.meta.url)),
    cli,
    hooks: join(grokHome, 'hooks', `${flag(args, '--name') ?? 'mesh'}.json`),
  })
  const argv = grokAddArgs(o)
  const text = JSON.stringify(grokHooksFile(o), null, 2) + '\n'
  log(`grok ${argv.map(shellQuote).join(' ')}`)
  log(`${o.hooks}: ${JSON.stringify(grokHooksFile(o))}`)
  log('Name each session before starting it: export MESH_SESSION_NAME=<name>; grok. Unnamed sessions are grok-<Herdr tab label> or grok-<directory>.')
  log('Standing rules for a session: grok --rules "<text>" (alias --append-system-prompt).')
  log('Messages wait in an inbox read with read_messages; while the agent works, a tool result tells it when one arrives, and a turn that ends with mail unread runs once more. With MESH_WAKE=herdr set before starting grok in a Herdr pane, a message to an idle session also prompts it to read.')
  log('Grok Build also loads Claude Code plugins: if `grok inspect` lists the Claude mesh plugin, add "mesh" to [plugins] disabled in ~/.grok/config.toml.')
  if (!args.includes('--write')) return 0
  const run = io.run ?? ((file: string, a: string[]) => { execFileSync(file, a, { stdio: 'inherit' }) })
  run('grok', argv)
  const before = existsSync(o.hooks) ? readFileSync(o.hooks, 'utf8') : undefined
  if (before !== text) {
    mkdirSync(dirname(o.hooks), { recursive: true })
    // Not *.json, so Grok Build does not load the backup as a second set of hooks.
    if (before !== undefined) copyFileSync(o.hooks, `${o.hooks}.bak-mesh-${stamp()}`)
    writeFileSync(o.hooks, text)
  }
  log('written')
  return 0
}

const plural = (n: number, one: string, many: string) => (n === 1 ? one : many)

/** What a hook prints for Grok Build: a note on a tool result, or a blocked stop; {} for nothing. */
export function grokHookOutput(event: string, r: HookReply | undefined): Record<string, unknown> {
  if (!r || r.unread <= 0) return {}
  const n = r.unread
  const who = r.from.join(', ')
  if ((event === 'PostToolUse' || event === 'PostToolUseFailure') && r.notify) {
    return { hookSpecificOutput: { hookEventName: event, additionalContext: `[mesh] ${n} unread ${plural(n, 'message', 'messages')} from ${who} ${plural(n, 'is', 'are')} waiting. Call the mesh read_messages tool to read ${plural(n, 'it', 'them')}.` } }
  }
  if (event === 'Stop' && r.continue) {
    return { decision: 'block', reason: `[mesh] ${n} ${plural(n, 'message', 'messages')} from ${who} arrived and ${plural(n, 'is', 'are')} still unread. Call the mesh read_messages tool and deal with ${plural(n, 'it', 'them')} before you finish.` }
  }
  return {}
}

/**
 * Grok Build's Stop carries reason "end_turn" when the turn ended on its own ("shutdown" when
 * the session closes); interrupts, declined permissions and turn limits fire StopCancelled,
 * API errors StopFailure. Only the first may be kept going.
 */
export function grokHookRequest(event: string, payload: unknown): HookRequest | undefined {
  const r = (payload as { reason?: unknown } | null | undefined)?.reason
  const reason = typeof r === 'string' ? { reason: r } : {}
  if (event === 'SessionStart') return { op: 'idle' }
  if (event === 'UserPromptSubmit') return { op: 'turn' }
  if (event === 'PostToolUse' || event === 'PostToolUseFailure') return { op: 'tool' }
  if (event === 'Stop') return { op: 'stop', ...reason, natural: r === 'end_turn' }
  if (event === 'StopCancelled' || event === 'StopFailure') return { op: 'stop', ...reason, natural: false }
  return undefined
}

/** The hook command itself. Prints a JSON object and exits 0 whatever happens: a failing hook must never get in the agent's way. */
export async function runGrokHook(args: string[], io: { stdin?: () => Promise<string>; write?: (s: string) => void; ppid?: number } = {}): Promise<number> {
  const write = io.write ?? (s => process.stdout.write(s))
  try {
    const event = args[0] ?? ''
    const raw = await (io.stdin ?? readStdin)()
    let payload: unknown = undefined
    try { payload = raw.trim() ? JSON.parse(raw) : undefined } catch { /* not JSON */ }
    const req = grokHookRequest(event, payload)
    const reply = req ? await askHostPeer(req, io.ppid ?? process.ppid) : undefined
    write(JSON.stringify(grokHookOutput(event, reply)) + '\n')
  } catch {
    write('{}\n')
  }
  return 0
}

export async function runGrok(args: string[]): Promise<number> {
  const [sub, ...rest] = args
  if (sub === 'install') return runGrokInstall(rest)
  if (sub === 'hook') return runGrokHook(rest)
  console.error(GROK_USAGE)
  return 2
}
