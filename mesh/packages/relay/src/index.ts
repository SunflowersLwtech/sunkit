#!/usr/bin/env node
import { openDatabase } from './db/db.ts'
import { initTeam } from './cli/init.ts'
import { startServer } from './cli/serve.ts'
import { writeFileSync, chmodSync, existsSync, mkdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { createInterface } from 'node:readline'
import { pathToFileURL } from 'node:url'
import { ulid } from 'ulid'
import { loadEnvFiles } from '@claude-mesh/shared'

async function prompt(q: string): Promise<string> {
  const rl = createInterface({ input: process.stdin, output: process.stdout })
  return new Promise(res => rl.question(q, a => { rl.close(); res(a.trim()) }))
}

async function main() {
  loadEnvFiles()
  const [, , cmd] = process.argv
  const dataDir = process.env.MESH_DATA ?? '/data'
  const dbPath = join(dataDir, 'mesh.sqlite')
  const port = Number(process.env.PORT ?? 443)
  const host = process.env.HOST ?? '0.0.0.0'
  const inactiveDays = Number(process.env.MESH_INACTIVE_DAYS ?? 30)

  if (cmd === 'init') {
    if (existsSync(dbPath)) {
      console.error('refusing to init: db exists at', dbPath)
      process.exit(1)
    }
    mkdirSync(dirname(dbPath), { recursive: true })
    const db = openDatabase(dbPath)
    // Env vars allow non-interactive init (e.g. `docker run` without a TTY).
    const team_name = process.env.MESH_TEAM_NAME ?? await prompt('Team name: ')
    const admin_handle = process.env.MESH_ADMIN_HANDLE ?? await prompt('Admin handle: ')
    const admin_display_name = process.env.MESH_ADMIN_NAME ?? admin_handle
    const r = initTeam(db, { team_id: `team_${ulid()}`, team_name, admin_handle, admin_display_name })

    const adminTokenPath = join(dataDir, 'admin.token')
    const paircodePath = join(dataDir, `${admin_handle}.paircode`)
    writeFileSync(adminTokenPath, r.admin_token)
    chmodSync(adminTokenPath, 0o600)
    writeFileSync(paircodePath, r.human_pair_code)
    chmodSync(paircodePath, 0o600)
    console.log(`OK Team "${team_name}" created`)
    console.log(`OK Admin-tier token written to ${adminTokenPath}`)
    console.log(`OK Human-tier pair code for "${admin_handle}" written to ${paircodePath} (expires ${r.human_pair_expires_at})`)
    return
  }

  startServer({ db_path: dbPath, port, host, inactive_days: inactiveDays })
}

const invokedAsScript = Boolean(process.argv[1]) && import.meta.url === pathToFileURL(process.argv[1]!).href
if (invokedAsScript) {
  main().catch(err => { console.error(err); process.exit(1) })
}
