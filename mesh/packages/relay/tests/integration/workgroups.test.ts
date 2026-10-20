import { describe, it, expect } from 'vitest'
import { harness, openSession, readSse, req, S } from './ledger-helpers.ts'

const LIUWEI = { role: 'worker' as const, workgroup: 'liuwei', visible: ['team'] }
const specs = [
  { id: 'tk_m4', handle: 'duocode', label: 'm4', grant: LIUWEI },
  { id: 'tk_sec', handle: 'weiliu', label: 'n150', grant: LIUWEI },
  { id: 'tk_mate', handle: 'jovie', label: 'jovie-laptop' },
  { id: 'tk_mate2', handle: 'frankie', label: 'frankie-laptop' },
]

const send = (h: ReturnType<typeof harness>, tok: string, body: Record<string, unknown>, fromSession?: string) =>
  req(h.app, tok, 'POST', '/v1/messages', { kind: 'chat', ...body }, fromSession ? { 'x-mesh-session': fromSession } : {})

describe('workgroup boundary on messages', () => {
  it('a teammate cannot address a private session, even knowing its id', async () => {
    const h = harness(specs)
    await openSession(h.app, h.tok.tk_m4!, S.a1, 'private')
    await openSession(h.app, h.tok.tk_mate!, S.b1, 'mate')
    const res = await send(h, h.tok.tk_mate!, { to: 'duocode', to_session: S.a1, content: 'hi' }, S.b1)
    expect(res.status).toBe(403)
    expect(await res.json()).toMatchObject({ error: 'cross_workgroup' })
  })

  it('the owner can message a teammate, and the teammate can answer that message', async () => {
    const h = harness(specs)
    const sec = await openSession(h.app, h.tok.tk_sec!, S.o1, 'feishu-assistant')
    await openSession(h.app, h.tok.tk_mate!, S.b1, 'mate')
    const out = await send(h, h.tok.tk_sec!, { to: 'jovie', to_session: S.b1, content: 'please look at #12' }, S.o1)
    expect(out.status).toBe(201)
    const first = (await out.json()) as { id: string }
    const reply = await send(h, h.tok.tk_mate!, { to: 'weiliu', to_session: S.o1, content: 'done', in_reply_to: first.id }, S.b1)
    expect(reply.status).toBe(201)
    const got = await readSse(sec.body!, 1)
    expect(got[0]!.data).toContain('"content":"done"')
    // Without the reply link the private session stays unreachable.
    expect((await send(h, h.tok.tk_mate!, { to: 'weiliu', to_session: S.o1, content: 'again' }, S.b1)).status).toBe(403)
  })

  it('a reply link only opens the session that wrote to you, not a sibling', async () => {
    const h = harness(specs)
    await openSession(h.app, h.tok.tk_sec!, S.o1, 'feishu-assistant')
    await openSession(h.app, h.tok.tk_sec!, S.o1.replace('ooooo1', 'ooooo2'), 'other-private')
    await openSession(h.app, h.tok.tk_mate!, S.b1, 'mate')
    const first = (await (await send(h, h.tok.tk_sec!, { to: 'jovie', to_session: S.b1, content: 'x' }, S.o1)).json()) as { id: string }
    const res = await send(h, h.tok.tk_mate!, { to: 'weiliu', to_session: S.o1.replace('ooooo1', 'ooooo2'), content: 'y', in_reply_to: first.id }, S.b1)
    expect(res.status).toBe(403)
  })

  it('a private @team broadcast reaches the owner\'s other private sessions but no teammate', async () => {
    const h = harness(specs)
    await openSession(h.app, h.tok.tk_m4!, S.a1, 'private-a')
    const sec = await openSession(h.app, h.tok.tk_sec!, S.o1, 'sec')
    const mate = await openSession(h.app, h.tok.tk_mate!, S.b1, 'mate')
    const res = await send(h, h.tok.tk_m4!, { to: '@team', content: 'private news' }, S.a1)
    expect(res.status).toBe(201)
    const [atSec, atMate] = await Promise.all([readSse(sec.body!, 1), readSse(mate.body!, 1)])
    expect(atSec).toHaveLength(1)
    expect(atMate).toHaveLength(0)
  })

  it('the backlog obeys the same boundary as live delivery', async () => {
    const h = harness(specs)
    await openSession(h.app, h.tok.tk_m4!, S.a1, 'private-a')
    await send(h, h.tok.tk_m4!, { to: '@team', content: 'private news' }, S.a1)
    await send(h, h.tok.tk_mate2!, { to: '@team', content: 'team news' })
    const mate = await openSession(h.app, h.tok.tk_mate!, S.b1, 'mate')
    const got = await readSse(mate.body!, 2)
    expect(got.map(e => JSON.parse(e.data).content)).toEqual(['team news'])
  })

  it('a teammate\'s broadcast does not land in private sessions', async () => {
    const h = harness(specs)
    const priv = await openSession(h.app, h.tok.tk_m4!, S.a1, 'private-a')
    await send(h, h.tok.tk_mate!, { to: '@team', content: 'team news' })
    expect(await readSse(priv.body!, 1)).toHaveLength(0)
  })

  it('presence from a private token is not shown to a teammate', async () => {
    const h = harness(specs)
    await req(h.app, h.tok.tk_m4!, 'POST', '/v1/presence', { summary: 'secret project', repo: 'bossai' })
    const peers = (await (await req(h.app, h.tok.tk_mate!, 'GET', '/v1/peers')).json()) as Array<{ handle: string; summary: string; sessions: unknown[] }>
    const duocode = peers.find(p => p.handle === 'duocode')!
    expect(duocode.summary).toBe('')
    expect(duocode.sessions).toEqual([])
    const own = (await (await req(h.app, h.tok.tk_sec!, 'GET', '/v1/peers')).json()) as Array<{ handle: string; summary: string }>
    expect(own.find(p => p.handle === 'duocode')!.summary).toBe('secret project')
  })

  it('old tokens with no grant keep talking to each other exactly as before', async () => {
    const h = harness([{ id: 'tk_x', handle: 'xx', label: 'a' }, { id: 'tk_y', handle: 'yy', label: 'b' }])
    await openSession(h.app, h.tok.tk_x!, S.a1, 'x')
    const y = await openSession(h.app, h.tok.tk_y!, S.b1, 'y')
    expect((await send(h, h.tok.tk_x!, { to: 'yy', to_session: S.b1, content: 'hello' }, S.a1)).status).toBe(201)
    expect(await readSse(y.body!, 1)).toHaveLength(1)
  })
})
