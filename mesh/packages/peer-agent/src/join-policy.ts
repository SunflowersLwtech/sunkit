import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { homedir } from 'node:os'

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

/** Claude Code's cached copy of the org's managed settings (what it enforces at startup). */
export function readOrgChannelPolicy(path = join(homedir(), '.claude', 'remote-settings.json')): OrgChannelPolicy | null {
  try { return JSON.parse(readFileSync(path, 'utf8')) as OrgChannelPolicy } catch { return null }
}

/**
 * Mirror Claude Code's own registration rules so we never advertise a session
 * whose channel it is about to reject. Both read the same cache, so a stale
 * cache (e.g. the first launch after an allowlist change) fails closed on both
 * sides instead of producing silent drops.
 */
export function orgAllows(opt: Exclude<OptIn, null>, policy: OrgChannelPolicy | null, plugin = 'mesh'): boolean {
  if (!policy || policy.channelsEnabled !== true) return false
  if (opt.via === 'dev') return true
  return (policy.allowedChannelPlugins ?? []).some(e => e.marketplace === opt.marketplace && e.plugin === plugin)
}

export function parentCommandLine(ppid: number = process.ppid): string {
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
  /** undefined = read Claude Code's cache; null = no cached policy. */
  policy?: OrgChannelPolicy | null
}): JoinDecision {
  if (opts.env === 'always') return { join: true, reason: 'MESH_JOIN=always' }
  if (opts.env === 'never') return { join: false, reason: 'MESH_JOIN=never' }
  if (opts.sessionKind && opts.sessionKind !== 'interactive') {
    return { join: false, reason: `session kind ${opts.sessionKind}` }
  }
  const opt = channelOptInVia(opts.commandLine, opts.serverName)
  if (!opt) return { join: false, reason: 'parent not launched with the mesh channel' }
  const policy = opts.policy === undefined ? readOrgChannelPolicy() : opts.policy
  if (!orgAllows(opt, policy)) {
    return { join: false, reason: `org policy would reject the channel (${opt.via}); restart once the managed settings are cached` }
  }
  return { join: true, reason: `channel opt-in via ${opt.via}, allowed by org policy` }
}
