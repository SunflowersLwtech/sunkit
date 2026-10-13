import { createHash, randomBytes, timingSafeEqual as nodeTimingSafeEqual } from 'node:crypto'

/** 32 random bytes encoded as url-safe base64 (43 chars, no padding). */
export function generateRawToken(): string {
  return randomBytes(32).toString('base64url')
}

/** SHA-256 hash of the raw token for storage. We never persist raw tokens. */
export function hashToken(raw: string): Buffer {
  return createHash('sha256').update(raw, 'utf8').digest()
}

export function timingSafeEqual(a: Buffer, b: Buffer): boolean {
  if (a.length !== b.length) return false
  return nodeTimingSafeEqual(a, b)
}
