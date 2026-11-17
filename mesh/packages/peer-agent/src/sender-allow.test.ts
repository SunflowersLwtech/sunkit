import { describe, it, expect } from 'vitest'
import { allowVerdict, parseAllow } from './sender-allow.ts'

const live = (name: string, account = 'weiliu') => ({ from: account, from_session: 's_01abcdef', from_name: name })

describe('parseAllow', () => {
  it('splits a comma list and trims it', () => {
    expect(parseAllow(' feishu-assistant, bossai-handoff ,')).toEqual(['feishu-assistant', 'bossai-handoff'])
  })
  it('unset or blank is no allow-list', () => {
    expect(parseAllow(undefined)).toBeUndefined()
    expect(parseAllow(' , ')).toBeUndefined()
  })
})

describe('allowVerdict', () => {
  const allow = ['feishu-assistant', 'bossai-handoff']

  it('a live session with an allowed name on the own account is ok', () => {
    expect(allowVerdict(live('feishu-assistant'), allow, 'weiliu')).toBe('ok')
    expect(allowVerdict(live('bossai-handoff'), allow, 'weiliu')).toBe('ok')
  })
  it('a send-only sender is refused even under an allowed name: its name is any script\'s label', () => {
    expect(allowVerdict({ from: 'weiliu', from_session: null, from_name: 'feishu-assistant' }, allow, 'weiliu')).toBe('send-only')
  })
  it('a session without a name is refused', () => {
    expect(allowVerdict({ from: 'weiliu', from_session: 's_01abcdef', from_name: null }, allow, 'weiliu')).toBe('send-only')
  })
  it('names match exactly, not by prefix', () => {
    expect(allowVerdict(live('feishu-assistant-x'), allow, 'weiliu')).toBe('not-listed')
    expect(allowVerdict(live('feishu'), allow, 'weiliu')).toBe('not-listed')
  })
  it('an allowed name on another account is refused', () => {
    expect(allowVerdict(live('feishu-assistant', 'mallory'), allow, 'weiliu')).toBe('foreign-account')
  })
  it('an unknown own account fails closed', () => {
    expect(allowVerdict(live('feishu-assistant'), allow, undefined)).toBe('no-own-account')
  })
})
