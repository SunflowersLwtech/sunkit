import { describe, it, expect, beforeEach } from 'vitest'
import { writeFileSync, mkdtempSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { readTokenFile } from './token-file.ts'

let dir: string
beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), 'mesh-token-'))
})

function write(name: string, bytes: Buffer): string {
  const p = join(dir, name)
  writeFileSync(p, bytes)
  return p
}

describe('readTokenFile', () => {
  it('reads a plain ASCII token', () => {
    const p = write('t', Buffer.from('mt_abc123\n', 'ascii'))
    expect(readTokenFile(p)).toBe('mt_abc123')
  })

  it('strips a UTF-8 BOM', () => {
    const p = write('t', Buffer.concat([Buffer.from([0xef, 0xbb, 0xbf]), Buffer.from('mt_abc123', 'utf8')]))
    expect(readTokenFile(p)).toBe('mt_abc123')
  })

  it('decodes UTF-16 LE with BOM (PowerShell `>` default)', () => {
    const p = write('t', Buffer.concat([Buffer.from([0xff, 0xfe]), Buffer.from('mt_abc123', 'utf16le')]))
    expect(readTokenFile(p)).toBe('mt_abc123')
  })

  it('decodes UTF-16 BE with BOM', () => {
    // Build the BE payload by taking UTF-16 LE bytes and swapping pairs
    const le = Buffer.from('mt_abc123', 'utf16le')
    const be = Buffer.from(le)
    for (let i = 0; i + 1 < be.length; i += 2) {
      const tmp = be[i]!
      be[i] = be[i + 1]!
      be[i + 1] = tmp
    }
    const p = write('t', Buffer.concat([Buffer.from([0xfe, 0xff]), be]))
    expect(readTokenFile(p)).toBe('mt_abc123')
  })

  it('rejects a file containing non-ASCII characters with a helpful hint', () => {
    const p = write('t', Buffer.from('mt_abc\u2028oops', 'utf8'))
    expect(() => readTokenFile(p)).toThrow(/non-ASCII/)
  })

  it('trims surrounding whitespace', () => {
    const p = write('t', Buffer.from('\n  mt_abc123  \r\n', 'utf8'))
    expect(readTokenFile(p)).toBe('mt_abc123')
  })
})

