import { describe, it, expect, beforeEach } from 'vitest'
import { Fanout, type Subscriber } from './fanout.ts'
import type { Envelope } from '@claude-mesh/shared'

const env = (id: string, to: string, from = 'alice'): Envelope => ({
  id: `msg_01HRK7Y000000000000000000${id.padStart(1, '0')}`, v: 1,
  team: 't1', from, to, in_reply_to: null, thread_root: null,
  kind: 'chat', content: 'x', meta: {},
  sent_at: new Date().toISOString(), delivered_at: null
})

function collectingSub(handle: string): Subscriber & { received: Envelope[] } {
  const received: Envelope[] = []
  return { handle, team_id: 't1', deliver: e => { received.push(e) }, received }
}

describe('Fanout', () => {
  let f: Fanout
  beforeEach(() => { f = new Fanout() })

  it('delivers DM to exactly the addressed recipient', () => {
    const alice = collectingSub('alice')
    const bob = collectingSub('bob')
    f.subscribe(alice); f.subscribe(bob)
    f.deliver(env('A', 'bob'))
    expect(alice.received).toHaveLength(0)
    expect(bob.received).toHaveLength(1)
  })

  it('delivers @team broadcast to all in the team except the sender', () => {
    const alice = collectingSub('alice')
    const bob = collectingSub('bob')
    const charlie = collectingSub('charlie')
    f.subscribe(alice); f.subscribe(bob); f.subscribe(charlie)
    f.deliver(env('A', '@team', 'alice'))
    expect(alice.received).toHaveLength(0)
    expect(bob.received).toHaveLength(1)
    expect(charlie.received).toHaveLength(1)
  })

  it('delivers to all of a human\'s sessions (fan-in)', () => {
    const bobLaptop = collectingSub('bob')
    const bobDesk = collectingSub('bob')
    f.subscribe(bobLaptop); f.subscribe(bobDesk)
    f.deliver(env('A', 'bob'))
    expect(bobLaptop.received).toHaveLength(1)
    expect(bobDesk.received).toHaveLength(1)
  })

  it('unsubscribe stops delivery to that subscriber only', () => {
    const bob1 = collectingSub('bob')
    const bob2 = collectingSub('bob')
    f.subscribe(bob1); f.subscribe(bob2)
    f.unsubscribe(bob1)
    f.deliver(env('A', 'bob'))
    expect(bob1.received).toHaveLength(0)
    expect(bob2.received).toHaveLength(1)
  })

  it('does not cross teams (sub on team t2 never sees t1 messages)', () => {
    const otherReceived: Envelope[] = []
    const other: Subscriber = {
      handle: 'bob', team_id: 't2', deliver: (e: Envelope) => otherReceived.push(e),
    }
    const bob = collectingSub('bob')
    f.subscribe(other); f.subscribe(bob)
    f.deliver(env('A', 'bob'))
    expect(bob.received).toHaveLength(1)
    expect(otherReceived).toHaveLength(0)
  })

  it('tracks online handles per team', () => {
    f.subscribe(collectingSub('alice'))
    f.subscribe(collectingSub('bob'))
    expect(new Set(f.onlineHandles('t1'))).toEqual(new Set(['alice', 'bob']))
  })
})
