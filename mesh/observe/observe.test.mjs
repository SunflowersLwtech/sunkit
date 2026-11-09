// mesh observe: what the desk's Mesh page is sent. Run: node --test mesh/observe/
import { test, after } from 'node:test'
import assert from 'node:assert/strict'
import http from 'node:http'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { foldEvents, messages, newState, peers, prune, MESSAGES_KEPT } from './feed.mjs'
import { send, snapshot } from './observe.mjs'

const NOW = Date.parse('2026-11-03T06:00:00.000Z')
const iso = (msAgo) => new Date(NOW - msAgo).toISOString()
const NAMES = { sunfl: 'M4', m4: 'M4', m2: 'mone', 'aws-sin-8c32g-261016': 'aws-sin' }

test('peers: one a session, its state in the desk\'s words, its machine by the desk\'s name', () => {
  const out = peers([
    { ref: 'aaaaaa', name: 'hm', account: 'duocode', device: 'sunfl', status: 'busy', mode: 'push', agent: 'claude', model: 'claude-opus-5-5', herdr: { machine: 'm4' }, cwd: '/Users/x/Developer/products/HipiMind', age_s: 12, last_seen: iso(1) },
    { ref: 'bbbbbb', name: 'dv', account: 'duocode', device: 'mone', status: 'reconnecting', mode: 'pull', agent: 'devin', repo: 'obsun' },
    { ref: 'cccccc', name: 'x', account: 'weiliu', device: 'm2', status: 'weird' },
    { ref: 'aaaaaa', name: 'dup' },
  ], NAMES)
  assert.deepEqual(out.map((p) => [p.key, p.state, p.body.machine]), [['aaaaaa', 'busy', 'M4'], ['bbbbbb', 'away', 'mone'], ['cccccc', 'unknown', 'mone']])
  assert.deepEqual(out[0].body, { machine: 'M4', account: 'duocode', ref: 'aaaaaa', harness: 'claude', model: 'claude-opus-5-5', mode: 'push', where: 'HipiMind' })
  assert.equal(out[1].body.mode, 'pull')
  assert.equal(out[1].body.where, 'obsun')
  // Nothing that changes every minute: a snapshot with no news writes nothing on the desk.
  for (const p of out) assert.ok(!('age_s' in p.body) && !('last_seen' in p.body) && !('cwd' in p.body))
})

const ev = (seq, msg, state, extra = {}) => ({
  seq, at: extra.at ?? iso(60_000 - seq), msg_id: msg, state, bytes: 412, sent_at: extra.sent_at ?? iso(60_000),
  from: { account: 'duocode', name: 'm4-dsh', ref: 'g0wkjh', device: 'm2' },
  to: { account: 'weiliu', name: extra.to ?? 'feishu-assistant', ref: '88ex02', device: 'n150' },
  ...(state === 'delivered' ? { latency_ms: extra.latency_ms ?? 180, via: extra.via ?? 'live' } : {}),
})

test('messages: sent then delivered is one message, delivered, with the relay\'s latency as logged', () => {
  const st = foldEvents(newState(), [ev(1, 'msg_A', 'sent'), ev(2, 'msg_A', 'delivered', { latency_ms: 4321, via: 'backlog', to: 'feishu-assistant' }), ev(3, 'msg_B', 'sent', { sent_at: iso(30_000) })])
  const out = messages(st, { m2: 'mone', n150: 'N150' }, { now: NOW })
  assert.deepEqual(out.map((m) => [m.key, m.state, m.body.latency_ms]), [['msg_B', 'sent', undefined], ['msg_A', 'delivered', 4321]])
  const a = out[1]
  assert.equal(a.title, 'm4-dsh → feishu-assistant')
  assert.deepEqual(a.body.from, { name: 'm4-dsh', machine: 'mone', account: 'duocode', ref: 'g0wkjh' })
  assert.equal(a.body.to.machine, 'N150')
  assert.equal(a.body.via, 'backlog')
  assert.equal(a.body.sent_at, iso(60_000))
  assert.ok(!('content' in a.body))
  // A message still waiting has no delivery fields.
  assert.ok(!('at' in out[0].body) && !('latency_ms' in out[0].body) && !('via' in out[0].body))
})

test('messages: a delivered row read before its sent row still ends delivered', () => {
  const st = foldEvents(newState(), [ev(2, 'msg_A', 'delivered', { latency_ms: 90 })])
  foldEvents(st, [ev(1, 'msg_A', 'sent')])
  assert.equal(messages(st, {}, { now: NOW })[0].state, 'delivered')
})

test('messages: the newest 200, none older than a day, and the fold does not grow without end', () => {
  const evs = []
  for (let i = 0; i < 500; i++) evs.push(ev(i, `msg_${String(i).padStart(4, '0')}`, 'sent', { sent_at: iso(i * 1000) }))
  evs.push(ev(999, 'msg_old', 'sent', { sent_at: iso(25 * 3600_000) }))
  const st = foldEvents(newState(), evs)
  prune(st, NOW)
  const out = messages(st, {}, { now: NOW })
  assert.equal(out.length, MESSAGES_KEPT)
  assert.equal(out[0].key, 'msg_0000')
  assert.ok(!out.some((m) => m.key === 'msg_old'))
  assert.ok(st.byId.size <= MESSAGES_KEPT * 2 && !st.byId.has('msg_old'))
})

// ---- against a relay and a desk on this machine ----
// Closed after the file's tests whatever they did: a test that fails before its own close would
// otherwise leave a server listening and the file would never end.
const servers = []
after(() => Promise.all(servers.map((s) => { s.closeAllConnections(); return new Promise((r) => s.close(() => r())) })))
function server(handler) {
  return new Promise((resolve) => {
    const s = http.createServer(async (req, res) => {
      let body = ''
      for await (const c of req) body += c
      handler(req, body, res)
    })
    servers.push(s)
    s.listen(0, '127.0.0.1', () => resolve({ url: `http://127.0.0.1:${s.address().port}`, close: () => new Promise((r) => s.close(r)) }))
  })
}
function files() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'mesh-observe-'))
  fs.writeFileSync(path.join(dir, 'mesh'), 'm'.repeat(43), { mode: 0o600 })
  fs.writeFileSync(path.join(dir, 'desk'), 'frdk_' + 'x'.repeat(40), { mode: 0o600 })
  return dir
}

test('snapshot: reads the log from where it stopped; a relay with no log still sends the sessions', async () => {
  const asked = []
  let events = true
  const relay = await server((req, _b, res) => {
    asked.push(req.url)
    if (req.headers.authorization !== `Bearer ${'m'.repeat(43)}`) { res.writeHead(401).end(); return }
    if (req.url === '/v1/sessions') { res.writeHead(200, { 'content-type': 'application/json' }).end(JSON.stringify([{ ref: 'aaaaaa', name: 'a', status: 'idle', device: 'sunfl' }])); return }
    if (!events) { res.writeHead(404).end('{}'); return }
    const since = new URL(req.url, 'http://x').searchParams.get('since_seq')
    // sent_at is now, not the fixture's fixed NOW: the pusher prunes what is older than a day
    // against the real clock, and a delivered row carries the message's own sent_at.
    const at = new Date().toISOString()
    const page = since === null ? { events: [ev(7, 'msg_A', 'sent', { sent_at: at })], seq: 7 } : { events: [ev(8, 'msg_A', 'delivered', { latency_ms: 55, sent_at: at })], seq: 8 }
    res.writeHead(200, { 'content-type': 'application/json' }).end(JSON.stringify(page))
  })
  const dir = files()
  const cfg = { relay: relay.url, meshToken: () => fs.readFileSync(path.join(dir, 'mesh'), 'utf8'), names: NAMES, source: 'mesh' }
  const st = newState()
  const s1 = await snapshot(cfg, st)
  assert.deepEqual([s1.peers, s1.messages, s1.items[1].state], [1, 1, 'sent'])
  assert.equal(s1.items[0].body.machine, 'M4')
  const s2 = await snapshot(cfg, st)
  assert.equal(s2.items[1].state, 'delivered')
  assert.equal(s2.items[1].body.latency_ms, 55)
  assert.ok(asked.includes('/v1/events?limit=500') && asked.includes('/v1/events?since_seq=7&limit=500'), asked.join(' '))
  events = false
  const s3 = await snapshot(cfg, st)
  assert.equal(s3.peers, 1)
  assert.equal(s3.messages, 1)
  assert.match(s3.events_error, /404/)
  await relay.close()
})

test('snapshot: a relay that does not answer for the sessions sends nothing (the page is never emptied)', async () => {
  const relay = await server((_req, _b, res) => { res.writeHead(502).end() })
  await assert.rejects(snapshot({ relay: relay.url, meshToken: () => 'm', names: {} }, newState()), /HTTP 502/)
  await relay.close()
})

test('send: one PUT with the feed token; a thing the desk refuses is left out and the rest sent', async () => {
  const puts = []
  const desk = await server((req, body, res) => {
    puts.push({ url: req.url, auth: req.headers.authorization, body: JSON.parse(body) })
    const keys = puts.at(-1).body.items.map((i) => i.key)
    if (keys.includes('bad')) { res.writeHead(422, { 'content-type': 'application/json' }).end(JSON.stringify({ error: 'looks_like_secret', field: 'title', key: 'mesh/bad' })); return }
    res.writeHead(200, { 'content-type': 'application/json' }).end(JSON.stringify({ changed: keys.length, removed: 0, items: keys.length }))
  })
  const dir = files()
  const cfg = { api: desk.url, desk: 'desk', source: 'mesh', deskToken: () => fs.readFileSync(path.join(dir, 'desk'), 'utf8') }
  const r = await send(cfg, [{ key: 'ok1' }, { key: 'bad' }, { key: 'ok2' }], 60)
  assert.equal(r.status, 200)
  assert.deepEqual(r.dropped, [{ key: 'bad', error: 'looks_like_secret', field: 'title' }])
  assert.equal(puts.length, 2)
  assert.equal(puts[0].url, '/desk/desk/feed/mesh')
  assert.equal(puts[0].auth, `Bearer frdk_${'x'.repeat(40)}`)
  assert.equal(puts[0].body.every_s, 60)
  assert.deepEqual(puts[1].body.items.map((i) => i.key), ['ok1', 'ok2'])
  await desk.close()
})
test('send: when every thing is refused nothing is PUT after it (an empty replace would blank the page)', async () => {
  const puts = []
  const desk = await server((_req, body, res) => {
    puts.push(JSON.parse(body))
    res.writeHead(422, { 'content-type': 'application/json' }).end(JSON.stringify({ error: 'looks_like_secret', field: 'title', key: 'mesh/secret-thing' }))
  })
  const dir = files()
  const cfg = { api: desk.url, desk: 'desk', source: 'mesh', deskToken: () => fs.readFileSync(path.join(dir, 'desk'), 'utf8') }
  const r = await send(cfg, [{ key: 'secret-thing' }], 60)
  assert.equal(puts.length, 1)
  assert.equal(r.status, 422)
  assert.deepEqual(r.dropped, [{ key: 'secret-thing', error: 'looks_like_secret', field: 'title' }])
  await desk.close()
})

