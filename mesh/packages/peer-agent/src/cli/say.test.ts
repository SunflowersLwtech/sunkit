import { describe, it, expect, vi } from 'vitest'
import { parseSayArgs, sayWith, SAY_USAGE } from './say.ts'
import type { SessionRow } from '../resolve-target.ts'

const rows: SessionRow[] = [
  { session_id: 's_01hrk7y0000000000000aaaaaa', ref: 'aaaaaa', name: 'lead', account: 'carol', device: 'server', status: 'idle', last_seen: 'x' },
  { session_id: 's_01hrk7y0000000000000bbbbbb', ref: 'bbbbbb', name: 'dup', account: 'bob', device: 'laptop', status: 'idle', last_seen: 'x' },
  { session_id: 's_01hrk7y0000000000000cccccc', ref: 'cccccc', name: 'dup', account: 'bob', device: 'desktop', status: 'idle', last_seen: 'x' },
]

describe('mesh say: arguments', () => {
  it('takes the name from --as, else MESH_SESSION_NAME, and the rest of the line as the message', () => {
    expect(parseSayArgs(['--as', 'docs-devin', 'lead', '[ci]', 'gates', 'green'], {}))
      .toEqual({ as: 'docs-devin', to: 'lead', message: '[ci] gates green' })
    expect(parseSayArgs(['lead', 'hi'], { MESH_SESSION_NAME: 'api-devin' }).as).toBe('api-devin')
    expect(parseSayArgs(['--as', 'a', 'lead', 'hi'], { MESH_SESSION_NAME: 'b' }).as).toBe('a')
  })
  it('sanitizes the name the same way session names are', () => {
    expect(parseSayArgs(['--as', 'my devin [1]', 'x', 'hi'], {}).as).toBe('my-devin-1')
  })
  it('passes --reply-to through and reads the message from stdin for "-"', () => {
    expect(parseSayArgs(['--reply-to', 'msg_01HRK7Y000000000000000000A', '--as', 'a', 'x', '-'], {}, () => 'from stdin\n'))
      .toEqual({ as: 'a', to: 'x', message: 'from stdin\n', replyTo: 'msg_01HRK7Y000000000000000000A' })
  })
  it('refuses without a name, a recipient or a message', () => {
    expect(() => parseSayArgs(['x', 'hi'], {})).toThrow(SAY_USAGE)
    expect(() => parseSayArgs(['--as', 'a', 'x'], {})).toThrow(SAY_USAGE)
    expect(() => parseSayArgs(['--as', 'a'], {})).toThrow(SAY_USAGE)
  })
})

describe('mesh say: sending', () => {
  const client = (delivered = true) => {
    const send = vi.fn(async () => ({ id: 'msg_01HRK7Y000000000000000000B', delivered_at: delivered ? 'now' : null }))
    return { listSessions: vi.fn(async () => rows), send } as never as { listSessions: () => Promise<SessionRow[]>; send: typeof send }
  }
  it('addresses the resolved session and sets in_reply_to', async () => {
    const c = client()
    const out = await sayWith(c as never, { as: 'api-devin', to: 'lead', message: 'done', replyTo: 'msg_01HRK7Y000000000000000000A' })
    expect(c.send).toHaveBeenCalledWith({ to: 'carol', to_session: 's_01hrk7y0000000000000aaaaaa', kind: 'chat', content: 'done', meta: {}, in_reply_to: 'msg_01HRK7Y000000000000000000A' })
    expect(out).toBe('delivered to lead [aaaaaa] as api-devin (msg_01HRK7Y000000000000000000B)')
  })
  it('reports a session that is reconnecting, and refuses ambiguous or unknown names', async () => {
    expect(await sayWith(client(false) as never, { as: 'a', to: 'lead', message: 'x' })).toMatch(/^queued/)
    await expect(sayWith(client() as never, { as: 'a', to: 'dup', message: 'x' })).rejects.toThrow(/matches 2 sessions/)
    await expect(sayWith(client() as never, { as: 'a', to: 'nobody', message: 'x' })).rejects.toThrow(/no live session named "nobody"/)
    await expect(sayWith(client() as never, { as: 'a', to: 'dup [cccccc]', message: 'x' })).resolves.toMatch(/dup \[cccccc\]/)
  })
})
