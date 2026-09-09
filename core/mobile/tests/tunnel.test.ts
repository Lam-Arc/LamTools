import { describe, expect, it, vi } from 'vitest'
import {
  MultiplexedTunnelTransport,
  TunnelFrameDecoder,
  type TunnelWire,
  decodeTunnelFrames,
  encodeTunnelFrame,
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
    version: 1,
    type: 'rpc.data',
    stream_id: 'rpc',
    payload,
    sequence,
  }
}

describe('mobile tunnel framing', () => {
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
