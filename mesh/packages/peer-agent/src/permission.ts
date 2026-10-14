export interface PermissionTrackerOpts { ttlMs: number }

interface Entry {
  msg_id: string
  expires_at: number
  sender_handle: string
}

export class PermissionTracker {
  private map = new Map<string, Entry>()

  constructor(private opts: PermissionTrackerOpts) {}

  recordIncoming(request_id: string, msg_id: string, sender_handle = ''): void {
    this.map.set(request_id.toLowerCase(), {
      msg_id, sender_handle, expires_at: Date.now() + this.opts.ttlMs
    })
    this.gc()
  }

  msgIdFor(request_id: string): string | undefined {
    const key = request_id.toLowerCase()
    const v = this.map.get(key)
    if (!v) return undefined
    if (v.expires_at < Date.now()) { this.map.delete(key); return undefined }
    return v.msg_id
  }

  senderFor(request_id: string): string | undefined {
    return this.map.get(request_id.toLowerCase())?.sender_handle
  }

  private gc(): void {
    const now = Date.now()
    for (const [k, v] of this.map) if (v.expires_at < now) this.map.delete(k)
  }
}
