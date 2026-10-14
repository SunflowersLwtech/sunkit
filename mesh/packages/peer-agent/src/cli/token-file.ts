import { readFileSync } from 'node:fs'

/**
 * Read a bearer-token file tolerantly.
 *
 * Token files are always ASCII (base32/base64 bearer strings), but users on
 * Windows who write them with PowerShell's `>` redirect end up with UTF-16 LE
 * and a BOM. Reading that as UTF-8 produces U+FFFD replacement chars, which
 * undici refuses to put in Authorization headers ("ByteString ... character
 * at index 7 has a value of 65533"). We detect UTF-16 LE / BE / UTF-8 BOMs,
 * strip them, and validate that the result is plain ASCII before returning.
 */
export function readTokenFile(path: string): string {
  const buf = readFileSync(path)
  let text: string
  if (buf.length >= 2 && buf[0] === 0xff && buf[1] === 0xfe) {
    // UTF-16 LE BOM — PowerShell `>` default on Windows
    text = buf.subarray(2).toString('utf16le')
  } else if (buf.length >= 2 && buf[0] === 0xfe && buf[1] === 0xff) {
    // UTF-16 BE BOM
    text = buf.subarray(2).swap16().toString('utf16le')
  } else if (buf.length >= 3 && buf[0] === 0xef && buf[1] === 0xbb && buf[2] === 0xbf) {
    // UTF-8 BOM
    text = buf.subarray(3).toString('utf8')
  } else {
    text = buf.toString('utf8')
  }
  const trimmed = text.trim()
  // Bearer tokens are ASCII. Reject anything that isn't, with a helpful hint.
  if (!/^[\x20-\x7e]+$/.test(trimmed)) {
    throw new Error(
      `token file ${path} contains non-ASCII characters. If you wrote it with ` +
      `PowerShell's \`>\` redirect, rewrite it as plain UTF-8, e.g.: ` +
      `[System.IO.File]::WriteAllText("${path}", "<token>")`
    )
  }
  return trimmed
}
