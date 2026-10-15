import { describe, it, expect } from 'vitest'
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { OFFICIAL_CHANNEL_PLUGINS, elevatedCommands, planInstall, runPolicyInstall, withMeshChannel } from './policy.ts'

const MESH = { marketplace: 'sunkit', plugin: 'mesh' }

describe('withMeshChannel', () => {
  it('a new file gets channelsEnabled, the official defaults and the mesh entry', () => {
    expect(withMeshChannel(null, MESH)).toEqual({ channelsEnabled: true, allowedChannelPlugins: [...OFFICIAL_CHANNEL_PLUGINS, MESH] })
  })

  it('keeps every other key and an admin-chosen list, adding only the mesh entry', () => {
    const existing = { permissions: { deny: ['Read(./.env)'] }, allowedChannelPlugins: [{ marketplace: 'corp', plugin: 'pager' }] }
    expect(withMeshChannel(existing, MESH)).toEqual({
      permissions: { deny: ['Read(./.env)'] },
      channelsEnabled: true,
      allowedChannelPlugins: [{ marketplace: 'corp', plugin: 'pager' }, MESH],
    })
  })

  it('is idempotent', () => {
    const once = withMeshChannel(null, MESH)
    expect(withMeshChannel(once, MESH)).toEqual(once)
  })
})

describe('planInstall / runPolicyInstall', () => {
  it('refuses to touch a file that is not valid JSON', () => {
    const dir = mkdtempSync(join(tmpdir(), 'pol-'))
    writeFileSync(join(dir, 'managed-settings.json'), '{ nope')
    expect(() => planInstall(dir, MESH)).toThrow(/not valid JSON/)
  })

  it('reports an up-to-date file and flags an explicit channelsEnabled: false', () => {
    const dir = mkdtempSync(join(tmpdir(), 'pol-'))
    writeFileSync(join(dir, 'managed-settings.json'), JSON.stringify(withMeshChannel(null, MESH)))
    expect(planInstall(dir, MESH).upToDate).toBe(true)
    writeFileSync(join(dir, 'managed-settings.json'), JSON.stringify({ channelsEnabled: false }))
    expect(planInstall(dir, MESH).notes.join()).toContain('explicitly false')
  })

  it('--write merges into a writable target and keeps other keys', () => {
    const dir = mkdtempSync(join(tmpdir(), 'pol-'))
    writeFileSync(join(dir, 'managed-settings.json'), JSON.stringify({ model: 'opus' }))
    const lines: string[] = []
    expect(runPolicyInstall(['--write'], { dir, platform: 'linux', log: l => lines.push(l) })).toBe(0)
    expect(JSON.parse(readFileSync(join(dir, 'managed-settings.json'), 'utf8'))).toEqual({ model: 'opus', ...withMeshChannel(null, MESH) })
  })

  it('without --write it only stages a copy and prints the commands; the target is untouched', () => {
    const dir = mkdtempSync(join(tmpdir(), 'pol-'))
    const lines: string[] = []
    runPolicyInstall([], { dir, platform: 'darwin', log: l => lines.push(l) })
    expect(existsSync(join(dir, 'managed-settings.json'))).toBe(false)
    const install = lines.find(l => l.includes('sudo install -m 0644'))
    expect(install).toBeDefined()
    const staged = /'([^']+managed-settings\.json)'/.exec(install!)![1]!
    expect(JSON.parse(readFileSync(staged, 'utf8'))).toEqual(withMeshChannel(null, MESH))
  })

  it('--marketplace / --plugin name the entry to add', () => {
    const dir = mkdtempSync(join(tmpdir(), 'pol-'))
    runPolicyInstall(['--write', '--marketplace', 'my-mkt', '--plugin', 'mesh'], { dir, platform: 'linux', log: () => {} })
    const out = JSON.parse(readFileSync(join(dir, 'managed-settings.json'), 'utf8'))
    expect(out.allowedChannelPlugins).toContainEqual({ marketplace: 'my-mkt', plugin: 'mesh' })
  })
})

describe('elevatedCommands', () => {
  it('quotes paths with spaces for sh and PowerShell, and never runs anything itself', () => {
    expect(elevatedCommands('darwin', '/tmp/x/managed-settings.json', '/Library/Application Support/ClaudeCode/managed-settings.json')).toEqual([
      "sudo mkdir -p '/Library/Application Support/ClaudeCode'",
      "sudo install -m 0644 '/tmp/x/managed-settings.json' '/Library/Application Support/ClaudeCode/managed-settings.json'",
    ])
    const win = elevatedCommands('win32', 'C:\\Temp\\m\\managed-settings.json', 'C:\\Program Files\\ClaudeCode\\managed-settings.json')
    expect(win[1]).toBe("New-Item -ItemType Directory -Force 'C:\\Program Files\\ClaudeCode' | Out-Null")
    expect(win[2]).toBe("Copy-Item 'C:\\Temp\\m\\managed-settings.json' 'C:\\Program Files\\ClaudeCode\\managed-settings.json' -Force")
  })
})
