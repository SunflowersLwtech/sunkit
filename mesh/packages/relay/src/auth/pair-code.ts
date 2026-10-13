import { randomBytes, createHash } from 'node:crypto'

const ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ' // Crockford base32-ish; no I L O U

function base32(bytes: Buffer): string {
  let bits = 0
  let value = 0
  let out = ''
  for (const b of bytes) {
    value = (value << 8) | b
    bits += 8
    while (bits >= 5) {
      out += ALPHABET[(value >>> (bits - 5)) & 31]
      bits -= 5
    }
  }
  if (bits > 0) out += ALPHABET[(value << (5 - bits)) & 31]
  return out
}

export function checksumOf(body: string): string {
  const hash = createHash('sha256').update(body).digest()
  return base32(hash.subarray(0, 3)).slice(0, 4).padEnd(4, '0')
}

export function generatePairCode(): string {
  const body8 = base32(randomBytes(5)).slice(0, 8)
  const body = `${body8.slice(0, 4)}-${body8.slice(4, 8)}`
  const cs = checksumOf(body)
  return `MESH-${body}-${cs}`
}

export function parsePairCode(s: string): { body: string } | null {
  const m = /^MESH-([0-9A-Z]{4})-([0-9A-Z]{4})-([0-9A-Z]{4})$/.exec(s)
  if (!m) return null
  const body = `${m[1]}-${m[2]}`
  if (checksumOf(body) !== m[3]) return null
  return { body }
}
