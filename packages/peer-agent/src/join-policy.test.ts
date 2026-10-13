import { describe, it, expect } from 'vitest'
import { channelOptIn, decideJoin, parentCommandLine } from './join-policy.ts'

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

describe('decideJoin', () => {
  const opted = 'claude --channels plugin:mesh@claude-mesh'
  it('joins an interactive session launched with the channel', () => {
    expect(decideJoin({ commandLine: opted, sessionKind: 'interactive' }).join).toBe(true)
  })
  it('never joins non-interactive sessions, even with the flag', () => {
    expect(decideJoin({ commandLine: opted, sessionKind: 'print' }).join).toBe(false)
  })
  it('does not join without the channel flag', () => {
    expect(decideJoin({ commandLine: 'claude', sessionKind: 'interactive' }).join).toBe(false)
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
