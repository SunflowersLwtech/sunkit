import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { mkdtempSync, writeFileSync, mkdirSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { loadConfig, loadToken, isInsideGitRepoWithRemote } from './config.ts'

let workdir = ''
beforeEach(() => { workdir = mkdtempSync(join(tmpdir(), 'mesh-')) })
afterEach(() => { rmSync(workdir, { recursive: true, force: true }) })

describe('loadConfig', () => {
  it('loads a valid config file', () => {
    const p = join(workdir, 'config.json')
    writeFileSync(p, JSON.stringify({
      relay_url: 'https://mesh.example.com', token_path: join(workdir, 'tok'),
      permission_relay: { enabled: false, routing: 'never_relay' },
      presence: { auto_publish_cwd: true, auto_publish_branch: true, auto_publish_repo: true },
      audit_log: join(workdir, 'audit')
    }))
    const cfg = loadConfig(p)
    expect(cfg.relay_url).toBe('https://mesh.example.com')
  })

  it('rejects config missing required field', () => {
    const p = join(workdir, 'bad.json')
    writeFileSync(p, JSON.stringify({ relay_url: 'x' }))
    expect(() => loadConfig(p)).toThrow()
  })

  it('surfaces self_handle written by mesh pair', () => {
    const p = join(workdir, 'config.json')
    writeFileSync(p, JSON.stringify({
      relay_url: 'https://mesh.example.com', token_path: join(workdir, 'tok'),
      self_handle: 'alice'
    }))
    expect(loadConfig(p).self_handle).toBe('alice')
  })
})

describe('loadToken', () => {
  it('reads a token file', () => {
    const p = join(workdir, 'token')
    writeFileSync(p, 'some-token', { mode: 0o600 })
    expect(loadToken(p)).toBe('some-token')
  })
  it('trims whitespace / trailing newline', () => {
    const p = join(workdir, 'token')
    writeFileSync(p, 'tok\n', { mode: 0o600 })
    expect(loadToken(p)).toBe('tok')
  })
  it('throws if token file missing', () => {
    expect(() => loadToken(join(workdir, 'nope'))).toThrow(/token file not found/)
  })
})

describe('isInsideGitRepoWithRemote', () => {
  it('returns false for a non-git directory', () => {
    expect(isInsideGitRepoWithRemote(workdir)).toBe(false)
  })
  it('returns false for a git repo with no remotes', () => {
    mkdirSync(join(workdir, '.git'), { recursive: true })
    writeFileSync(join(workdir, '.git/config'), '[core]\nrepositoryformatversion = 0\n')
    expect(isInsideGitRepoWithRemote(workdir)).toBe(false)
  })
  it('returns true for a git repo with a remote', () => {
    mkdirSync(join(workdir, '.git'), { recursive: true })
    writeFileSync(join(workdir, '.git/config'),
      '[core]\nrepositoryformatversion = 0\n\n[remote "origin"]\n  url = git@github.com:x/y.git\n')
    expect(isInsideGitRepoWithRemote(workdir)).toBe(true)
  })
})
