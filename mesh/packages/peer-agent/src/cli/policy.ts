import { accessSync, constants, existsSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join, win32 } from 'node:path'
import { tmpdir } from 'node:os'
import {
  claudeConfigDir, claudeGlobalConfigPath, readLoginPlan, selectManagedPolicy, systemManagedDir,
} from '../managed-policy.ts'
import { decideJoin, readChannelPolicy } from '../join-policy.ts'

export interface ChannelEntry { marketplace: string; plugin: string }

/** Anthropic's default channel plugins; setting allowedChannelPlugins replaces that list, so keep them. */
export const OFFICIAL_CHANNEL_PLUGINS: ChannelEntry[] = ['telegram', 'discord', 'imessage', 'fakechat']
  .map(plugin => ({ marketplace: 'claude-plugins-official', plugin }))

/**
 * Merge the mesh channel into an existing managed settings document without
 * touching any other key. An existing allowedChannelPlugins list is an admin's
 * choice, so only the mesh entry is added to it; without one, the official
 * defaults come along so they keep working.
 */
export function withMeshChannel(existing: Record<string, unknown> | null, entry: ChannelEntry): Record<string, unknown> {
  const out: Record<string, unknown> = { ...(existing ?? {}) }
  const current = Array.isArray(out.allowedChannelPlugins) ? out.allowedChannelPlugins as unknown[] : null
  const list = current ? [...current] : [...OFFICIAL_CHANNEL_PLUGINS]
  const has = list.some(e => typeof e === 'object' && e !== null
    && (e as ChannelEntry).marketplace === entry.marketplace && (e as ChannelEntry).plugin === entry.plugin)
  if (!has) list.push({ marketplace: entry.marketplace, plugin: entry.plugin })
  out.channelsEnabled = true
  out.allowedChannelPlugins = list
  return out
}

export interface InstallPlan {
  target: string
  existing: Record<string, unknown> | null
  next: Record<string, unknown>
  upToDate: boolean
  notes: string[]
}

export function planInstall(dir: string, entry: ChannelEntry): InstallPlan {
  const target = join(dir, 'managed-settings.json')
  let existing: Record<string, unknown> | null = null
  if (existsSync(target)) {
    const raw = readFileSync(target, 'utf8')
    let parsed: unknown
    try { parsed = JSON.parse(raw) } catch {
      throw new Error(`${target} exists but is not valid JSON; fix or remove it first (Claude Code refuses to start with it as well)`)
    }
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) throw new Error(`${target} does not hold a JSON object`)
    existing = parsed as Record<string, unknown>
  }
  const next = withMeshChannel(existing, entry)
  const notes: string[] = []
  if (existing?.channelsEnabled === false) notes.push('channelsEnabled was explicitly false in this file; it becomes true')
  return { target, existing, next, upToDate: existing !== null && JSON.stringify(existing) === JSON.stringify(next), notes }
}

/** Commands an administrator runs to put `staged` in place; never executed by this tool. */
export function elevatedCommands(platform: NodeJS.Platform, staged: string, target: string): string[] {
  const q = (s: string) => `'${s.replace(/'/g, `'\\''`)}'`
  if (platform === 'win32') {
    const ps = (s: string) => `'${s.replace(/'/g, "''")}'`
    return [
      '# in an elevated PowerShell (Run as administrator):',
      `New-Item -ItemType Directory -Force ${ps(win32.dirname(target))} | Out-Null`,
      `Copy-Item ${ps(staged)} ${ps(target)} -Force`,
    ]
  }
  return [
    `sudo mkdir -p ${q(dirname(target))}`,
    `sudo install -m 0644 ${q(staged)} ${q(target)}`,
  ]
}

function canWrite(target: string): boolean {
  try { accessSync(existsSync(target) ? target : dirname(target), constants.W_OK); return true } catch { return false }
}

function argValue(args: string[], flag: string): string | undefined {
  const i = args.indexOf(flag)
  return i >= 0 && i + 1 < args.length ? args[i + 1] : undefined
}

export interface PolicyCliOpts {
  platform?: NodeJS.Platform
  dir?: string
  log?: (line: string) => void
}

export function runPolicyInstall(args: string[], opts: PolicyCliOpts = {}): number {
  const log = opts.log ?? console.log
  const platform = opts.platform ?? process.platform
  const entry = { marketplace: argValue(args, '--marketplace') ?? 'sunkit', plugin: argValue(args, '--plugin') ?? 'mesh' }
  const plan = planInstall(opts.dir ?? systemManagedDir(platform), entry)
  const body = JSON.stringify(plan.next, null, 2) + '\n'
  log(`target: ${plan.target}${plan.existing ? ' (exists; merged, other keys kept)' : ' (new file)'}`)
  for (const n of plan.notes) log(`note: ${n}`)
  if (plan.upToDate) { log('already up to date; nothing to do'); return 0 }
  log(body.trimEnd())
  if (args.includes('--write') && canWrite(plan.target)) {
    writeFileSync(plan.target, body)
    log(`wrote ${plan.target}`)
    return 0
  }
  const staged = join(mkdtempSync(join(tmpdir(), 'mesh-policy-')), 'managed-settings.json')
  writeFileSync(staged, body)
  log(args.includes('--write')
    ? `no write access to ${dirname(plan.target)}; this tool does not elevate. Run:`
    : 'dry run (pass --write to write it when you already have access). To install it, run:')
  for (const c of elevatedCommands(platform, staged, plan.target)) log(`  ${c}`)
  log('The file applies to every account on this machine; see the mesh README before installing it.')
  return 0
}

export function runPolicyStatus(args: string[], opts: PolicyCliOpts = {}): number {
  const log = opts.log ?? console.log
  const marketplace = argValue(args, '--marketplace') ?? 'sunkit'
  const managed = selectManagedPolicy()
  const { policy, source } = readChannelPolicy(() => managed)
  log(`config dir:  ${claudeConfigDir()}`)
  log(`login plan:  ${readLoginPlan(claudeGlobalConfigPath()) ?? 'unknown'}`)
  log(`policy from: ${source}`)
  log(`channel keys: ${JSON.stringify({ channelsEnabled: policy?.channelsEnabled, allowedChannelPlugins: policy?.allowedChannelPlugins })}`)
  const d = decideJoin({ commandLine: `claude --channels plugin:mesh@${marketplace}`, sessionKind: 'interactive', select: () => managed })
  log(`a session launched with --channels plugin:mesh@${marketplace} would ${d.join ? 'join (send + receive)' : 'be send-only'}: ${d.reason}`)
  return 0
}

export function runPolicy(args: string[]): number {
  const [sub, ...rest] = args
  if (sub === 'install') return runPolicyInstall(rest)
  if (sub === 'status') return runPolicyStatus(rest)
  console.error('usage: mesh policy status [--marketplace <name>]\n       mesh policy install [--marketplace <name>] [--plugin <name>] [--write]')
  return 2
}
