import { Server } from '@modelcontextprotocol/sdk/server/index.js'
import type { ServerCapabilities } from '@modelcontextprotocol/sdk/types.js'
import { CHANNEL_INSTRUCTIONS, PULL_INSTRUCTIONS } from './instructions.ts'

export interface McpServerOpts {
  permissionRelay: boolean
  /** Pull mode: no channel capability; the host reads messages with read_messages. */
  pull?: boolean
}

export interface McpServerHandle {
  server: Server
  capabilities: ServerCapabilities
  instructions: string
}

export function createMcpServer(opts: McpServerOpts): McpServerHandle {
  const capabilities: ServerCapabilities = opts.pull
    ? { tools: {} }
    : {
        experimental: {
          'claude/channel': {},
          ...(opts.permissionRelay ? { 'claude/channel/permission': {} } : {}),
        },
        tools: {},
      }
  const instructions = opts.pull ? PULL_INSTRUCTIONS : CHANNEL_INSTRUCTIONS
  const server = new Server(
    { name: 'claude-mesh-peers', version: '0.1.0' },
    { capabilities, instructions }
  )
  return { server, capabilities, instructions }
}
