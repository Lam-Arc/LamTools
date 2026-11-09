import { describe, expect, it } from 'vitest'

import { base64ToBytes, bytesToBase64, isReplaySafe } from '../src/transport/remoteCodec'

describe('remote transport codec', () => {
  it('round-trips binary bytes without touching them', () => {
    // user:“远程模式下图片预览是坏的”+(0x89 / 0x00 / 0xff 在“当文本解码”的方案里会坏)。
    const bytes = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x00, 0x1a, 0x0a, 0xff])
    const encoded = bytesToBase64(bytes)
    expect(Array.from(base64ToBytes(encoded))).toEqual(Array.from(bytes))
    expect(base64ToBytes(undefined).length).toBe(0)
  })

  it('handles a payload larger than one chunk', () => {
    const bytes = new Uint8Array(40_000)
    for (let index = 0; index < bytes.length; index += 1) bytes[index] = index % 251
    const decoded = base64ToBytes(bytesToBase64(bytes))
    expect(decoded.length).toBe(bytes.length)
    expect(decoded[0]).toBe(bytes[0])
    expect(decoded[39_999]).toBe(bytes[39_999])
  })

  it('replays reads but never writes', () => {
    expect(isReplaySafe({ kind: 'http', method: 'GET', path: '/x' })).toBe(true)
    expect(isReplaySafe({ kind: 'http', method: 'POST', path: '/x' })).toBe(false)
    expect(isReplaySafe({ kind: 'rpc', method: 'thread/resume' })).toBe(true)
    expect(isReplaySafe({ kind: 'rpc', method: 'settings/get' })).toBe(false)
    expect(isReplaySafe({ kind: 'rpc', method: 'settings.get' })).toBe(true)
    expect(isReplaySafe({ kind: 'rpc', method: 'thread/start' })).toBe(false)
    expect(isReplaySafe({ kind: 'rpc', method: 'turn/start' })).toBe(false)
  })
})
