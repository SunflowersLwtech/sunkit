import { describe, it, expect } from 'vitest'
import fc from 'fast-check'
import {
  EnvelopeSchema, OutboundMessageSchema,
  envelopeFromRow, envelopeToRow,
  type Envelope, type OutboundMessage
} from './envelope.ts'
import { PROTOCOL_VERSION, MAX_CONTENT_BYTES } from './constants.ts'

const validChatEnvelope = (): Envelope => ({
  id: 'msg_01HRK7Y0000000000000000000', v: PROTOCOL_VERSION,
  team: 'team_abc', from: 'alice', to: 'bob',
  in_reply_to: null, thread_root: null,
  kind: 'chat', content: 'hello',
  meta: { repo: 'claudes-talking' },
  sent_at: '2026-04-17T23:01:12.345Z', delivered_at: null,
  from_session: null, from_name: null, to_session: null, from_login: null
})

describe('EnvelopeSchema', () => {
  it('defaults session fields to null for legacy envelopes', () => {
    const { from_session: _a, from_name: _b, to_session: _c, ...legacy } = validChatEnvelope()
    const e = EnvelopeSchema.parse(legacy)
    expect([e.from_session, e.from_name, e.to_session]).toEqual([null, null, null])
  })
  it('rejects session names that could break the [ref] address syntax', () => {
    for (const bad of ['a b', 'x[1]', 'a"b', '<x>']) {
      expect(() => EnvelopeSchema.parse({ ...validChatEnvelope(), from_name: bad })).toThrow()
    }
  })
  it('accepts a minimal valid chat envelope', () => {
    expect(EnvelopeSchema.parse(validChatEnvelope())).toBeDefined()
  })
  it('rejects wrong protocol version', () => {
    expect(() => EnvelopeSchema.parse({ ...validChatEnvelope(), v: 2 })).toThrow()
  })
  it('rejects content larger than MAX_CONTENT_BYTES', () => {
    const e = { ...validChatEnvelope(), content: 'a'.repeat(MAX_CONTENT_BYTES + 1) }
    expect(() => EnvelopeSchema.parse(e)).toThrow(/content/)
  })
  it('accepts content at exactly MAX_CONTENT_BYTES', () => {
    const e = { ...validChatEnvelope(), content: 'a'.repeat(MAX_CONTENT_BYTES) }
    expect(EnvelopeSchema.parse(e)).toBeDefined()
  })
  it('rejects meta keys with invalid characters', () => {
    const e = { ...validChatEnvelope(), meta: { 'bad-key': 'x' } }
    expect(() => EnvelopeSchema.parse(e)).toThrow()
  })
  it('accepts `to: "@team"` for broadcast', () => {
    expect(EnvelopeSchema.parse({ ...validChatEnvelope(), to: '@team' })).toBeDefined()
  })
  it('rejects unknown kind', () => {
    expect(() => EnvelopeSchema.parse({ ...validChatEnvelope(), kind: 'surprise' })).toThrow()
  })
  it('requires in_reply_to on permission_verdict kind', () => {
    const e = {
      ...validChatEnvelope(), kind: 'permission_verdict', in_reply_to: null,
      meta: { request_id: 'abcde', behavior: 'allow' }
    }
    expect(() => EnvelopeSchema.parse(e)).toThrow(/in_reply_to/)
  })
})

describe('OutboundMessageSchema', () => {
  it('accepts a minimal outbound chat', () => {
    const m: OutboundMessage = { to: 'bob', kind: 'chat', content: 'hi' }
    expect(OutboundMessageSchema.parse(m)).toBeDefined()
  })
  it('rejects outbound with id (server assigns)', () => {
    expect(() => OutboundMessageSchema.parse({
      to: 'bob', kind: 'chat', content: 'hi', id: 'msg_x'
    })).toThrow()
  })
  it('rejects outbound with from (server assigns)', () => {
    expect(() => OutboundMessageSchema.parse({
      to: 'bob', kind: 'chat', content: 'hi', from: 'alice'
    })).toThrow()
  })
})

describe('row <-> envelope conversion', () => {
  it('round-trips a known envelope through the DB row shape', () => {
    const e = validChatEnvelope()
    expect(envelopeFromRow(envelopeToRow(e))).toEqual(e)
  })
  it('property: arbitrary valid envelopes round-trip cleanly', () => {
    const arb = fc.record({
      id: fc.constantFrom('msg_01HRK7Y0000000000000000000', 'msg_01HRK7Y0000000000000000001'),
      v: fc.constant(PROTOCOL_VERSION),
      team: fc.stringMatching(/^[a-zA-Z0-9_-]{1,32}$/),
      from: fc.constantFrom('alice', 'bob', 'charlie'),
      to: fc.constantFrom('alice', 'bob', '@team'),
      in_reply_to: fc.constant(null),
      thread_root: fc.constant(null),
      kind: fc.constantFrom('chat', 'presence_update'),
      content: fc.string({ maxLength: 1024 }),
      meta: fc.dictionary(
        fc.stringMatching(/^[a-zA-Z_][a-zA-Z0-9_]{0,63}$/),
        fc.string({ maxLength: 256 }), { maxKeys: 8 }
      ),
      sent_at: fc.constant('2026-04-17T23:01:12.345Z'),
      delivered_at: fc.constant(null),
      from_session: fc.constantFrom(null, 's_01hrk7y0000000000000ab'),
      from_name: fc.constantFrom(null, 'opensource-1c'),
      to_session: fc.constantFrom(null, 's_01hrk7y0000000000000cd'),
      from_login: fc.constantFrom(null, 'someone@example.com')
    })
    fc.assert(fc.property(arb, e => {
      expect(envelopeFromRow(envelopeToRow(e as Envelope))).toEqual(e)
    }), { numRuns: 200 })
  })
})
