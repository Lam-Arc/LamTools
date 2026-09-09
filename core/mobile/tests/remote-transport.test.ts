import { describe, expect, it, vi } from 'vitest'
import type { TransportConnectionState, TransportMessage } from '@lamtools/ui/transport'
import {
  decodeTunnelFrames,
  encodeTunnelFrame,
  RemoteTransport,
  type TunnelFrame,
  type TunnelWire,
} from '../src/connection'

class FakeWire implements TunnelWire {
  readonly sent: Uint8Array[] = []
  private readonly dataListeners = new Set<(data: Uint8Array) => void>()
  private readonly stateListeners = new Set<(state: TransportConnectionState) => void>()
  private state: TransportConnectionState = 'disconnected'

  async connect(): Promise<void> {
    this.setState('connected')
  }

  send(data: Uint8Array): void {
    this.sent.push(data)
  }

  onData(listener: (data: Uint8Array) => void): () => void {
    this.dataListeners.add(listener)
    return () => this.dataListeners.delete(listener)
  }

  onState(listener: (state: TransportConnectionState) => void): () => void {
    this.stateListeners.add(listener)
    listener(this.state)
    return () => this.stateListeners.delete(listener)
  }

  close(): void {
    this.setState('disconnected')
  }

  receive(frame: TunnelFrame): void {
    const encoded = encodeTunnelFrame(frame)
    for (const listener of this.dataListeners) listener(encoded)
  }

  drop(): void {
    this.setState('disconnected')
  }

  private setState(state: TransportConnectionState): void {
    this.state = state
    for (const listener of this.stateListeners) listener(state)
  }
}

class ControlledWire extends FakeWire {
  private connectResolver: (() => void) | null = null

  override connect(): Promise<void> {
    return new Promise((resolve) => {
      this.connectResolver = () => {
        this.connectResolver = null
        super.connect()
        resolve()
      }
    })
  }

  isConnectPending(): boolean { return this.connectResolver !== null }
  releaseConnect(): void { this.connectResolver?.() }
}

describe('RemoteTransport', () => {
  it('keeps the facade stable while routing RPC, events, disconnect and reconnect', async () => {
    const wires: FakeWire[] = []
    const transport = new RemoteTransport({
      createWire: () => {
        const wire = new FakeWire()
        wires.push(wire)
        return wire
      },
    })
    const states: TransportConnectionState[] = []
    const messages: TransportMessage[] = []
    transport.onState((state) => states.push(state))
    transport.subscribe((message) => messages.push(message))

    await transport.connect()
    expect(transport.getState()).toBe('connected')
    expect(states).toContain('connecting')
    expect(states).toContain('connected')

    const responsePromise = transport.request<{ ok: boolean }>({
      kind: 'rpc',
      method: 'thread/resume',
      params: { thread_id: 'thread-1' },
    })
    await vi.waitFor(() => expect(wires[0].sent).toHaveLength(1))
    const request = decodeTunnelFrames(wires[0].sent[0]).frames[0]
    expect(JSON.parse(request.payload || '{}')).toMatchObject({
      id: 'remote-1',
      method: 'thread/resume',
    })
    wires[0].receive({
      version: 1,
      type: 'rpc.data',
      stream_id: 'rpc',
      sequence: 1,
      payload: JSON.stringify({ id: 'remote-1', result: { ok: true } }),
    })
    await expect(responsePromise).resolves.toEqual({ ok: true })

    wires[0].receive({
      version: 1,
      type: 'rpc.data',
      stream_id: 'rpc',
      sequence: 2,
      payload: JSON.stringify({ method: 'thread/event', params: { value: 1 } }),
    })
    expect(messages).toContainEqual(expect.objectContaining({
      type: 'notification',
      method: 'thread/event',
    }))

    wires[0].drop()
    expect(transport.getState()).toBe('disconnected')
    await transport.connect()
    expect(wires).toHaveLength(2)
    expect(transport.getState()).toBe('connected')
    expect(states).toContain('reconnecting')

    await transport.close()
    expect(transport.getState()).toBe('disconnected')
  })

  it('does not resurrect a transport when close races with wire creation', async () => {
    let resolveWire!: (wire: FakeWire) => void
    const wirePromise = new Promise<FakeWire>((resolve) => { resolveWire = resolve })
    const transport = new RemoteTransport({ createWire: () => wirePromise })
    const connectPromise = transport.connect()
    await vi.waitFor(() => expect(transport.getState()).toBe('connecting'))

    await transport.close()
    const wire = new FakeWire()
    const closeSpy = vi.spyOn(wire, 'close')
    resolveWire(wire)

    await expect(connectPromise).rejects.toThrow('取消')
    expect(closeSpy).toHaveBeenCalledOnce()
    expect(transport.getState()).toBe('disconnected')
  })

  it('does not publish connected after close races with the inner wire handshake', async () => {
    const wire = new ControlledWire()
    const transport = new RemoteTransport({ createWire: () => wire })
    const states: TransportConnectionState[] = []
    transport.onState((state) => states.push(state))
    const connectPromise = transport.connect()
    await vi.waitFor(() => expect(wire.isConnectPending()).toBe(true))

    await transport.close()
    wire.releaseConnect()

    await expect(connectPromise).rejects.toThrow('取消')
    expect(transport.getState()).toBe('disconnected')
    expect(states).not.toContain('connected')
  })
})
