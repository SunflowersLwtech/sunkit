import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { selectManagedPolicy, type ManagedPolicy } from './managed-policy.ts'

/**
 * Claude Code gives an MCP server no signal (initialize capabilities are
 * identical) about whether it was opted in as a channel. Without that opt-in,
 * pushed messages are silently dropped — so a session that wasn't launched with
 * the mesh channel must not register as reachable, or senders would see
 * "delivered" for messages nobody reads. The only reliable signal is the
 * parent Claude Code process's own command line.
 */
const FLAG = /(?:^|\s)--(?:channels|dangerously-load-development-channels)(?:=|\s+)((?:(?:plugin|server):\S+(?:\s+|$))+)/g

export type OptIn =
  | { via: 'dev' }
  | { via: 'channels'; marketplace: string }
  | null

/** How (if at all) the parent opted this server in as a channel. */
export function channelOptInVia(commandLine: string, serverName = 'mesh'): OptIn {
  for (const m of commandLine.matchAll(FLAG)) {
    const dev = m[0].includes('--dangerously-load-development-channels')
    for (const entry of m[1]!.trim().split(/\s+/)) {
      if (entry === `server:${serverName}`) return dev ? { via: 'dev' } : null
      if (entry.startsWith(`plugin:${serverName}@`)) {
        return dev ? { via: 'dev' } : { via: 'channels', marketplace: entry.slice(`plugin:${serverName}@`.length) }
      }
    }
  }
  return null
}

export function channelOptIn(commandLine: string, serverName = 'mesh'): boolean {
  return channelOptInVia(commandLine, serverName) !== null
}

export interface OrgChannelPolicy {
  channelsEnabled?: boolean
  allowedChannelPlugins?: Array<{ marketplace?: string; plugin?: string }>
}

/**
 * The channel keys of the managed settings Claude Code enforces: the org's
 * server-managed settings when they carry a policy, otherwise the machine's
 * MDM profile, registry policy or managed-settings.json (see managed-policy.ts).
 */
export function readChannelPolicy(select: () => ManagedPolicy | null = selectManagedPolicy): { policy: OrgChannelPolicy | null; source: string } {
  const managed = select()
  if (!managed) return { policy: null, source: 'no managed settings' }
  return { policy: managed.settings as OrgChannelPolicy, source: managed.sources.map(s => `${s.kind}:${s.label}`).join(' + ') }
}

/**
 * Mirror Claude Code's own registration rules so we never advertise a session
 * whose channel it is about to reject. Both read the same managed sources, so a
 * stale cache (e.g. the first launch after an allowlist change) fails closed on
 * both sides instead of producing silent drops. channelsEnabled is required even
 * though Claude Code skips that check for personal Pro/Max logins: a policy
 * without it leaves the session send-only rather than risking a silent drop.
 */
export function orgAllows(opt: Exclude<OptIn, null>, policy: OrgChannelPolicy | null, plugin = 'mesh'): boolean {
  if (!policy || policy.channelsEnabled !== true) return false
  if (opt.via === 'dev') return true
  return (policy.allowedChannelPlugins ?? []).some(e => e.marketplace === opt.marketplace && e.plugin === plugin)
}

/** Linux /proc/<pid>/cmdline as one space-joined line; '' when unreadable. */
export function readProcCmdline(pid: number, procRoot = '/proc'): string {
  try {
    return readFileSync(join(procRoot, String(pid), 'cmdline'), 'utf8').split('\0').filter(Boolean).join(' ')
  } catch {
    return ''
  }
}

export function parentCommandLine(ppid: number = process.ppid): string {
  // Linux: read /proc first. Minimal containers (node images, OpenWrt) often have no `ps`,
  // and an empty answer here reads as "not launched with the channel".
  if (process.platform === 'linux') {
    const line = readProcCmdline(ppid)
    if (line) return line
  }
  try {
    if (process.platform === 'win32') {
      return execFileSync('powershell.exe', [
        '-NoProfile', '-NonInteractive', '-Command',
        `(Get-CimInstance Win32_Process -Filter "ProcessId=${ppid}").CommandLine`,
      ], { encoding: 'utf8', timeout: 10_000, windowsHide: true }).trim()
    }
    return execFileSync('ps', ['-o', 'command=', '-p', String(ppid)], { encoding: 'utf8', timeout: 5_000 }).trim()
  } catch {
    return ''
  }
}

export interface JoinDecision { join: boolean; reason: string }

export function decideJoin(opts: {
  env?: string | undefined
  commandLine: string
  sessionKind?: string | undefined
  serverName?: string
  /** undefined = read the managed sources Claude Code reads; null = none. */
  policy?: OrgChannelPolicy | null
  /** Source selection used when policy is undefined (tests inject readers here). */
  select?: () => ManagedPolicy | null
}): JoinDecision {
  if (opts.env === 'always') return { join: true, reason: 'MESH_JOIN=always' }
  if (opts.env === 'never') return { join: false, reason: 'MESH_JOIN=never' }
  if (opts.sessionKind && opts.sessionKind !== 'interactive') {
    return { join: false, reason: `session kind ${opts.sessionKind}` }
  }
  const opt = channelOptInVia(opts.commandLine, opts.serverName)
  if (!opt) return { join: false, reason: 'parent not launched with the mesh channel' }
  const { policy, source } = opts.policy === undefined ? readChannelPolicy(opts.select) : { policy: opts.policy, source: 'given policy' }
  if (!orgAllows(opt, policy)) {
    return { join: false, reason: `managed policy would reject the channel (${opt.via}; ${source}); restart once the managed settings are in place` }
  }
  return { join: true, reason: `channel opt-in via ${opt.via}, allowed by managed policy (${source})` }
}
