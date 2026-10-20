import { describe, it, expect, afterEach } from 'vitest'
import { mkdirSync, mkdtempSync, writeFileSync, statSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { Inbox } from './inbox.ts'
import { HookChannel, hookSocketPath, serveHookSocket, askHookSocket } from './hook-socket.ts'

const msg = (from: string) => ({ content: 'x', meta: { from, account: 'alice', msg_id: 'm', source: 'peers' } })

describe('HookChannel', () => {
  const make = () => {
    const inbox = new Inbox()
    const statuses: string[] = []
    return { inbox, statuses, ch: new HookChannel(inbox, s => statuses.push(s)) }
  }

  it('a turn marks the session busy and reports what is unread, by sender', () => {
    const { inbox, statuses, ch } = make()
    expect(ch.handle({ op: 'turn' })).toEqual({ unread: 0, from: [] })
    inbox.push(msg('lead [abc123]')); inbox.push(msg('lead [abc123]')); inbox.push(msg('ops [def456]'))
    expect(ch.handle({ op: 'turn' })).toEqual({ unread: 3, from: ['lead [abc123]', 'ops [def456]'] })
    expect(statuses).toEqual(['busy', 'busy'])
  })

  it('stop asks to continue once per new arrival, then lets the session go idle', () => {
    const { inbox, statuses, ch } = make()
    expect(ch.handle({ op: 'stop', reason: 'NO_TOOL_CALL' })).toEqual({ unread: 0, from: [], continue: false })
    inbox.push(msg('lead [abc123]'))
    expect(ch.handle({ op: 'stop', reason: 'NO_TOOL_CALL' })).toEqual({ unread: 1, from: ['lead [abc123]'], continue: true })
    // The agent stopped again without reading it: no second nudge for the same message.
    expect(ch.handle({ op: 'stop', reason: 'NO_TOOL_CALL' })).toEqual({ unread: 1, from: ['lead [abc123]'], continue: false })
    inbox.push(msg('ops [def456]'))
    expect(ch.handle({ op: 'stop', reason: 'NO_TOOL_CALL' }).continue).toBe(true)
    inbox.take()
    expect(ch.handle({ op: 'stop', reason: 'NO_TOOL_CALL' })).toEqual({ unread: 0, from: [], continue: false })
    expect(statuses).toEqual(['idle', 'idle', 'idle'])
  })

  it('never overrides a stop the user asked for, an error, or a limit', () => {
    for (const reason of ['USER_CANCELED', 'ERROR', 'MAX_INVOCATIONS', 'MAX_FORCED_INVOCATIONS', undefined]) {
      const { inbox, statuses, ch } = make()
      inbox.push(msg('lead [abc123]'))
      expect(ch.handle({ op: 'stop', ...(reason ? { reason } : {}) }).continue).toBe(false)
      expect(statuses).toEqual(['idle'])
      // A user's Esc does not use up the nudge for that message.
      expect(ch.handle({ op: 'stop', reason: 'NO_TOOL_CALL' }).continue).toBe(true)
    }
  })

  it('a stop marked natural nudges whatever its reason; natural: false never does', () => {
    const { inbox, statuses, ch } = make()
    inbox.push(msg('lead [abc123]'))
    expect(ch.handle({ op: 'stop', reason: 'shutdown', natural: false }).continue).toBe(false)
    expect(ch.handle({ op: 'stop', reason: 'NO_TOOL_CALL', natural: false }).continue).toBe(false)
    expect(ch.handle({ op: 'stop', reason: 'end_turn', natural: true })).toEqual({ unread: 1, from: ['lead [abc123]'], continue: true })
    expect(ch.handle({ op: 'stop', reason: 'end_turn', natural: true }).continue).toBe(false)
    expect(statuses).toEqual(['idle', 'idle', 'idle'])
  })

  it('a tool call marks the session busy and asks for a notice once per new arrival', () => {
    const { inbox, statuses, ch } = make()
    expect(ch.handle({ op: 'tool' })).toEqual({ unread: 0, from: [], notify: false })
    inbox.push(msg('lead [abc123]'))
    expect(ch.handle({ op: 'tool' })).toEqual({ unread: 1, from: ['lead [abc123]'], notify: true })
    // Still unread on the next tool call: the agent was already told.
    expect(ch.handle({ op: 'tool' })).toEqual({ unread: 1, from: ['lead [abc123]'], notify: false })
    inbox.push(msg('ops [def456]'))
    expect(ch.handle({ op: 'tool' }).notify).toBe(true)
    inbox.take()
    expect(ch.handle({ op: 'tool' }).notify).toBe(false)
    expect(statuses).toEqual(['busy', 'busy', 'busy', 'busy', 'busy'])
  })

  it('a notice after a tool call does not use up the nudge at the stop', () => {
    const { inbox, ch } = make()
    inbox.push(msg('lead [abc123]'))
    expect(ch.handle({ op: 'tool' }).notify).toBe(true)
    expect(ch.handle({ op: 'stop', natural: true }).continue).toBe(true)
  })

  it('idle reports the session idle and what is waiting', () => {
    const { inbox, statuses, ch } = make()
    inbox.push(msg('lead [abc123]'))
    expect(ch.handle({ op: 'idle' })).toEqual({ unread: 1, from: ['lead [abc123]'] })
    expect(statuses).toEqual(['idle'])
  })

  it('wake starts a turn once per new arrival and shares that count with the stop nudge', () => {
    const { inbox, statuses, ch } = make()
    expect(ch.handle({ op: 'wake' })).toEqual({ unread: 0, from: [], continue: false })
    inbox.push(msg('lead [abc123]'))
    expect(ch.handle({ op: 'wake' })).toEqual({ unread: 1, from: ['lead [abc123]'], continue: true })
    // Still unread on the next poll: not woken again for the same message.
    expect(ch.handle({ op: 'wake' })).toEqual({ unread: 1, from: ['lead [abc123]'], continue: false })
    // The turn it started ends without reading it: no second nudge either.
    expect(ch.handle({ op: 'stop', natural: true })).toEqual({ unread: 1, from: ['lead [abc123]'], continue: false })
    inbox.push(msg('ops [def456]'))
    expect(ch.handle({ op: 'stop', natural: true }).continue).toBe(true)
    expect(ch.handle({ op: 'wake' }).continue).toBe(false)
    expect(statuses).toEqual(['idle', 'idle', 'idle', 'idle'])
  })

  it('a request it does not know changes nothing', () => {
    const { inbox, statuses, ch } = make()
    inbox.push(msg('lead [abc123]'))
    expect(ch.handle({ op: 'bogus' } as never)).toEqual({ unread: 1, from: ['lead [abc123]'] })
    expect(statuses).toEqual([])
  })
})

describe('hook socket', () => {
  const closers: Array<() => void> = []
  afterEach(() => { for (const c of closers.splice(0)) c() })

  it('lives under the mesh home, one per host process', () => {
    if (process.platform === 'win32') {
      expect(hookSocketPath(4242, 'C:\\m')).toMatch(/^\\\\\.\\pipe\\claude-mesh-hook-[0-9a-f]{8}-4242$/)
    } else {
      expect(hookSocketPath(4242, '/h/.claude-mesh')).toBe('/h/.claude-mesh/hooks/4242.sock')
    }
  })

  it('answers hook requests from the inbox, replacing a stale socket file, readable only by its owner', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'mesh-hk-'))
    const path = hookSocketPath(4242, dir)
    const inbox = new Inbox()
    inbox.push(msg('lead [abc123]'))
    const statuses: string[] = []
    if (process.platform !== 'win32') {
      // Left behind by a peer that crashed.
      mkdirSync(join(dir, 'hooks'), { recursive: true })
      writeFileSync(path, '')
    }
    const server = await serveHookSocket(path, new HookChannel(inbox, s => statuses.push(s)))
    closers.push(() => server.close())
    if (process.platform !== 'win32') expect(statSync(path).mode & 0o777).toBe(0o600)
    expect(await askHookSocket(path, { op: 'turn' })).toEqual({ unread: 1, from: ['lead [abc123]'] })
    expect(await askHookSocket(path, { op: 'stop', reason: 'NO_TOOL_CALL' })).toEqual({ unread: 1, from: ['lead [abc123]'], continue: true })
    expect(statuses).toEqual(['busy'])
    // A second peer for the same host pid (pid reuse after a crash) takes the path over.
    const again = await serveHookSocket(path, new HookChannel(new Inbox(), () => {}))
    closers.push(() => again.close())
    expect(await askHookSocket(path, { op: 'turn' })).toEqual({ unread: 0, from: [] })
  })

  it('a missing socket or a silent server yields undefined, quickly', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'mesh-hk-'))
    expect(await askHookSocket(hookSocketPath(9, dir), { op: 'turn' })).toBeUndefined()
    if (process.platform === 'win32') return
    const { createServer } = await import('node:net')
    const path = join(dir, 'silent.sock')
    const silent = createServer(() => { /* never answers */ })
    await new Promise<void>(r => silent.listen(path, r))
    closers.push(() => silent.close())
    const t0 = Date.now()
    expect(await askHookSocket(path, { op: 'turn' }, 300)).toBeUndefined()
    expect(Date.now() - t0).toBeLessThan(2_000)
    expect(existsSync(path)).toBe(true)
  })
})

describe('HookChannel: card, task and identity events', () => {
  const make = (extra: ConstructorParameters<typeof HookChannel>[2] = {}) => {
    const inbox = new Inbox()
    const statuses: string[] = []
    const events: string[] = []
    const cards: unknown[] = []
    const ch = new HookChannel(inbox, s => statuses.push(s), {
      onEvent: e => events.push(e), onCard: c => cards.push(c), whoami: () => ({ session: 's_01hrk7y0000000000000aaaaa1', name: 'fr-inkrec' }), ...extra,
    })
    return { inbox, statuses, events, cards, ch }
  }

  it('forwards the host\'s lifecycle to the task driver', () => {
    const { statuses, events, ch } = make()
    ch.handle({ op: 'turn' }); ch.handle({ op: 'tool' }); ch.handle({ op: 'blocked' }); ch.handle({ op: 'stop', natural: true }); ch.handle({ op: 'end' })
    expect(events).toEqual(['turn', 'tool', 'blocked', 'done', 'end'])
    expect(statuses).toEqual(['busy', 'busy', 'idle', 'idle'])
  })

  it('tells a turn that ended on its own from one that was cut short or a session closing', () => {
    const { events, ch } = make()
    ch.handle({ op: 'stop', natural: true })
    ch.handle({ op: 'stop', reason: 'NO_TOOL_CALL' })
    ch.handle({ op: 'stop', reason: 'end_turn', natural: true })
    ch.handle({ op: 'stop', reason: 'shutdown', natural: false })
    ch.handle({ op: 'stop', reason: 'interrupted' })
    expect(events).toEqual(['done', 'done', 'done', 'stop', 'stop'])
  })

  it('a stop that keeps the turn going is not an end of turn', () => {
    const { inbox, events, ch } = make()
    inbox.push(msg('lead [abc123]'))
    expect(ch.handle({ op: 'stop', natural: true }).continue).toBe(true)
    expect(events).toEqual([])
  })

  it('answers whoami with this session, so commands run inside the host can name it', () => {
    const { ch } = make()
    expect(ch.handle({ op: 'whoami' })).toMatchObject({ session: 's_01hrk7y0000000000000aaaaa1', name: 'fr-inkrec' })
  })

  it('passes card fields from a hook to the card writer', () => {
    const { cards, ch } = make()
    ch.handle({ op: 'card', card: { model: 'claude-opus-5-5' } })
    expect(cards).toEqual([{ model: 'claude-opus-5-5' }])
  })

  it('a wake the budget refuses starts no turn', () => {
    const { inbox, statuses, ch } = make({ wakeAllowed: () => false })
    inbox.push(msg('lead [abc123]'))
    expect(ch.handle({ op: 'wake' }).continue).toBe(false)
    expect(statuses).toEqual(['idle'])
  })
})

describe('HookChannel: hooks that arrive out of order', () => {
  it('ignores an event older than one already applied (separate background hook processes can race)', () => {
    const inbox = new Inbox()
    const statuses: string[] = []
    const events: string[] = []
    const ch = new HookChannel(inbox, s => statuses.push(s), { onEvent: e => events.push(e) })
    ch.handle({ op: 'stop', natural: true, at: 2_000 })
    ch.handle({ op: 'turn', at: 1_000 })
    ch.handle({ op: 'blocked', at: 1_500 })
    expect(statuses).toEqual(['idle'])
    expect(events).toEqual(['done'])
    ch.handle({ op: 'turn', at: 3_000 })
    expect(statuses).toEqual(['idle', 'busy'])
    // Hosts that send no time keep the old behaviour.
    ch.handle({ op: 'idle' })
    expect(statuses).toEqual(['idle', 'busy', 'idle'])
  })
})
