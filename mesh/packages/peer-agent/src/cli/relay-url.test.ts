import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { readFileSync, writeFileSync, mkdirSync, rmSync, existsSync } from 'node:fs'
import { join } from 'node:path'
import { homedir } from 'node:os'
import { resolveRelayUrl } from './relay-url.ts'

// The resolver reads ~/.claude-mesh/config.json via homedir(). We can't remap
// homedir() without process env tricks, so we use the real home directory and
// clean up after each test.
const CFG_DIR = join(homedir(), '.claude-mesh')
const CFG_PATH = join(CFG_DIR, 'config.json')
let backup: string | null = null

describe('resolveRelayUrl', () => {
  beforeEach(() => {
    delete process.env.MESH_RELAY
    backup = null
    if (existsSync(CFG_PATH)) {
      backup = readFileSync(CFG_PATH, 'utf8')
      rmSync(CFG_PATH)
    }
  })

  afterEach(() => {
    if (existsSync(CFG_PATH)) rmSync(CFG_PATH)
    if (backup !== null) {
      mkdirSync(CFG_DIR, { recursive: true })
      writeFileSync(CFG_PATH, backup)
    }
  })

  it('prefers --relay flag over everything else', () => {
    process.env.MESH_RELAY = 'http://env:8443'
    writeConfig('http://cfg:8443')
    expect(resolveRelayUrl(['--relay', 'http://flag:8443'])).toBe('http://flag:8443')
  })

  it('falls back to MESH_RELAY env when no flag', () => {
    process.env.MESH_RELAY = 'http://env:8443'
    writeConfig('http://cfg:8443')
    expect(resolveRelayUrl([])).toBe('http://env:8443')
  })

  it('falls back to ~/.claude-mesh/config.json relay_url when neither flag nor env', () => {
    writeConfig('http://cfg:8443')
    expect(resolveRelayUrl([])).toBe('http://cfg:8443')
  })

  it('throws a helpful error when nothing is configured', () => {
    expect(() => resolveRelayUrl([])).toThrow(/missing relay URL/)
  })

  it('ignores an unparseable config.json and treats as missing', () => {
    mkdirSync(CFG_DIR, { recursive: true })
    writeFileSync(CFG_PATH, '{not valid json')
    expect(() => resolveRelayUrl([])).toThrow(/missing relay URL/)
  })

  it('ignores a config.json without relay_url and treats as missing', () => {
    mkdirSync(CFG_DIR, { recursive: true })
    writeFileSync(CFG_PATH, JSON.stringify({ self_handle: 'alice' }))
    expect(() => resolveRelayUrl([])).toThrow(/missing relay URL/)
  })
})

function writeConfig(relayUrl: string): void {
  mkdirSync(CFG_DIR, { recursive: true })
  writeFileSync(CFG_PATH, JSON.stringify({ relay_url: relayUrl, token_path: '/tmp/x' }))
}
