import { describe, it, expect } from 'vitest'
import { mkdtempSync, mkdirSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { channelOptIn, decideJoin, parentCommandLine, readProcCmdline } from './join-policy.ts'

describe('channelOptIn', () => {
  it.each([
    ['claude --channels plugin:mesh@claude-mesh', true],
    ['claude --channels plugin:telegram@claude-plugins-official plugin:mesh@claude-mesh', true],
    ['claude --dangerously-load-development-channels server:mesh', true],
    ['claude --channels=plugin:mesh@claude-mesh --resume', true],
    ['C:\\Users\\x\\.local\\bin\\claude.exe --channels plugin:mesh@claude-mesh', true],
    ['claude', false],
    ['claude -p hello', false],
    ['claude --channels plugin:telegram@claude-plugins-official', false],
    ['claude --channels plugin:meshy@other', false],
    ['claude --dangerously-load-development-channels server:mesh2', false],
    ['claude --mcp-config mesh.json "--channels plugin:mesh@x is in a prompt"', false],
  ])('%s → %s', (cmd, want) => {
    expect(channelOptIn(cmd)).toBe(want)
  })
})

const ALLOW = { channelsEnabled: true, allowedChannelPlugins: [{ marketplace: 'claude-mesh', plugin: 'mesh' }] }

describe('decideJoin', () => {
  const opted = 'claude --channels plugin:mesh@claude-mesh'
  it('joins an interactive session launched with the channel', () => {
    expect(decideJoin({ commandLine: opted, sessionKind: 'interactive', policy: ALLOW }).join).toBe(true)
  })
  it('never joins non-interactive sessions, even with the flag', () => {
    expect(decideJoin({ commandLine: opted, sessionKind: 'print', policy: ALLOW }).join).toBe(false)
  })
  it('does not join without the channel flag', () => {
    expect(decideJoin({ commandLine: 'claude', sessionKind: 'interactive', policy: ALLOW }).join).toBe(false)
  })
  it('MESH_JOIN overrides', () => {
    expect(decideJoin({ env: 'always', commandLine: 'claude' }).join).toBe(true)
    expect(decideJoin({ env: 'never', commandLine: opted }).join).toBe(false)
  })
})

describe('parentCommandLine', () => {
  it('reads a real process command line (our own parent is the test runner)', () => {
    expect(parentCommandLine(process.pid)).toMatch(/node|vitest/)
  })
  it('returns empty string for a pid that does not exist', () => {
    expect(parentCommandLine(2 ** 22 - 3)).toBe('')
  })
})

describe('org policy mirror', () => {
  const opted = 'claude --channels plugin:mesh@claude-mesh'
  const dev = 'claude --dangerously-load-development-channels plugin:mesh@claude-mesh'
  it('does not join when the cached allowlist lacks the plugin (stale cache after an allowlist change)', () => {
    const stale = { channelsEnabled: true }
    expect(decideJoin({ commandLine: opted, sessionKind: 'interactive', policy: stale }).join).toBe(false)
  })
  it('does not join when the allowlisted marketplace differs from the one launched', () => {
    expect(decideJoin({ commandLine: 'claude --channels plugin:mesh@evil', sessionKind: 'interactive', policy: ALLOW }).join).toBe(false)
  })
  it('does not join when channels are off for the org or no policy is cached', () => {
    expect(decideJoin({ commandLine: dev, sessionKind: 'interactive', policy: { channelsEnabled: false } }).join).toBe(false)
    expect(decideJoin({ commandLine: dev, sessionKind: 'interactive', policy: null }).join).toBe(false)
  })
  it('the dev flag bypasses the allowlist but not channelsEnabled', () => {
    expect(decideJoin({ commandLine: dev, sessionKind: 'interactive', policy: { channelsEnabled: true } }).join).toBe(true)
  })
  it('server:mesh only counts under the dev flag (--channels takes plugins only)', () => {
    expect(decideJoin({ commandLine: 'claude --channels server:mesh', sessionKind: 'interactive', policy: ALLOW }).join).toBe(false)
  })
})

describe('readProcCmdline', () => {
  it('joins NUL-separated argv from <procRoot>/<pid>/cmdline', () => {
    const root = mkdtempSync(join(tmpdir(), 'proc-'))
    mkdirSync(join(root, '363'))
    writeFileSync(join(root, '363', 'cmdline'), 'claude\0--channels\0plugin:mesh@claude-mesh\0')
    const line = readProcCmdline(363, root)
    expect(line).toBe('claude --channels plugin:mesh@claude-mesh')
    expect(channelOptIn(line)).toBe(true)
  })
  it('returns empty for a missing pid so the caller can fall back', () => {
    const root = mkdtempSync(join(tmpdir(), 'proc-'))
    expect(readProcCmdline(999, root)).toBe('')
  })
})
