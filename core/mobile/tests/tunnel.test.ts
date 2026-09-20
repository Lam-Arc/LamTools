import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it, vi } from 'vitest'
import {
  MultiplexedTunnelTransport,
  TUNNEL_FRAME_TYPES,
  TUNNEL_LIMITS,
  TUNNEL_PROTOCOL_VERSION,
  TUNNEL_STREAMS,
  TunnelFrameDecoder,
  type TunnelWire,
  decodeTunnelFrames,
  encodeTunnelFrame,
  splitTunnelPayload,
  utf8ByteLength,
  type TunnelFrame,
} from '../src/connection/TunnelTransport'
import type {
  TransportConnectionState,
  TransportMessage,
} from '@lamtools/ui/transport'

class FakeWire implements TunnelWire {
  sent: Uint8Array[] = []
  private dataListeners = new Set<(data: Uint8Array) => void>()
  private stateListeners = new Set<(state: TransportConnectionState) => void>()
  async connect(): Promise<void> { this.emitState('connected') }
  send(data: Uint8Array): void { this.sent.push(data) }
  onData(listener: (data: Uint8Array) => void): () => void {
    this.dataListeners.add(listener)
    return () => this.dataListeners.delete(listener)
  }
  onState(listener: (state: TransportConnectionState) => void): () => void {
    this.stateListeners.add(listener)
    return () => this.stateListeners.delete(listener)
  }
  close(): void { this.emitState('disconnected') }
  receive(frame: TunnelFrame): void {
    for (const listener of this.dataListeners) listener(encodeTunnelFrame(frame))
  }
  receiveBytes(data: Uint8Array): void {
    for (const listener of this.dataListeners) listener(data)
  }
  private emitState(state: TransportConnectionState): void {
    for (const listener of this.stateListeners) listener(state)
  }
}

function frame(sequence: number, payload = '你好，LamTools'): TunnelFrame {
  return {
    version: TUNNEL_PROTOCOL_VERSION,
    type: TUNNEL_FRAME_TYPES.rpc,
    stream_id: TUNNEL_STREAMS.rpc,
    payload,
    sequence,
  }
}

type TunnelGoldenFixture = {
  name: string
  frame: TunnelFrame
  json_line: string
}

const tunnelGoldenFixture = JSON.parse(readFileSync(
  fileURLToPath(new URL('../../protocol/tunnel-v1-fixtures.json', import.meta.url)),
  'utf8',
)) as TunnelGoldenFixture

function rawFrameBytes(frame: Record<string, unknown>): Uint8Array {
  return new TextEncoder().encode(`${JSON.stringify(frame)}\n`)
}

describe('mobile tunnel framing', () => {
  it('matches the shared Rust v1 golden fixture on the wire', () => {
    const encoded = encodeTunnelFrame(tunnelGoldenFixture.frame)
    expect(new TextDecoder().decode(encoded)).toBe(tunnelGoldenFixture.json_line)
    expect(decodeTunnelFrames(new TextEncoder().encode(tunnelGoldenFixture.json_line))).toEqual({
      frames: [tunnelGoldenFixture.frame],
      remainder: new Uint8Array(),
    })
  })

  it('keeps an incomplete UTF-8 frame as raw remainder', () => {
    const bytes = encodeTunnelFrame(frame(1))
    const split = bytes.length - 4
    const first = decodeTunnelFrames(bytes.slice(0, split))
    expect(first.frames).toEqual([])
    const merged = new Uint8Array(first.remainder.length + bytes.slice(split).length)
    merged.set(first.remainder)
    merged.set(bytes.slice(split), first.remainder.length)
    expect(decodeTunnelFrames(merged).frames).toEqual([frame(1)])
  })

  it('decodes packet coalescing and rejects sequence replay', () => {
    const decoder = new TunnelFrameDecoder()
    const first = encodeTunnelFrame(frame(1, 'a'))
    const second = encodeTunnelFrame(frame(2, 'b'))
    const merged = new Uint8Array(first.length + second.length)
    merged.set(first)
    merged.set(second, first.length)
    expect(decoder.push(merged).map((item) => item.sequence)).toEqual([1, 2])
    expect(decoder.sequence()).toBe(2)
    expect(() => decoder.push(encodeTunnelFrame(frame(2, 'replay')))).toThrow(/replay/)
  })

  it('allows a coalesced batch larger than the per-frame limit', () => {
    const first = frame(1, 'a'.repeat(2_100_000))
    const second = frame(2, 'b'.repeat(2_100_000))
    const firstBytes = encodeTunnelFrame(first)
    const secondBytes = encodeTunnelFrame(second)
    expect(firstBytes.length).toBeLessThan(4 * 1024 * 1024)
    expect(secondBytes.length).toBeLessThan(4 * 1024 * 1024)
    expect(firstBytes.length + secondBytes.length).toBeGreaterThan(4 * 1024 * 1024)
    const batch = new Uint8Array(firstBytes.length + secondBytes.length)
    batch.set(firstBytes)
    batch.set(secondBytes, firstBytes.length)
    expect(new TunnelFrameDecoder().push(batch)).toEqual([first, second])
  })

  it('rejects malformed protocol frames', () => {
    const decoder = new TunnelFrameDecoder()
    expect(() => decoder.push(new TextEncoder().encode('{"version":2}\n'))).toThrow(/无效/)
  })

  it('splits by UTF-8 bytes without breaking multi-byte code points', () => {
    const payload = '你'.repeat(Math.ceil(TUNNEL_LIMITS.chunkPayloadBytes / 3) + 11)
    const chunks = splitTunnelPayload(payload)
    expect(chunks.length).toBeGreaterThan(1)
    expect(chunks.join('')).toBe(payload)
    expect(chunks.every((chunk) => utf8ByteLength(chunk) <= TUNNEL_LIMITS.chunkPayloadBytes)).toBe(true)
    expect(utf8ByteLength(chunks[0])).toBeLessThanOrEqual(TUNNEL_LIMITS.chunkPayloadBytes)
    expect(chunks[0].endsWith('\ud800')).toBe(false)
    expect(chunks[0].endsWith('\udc00')).toBe(false)
  })

  it('applies Rust-compatible UTF-8 byte limits to envelope identifiers', () => {
    const valid = frame(1)
    valid.type = '你'.repeat(21) // 63 UTF-8 bytes, despite 21 JS code points.
    expect(() => encodeTunnelFrame(valid)).not.toThrow()

    const oversized = { ...valid, type: '你'.repeat(22) } // 66 UTF-8 bytes.
    expect(() => encodeTunnelFrame(oversized)).toThrow(/无效/)
  })

  it.each([
    ['type', { type: TUNNEL_FRAME_TYPES.event }],
    ['stream_id', { stream_id: TUNNEL_STREAMS.event }],
    ['request_id', { request_id: 'tampered-request' }],
    ['version', { version: 2 }],
  ])('rejects continuation envelope tampering in %s', (_field, change) => {
    const decoder = new TunnelFrameDecoder()
    const first: TunnelFrame = {
      ...frame(1, 'a'),
      request_id: 'request-1',
      message_id: 'message-1',
      chunk_index: 0,
      chunk_final: false,
    }
    decoder.push(encodeTunnelFrame(first))
    const continuation = {
      ...first,
      ...change,
      sequence: 2,
      payload: 'b',
      chunk_index: 1,
      chunk_final: true,
    }
    expect(() => decoder.push(rawFrameBytes(continuation))).toThrow()
  })

  it('rejects a reassembled message once the narrowed UTF-8 byte limit is exceeded', () => {
    expect(() => new TunnelFrameDecoder({
      maxMessageBytes: TUNNEL_LIMITS.messageBytes + 1,
    })).toThrow(/limit/)

    const decoder = new TunnelFrameDecoder({ maxMessageBytes: 6 })
    decoder.push(encodeTunnelFrame({
      ...frame(1, '你'),
      message_id: 'message-limit',
      chunk_index: 0,
      chunk_final: false,
    }))
    expect(() => decoder.push(encodeTunnelFrame({
      ...frame(2, '你好'),
      message_id: 'message-limit',
      chunk_index: 1,
      chunk_final: true,
    }))).toThrow(/过大/)
  })

  it('multiplexes RPC and HTTP over one tunnel wire', async () => {
    const wire = new FakeWire()
    const diagnostics: Array<Record<string, unknown>> = []
    const transport = new MultiplexedTunnelTransport(wire, (event) => diagnostics.push(event))
    const messages: TransportMessage[] = []
    transport.subscribe((message) => messages.push(message))
    await transport.connect()

    const rpcPromise = transport.request<{ status: string }>({
      kind: 'rpc',
      method: 'thread/resume',
    })
    await vi.waitFor(() => expect(wire.sent).toHaveLength(1))
    const outboundRpc = decodeTunnelFrames(wire.sent[0]).frames[0]
    expect(outboundRpc.type).toBe('rpc.data')
    expect(outboundRpc.request_id).toBe('remote-1')
    expect(diagnostics).toContainEqual(expect.objectContaining({
      component: 'mobile',
      event: 'rpc_sent',
      request_id: 'remote-1',
      method: 'thread/resume',
    }))
    wire.receive({
      version: 1,
      type: 'rpc.data',
      stream_id: 'rpc',
      sequence: 1,
      payload: JSON.stringify({ id: 'remote-1', result: { status: 'resumed' } }),
    })
    await expect(rpcPromise).resolves.toEqual({ status: 'resumed' })
    expect(diagnostics).toContainEqual(expect.objectContaining({
      component: 'mobile',
      event: 'rpc_received',
      request_id: 'remote-1',
    }))
    expect(messages.at(-1)).toMatchObject({ type: 'response', id: 'remote-1' })

    const responsePromise = transport.request({
      kind: 'http',
      method: 'POST',
      path: '/sessions',
      body: new TextEncoder().encode('request body'),
    })
    await vi.waitFor(() => expect(wire.sent).toHaveLength(2))
    const outboundHttp = decodeTunnelFrames(wire.sent[1]).frames[0]
    expect(outboundHttp.type).toBe('http.request')
    wire.receive({
      version: 1,
      type: 'http.response',
      stream_id: outboundHttp.stream_id,
      request_id: outboundHttp.request_id,
      sequence: 2,
      payload: JSON.stringify({
        status: 201,
        headers: { 'content-type': 'text/plain' },
        body: btoa('response body'),
      }),
    })
    const response = await responsePromise
    expect(response.status).toBe(201)
    expect(new TextDecoder().decode(response.body)).toBe('response body')
    await transport.close()
  })

  it('delivers business-neutral RPC events without routing them as responses', async () => {
    const wire = new FakeWire()
    const transport = new MultiplexedTunnelTransport(wire)
    const messages: TransportMessage[] = []
    transport.subscribe((message) => messages.push(message))
    await transport.connect()
    const bytes = encodeTunnelFrame({
      version: 1,
      type: 'rpc.data',
      stream_id: 'rpc',
      sequence: 1,
      payload: JSON.stringify({ method: 'thread/event', params: { value: 1 } }),
    })
    wire.receiveBytes(bytes.slice(0, 7))
    wire.receiveBytes(bytes.slice(7))
    expect(messages).toContainEqual(expect.objectContaining({
      type: 'notification',
      method: 'thread/event',
      params: { value: 1 },
    }))
  })

  it('carries binary, control and event messages without dropping their channels', async () => {
    const wire = new FakeWire()
    const transport = new MultiplexedTunnelTransport(wire)
    const messages: TransportMessage[] = []
    transport.subscribe((message) => messages.push(message))
    await transport.connect()

    transport.send({ type: 'binary', channel: 'binary', data: Uint8Array.from([1, 2, 3]) })
    transport.send({ type: 'control', channel: 'control', payload: { reason: 'reconnect' } })
    transport.send({ type: 'event', channel: 'event', payload: 'server hint' })
    const sent = wire.sent.flatMap((packet) => decodeTunnelFrames(packet).frames)
    expect(sent.map((item) => item.type)).toEqual(['binary.data', 'control.data', 'event.data'])

    wire.receive({
      version: 1,
      type: 'binary.data',
      stream_id: 'binary',
      sequence: 1,
      payload: btoa(String.fromCharCode(9, 8)),
    })
    wire.receive({
      version: 1,
      type: 'control.data',
      stream_id: 'control',
      sequence: 2,
      payload: JSON.stringify({ ok: true }),
    })
    wire.receive({
      version: 1,
      type: 'event.data',
      stream_id: 'event',
      sequence: 3,
      payload: 'event text',
    })
    expect(messages).toContainEqual(expect.objectContaining({
      type: 'binary',
      channel: 'binary',
      data: Uint8Array.from([9, 8]),
    }))
    expect(messages).toContainEqual(expect.objectContaining({
      type: 'control',
      channel: 'control',
      payload: { ok: true },
    }))
    expect(messages).toContainEqual(expect.objectContaining({
      type: 'event',
      channel: 'event',
      payload: 'event text',
    }))
    await transport.close()
  })

})
