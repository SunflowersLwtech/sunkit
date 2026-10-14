import { describe, it, expect, afterEach } from 'vitest'
import { mkdtempSync, mkdirSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import {
  claudeConfigDir, claudeGlobalConfigPath, defaultReaders, hasPolicyKey, mergeSettings, parseRegQuery,
  readFileDocument, readHkcuDocument, readLoginPlan, readMdmDocument, readRemoteDocument, selectManagedPolicy,
  type ManagedDocument, type ManagedSourceReaders,
} from './managed-policy.ts'
import { decideJoin } from './join-policy.ts'

const MESH = { marketplace: 'sunkit', plugin: 'mesh' }
const TEAM = { channelsEnabled: true, allowedChannelPlugins: [{ marketplace: 'claude-plugins-official', plugin: 'telegram' }, MESH] }
const ENDPOINT = { channelsEnabled: true, allowedChannelPlugins: [MESH] }
const opted = 'claude --channels plugin:mesh@sunkit'
const dev = 'claude --dangerously-load-development-channels plugin:mesh@sunkit'

function doc(kind: ManagedDocument['kind'], settings: Record<string, unknown>): ManagedDocument {
  return { kind, label: kind, settings }
}

function readers(r: Partial<{ remote: object; mdm: object; file: object; hkcu: object; plan: string }>): ManagedSourceReaders {
  return {
    remote: () => (r.remote ? doc('remote', r.remote as Record<string, unknown>) : null),
    mdm: () => (r.mdm ? doc('mdm', r.mdm as Record<string, unknown>) : null),
    file: () => (r.file ? doc('file', r.file as Record<string, unknown>) : null),
    hkcu: () => (r.hkcu ? doc('hkcu', r.hkcu as Record<string, unknown>) : null),
    loginPlan: () => r.plan,
  }
}

function join_(r: Parameters<typeof readers>[0], commandLine = opted) {
  return decideJoin({ commandLine, sessionKind: 'interactive', select: () => selectManagedPolicy(readers(r)) })
}

describe('selectManagedPolicy: which source Claude Code applies', () => {
  it('Team login: the cached server-managed settings apply', () => {
    const p = selectManagedPolicy(readers({ remote: TEAM, plan: 'claude_team' }))
    expect(p?.sources.map(s => s.kind)).toEqual(['remote'])
    expect(join_({ remote: TEAM, plan: 'claude_team' }).join).toBe(true)
  })

  it('personal account with only the machine file: the file applies and the session joins', () => {
    const p = selectManagedPolicy(readers({ file: ENDPOINT, plan: 'claude_max' }))
    expect(p?.sources.map(s => s.kind)).toEqual(['file'])
    const d = join_({ file: ENDPOINT, plan: 'claude_max' })
    expect(d.join).toBe(true)
    expect(d.reason).toContain('file:')
  })

  it('both present: server-managed wins and the machine file is ignored', () => {
    const p = selectManagedPolicy(readers({ remote: { channelsEnabled: true, allowedChannelPlugins: [] }, file: ENDPOINT, plan: 'claude_team' }))
    expect(p?.sources.map(s => s.kind)).toEqual(['remote'])
    // The org's list lacks mesh, so the machine file must not let the session in.
    expect(join_({ remote: { channelsEnabled: true, allowedChannelPlugins: [] }, file: ENDPOINT, plan: 'claude_team' }).join).toBe(false)
  })

  it('a personal login ignores a remote cache left by an earlier Team login in the same config dir', () => {
    expect(selectManagedPolicy(readers({ remote: TEAM, file: ENDPOINT, plan: 'claude_pro' }))?.sources.map(s => s.kind)).toEqual(['file'])
    expect(selectManagedPolicy(readers({ remote: TEAM, plan: 'claude_max' }))).toBeNull()
    expect(join_({ remote: TEAM, plan: 'claude_max' }).join).toBe(false)
  })

  it('an unknown or missing plan keeps the remote cache (API keys and OAuth tokens also get server-managed settings)', () => {
    expect(selectManagedPolicy(readers({ remote: TEAM }))?.sources.map(s => s.kind)).toEqual(['remote'])
  })

  it('fails closed when no source carries a policy, for --channels and the dev flag alike', () => {
    expect(selectManagedPolicy(readers({ plan: 'claude_max' }))).toBeNull()
    expect(join_({ plan: 'claude_max' }).join).toBe(false)
    expect(join_({ plan: 'claude_max' }, dev).join).toBe(false)
  })

  it('the dev flag skips the allowlist but still needs channelsEnabled from the selected source', () => {
    expect(join_({ file: { channelsEnabled: true }, plan: 'claude_max' }, dev).join).toBe(true)
    expect(join_({ file: { channelsEnabled: true }, plan: 'claude_max' }, opted).join).toBe(false)
    expect(join_({ file: { allowedChannelPlugins: [MESH] }, plan: 'claude_max' }, dev).join).toBe(false)
  })

  it('a document holding only control keys does not count; the next source applies', () => {
    const p = selectManagedPolicy(readers({ remote: { managedSourcesBehavior: 'first-wins' }, file: ENDPOINT }))
    expect(p?.sources.map(s => s.kind)).toEqual(['file'])
  })

  it('an MDM profile outranks the managed settings file', () => {
    expect(selectManagedPolicy(readers({ mdm: { channelsEnabled: false }, file: ENDPOINT }))?.sources.map(s => s.kind)).toEqual(['mdm'])
  })

  it('HKCU applies only when no admin source carries a policy', () => {
    expect(selectManagedPolicy(readers({ hkcu: ENDPOINT }))?.sources.map(s => s.kind)).toEqual(['hkcu'])
    expect(selectManagedPolicy(readers({ file: { channelsEnabled: false }, hkcu: ENDPOINT }))?.sources.map(s => s.kind)).toEqual(['file'])
  })

  it('managedSourcesBehavior "merge" in the top source combines admin sources: higher values win, lists union', () => {
    const p = selectManagedPolicy(readers({
      remote: { managedSourcesBehavior: 'merge', channelsEnabled: true, allowedChannelPlugins: [{ marketplace: 'claude-plugins-official', plugin: 'discord' }] },
      file: { channelsEnabled: false, allowedChannelPlugins: [MESH] },
    }))
    expect(p?.sources.map(s => s.kind)).toEqual(['remote', 'file'])
    expect(p?.settings.channelsEnabled).toBe(true)
    expect(p?.settings.allowedChannelPlugins).toEqual([MESH, { marketplace: 'claude-plugins-official', plugin: 'discord' }])
  })

  it('"merge" set only in a lower source does not opt it in', () => {
    const p = selectManagedPolicy(readers({ remote: TEAM, file: { managedSourcesBehavior: 'merge', allowedChannelPlugins: [MESH] } }))
    expect(p?.sources.map(s => s.kind)).toEqual(['remote'])
  })
})

describe('CLAUDE_CONFIG_DIR', () => {
  const saved = process.env.CLAUDE_CONFIG_DIR
  afterEach(() => { if (saved === undefined) delete process.env.CLAUDE_CONFIG_DIR; else process.env.CLAUDE_CONFIG_DIR = saved })

  it('the remote cache and the login are read from CLAUDE_CONFIG_DIR, not ~/.claude', () => {
    const dir = mkdtempSync(join(tmpdir(), 'ccd-'))
    writeFileSync(join(dir, 'remote-settings.json'), JSON.stringify(TEAM))
    writeFileSync(join(dir, '.claude.json'), JSON.stringify({ oauthAccount: { organizationType: 'claude_team' } }))
    const env = { CLAUDE_CONFIG_DIR: dir }
    expect(claudeConfigDir(env)).toBe(dir)
    expect(claudeGlobalConfigPath(env)).toBe(join(dir, '.claude.json'))
    const r = defaultReaders(env, 'linux')
    expect(r.remote()?.label).toBe(join(dir, 'remote-settings.json'))
    expect(r.loginPlan()).toBe('claude_team')
  })

  it('an isolated personal login in CLAUDE_CONFIG_DIR does not inherit the Team cache in ~/.claude', () => {
    const dir = mkdtempSync(join(tmpdir(), 'ccd-'))
    writeFileSync(join(dir, '.claude.json'), JSON.stringify({ oauthAccount: { organizationType: 'claude_max' } }))
    const r = defaultReaders({ CLAUDE_CONFIG_DIR: dir }, 'linux')
    expect(r.remote()).toBeNull()
  })

  it('falls back to ~/.claude when unset', () => {
    delete process.env.CLAUDE_CONFIG_DIR
    expect(claudeConfigDir({})).toMatch(/\.claude$/)
  })
})

describe('reading the sources', () => {
  it('managed-settings.json then managed-settings.d/*.json in name order; lists union; hidden and non-json skipped', () => {
    const dir = mkdtempSync(join(tmpdir(), 'msd-'))
    writeFileSync(join(dir, 'managed-settings.json'), JSON.stringify({ channelsEnabled: false, allowedChannelPlugins: [{ marketplace: 'a', plugin: 'x' }], other: 1 }))
    mkdirSync(join(dir, 'managed-settings.d'))
    writeFileSync(join(dir, 'managed-settings.d', '20-mesh.json'), JSON.stringify({ channelsEnabled: true, allowedChannelPlugins: [MESH] }))
    writeFileSync(join(dir, 'managed-settings.d', '10-x.json'), JSON.stringify({ allowedChannelPlugins: [{ marketplace: 'a', plugin: 'x' }] }))
    writeFileSync(join(dir, 'managed-settings.d', '.hidden.json'), JSON.stringify({ channelsEnabled: false }))
    writeFileSync(join(dir, 'managed-settings.d', 'notes.txt'), 'channelsEnabled false')
    const d = readFileDocument(dir)
    expect(d?.settings).toEqual({ channelsEnabled: true, allowedChannelPlugins: [{ marketplace: 'a', plugin: 'x' }, MESH], other: 1 })
  })

  it('drop-ins alone count as a file source; an empty directory yields none', () => {
    const dir = mkdtempSync(join(tmpdir(), 'msd-'))
    expect(readFileDocument(dir)).toBeNull()
    mkdirSync(join(dir, 'managed-settings.d'))
    writeFileSync(join(dir, 'managed-settings.d', 'mesh.json'), JSON.stringify(ENDPOINT))
    expect(readFileDocument(dir)?.settings).toEqual(ENDPOINT)
  })

  it('remote cache: missing or non-object files read as absent', () => {
    const dir = mkdtempSync(join(tmpdir(), 'rs-'))
    expect(readRemoteDocument(dir)).toBeNull()
    writeFileSync(join(dir, 'remote-settings.json'), '[1,2]')
    expect(readRemoteDocument(dir)).toBeNull()
    writeFileSync(join(dir, 'remote-settings.json'), JSON.stringify(TEAM))
    expect(readRemoteDocument(dir)?.settings).toEqual(TEAM)
  })

  it('reads the login plan from oauthAccount.organizationType', () => {
    const dir = mkdtempSync(join(tmpdir(), 'cj-'))
    const p = join(dir, '.claude.json')
    expect(readLoginPlan(p)).toBeUndefined()
    writeFileSync(p, JSON.stringify({ oauthAccount: { organizationType: 'claude_max' } }))
    expect(readLoginPlan(p)).toBe('claude_max')
  })

  it('Windows: HKLM Settings value via reg.exe; HKCU only through its own reader', () => {
    const out = '\r\nHKEY_LOCAL_MACHINE\\SOFTWARE\\Policies\\ClaudeCode\r\n    Settings    REG_SZ    {"channelsEnabled":true}\r\n'
    const calls: string[][] = []
    const d = readMdmDocument('win32', (file, args) => { calls.push([file, ...args]); return out })
    expect(d?.settings).toEqual({ channelsEnabled: true })
    expect(calls[0]).toEqual(['reg.exe', 'query', 'HKLM\\SOFTWARE\\Policies\\ClaudeCode', '/v', 'Settings'])
    expect(readMdmDocument('win32', () => { throw new Error('not found') })).toBeNull()
  })

  it('parseRegQuery accepts REG_SZ / REG_EXPAND_SZ JSON objects only', () => {
    expect(parseRegQuery('    Settings    REG_EXPAND_SZ    {"a":1}')).toEqual({ a: 1 })
    expect(parseRegQuery('    Settings    REG_SZ    [1]')).toBeNull()
    expect(parseRegQuery('    Settings    REG_SZ    not json')).toBeNull()
    expect(parseRegQuery('    Other    REG_SZ    {"a":1}')).toBeNull()
  })

  it('macOS: the first readable managed-preferences plist, converted with plutil', () => {
    const dir = mkdtempSync(join(tmpdir(), 'mdm-'))
    const user = join(dir, 'user.plist'), device = join(dir, 'device.plist')
    writeFileSync(device, 'plist')
    const calls: string[][] = []
    const run = (file: string, args: string[]) => { calls.push([file, ...args]); return '{"channelsEnabled":true}' }
    expect(readMdmDocument('darwin', run, [user, device])).toEqual({ kind: 'mdm', label: device, settings: { channelsEnabled: true } })
    expect(calls).toEqual([['/usr/bin/plutil', '-convert', 'json', '-o', '-', '--', device]])
    writeFileSync(user, 'plist')
    expect(readMdmDocument('darwin', run, [user, device])?.label).toBe(user)
    expect(readMdmDocument('darwin', () => { throw new Error('malformed') }, [user, device])).toBeNull()
    expect(readMdmDocument('darwin', run, [join(dir, 'none.plist')])).toBeNull()
  })

  it('Windows HKCU is read from its own key, and only on Windows', () => {
    const calls: string[][] = []
    const d = readHkcuDocument('win32', (file, args) => { calls.push([file, ...args]); return '    Settings    REG_SZ    {"channelsEnabled":true}' })
    expect(d).toEqual({ kind: 'hkcu', label: 'HKCU\\SOFTWARE\\Policies\\ClaudeCode', settings: { channelsEnabled: true } })
    expect(calls[0]).toEqual(['reg.exe', 'query', 'HKCU\\SOFTWARE\\Policies\\ClaudeCode', '/v', 'Settings'])
    expect(readHkcuDocument('darwin', () => { throw new Error('must not run') })).toBeNull()
  })

  it('Linux has no MDM source', () => {
    expect(readMdmDocument('linux', () => { throw new Error('must not run') })).toBeNull()
  })

  it('hasPolicyKey ignores control keys and null values', () => {
    expect(hasPolicyKey({ managedSourcesBehavior: 'merge', wslInheritsWindowsSettings: true })).toBe(false)
    expect(hasPolicyKey({ channelsEnabled: null })).toBe(false)
    expect(hasPolicyKey({ channelsEnabled: false })).toBe(true)
  })

  it('mergeSettings deep-merges objects and de-duplicates list entries', () => {
    expect(mergeSettings({ a: { b: 1, c: [1] } }, { a: { c: [1, 2] }, d: 3 })).toEqual({ a: { b: 1, c: [1, 2] }, d: 3 })
  })
})
