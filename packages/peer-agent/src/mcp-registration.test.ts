import { describe, it, expect } from 'vitest'
import { mkdtempSync, readFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { writeMeshMcpConfig } from './mcp-registration.ts'

describe('writeMeshMcpConfig', () => {
  it('writes a standalone mcp.json and leaves ~/.claude.json alone', () => {
    const home = mkdtempSync(join(tmpdir(), 'mesh-home-'))
    const path = writeMeshMcpConfig(join(home, '.claude-mesh'))
    expect(path).toBe(join(home, '.claude-mesh', 'mcp.json'))
    const cfg = JSON.parse(readFileSync(path, 'utf8'))
    expect(Object.keys(cfg.mcpServers)).toEqual(['mesh'])
    expect(cfg.mcpServers.mesh.type).toBe('stdio')
    expect(existsSync(join(home, '.claude.json'))).toBe(false)
  })
})
