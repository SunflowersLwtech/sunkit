import { mkdirSync, writeFileSync, chmodSync } from 'node:fs'
import { join } from 'node:path'
import { meshDir } from '../paths.ts'

export interface PairOpts {
  relayUrl: string
  pairCode: string
  deviceLabel: string
  home?: string
  fetch?: typeof globalThis.fetch
}

interface PairResponse {
  token: string
  human: { handle: string; display_name: string }
  team: { id: string; name: string }
}

export async function runPair(opts: PairOpts): Promise<void> {
  const fetchImpl = opts.fetch ?? globalThis.fetch

  const res = await fetchImpl(new URL('/v1/auth/pair', opts.relayUrl), {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ pair_code: opts.pairCode, device_label: opts.deviceLabel })
  })
  const text = await res.text()
  if (res.status !== 200) throw new Error(`pair failed: ${res.status} ${text}`)
  const r = JSON.parse(text) as PairResponse

  const dir = opts.home ? join(opts.home, '.claude-mesh') : meshDir()
  mkdirSync(dir, { recursive: true })
  const tokenPath = join(dir, 'token')
  writeFileSync(tokenPath, r.token, { mode: 0o600 })
  try { chmodSync(tokenPath, 0o600) } catch { /* Windows */ }

  const cfgPath = join(dir, 'config.json')
  const cfg = {
    relay_url: opts.relayUrl,
    token_path: tokenPath,
    self_handle: r.human.handle,
    permission_relay: { enabled: false, routing: 'never_relay' },
    presence: { auto_publish_cwd: true, auto_publish_branch: true, auto_publish_repo: true },
    audit_log: join(dir, 'audit')
  }
  writeFileSync(cfgPath, JSON.stringify(cfg, null, 2))
  mkdirSync(cfg.audit_log, { recursive: true })

  process.stdout.write(`OK Paired as "${r.human.handle}" on device "${opts.deviceLabel}"\n`)
  process.stdout.write(`OK Bearer token saved to ${tokenPath} (chmod 600)\n`)
  process.stdout.write(`OK Config written to ${cfgPath}\n`)
}
