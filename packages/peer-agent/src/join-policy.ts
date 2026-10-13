import { execFileSync } from 'node:child_process'

/**
 * Claude Code gives an MCP server no signal (initialize capabilities are
 * identical) about whether it was opted in as a channel. Without that opt-in,
 * pushed messages are silently dropped — so a session that wasn't launched with
 * the mesh channel must not register as reachable, or senders would see
 * "delivered" for messages nobody reads. The only reliable signal is the
 * parent Claude Code process's own command line.
 */
const FLAG = /(?:^|\s)--(?:channels|dangerously-load-development-channels)(?:=|\s+)((?:(?:plugin|server):\S+(?:\s+|$))+)/g

export function channelOptIn(commandLine: string, serverName = 'mesh'): boolean {
  for (const m of commandLine.matchAll(FLAG)) {
    for (const entry of m[1]!.trim().split(/\s+/)) {
      if (entry === `server:${serverName}`) return true
      if (entry.startsWith(`plugin:${serverName}@`)) return true
    }
  }
  return false
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
}): JoinDecision {
  if (opts.env === 'always') return { join: true, reason: 'MESH_JOIN=always' }
  if (opts.env === 'never') return { join: false, reason: 'MESH_JOIN=never' }
  if (opts.sessionKind && opts.sessionKind !== 'interactive') {
    return { join: false, reason: `session kind ${opts.sessionKind}` }
  }
  if (!channelOptIn(opts.commandLine, opts.serverName)) {
    return { join: false, reason: 'parent not launched with the mesh channel' }
  }
  return { join: true, reason: 'channel opt-in on parent command line' }
}
