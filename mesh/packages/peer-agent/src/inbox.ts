import type { JoinDecision } from './join-policy.ts'

/**
 * How this peer takes part in the mesh:
 * - push: listed; inbound chat goes to Claude Code as channel notifications.
 * - pull: listed (marked pull); inbound chat waits in an in-memory inbox until the
 *   host calls read_messages. For MCP hosts without channels, such as Devin CLI.
 * - send: not listed, receives nothing; can still send.
 */
export type JoinMode = 'push' | 'pull' | 'send'

/** MESH_JOIN=pull opts into pull mode; anything else keeps the Claude Code join rules. */
export function chooseJoinMode(env: string | undefined, decide: () => JoinDecision): { mode: JoinMode; reason: string } {
  if (env === 'pull') return { mode: 'pull', reason: 'MESH_JOIN=pull' }
  const d = decide()
  return { mode: d.join ? 'push' : 'send', reason: d.reason }
}

export interface InboxItem {
  content: string
  meta: Record<string, string>
}

/**
 * Messages received in pull mode, oldest first, held until read_messages takes them.
 * Bounded so a host that never reads cannot grow the process without limit; when full,
 * the oldest message is dropped and counted so the reader is told.
 */
export class Inbox {
  private items: InboxItem[] = []
  private dropped = 0
  private arrived = 0

  constructor(private readonly max = 200) {}

  push(item: InboxItem): void {
    this.arrived++
    this.items.push(item)
    if (this.items.length > this.max) {
      this.items.shift()
      this.dropped++
    }
  }

  get size(): number {
    return this.items.length
  }

  /** What is waiting, without taking it: count, up to five distinct senders, and a counter of every arrival so far. */
  peek(): { size: number; seq: number; from: string[] } {
    const from = [...new Set(this.items.map(m => m.meta.from ?? '?'))].slice(0, 5)
    return { size: this.items.length, seq: this.arrived, from }
  }

  /** Remove and return up to `limit` of the oldest messages, plus how many were dropped since the last take. */
  take(limit = 20): { items: InboxItem[]; dropped: number; remaining: number } {
    const items = this.items.splice(0, Math.max(1, limit))
    const dropped = this.dropped
    this.dropped = 0
    return { items, dropped, remaining: this.items.length }
  }
}

function attr(meta: Record<string, string>): string {
  // Values are already escaped for attributes by envelopeToChannelNotification.
  return Object.entries(meta).map(([k, v]) => ` ${k}="${v}"`).join('')
}

/** Same <channel> shape Claude Code shows for pushed messages, so one set of rules covers both. */
export function formatInbox(r: { items: InboxItem[]; dropped: number; remaining: number }): string {
  const lines: string[] = []
  if (r.dropped > 0) lines.push(`(${r.dropped} older message(s) were dropped because the inbox was full)`)
  if (r.items.length === 0) lines.push('No new messages.')
  for (const m of r.items) lines.push(`<channel${attr(m.meta)}>\n${m.content}\n</channel>`)
  if (r.remaining > 0) lines.push(`(${r.remaining} more waiting; call read_messages again)`)
  return lines.join('\n')
}
