import { describe, it, expect } from 'vitest'
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { runClaudeHook, CLAUDE_HOOK_EVENTS } from './claude.ts'
import type { HookReply, HookRequest } from '../hook-socket.ts'

function rig(reply: Partial<HookReply> | undefined = { unread: 0, from: [] }) {
  const asked: Array<{ req: HookRequest; key: string | undefined; waitMs: number | undefined }> = []
  const forgotten: Array<string | undefined> = []
  const deps = {
    stdin: async () => JSON.stringify({ session_id: 'cc-session-1', hook_event_name: 'X', model: 'claude-opus-5-5' }),
    ask: async (req: HookRequest, opts: { cacheKey?: string | undefined; waitMs?: number }) => {
      asked.push({ req, key: opts.cacheKey, waitMs: opts.waitMs })
      return reply ? { unread: 0, from: [], ...reply } : undefined
    },
    forget: (k: string | undefined) => { forgotten.push(k) },
    env: {} as NodeJS.ProcessEnv,
  }
  return { asked, forgotten, deps }
}

describe('mesh claude hook', () => {
  it('maps Claude Code\'s events onto the peer\'s hook ops', async () => {
    const r = rig()
    for (const [ev, op] of [['turn', 'turn'], ['blocked', 'blocked'], ['stop', 'stop'], ['end', 'end']] as const) {
      expect(await runClaudeHook([ev], r.deps)).toBe(0)
      expect(r.asked.at(-1)!.req.op).toBe(op)
      expect(r.asked.at(-1)!.key).toBe('cc-session-1')
    }
    expect(r.asked.find(a => a.req.op === 'stop')!.req).toEqual({ op: 'stop', natural: true })
    expect(r.forgotten).toEqual(['cc-session-1'])
  })

  it('at session start passes the model on and puts MESH_SESSION_ID in Claude Code\'s env file', async () => {
    const r = rig({ session: 's_01hrk7y0000000000000aaaaa1', name: 'x' })
    const dir = mkdtempSync(join(tmpdir(), 'cc-env-'))
    const envFile = join(dir, 'env'); writeFileSync(envFile, 'export A=1\n')
    r.deps.env = { CLAUDE_ENV_FILE: envFile }
    expect(await runClaudeHook(['session-start'], r.deps)).toBe(0)
    expect(r.asked.map(a => a.req)).toEqual([{ op: 'card', card: { model: 'claude-opus-5-5' } }, { op: 'whoami' }])
    expect(r.asked[0]!.waitMs).toBeGreaterThan(0)
    expect(readFileSync(envFile, 'utf8')).toBe('export A=1\nexport MESH_SESSION_ID=s_01hrk7y0000000000000aaaaa1\n')
  })

  it('never writes a session id it did not validate, and never fails the host when no peer answers', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'cc-env-'))
    const envFile = join(dir, 'env')
    const bad = rig({ session: 's_x; rm -rf ~', name: 'x' })
    bad.deps.env = { CLAUDE_ENV_FILE: envFile }
    expect(await runClaudeHook(['session-start'], bad.deps)).toBe(0)
    expect(() => readFileSync(envFile, 'utf8')).toThrow()
    const none = rig(undefined)
    none.deps.env = { CLAUDE_ENV_FILE: envFile }
    expect(await runClaudeHook(['session-start'], none.deps)).toBe(0)
    expect(await runClaudeHook(['turn'], none.deps)).toBe(0)
  })

  it('an unknown event or unreadable input is ignored, still exit 0', async () => {
    const r = rig()
    r.deps.stdin = async () => 'not json'
    expect(await runClaudeHook(['turn'], r.deps)).toBe(0)
    expect(r.asked.at(-1)!.key).toBeUndefined()
    expect(await runClaudeHook(['nope'], r.deps)).toBe(0)
    expect(r.asked).toHaveLength(1)
  })

  it('lists the events the plugin hooks use', () => {
    expect(CLAUDE_HOOK_EVENTS).toEqual(['session-start', 'turn', 'blocked', 'stop', 'end'])
  })
})
