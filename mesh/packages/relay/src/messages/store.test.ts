import { describe, it, expect, beforeEach } from 'vitest'
import { openDatabase, type Db } from '../db/db.ts'
import { MessageStore } from './store.ts'
import type { OutboundMessage } from '@claude-mesh/shared'

function seed(db: Db) {
  const now = new Date().toISOString()
  db.prepare("INSERT INTO team(id,name,retention_days,created_at) VALUES (?,?,?,?)")
    .run('t1', 'acme', 7, now)
  for (const h of ['alice', 'bob', 'charlie']) {
    db.prepare("INSERT INTO human(id,team_id,handle,display_name,created_at) VALUES (?,?,?,?,?)")
      .run(`h_${h}`, 't1', h, h, now)
  }
}

describe('MessageStore', () => {
  let db: Db
  let store: MessageStore
  beforeEach(() => { db = openDatabase(':memory:'); seed(db); store = new MessageStore(db) })

  it('assigns id/from/sent_at and returns the full envelope', () => {
    const inbound: OutboundMessage = { to: 'bob', kind: 'chat', content: 'hi' }
    const e = store.insert('t1', 'alice', inbound)
    expect(e.id).toMatch(/^msg_/)
    expect(e.from).toBe('alice')
    expect(e.to).toBe('bob')
    expect(e.sent_at).toBeTruthy()
    expect(e.delivered_at).toBeNull()
    expect(e.thread_root).toBeNull()
  })

  it('denormalizes thread_root from in_reply_to chain', () => {
    const root = store.insert('t1', 'alice', { to: 'bob', kind: 'chat', content: 'root' })
    const r1 = store.insert('t1', 'bob', {
      to: 'alice', kind: 'chat', content: 'r1', in_reply_to: root.id
    })
    const r2 = store.insert('t1', 'alice', {
      to: 'bob', kind: 'chat', content: 'r2', in_reply_to: r1.id
    })
    expect(r1.thread_root).toBe(root.id)
    expect(r2.thread_root).toBe(root.id)
  })

  it('rejects unknown recipient handle', () => {
    expect(() => store.insert('t1', 'alice', {
      to: 'mallory', kind: 'chat', content: 'x'
    })).toThrow(/unknown recipient/)
  })

  it('allows broadcast with no other team members (stored as no-op fanout)', () => {
    // Broadcast with no other peers is NOT an error — it's just a no-op fanout.
    const e = store.insert('t1', 'alice', { to: '@team', kind: 'chat', content: 'anyone?' })
    expect(e.to).toBe('@team')
  })

  it('rejects permission_verdict without in_reply_to', () => {
    expect(() => store.insert('t1', 'alice', {
      to: 'bob', kind: 'permission_verdict', content: '',
      meta: { request_id: 'abcde', behavior: 'allow' }
    } as OutboundMessage)).toThrow(/in_reply_to/)
  })

  it('fetchSince returns messages after the given ULID ordered ascending', () => {
    const a = store.insert('t1', 'alice', { to: 'bob', kind: 'chat', content: '1' })
    const b = store.insert('t1', 'alice', { to: 'bob', kind: 'chat', content: '2' })
    const c = store.insert('t1', 'alice', { to: 'bob', kind: 'chat', content: '3' })
    const list = store.fetchSince('t1', 'bob', a.id)
    expect(list.map(e => e.id)).toEqual([b.id, c.id])
  })

  it('fetchPendingFor returns undelivered messages for a handle', () => {
    const a = store.insert('t1', 'alice', { to: 'bob', kind: 'chat', content: '1' })
    store.markDelivered(a.id)
    store.insert('t1', 'alice', { to: 'bob', kind: 'chat', content: '2' })
    const pending = store.fetchPendingFor('t1', 'bob')
    expect(pending).toHaveLength(1)
    expect(pending[0]!.content).toBe('2')
  })

  it('markDelivered is idempotent', () => {
    const a = store.insert('t1', 'alice', { to: 'bob', kind: 'chat', content: '1' })
    store.markDelivered(a.id)
    expect(() => store.markDelivered(a.id)).not.toThrow()
  })
})
