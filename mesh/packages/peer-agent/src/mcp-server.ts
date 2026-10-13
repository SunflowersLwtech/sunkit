import { Server } from '@modelcontextprotocol/sdk/server/index.js'
import type { ServerCapabilities } from '@modelcontextprotocol/sdk/types.js'
import { CHANNEL_INSTRUCTIONS } from './instructions.ts'

export interface McpServerOpts {
  permissionRelay: boolean
}

export interface McpServerHandle {
  server: Server
  capabilities: ServerCapabilities
  instructions: string
}

export function createMcpServer(opts: McpServerOpts): McpServerHandle {
  const capabilities: ServerCapabilities = {
    experimental: {
      'claude/channel': {},
      ...(opts.permissionRelay ? { 'claude/channel/permission': {} } : {}),
    },
    tools: {},
  }
  const server = new Server(
    { name: 'claude-mesh-peers', version: '0.1.0' },
    { capabilities, instructions: CHANNEL_INSTRUCTIONS }
  )
  return { server, capabilities, instructions: CHANNEL_INSTRUCTIONS }
}
