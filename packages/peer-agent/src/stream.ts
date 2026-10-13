import { fetch } from 'undici'
import { EnvelopeSchema, type Envelope } from '@claude-mesh/shared'
import { logJson } from './logger.ts'

export interface SseEvent { event: string; data: string }

export function parseSseEvent(block: string): SseEvent | null {
  const lines = block.split('\n')
  let event = 'message'
  const dataParts: string[] = []
  let anyField = false
  for (const line of lines) {
    if (line.startsWith(':')) continue
    if (line.length === 0) continue
    const idx = line.indexOf(':')
    const field = idx === -1 ? line : line.slice(0, idx)
    const value = idx === -1 ? '' : line.slice(idx + 1).replace(/^ /, '')
    anyField = true
    if (field === 'event') event = value
    else if (field === 'data') dataParts.push(value)
  }
  if (!anyField || (dataParts.length === 0 && event === 'message')) return null
  return { event, data: dataParts.join('\n') }
}

export interface StreamClientOpts {
  relayUrl: string
  token: string
  sinceCursor: () => string | undefined
  /** Session binding sent on every (re)connect, so the relay always has current name/status. */
  sessionParams?: () => Record<string, string>
  onEnvelope: (e: Envelope) => void
  onAuthError: () => void
  reconnectBaseMs?: number
  reconnectMaxMs?: number
}

export class StreamClient {
  private aborter: AbortController | null = null
  private stopped = false
  private attempt = 0

  constructor(private opts: StreamClientOpts) {}

  async start(): Promise<void> {
    while (!this.stopped) {
      this.aborter = new AbortController()
      try {
        const since = this.opts.sinceCursor()
        const url = new URL('/v1/stream', this.opts.relayUrl)
        if (since) url.searchParams.set('since', since)
        for (const [k, v] of Object.entries(this.opts.sessionParams?.() ?? {})) url.searchParams.set(k, v)
        const res = await fetch(url, {
          headers: { authorization: `Bearer ${this.opts.token}`, accept: 'text/event-stream' },
          signal: this.aborter.signal,
        })
        if (res.status === 401) { this.opts.onAuthError(); return }
        if (res.status !== 200 || !res.body) throw new Error(`stream http ${res.status}`)
        this.attempt = 0
        logJson('info', 'peer.stream.open', { since: since ?? '' })
        await this.readStream(res.body as unknown as ReadableStream<Uint8Array>)
      } catch (err) {
        logJson('warn', 'peer.stream.disconnect', { err: String(err instanceof Error ? err.message : err) })
      }
      if (this.stopped) break
      const delay = Math.min(
        this.opts.reconnectMaxMs ?? 30_000,
        (this.opts.reconnectBaseMs ?? 500) * 2 ** Math.min(this.attempt++, 6)
      )
      await new Promise(r => setTimeout(r, delay))
    }
  }

  stop(): void { this.stopped = true; this.aborter?.abort() }

  private async readStream(body: ReadableStream<Uint8Array>): Promise<void> {
    const decoder = new TextDecoder()
    let buf = ''
    const reader = body.getReader()
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      buf = this.consume(buf)
    }
  }

  private consume(buf: string): string {
    const parts = buf.split('\n\n')
    const rest = parts.pop() ?? ''
    for (const block of parts) {
      const ev = parseSseEvent(block)
      if (!ev) continue
      logJson('info', 'peer.stream.event', { event: ev.event })
      if (ev.event === 'ping') continue
      if (ev.event !== 'message') continue
      try {
        const raw = JSON.parse(ev.data)
        const envelope = EnvelopeSchema.parse(raw)
        this.opts.onEnvelope(envelope)
      } catch (err) {
        logJson('warn', 'peer.stream.decode_error', { err: String(err instanceof Error ? err.message : err) })
      }
    }
    return rest
  }
}
