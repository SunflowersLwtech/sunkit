import { describe, it, expect, afterEach } from 'vitest'
import { join } from 'node:path'
import { homedir } from 'node:os'
import { meshDir } from './paths.ts'
import { defaultConfigPath } from './config.ts'

describe('meshDir', () => {
  const saved = process.env.MESH_HOME
  afterEach(() => { if (saved === undefined) delete process.env.MESH_HOME; else process.env.MESH_HOME = saved })

  it('defaults to ~/.claude-mesh', () => {
    delete process.env.MESH_HOME
    expect(meshDir()).toBe(join(homedir(), '.claude-mesh'))
  })
  it('MESH_HOME relocates config for a second identity on the same machine', () => {
    process.env.MESH_HOME = '/tmp/mesh-b'
    expect(defaultConfigPath()).toBe(join('/tmp/mesh-b', 'config.json'))
  })
})
