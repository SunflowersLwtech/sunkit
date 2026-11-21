import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { mkdtempSync, writeFileSync, mkdirSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { loadConfig, loadToken, loadPeerCredentials, isInsideGitRepoWithRemote } from './config.ts'
import { InboundDispatcher } from './inbound.ts'
import { SenderGate } from './gate.ts'
import { parseAllow } from './sender-allow.ts'
import type { Envelope } from '@claude-mesh/shared'

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

describe('loadPeerCredentials', () => {
  const env = { MESH_RELAY: 'https://env.example.com', MESH_TOKEN: 'env-secret' }
  const path = () => join(workdir, 'missing-home', 'config.json')

  it('uses environment credentials without creating a home or checking a token file', () => {
    mkdirSync(join(workdir, '.git'))
    writeFileSync(join(workdir, '.git/config'), '[remote "origin"]\nurl = https://example.com/repo\n')
    const credentials = loadPeerCredentials(path(), env)!
    expect(credentials.token).toBe(env.MESH_TOKEN)
    expect(credentials.cfg.relay_url).toBe(env.MESH_RELAY)
    expect(credentials.cfg.permission_relay.enabled).toBe(false)
    expect(credentials.cfg.presence.auto_publish_cwd).toBe(true)
    expect(() => loadConfig(path())).toThrow(/config file not found/)
  })

  it.each([{}, { MESH_RELAY: env.MESH_RELAY }, { MESH_TOKEN: env.MESH_TOKEN },
    { ...env, MESH_TOKEN: '' }, { ...env, MESH_RELAY: '' }])('stays unpaired for incomplete credentials %j', partial => {
    expect(loadPeerCredentials(path(), partial)).toBeUndefined()
  })

  it('rejects an invalid environment relay without exposing the token', () => {
    expect(() => loadPeerCredentials(path(), { ...env, MESH_RELAY: 'invalid' })).toThrow()
    try { loadPeerCredentials(path(), { ...env, MESH_RELAY: 'invalid' }) }
    catch (err) { expect(String(err)).not.toContain(env.MESH_TOKEN) }
  })

  it('trims environment tokens like token files', () => {
    expect(loadPeerCredentials(path(), { ...env, MESH_TOKEN: ' \n env-secret \r\n' })!.token).toBe('env-secret')
  })

  it.each(['secret\nsecond-line', 'secret\tvalue', 'secret\u0000value', 'secret\u007fvalue', 'secret\u2028value', ' \r\n '])(
    'rejects malformed environment tokens without including their value (case %#)', token => {
      expect(() => loadPeerCredentials(path(), { ...env, MESH_TOKEN: token })).toThrow(/MESH_TOKEN/)
      try { loadPeerCredentials(path(), { ...env, MESH_TOKEN: token }) }
      catch (err) { expect(String(err)).not.toContain(token) }
    },
  )

  it('requires an own account for env-only pinned mail before joining', () => {
    expect(() => loadPeerCredentials(path(), { ...env, MESH_ALLOW: 'assistant@tk_1' }))
      .toThrow(/MESH_SELF_HANDLE/)
    expect(() => loadPeerCredentials(path(), { ...env, MESH_ALLOW: 'assistant@tk_1', MESH_SELF_HANDLE: '  ' }))
      .toThrow(/MESH_SELF_HANDLE/)
  })

  it('delivers only correctly pinned env-only mail on the configured account', () => {
    const credentials = loadPeerCredentials(path(), { ...env, MESH_ALLOW: 'assistant@tk_1', MESH_SELF_HANDLE: ' alice ' })!
    expect(credentials.cfg.self_handle).toBe('alice')
    const received: unknown[] = []
    const dispatcher = new InboundDispatcher({
      gate: new SenderGate(['alice', 'mallory']),
      allow: { names: parseAllow('assistant@tk_1')!, ownAccount: credentials.cfg.self_handle },
      emit: notification => { received.push(notification) },
      setCursor: () => {},
    })
    const message: Envelope = {
      id: 'msg_01HRK7Y0000000000000000000', v: 1, team: 't1', from: 'alice', to: 'alice',
      in_reply_to: null, thread_root: null, kind: 'chat', content: 'pinned', meta: {},
      sent_at: '2026-04-17T00:00:00.000Z', delivered_at: null,
      from_session: 's_01abcdef', from_name: 'assistant', to_session: null, from_token: 'tk_1',
    }
    dispatcher.handle(message)
    dispatcher.handle({ ...message, from_token: 'tk_other' })
    dispatcher.handle({ ...message, from: 'mallory' })
    dispatcher.handle({ ...message, from_name: 'other' })
    expect(received).toHaveLength(1)
  })

  it('prefers file config and token over environment credentials', () => {
    const tokenPath = join(workdir, 'token')
    writeFileSync(tokenPath, 'file-secret', { mode: 0o600 })
    const configPath = join(workdir, 'config.json')
    writeFileSync(configPath, JSON.stringify({ relay_url: 'https://file.example.com', token_path: tokenPath }))
    const credentials = loadPeerCredentials(configPath, env)!
    expect(credentials.cfg.relay_url).toBe('https://file.example.com')
    expect(credentials.token).toBe('file-secret')
  })

  it('does not fall back when an existing config is invalid or its token is missing', () => {
    const configPath = join(workdir, 'config.json')
    writeFileSync(configPath, '{')
    expect(() => loadPeerCredentials(configPath, env)).toThrow()
    writeFileSync(configPath, JSON.stringify({ relay_url: env.MESH_RELAY, token_path: join(workdir, 'missing') }))
    expect(() => loadPeerCredentials(configPath, env)).toThrow(/token file not found/)
  })

  it('still rejects file tokens in a git worktree with a remote', () => {
    mkdirSync(join(workdir, '.git'))
    writeFileSync(join(workdir, '.git/config'), '[remote "origin"]\nurl = https://example.com/repo\n')
    const configPath = join(workdir, 'config.json')
    writeFileSync(configPath, JSON.stringify({ relay_url: env.MESH_RELAY, token_path: join(workdir, 'token') }))
    expect(() => loadPeerCredentials(configPath, env)).toThrow(/git worktree/)
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
