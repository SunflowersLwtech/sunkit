import { describe, it, expect } from 'vitest'
import { parseSseEvent } from './stream.ts'

describe('parseSseEvent', () => {
  it('parses event + data', () => {
    const ev = parseSseEvent('event: message\ndata: {"id":"msg_x"}')
    expect(ev).toEqual({ event: 'message', data: '{"id":"msg_x"}' })
  })
  it('defaults event to "message"', () => {
    const ev = parseSseEvent('data: hello')
    expect(ev?.event).toBe('message')
  })
  it('merges multi-line data with newlines', () => {
    const ev = parseSseEvent('event: x\ndata: a\ndata: b')
    expect(ev?.data).toBe('a\nb')
  })
  it('returns null for comment-only or empty blocks', () => {
    expect(parseSseEvent(': keepalive')).toBeNull()
    expect(parseSseEvent('')).toBeNull()
  })
})

describe('StreamClient', () => {
  it('reports the session params it attached with once the stream is open, so a status set meanwhile can be re-sent', async () => {
    const { createServer } = await import('node:http')
    const { StreamClient } = await import('./stream.ts')
    const seen: string[] = []
    const server = createServer((req, res) => {
      seen.push(req.url ?? '')
      res.writeHead(200, { 'content-type': 'text/event-stream' })
      res.write(': hi\n\n')
    })
    await new Promise<void>(r => server.listen(0, '127.0.0.1', r))
    const port = (server.address() as { port: number }).port
    let status = 'unknown'
    const opened: Array<Record<string, string>> = []
    const client = new StreamClient({
      relayUrl: `http://127.0.0.1:${port}`, token: 't', sinceCursor: () => undefined,
      sessionParams: () => ({ session: 's_1', status }),
      onEnvelope: () => {}, onAuthError: () => {},
      onOpen: sent => { opened.push(sent) },
    })
    void client.start()
    await new Promise(r => setTimeout(r, 200))
    status = 'idle'
    expect(opened).toEqual([{ session: 's_1', status: 'unknown' }])
    expect(seen[0]).toContain('status=unknown')
    client.stop()
    server.closeAllConnections()
    await new Promise(r => server.close(r))
  })
})
