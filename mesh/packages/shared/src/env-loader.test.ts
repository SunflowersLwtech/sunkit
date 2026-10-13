import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { loadEnvFiles } from './env-loader.ts'

const KEYS = ['MESH_ENV_TEST_A', 'MESH_ENV_TEST_B', 'MESH_ENV_TEST_C'] as const

let workdir = ''
beforeEach(() => {
  workdir = mkdtempSync(join(tmpdir(), 'mesh-env-'))
  for (const k of KEYS) delete process.env[k]
})
afterEach(() => {
  rmSync(workdir, { recursive: true, force: true })
  for (const k of KEYS) delete process.env[k]
})

describe('loadEnvFiles', () => {
  it('returns empty array when no files exist', () => {
    expect(loadEnvFiles(workdir)).toEqual([])
  })

  it('loads .env into process.env', () => {
    writeFileSync(join(workdir, '.env'), 'MESH_ENV_TEST_A=from-env\n')
    const loaded = loadEnvFiles(workdir)
    expect(loaded).toHaveLength(1)
    expect(process.env.MESH_ENV_TEST_A).toBe('from-env')
  })

  it('.env.local overrides .env', () => {
    writeFileSync(join(workdir, '.env'), 'MESH_ENV_TEST_B=from-env\n')
    writeFileSync(join(workdir, '.env.local'), 'MESH_ENV_TEST_B=from-local\n')
    loadEnvFiles(workdir)
    expect(process.env.MESH_ENV_TEST_B).toBe('from-local')
  })

  it('pre-existing process.env values are not overwritten', () => {
    process.env.MESH_ENV_TEST_C = 'from-shell'
    writeFileSync(join(workdir, '.env'), 'MESH_ENV_TEST_C=from-env\n')
    loadEnvFiles(workdir)
    expect(process.env.MESH_ENV_TEST_C).toBe('from-shell')
  })
})
