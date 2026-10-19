import { describe, it, expect, afterEach } from 'vitest'
import { mkdtempSync, readFileSync, readdirSync, writeFileSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { piExtensionFile, runPiInstall } from './pi.ts'

const opts = { node: '/opt/homebrew/bin/node', peer: '/k/mesh peer.mjs', module: '/k/mesh-pi.mjs', extension: '/x/extensions/mesh.ts' }

describe('mesh pi install', () => {
  it('writes a loader for the bundled extension with the node and peer it should run', () => {
    expect(piExtensionFile(opts).split('\n')).toEqual([
      '// Written by `mesh pi install` (sunkit mesh plugin). Rerun it instead of editing this file.',
      'import { createMeshExtension } from "file:///k/mesh-pi.mjs"',
      'export default createMeshExtension({ node: "/opt/homebrew/bin/node", peer: "/k/mesh peer.mjs" })',
      '',
    ])
  })

  describe('--write', () => {
    const saved = process.env.PI_CODING_AGENT_DIR
    afterEach(() => { if (saved === undefined) delete process.env.PI_CODING_AGENT_DIR; else process.env.PI_CODING_AGENT_DIR = saved })

    it('writes <pi agent dir>/extensions/mesh.ts, backing up a changed one under a name pi does not load; without it nothing is touched', () => {
      const dir = mkdtempSync(join(tmpdir(), 'pi-inst-'))
      process.env.PI_CODING_AGENT_DIR = dir
      const file = join(dir, 'extensions', 'mesh.ts')
      const log: string[] = []
      const args = ['--node', '/n', '--peer', '/p.mjs', '--module', '/m.mjs']
      expect(runPiInstall(args, { log: s => log.push(s) })).toBe(0)
      expect(existsSync(file)).toBe(false)
      expect(log.join('\n')).toContain('MESH_SESSION_NAME')

      expect(runPiInstall([...args, '--write'], { log: () => {} })).toBe(0)
      const text = readFileSync(file, 'utf8')
      expect(text).toContain('peer: "/p.mjs"')
      // Same content again: no backup.
      runPiInstall([...args, '--write'], { log: () => {} })
      expect(readdirSync(join(dir, 'extensions'))).toEqual(['mesh.ts'])

      writeFileSync(file, '// hand edit\n')
      runPiInstall([...args, '--write'], { log: () => {} })
      const files = readdirSync(join(dir, 'extensions')).sort()
      expect(files).toHaveLength(2)
      expect(files[0]).toBe('mesh.ts')
      expect(files[1]).toMatch(/^mesh\.ts\.bak-mesh-\d{8}-\d{6}$/)
      expect(readFileSync(join(dir, 'extensions', files[1]!), 'utf8')).toBe('// hand edit\n')
      expect(readFileSync(file, 'utf8')).toBe(text)
    })
  })
})
