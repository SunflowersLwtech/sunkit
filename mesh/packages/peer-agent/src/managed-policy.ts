import { execFileSync } from 'node:child_process'
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { homedir, userInfo } from 'node:os'

/**
 * Which managed settings Claude Code enforces, mirrored closely enough to
 * predict whether it will register a channel. Claude Code ranks four managed
 * sources and, by default, applies the first one that carries at least one
 * policy key (https://code.claude.com/docs/en/managed-settings):
 *
 *   1. remote   server-managed settings, cached at <config dir>/remote-settings.json
 *   2. mdm      macOS managed preferences (com.anthropic.claudecode) or HKLM\SOFTWARE\Policies\ClaudeCode
 *   3. file     <system dir>/managed-settings.json + managed-settings.d/*.json
 *   4. hkcu     HKCU\SOFTWARE\Policies\ClaudeCode, only when no admin source is present
 *
 * Server-managed settings are delivered only to organization credentials, so a
 * personal Pro/Max login skips the remote cache: one left behind by an earlier
 * Team login in the same config dir does not apply to it.
 */

export type ManagedSourceKind = 'remote' | 'mdm' | 'file' | 'hkcu'

export interface ManagedDocument {
  kind: ManagedSourceKind
  /** Where it came from (path or registry key), for logs and `mesh policy status`. */
  label: string
  settings: Record<string, unknown>
}

export interface ManagedPolicy {
  /** The source Claude Code applies, or several under managedSourcesBehavior "merge". */
  sources: ManagedDocument[]
  settings: Record<string, unknown>
}

/** The two keys that steer source selection and don't count as policy. */
const CONTROL_KEYS = new Set(['wslInheritsWindowsSettings', 'managedSourcesBehavior'])

const PERSONAL_PLANS = new Set(['claude_pro', 'claude_max'])

export function claudeConfigDir(env: NodeJS.ProcessEnv = process.env): string {
  return env.CLAUDE_CONFIG_DIR || join(homedir(), '.claude')
}

/** Claude Code's global config (.claude.json): inside CLAUDE_CONFIG_DIR when set, else in the home dir. */
export function claudeGlobalConfigPath(env: NodeJS.ProcessEnv = process.env): string {
  return env.CLAUDE_CONFIG_DIR ? join(env.CLAUDE_CONFIG_DIR, '.claude.json') : join(homedir(), '.claude.json')
}

export function systemManagedDir(platform: NodeJS.Platform = process.platform): string {
  if (platform === 'darwin') return '/Library/Application Support/ClaudeCode'
  if (platform === 'win32') return 'C:\\Program Files\\ClaudeCode'
  return '/etc/claude-code'
}

export function hasPolicyKey(doc: Record<string, unknown> | null | undefined): boolean {
  if (!doc) return false
  return Object.entries(doc).some(([k, v]) => !CONTROL_KEYS.has(k) && v !== null && v !== undefined)
}

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

/** Later document wins on scalars; objects merge; lists union without duplicates (Claude Code's merge). */
export function mergeSettings(base: Record<string, unknown>, over: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = { ...base }
  for (const [k, v] of Object.entries(over)) {
    const prev = out[k]
    if (Array.isArray(prev) && Array.isArray(v)) {
      const seen = new Set<string>()
      out[k] = [...prev, ...v].filter(x => { const key = JSON.stringify(x); return seen.has(key) ? false : (seen.add(key), true) })
    } else if (isObject(prev) && isObject(v)) {
      out[k] = mergeSettings(prev, v)
    } else {
      out[k] = v
    }
  }
  return out
}

function readJsonObject(path: string): Record<string, unknown> | null {
  try {
    const v = JSON.parse(readFileSync(path, 'utf8')) as unknown
    return isObject(v) ? v : null
  } catch {
    return null
  }
}

/** The plan of the account Claude Code is signed in with (oauthAccount.organizationType), if any. */
export function readLoginPlan(path = claudeGlobalConfigPath()): string | undefined {
  const j = readJsonObject(path)
  const oa = j?.oauthAccount
  return isObject(oa) && typeof oa.organizationType === 'string' ? oa.organizationType : undefined
}

export function readRemoteDocument(configDir = claudeConfigDir()): ManagedDocument | null {
  const label = join(configDir, 'remote-settings.json')
  const settings = readJsonObject(label)
  return settings ? { kind: 'remote', label, settings } : null
}

/** managed-settings.json first, then managed-settings.d/*.json in name order; hidden and non-.json files skipped. */
export function readFileDocument(dir = systemManagedDir()): ManagedDocument | null {
  let merged: Record<string, unknown> | null = readJsonObject(join(dir, 'managed-settings.json'))
  const dropDir = join(dir, 'managed-settings.d')
  let names: string[] = []
  try { names = readdirSync(dropDir).filter(n => n.endsWith('.json') && !n.startsWith('.')).sort() } catch { /* no drop-ins */ }
  for (const n of names) {
    const p = join(dropDir, n)
    try { if (!statSync(p).isFile()) continue } catch { continue }
    const doc = readJsonObject(p)
    if (doc) merged = merged ? mergeSettings(merged, doc) : doc
  }
  return merged ? { kind: 'file', label: dir, settings: merged } : null
}

export type CommandRunner = (file: string, args: string[]) => string

const runCommand: CommandRunner = (file, args) =>
  execFileSync(file, args, { encoding: 'utf8', timeout: 5_000, windowsHide: true, stdio: ['ignore', 'pipe', 'ignore'] })

/** `reg query` output → the JSON in its Settings value. */
export function parseRegQuery(out: string): Record<string, unknown> | null {
  const m = /^\s*Settings\s+REG_(?:EXPAND_)?SZ\s+(.*)$/m.exec(out)
  if (!m) return null
  try {
    const v = JSON.parse(m[1]!.trim()) as unknown
    return isObject(v) ? v : null
  } catch {
    return null
  }
}

function readRegistry(hive: 'HKLM' | 'HKCU', run: CommandRunner): Record<string, unknown> | null {
  try { return parseRegQuery(run('reg.exe', ['query', `${hive}\\SOFTWARE\\Policies\\ClaudeCode`, '/v', 'Settings'])) } catch { return null }
}

/** Per-user managed preferences first, then device-level, as Claude Code checks them. */
export function managedPlistPaths(): string[] {
  let user = ''
  try { user = userInfo().username } catch { /* unknown user */ }
  return [
    ...(user ? [`/Library/Managed Preferences/${user}/com.anthropic.claudecode.plist`] : []),
    '/Library/Managed Preferences/com.anthropic.claudecode.plist',
  ]
}

export function readMdmDocument(
  platform: NodeJS.Platform = process.platform, run: CommandRunner = runCommand, plists: string[] = managedPlistPaths(),
): ManagedDocument | null {
  if (platform === 'darwin') {
    for (const p of plists) {
      if (!existsSync(p)) continue
      try {
        const v = JSON.parse(run('/usr/bin/plutil', ['-convert', 'json', '-o', '-', '--', p])) as unknown
        if (isObject(v)) return { kind: 'mdm', label: p, settings: v }
      } catch { /* unreadable profile: treated as absent */ }
    }
    return null
  }
  if (platform === 'win32') {
    const settings = readRegistry('HKLM', run)
    return settings ? { kind: 'mdm', label: 'HKLM\\SOFTWARE\\Policies\\ClaudeCode', settings } : null
  }
  return null
}

export function readHkcuDocument(platform: NodeJS.Platform = process.platform, run: CommandRunner = runCommand): ManagedDocument | null {
  if (platform !== 'win32') return null
  const settings = readRegistry('HKCU', run)
  return settings ? { kind: 'hkcu', label: 'HKCU\\SOFTWARE\\Policies\\ClaudeCode', settings } : null
}

export interface ManagedSourceReaders {
  remote: () => ManagedDocument | null
  mdm: () => ManagedDocument | null
  file: () => ManagedDocument | null
  hkcu: () => ManagedDocument | null
  loginPlan: () => string | undefined
}

export function defaultReaders(env: NodeJS.ProcessEnv = process.env, platform: NodeJS.Platform = process.platform): ManagedSourceReaders {
  return {
    remote: () => readRemoteDocument(claudeConfigDir(env)),
    mdm: () => readMdmDocument(platform),
    file: () => readFileDocument(systemManagedDir(platform)),
    hkcu: () => readHkcuDocument(platform),
    loginPlan: () => readLoginPlan(claudeGlobalConfigPath(env)),
  }
}

/** The managed settings Claude Code would apply, or null when no source carries a policy key. */
export function selectManagedPolicy(readers: ManagedSourceReaders = defaultReaders()): ManagedPolicy | null {
  const plan = readers.loginPlan()
  const admin = [
    ...(plan !== undefined && PERSONAL_PLANS.has(plan) ? [] : [readers.remote()]),
    readers.mdm(),
    readers.file(),
  ].filter((d): d is ManagedDocument => d !== null)

  const withPolicy = admin.filter(d => hasPolicyKey(d.settings))
  // managedSourcesBehavior is read from the highest source carrying it or a policy key.
  const steering = admin.find(d => hasPolicyKey(d.settings) || d.settings.managedSourcesBehavior !== undefined)
  if (steering?.settings.managedSourcesBehavior === 'merge' && withPolicy.length > 1) {
    // Higher-ranked values win, lists union: fold from the lowest source up.
    const settings = [...withPolicy].reverse().reduce<Record<string, unknown>>((acc, d) => mergeSettings(acc, d.settings), {})
    return { sources: withPolicy, settings }
  }
  const first = withPolicy[0]
  if (first) return { sources: [first], settings: first.settings }

  // The user-writable HKCU value applies only when no admin source carries a policy key.
  const hkcu = readers.hkcu()
  if (hkcu && hasPolicyKey(hkcu.settings)) return { sources: [hkcu], settings: hkcu.settings }
  return null
}
