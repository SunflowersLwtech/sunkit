import { join } from 'node:path'
import { homedir } from 'node:os'
import { resolveRelayUrl } from './relay-url.ts'
import { readTokenFile } from './token-file.ts'
import { meshDir } from '../paths.ts'

export interface RespondOpts {
  relayUrl: string
  token: string
  requestId: string
  verdict: 'allow' | 'deny'
  reason?: string
  fetch?: typeof globalThis.fetch
}

interface RespondResponse { ok: boolean; verdict_id: string }

function argValue(args: string[], flag: string): string | undefined {
  const i = args.indexOf(flag)
  return i >= 0 && i + 1 < args.length ? args[i + 1] : undefined
}

export async function callRespond(opts: RespondOpts): Promise<RespondResponse> {
  const fetchImpl = opts.fetch ?? globalThis.fetch
  const body: Record<string, string> = {
    request_id: opts.requestId,
    verdict: opts.verdict,
  }
  if (opts.reason !== undefined) body.reason = opts.reason
  const res = await fetchImpl(new URL('/v1/permission/respond', opts.relayUrl), {
    method: 'POST',
    headers: { authorization: `Bearer ${opts.token}`, 'content-type': 'application/json' },
    body: JSON.stringify(body)
  })
  const text = await res.text()
  if (res.status !== 200) throw new Error(`respond failed: ${res.status} ${text}`)
  return JSON.parse(text) as RespondResponse
}

export async function runRespond(args: string[]): Promise<void> {
  const [requestId, verdictRaw] = args
  if (!requestId || !verdictRaw || !['allow', 'yes', 'deny', 'no'].includes(verdictRaw)) {
    throw new Error('usage: mesh respond <request_id> allow|yes|deny|no [--reason "..."] [--relay <url>]')
  }
  const verdict: 'allow' | 'deny' = (verdictRaw === 'yes' || verdictRaw === 'allow') ? 'allow' : 'deny'
  const reason = argValue(args, '--reason')
  const relayUrl = resolveRelayUrl(args)
  const token = readTokenFile(join(meshDir(), 'token'))
  const opts: RespondOpts = { relayUrl, token, requestId, verdict }
  if (reason !== undefined) opts.reason = reason
  const r = await callRespond(opts)
  process.stdout.write(`OK ${verdict} sent (verdict_id=${r.verdict_id})\n`)
}
