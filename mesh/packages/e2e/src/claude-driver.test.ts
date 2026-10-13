import { describe, it, expect } from 'vitest'
import { tmpdir } from 'node:os'
import { drive, canDrive } from './claude-driver.ts'

describe('claude-driver', () => {
  it('rejects when the claude binary cannot be spawned', async () => {
    // Empty PATH makes `claude` unresolvable, the same ENOENT a CI runner without
    // Claude Code installed produces.
    await expect(drive({
      cwd: tmpdir(),
      prompt: 'noop',
      env: { PATH: '', PATHEXT: '' },
      timeoutMs: 5_000,
    })).rejects.toThrow(/ENOENT/)
  }, 20_000)

  it('canDrive() is false unless CLAUDE_DRIVER names a driver', () => {
    const prev = process.env.CLAUDE_DRIVER
    try {
      delete process.env.CLAUDE_DRIVER
      expect(canDrive()).toBe(false)
      process.env.CLAUDE_DRIVER = ''
      expect(canDrive()).toBe(false)
      process.env.CLAUDE_DRIVER = 'cli'
      expect(canDrive()).toBe(true)
    } finally {
      if (prev === undefined) delete process.env.CLAUDE_DRIVER
      else process.env.CLAUDE_DRIVER = prev
    }
  })
})
