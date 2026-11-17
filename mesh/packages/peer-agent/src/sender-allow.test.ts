import { describe, it, expect } from 'vitest'
import { allowVerdict, parseAllow } from './sender-allow.ts'

const live = (name: string, account = 'weiliu', token = 'tk_N150') => ({ from: account, from_session: 's_01abcdef', from_name: name, from_token: token })

describe('parseAllow', () => {
  it('splits a comma list of <name>@<token-id> pins and trims it', () => {
    expect(parseAllow(' feishu-assistant@tk_N150, bossai-handoff@tk_M4 ,')).toEqual(['feishu-assistant@tk_N150', 'bossai-handoff@tk_M4'])
  })
  it('a bare name or an empty pin is a config error, not an allow-list', () => {
    expect(() => parseAllow('feishu-assistant')).toThrow('must be <session-name>@<token-id>')
    expect(() => parseAllow('feishu-assistant@')).toThrow('must be <session-name>@<token-id>')
    expect(() => parseAllow('feishu-assistant,bossai-handoff@tk_M4')).toThrow('must be <session-name>@<token-id>')
  })
  it('unset or blank is no allow-list', () => {
    expect(parseAllow(undefined)).toBeUndefined()
    expect(parseAllow(' , ')).toBeUndefined()
  })
})

describe('allowVerdict', () => {
  const allow = ['feishu-assistant@tk_N150', 'bossai-handoff@tk_M4']

  it('a live session with an allowed name on the own account, sent with the pinned token, is ok', () => {
    expect(allowVerdict(live('feishu-assistant', 'weiliu', 'tk_N150'), allow, 'weiliu')).toBe('ok')
    expect(allowVerdict(live('bossai-handoff', 'weiliu', 'tk_M4'), allow, 'weiliu')).toBe('ok')
  })
  it('a send-only sender is refused even under an allowed name and its token: its name is any script\'s label', () => {
    expect(allowVerdict({ from: 'weiliu', from_session: null, from_name: 'feishu-assistant', from_token: 'tk_N150' }, allow, 'weiliu')).toBe('send-only')
  })
  it('a session without a name is refused', () => {
    expect(allowVerdict({ from: 'weiliu', from_session: 's_01abcdef', from_name: null, from_token: 'tk_N150' }, allow, 'weiliu')).toBe('send-only')
  })
  it('names match exactly, not by prefix', () => {
    expect(allowVerdict(live('feishu-assistant-x', 'weiliu', 'tk_N150'), allow, 'weiliu')).toBe('not-listed')
    expect(allowVerdict(live('feishu', 'weiliu', 'tk_N150'), allow, 'weiliu')).toBe('not-listed')
  })
  it('an allowed name on another account is refused', () => {
    expect(allowVerdict(live('feishu-assistant', 'mallory', 'tk_N150'), allow, 'weiliu')).toBe('foreign-account')
  })
  it('an unknown own account fails closed', () => {
    expect(allowVerdict(live('feishu-assistant', 'weiliu', 'tk_N150'), allow, undefined)).toBe('no-own-account')
  })
  it('a same-name session on another token of the account is refused (the squat)', () => {
    expect(allowVerdict(live('feishu-assistant', 'weiliu', 'tk_DEVDESK'), allow, 'weiliu')).toBe('wrong-token')
    expect(allowVerdict(live('feishu-assistant', 'weiliu', 'tk_M4'), allow, 'weiliu')).toBe('wrong-token')
  })
  it('a letter without a stamp (older relay) fails closed', () => {
    expect(allowVerdict({ ...live('feishu-assistant'), from_token: null }, allow, 'weiliu')).toBe('no-token')
  })
  it('a bare entry is unpinned and never ok, alone or next to a pin for the same name', () => {
    expect(allowVerdict(live('feishu-assistant'), ['feishu-assistant'], 'weiliu')).toBe('unpinned')
    expect(allowVerdict(live('feishu-assistant', 'weiliu', 'tk_DEVDESK'), ['feishu-assistant'], 'weiliu')).toBe('unpinned')
    expect(allowVerdict(live('feishu-assistant', 'weiliu', 'tk_DEVDESK'), ['feishu-assistant', 'feishu-assistant@tk_N150'], 'weiliu')).toBe('wrong-token')
    expect(allowVerdict(live('feishu-assistant', 'weiliu', 'tk_DEVDESK'), ['feishu-assistant@tk_N150', 'feishu-assistant'], 'weiliu')).toBe('wrong-token')
    expect(allowVerdict(live('feishu-assistant'), ['feishu-assistant@'], 'weiliu')).toBe('unpinned')
  })
})
