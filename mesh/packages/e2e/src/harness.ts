import { mkdtempSync, writeFileSync, mkdirSync, chmodSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { serve, type ServerType } from '@hono/node-server'
import { ulid } from 'ulid'
import { openDatabase } from '../../relay/src/db/db.ts'
import { MessageStore } from '../../relay/src/messages/store.ts'
import { Fanout } from '../../relay/src/fanout.ts'
import { PresenceRegistry } from '../../relay/src/presence/registry.ts'
import { buildApp } from '../../relay/src/app.ts'
import { initTeam } from '../../relay/src/cli/init.ts'

export interface HarnessHuman {
  handle: string
  token: string
  configDir: string
}

export interface Harness {
  relayUrl: string
  humans: Record<string, HarnessHuman>
  cleanup: () => Promise<void>
}

export async function startHarness(
  handles: string[],
  opts: { permissionRelay?: boolean } = {}
): Promise<Harness> {
  const [adminHandle, ...otherHandles] = handles
  if (!adminHandle) throw new Error('startHarness requires at least one handle')

  const db = openDatabase(':memory:')
  const init = initTeam(db, {
    team_id: `team_${ulid()}`,
    team_name: 'e2e',
    admin_handle: adminHandle,
    admin_display_name: adminHandle,
  })

  const app = buildApp({
    db,
    store: new MessageStore(db),
    fanout: new Fanout(),
    presence: new PresenceRegistry(),
    now: () => new Date(),
  })
  const { server, port } = await new Promise<{ server: ServerType; port: number }>(resolve => {
    const s = serve({ fetch: app.fetch, port: 0, hostname: '127.0.0.1' }, info => {
      resolve({ server: s, port: info.port })
    })
  })
  const relayUrl = `http://127.0.0.1:${port}`

  const humans: Record<string, HarnessHuman> = {}

  const adminPair = await (await fetch(`${relayUrl}/v1/auth/pair`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ pair_code: init.human_pair_code, device_label: 'e2e' }),
  })).json() as { token: string }
  humans[adminHandle] = {
    handle: adminHandle,
    token: adminPair.token,
    configDir: makeConfigDir(adminHandle, relayUrl, adminPair.token, opts.permissionRelay ?? false),
  }

  for (const h of otherHandles) {
    const created = await (await fetch(`${relayUrl}/v1/admin/users`, {
      method: 'POST',
      headers: { authorization: `Bearer ${init.admin_token}`, 'content-type': 'application/json' },
      body: JSON.stringify({ handle: h, display_name: h }),
    })).json() as { pair_code: string }
    const pair = await (await fetch(`${relayUrl}/v1/auth/pair`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ pair_code: created.pair_code, device_label: 'e2e' }),
    })).json() as { token: string }
    humans[h] = {
      handle: h,
      token: pair.token,
      configDir: makeConfigDir(h, relayUrl, pair.token, opts.permissionRelay ?? false),
    }
  }

  return {
    relayUrl,
    humans,
    cleanup: async () => {
      await new Promise<void>(resolve => server.close(() => resolve()))
      for (const h of Object.values(humans)) rmSync(h.configDir, { recursive: true, force: true })
    },
  }
}

function makeConfigDir(handle: string, relayUrl: string, token: string, permissionRelay: boolean): string {
  const dir = mkdtempSync(join(tmpdir(), `e2e-${handle}-`))
  const meshDir = join(dir, '.claude-mesh')
  mkdirSync(meshDir, { recursive: true })
  const tokPath = join(meshDir, 'token')
  writeFileSync(tokPath, token, { mode: 0o600 })
  try { chmodSync(tokPath, 0o600) } catch { /* Windows */ }
  writeFileSync(join(meshDir, 'config.json'), JSON.stringify({
    relay_url: relayUrl,
    token_path: tokPath,
    self_handle: handle,
    permission_relay: { enabled: permissionRelay, routing: 'ask_thread_participants' },
    presence: { auto_publish_cwd: false, auto_publish_branch: false, auto_publish_repo: false },
    audit_log: join(meshDir, 'audit'),
  }, null, 2))
  return dir
}
