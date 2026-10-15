import { describe, it, expect, vi } from 'vitest'
import { PassThrough } from 'node:stream'
import { onHostClosed } from './host-lifetime.ts'

describe('onHostClosed', () => {
  it('fires once when the host ends stdin, after the data before it was read', async () => {
    const stdin = new PassThrough()
    const seen: string[] = []
    stdin.on('data', d => { seen.push(String(d)) })
    const gone = vi.fn()
    onHostClosed(stdin, gone)
    stdin.write('{"jsonrpc":"2.0"}\n')
    stdin.end()
    await new Promise(r => setImmediate(r))
    expect(seen).toEqual(['{"jsonrpc":"2.0"}\n'])
    expect(gone).toHaveBeenCalledTimes(1)
    expect(gone).toHaveBeenCalledWith('stdin_end')
  })

  it('fires on close without end (pipe destroyed), and only once when both happen', async () => {
    const destroyed = new PassThrough()
    const gone = vi.fn()
    onHostClosed(destroyed, gone)
    destroyed.destroy()
    await new Promise(r => setImmediate(r))
    expect(gone).toHaveBeenCalledWith('stdin_close')

    const both = new PassThrough()
    both.resume()
    const once = vi.fn()
    onHostClosed(both, once)
    both.end()
    await new Promise(r => setImmediate(r))
    await new Promise(r => setImmediate(r))
    expect(once).toHaveBeenCalledTimes(1)
  })

  it('does not fire while the host keeps stdin open', async () => {
    const stdin = new PassThrough()
    stdin.resume()
    const gone = vi.fn()
    onHostClosed(stdin, gone)
    stdin.write('x\n')
    await new Promise(r => setImmediate(r))
    expect(gone).not.toHaveBeenCalled()
  })
})
