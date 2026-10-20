import { ulid } from 'ulid'
import type { Envelope, OutboundMessage } from '@claude-mesh/shared'
import type { SessionRow } from './resolve-target.ts'

export interface RelayClientOpts {
  relayUrl: string
  token: string
  /** This Claude Code session's id; sent as x-mesh-session so the relay can stamp from_session. */
  sessionId?: string
  /** Name a send-only sender gives itself (no session); sent as x-mesh-sender-name. */
  senderName?: string
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
        ...(this.opts.sessionId
          ? { 'x-mesh-session': this.opts.sessionId }
          : this.opts.senderName ? { 'x-mesh-sender-name': this.opts.senderName } : {}),
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

  async updateSelf(patch: { name?: string; status?: string; cwd?: string; login?: string }): Promise<void> {
    if (!this.opts.sessionId) return
    const res = await this.fetchImpl(new URL('/v1/sessions/self', this.opts.relayUrl), {
      method: 'POST',
      headers: { authorization: `Bearer ${this.opts.token}`, 'content-type': 'application/json' },
      body: JSON.stringify({ session: this.opts.sessionId, ...patch }),
    })
    // 404 means the stream hasn't (re)attached yet; the next stream open carries fresh values.
    if (res.status !== 200 && res.status !== 404) throw new Error(`updateSelf failed: ${res.status}`)
  }

  /** Card fields for this session. Throws while the relay has not attached the session yet, so the writer tries again. */
  async writeCard(card: Record<string, unknown>): Promise<void> {
    if (!this.opts.sessionId) return
    const res = await this.fetchImpl(new URL('/v1/sessions/self', this.opts.relayUrl), {
      method: 'POST',
      headers: { authorization: `Bearer ${this.opts.token}`, 'content-type': 'application/json' },
      body: JSON.stringify({ session: this.opts.sessionId, ...card }),
    })
    if (res.status === 404) throw new Error('session not attached yet')
    if (res.status !== 200) throw new Error(`card update failed: ${res.status} ${(await res.text()).slice(0, 200)}`)
  }

  private sessionHeaders(): Record<string, string> {
    return {
      authorization: `Bearer ${this.opts.token}`,
      'content-type': 'application/json',
      ...(this.opts.sessionId ? { 'x-mesh-session': this.opts.sessionId } : {}),
    }
  }

  async getTask(id: string): Promise<{ status: number; task?: { state: string; assignee: { session: string | null } } }> {
    const res = await this.fetchImpl(new URL(`/v1/tasks/${encodeURIComponent(id)}`, this.opts.relayUrl), { headers: this.sessionHeaders() })
    const body = await res.json().catch(() => null) as { state: string; assignee: { session: string | null } } | null
    return res.status === 200 && body ? { status: 200, task: { state: body.state, assignee: { session: body.assignee?.session ?? null } } } : { status: res.status }
  }

  async patchTask(id: string, body: { state: string }): Promise<{ status: number; error?: string }> {
    const res = await this.fetchImpl(new URL(`/v1/tasks/${encodeURIComponent(id)}`, this.opts.relayUrl), {
      method: 'PATCH', headers: this.sessionHeaders(), body: JSON.stringify(body),
    })
    const j = await res.json().catch(() => null) as { error?: string } | null
    return { status: res.status, ...(j?.error ? { error: j.error } : {}) }
  }

  async rebindTask(id: string): Promise<{ status: number }> {
    const res = await this.fetchImpl(new URL(`/v1/tasks/${encodeURIComponent(id)}/rebind`, this.opts.relayUrl), {
      method: 'POST', headers: this.sessionHeaders(), body: '{}',
    })
    await res.text().catch(() => '')
    return { status: res.status }
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
