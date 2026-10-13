import { ulid } from 'ulid'
import type { Envelope, OutboundMessage } from '@claude-mesh/shared'
import type { SessionRow } from './resolve-target.ts'

export interface RelayClientOpts {
  relayUrl: string
  token: string
  /** This Claude Code session's id; sent as x-mesh-session so the relay can stamp from_session. */
  sessionId?: string
}

interface Injected { fetch?: typeof globalThis.fetch }

export interface PeerSummary {
  handle: string
  display_name: string
  online: boolean
  summary: string
  last_seen: string | null
  sessions: Array<{ label: string; cwd?: string; branch?: string; repo?: string }>
}

export class RelayClient {
  private fetchImpl: typeof globalThis.fetch

  constructor(private opts: RelayClientOpts, inj: Injected = {}) {
    this.fetchImpl = inj.fetch ?? globalThis.fetch
  }

  async send(msg: OutboundMessage): Promise<Envelope> {
    const res = await this.fetchImpl(new URL('/v1/messages', this.opts.relayUrl), {
      method: 'POST',
      headers: {
        authorization: `Bearer ${this.opts.token}`,
        'content-type': 'application/json',
        'idempotency-key': ulid().toLowerCase(),
        ...(this.opts.sessionId ? { 'x-mesh-session': this.opts.sessionId } : {}),
      },
      body: JSON.stringify(msg),
    })
    const text = await res.text()
    if (res.status !== 201) throw new Error(`send failed: ${res.status} ${text}`)
    return JSON.parse(text) as Envelope
  }

  async listPeers(): Promise<PeerSummary[]> {
    const res = await this.fetchImpl(new URL('/v1/peers', this.opts.relayUrl), {
      headers: { authorization: `Bearer ${this.opts.token}` },
    })
    if (res.status !== 200) throw new Error(`listPeers failed: ${res.status}`)
    return await res.json() as PeerSummary[]
  }

  async listSessions(): Promise<SessionRow[]> {
    const res = await this.fetchImpl(new URL('/v1/sessions', this.opts.relayUrl), {
      headers: { authorization: `Bearer ${this.opts.token}` },
    })
    if (res.status !== 200) throw new Error(`listSessions failed: ${res.status}`)
    return await res.json() as SessionRow[]
  }

  async updateSelf(patch: { name?: string; status?: string; cwd?: string }): Promise<void> {
    if (!this.opts.sessionId) return
    const res = await this.fetchImpl(new URL('/v1/sessions/self', this.opts.relayUrl), {
      method: 'POST',
      headers: { authorization: `Bearer ${this.opts.token}`, 'content-type': 'application/json' },
      body: JSON.stringify({ session: this.opts.sessionId, ...patch }),
    })
    // 404 means the stream hasn't (re)attached yet; the next stream open carries fresh values.
    if (res.status !== 200 && res.status !== 404) throw new Error(`updateSelf failed: ${res.status}`)
  }

  async setPresence(body: { summary: string; cwd?: string; branch?: string; repo?: string }): Promise<void> {
    const res = await this.fetchImpl(new URL('/v1/presence', this.opts.relayUrl), {
      method: 'POST',
      headers: { authorization: `Bearer ${this.opts.token}`, 'content-type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (res.status !== 200) throw new Error(`presence failed: ${res.status}`)
  }
}
