import { it, expect } from 'vitest'
import { createServer } from 'node:http'
import { mkdtempSync, rmSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js'

it('runs the bundled pull peer with env credentials for stream, roster, tools and presence', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'mesh-env-'))
  const home = join(dir, 'home')
  const token = 'startup-test-secret'
  const requests: { path: string; auth: string | undefined }[] = []
  let streamOpened!: () => void
  let presenceWritten!: () => void
  const opened = new Promise<void>(resolve => { streamOpened = resolve })
  const presence = new Promise<void>(resolve => { presenceWritten = resolve })
  const relay = createServer((req, res) => {
    requests.push({ path: req.url!, auth: req.headers.authorization })
    if (req.url!.startsWith('/v1/stream?')) {
      res.writeHead(200, { 'content-type': 'text/event-stream' })
      res.write(': connected\n\n')
      streamOpened()
    } else {
      res.setHeader('content-type', 'application/json')
      res.end(req.url === '/v1/sessions/self' ? '{}' : '[]')
      if (req.url === '/v1/sessions/self') presenceWritten()
    }
  })
  await new Promise<void>(resolve => relay.listen(0, '127.0.0.1', resolve))
  const address = relay.address() as { port: number }
  const transport = new StdioClientTransport({
    command: process.execPath,
    args: [fileURLToPath(new URL('../../../plugins/mesh/server/mesh-peer.mjs', import.meta.url))],
    env: { PATH: process.env.PATH!, MESH_HOME: home, MESH_JOIN: 'pull', MESH_HOST: 'devin',
      MESH_SESSION_NAME: 'cloud-test', MESH_RELAY: `http://127.0.0.1:${address.port}`, MESH_TOKEN: token },
    stderr: 'pipe',
  })
  let logs = ''
  transport.stderr?.on('data', chunk => { logs += String(chunk) })
  const client = new Client({ name: 'env-startup-test', version: '1.0.0' })
  try {
    await client.connect(transport)
    const tools = await client.listTools()
    expect(tools.tools.map(tool => tool.name)).toContain('read_messages')
    await client.callTool({ name: 'list_agents', arguments: {} })
    await client.callTool({ name: 'read_messages', arguments: {} })
    await Promise.all([opened, presence])
    expect(requests.some(req => req.path === '/v1/peers')).toBe(true)
    const stream = requests.find(req => req.path.startsWith('/v1/stream?'))!
    expect(new URL(stream.path, 'http://relay').searchParams.get('mode')).toBe('pull')
    expect(requests.every(req => req.auth === `Bearer ${token}`)).toBe(true)
    expect(existsSync(join(home, 'config.json'))).toBe(false)
    expect(existsSync(join(home, 'token'))).toBe(false)
    expect(logs).not.toContain(token)
    expect(logs).not.toContain('peer.unpaired')
  } finally {
    await client.close()
    relay.closeAllConnections()
    await new Promise<void>(resolve => relay.close(() => resolve()))
    rmSync(dir, { recursive: true, force: true })
  }
})
