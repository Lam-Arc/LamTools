import { describe, expect, it, vi } from 'vitest'
import { CoreAppServerClient } from '../src/appServer/client'
import { DirectHttpTransport, DirectTransport } from '../src/transport/directTransport'
import { TransportDisconnectedError } from '../src/transport/types'
import type {
  LamToolsTransport,
  TransportConnectionState,
  TransportMessage,
  TransportRequest,
} from '../src/transport/types'

class FakeRpcTransport implements LamToolsTransport {
  private messageListeners = new Set<(message: TransportMessage) => void>()
  private stateListeners = new Set<(state: TransportConnectionState) => void>()
  sent: string[] = []

  async connect(): Promise<void> {
    this.emitState('connecting')
    this.emitState('connected')
  }

  async request<TResponse = unknown>(request: TransportRequest): Promise<TResponse> {
    if (request.kind === 'http') {
      return { status: 200, headers: {}, body: new Uint8Array() } as TResponse
    }
    this.sent.push(JSON.stringify({ method: request.method, params: request.params || {} }))
    return { method: request.method } as TResponse
  }

  send(message: TransportMessage): void {
    this.sent.push(JSON.stringify(message.payload ?? message))
  }

  subscribe(listener: (message: TransportMessage) => void): () => void {
    this.messageListeners.add(listener)
    return () => this.messageListeners.delete(listener)
  }

  onState(listener: (state: TransportConnectionState) => void): () => void {
    this.stateListeners.add(listener)
    return () => this.stateListeners.delete(listener)
  }

  close(): void { this.emitState('disconnected') }

  emit(message: TransportMessage): void {
    for (const listener of this.messageListeners) listener(message)
  }

  getState(): TransportConnectionState { return 'connected' }

  private emitState(state: TransportConnectionState): void {
    for (const listener of this.stateListeners) listener(state)
  }
}

class ReconnectRaceTransport implements LamToolsTransport {
  private readonly stateListeners = new Set<(state: TransportConnectionState) => void>()
  readonly calls: string[] = []
  private initializeCount = 0
  private releaseInitialize: (() => void) | null = null

  async connect(): Promise<void> {
    this.emitState('connected')
  }

  async request<TResponse = unknown>(request: TransportRequest): Promise<TResponse> {
    if (request.kind === 'http') throw new Error('unexpected HTTP request')
    this.calls.push(request.method)
    if (request.method === 'initialize') {
      this.initializeCount += 1
      await new Promise<void>((resolve) => { this.releaseInitialize = resolve })
    }
    return { method: request.method } as TResponse
  }

  send(): void {}
  subscribe(): () => void { return () => {} }
  onState(listener: (state: TransportConnectionState) => void): () => void {
    this.stateListeners.add(listener)
    return () => this.stateListeners.delete(listener)
  }
  close(): void { this.emitState('disconnected') }
  getState(): TransportConnectionState { return 'connected' }
  release(): void { this.releaseInitialize?.() }
  get initializes(): number { return this.initializeCount }

  private emitState(state: TransportConnectionState): void {
    for (const listener of this.stateListeners) listener(state)
  }
}

class FakeSocket {
  readyState = 0
  readonly sent: unknown[] = []
  onopen: (() => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: (() => void) | null = null
  onclose: ((event: CloseEvent) => void) | null = null

  open(): void {
    this.readyState = 1
    this.onopen?.()
  }

  send(value: unknown): void { this.sent.push(value) }

  close(): void {
    if (this.readyState >= 2) return
    this.readyState = 3
    this.onclose?.({ code: 1000, reason: '', wasClean: true } as CloseEvent)
  }

  disconnect(code: number, reason: string, wasClean = false): void {
    if (this.readyState >= 2) return
    this.readyState = 3
    this.onclose?.({ code, reason, wasClean } as CloseEvent)
  }
}

describe('Core transport abstraction', () => {
  it('lets CoreAppServerClient use an injected RPC transport', async () => {
    const transport = new FakeRpcTransport()
    const states: string[] = []
    const client = new CoreAppServerClient({
      transport,
      clientInfo: { name: 'test' },
      onConnectionState: (state) => states.push(state),
    })

    await client.connect({ threadId: 'thread-1', lastSeenSeq: 4 })
    expect(states).toEqual(['connecting', 'open'])
    const initialize = JSON.parse(transport.sent[0]) as { method: string; params: Record<string, unknown> }
    expect(initialize.method).toBe('initialize')
    expect(initialize.params.threadId).toBe('thread-1')

    const response = await client.request('thread/read', { thread_id: 'thread-1' })
    expect(response.method).toBe('thread/read')
    client.close()
    expect(states.at(-1)).toBe('closed')
  })

  it('serializes reconnect RPCs behind one initialize handshake', async () => {
    const transport = new ReconnectRaceTransport()
    const client = new CoreAppServerClient({
      transport,
      clientInfo: { name: 'test' },
    })

    const reconnect = client.connect({ threadId: 'thread-1', lastSeenSeq: 4 })
    await vi.waitFor(() => expect(transport.calls).toEqual(['initialize']))
    const sync = client.request('sync.start')
    const turn = client.request('turn/start')
    await Promise.resolve()

    expect(transport.calls).toEqual(['initialize'])
    expect(transport.initializes).toBe(1)
    transport.release()
    await Promise.all([reconnect, sync, turn])
    expect(transport.calls).toEqual(['initialize', 'sync.start', 'turn/start'])
  })

  it('preserves HTTP bytes and merges default headers', async () => {
    const fetchImpl = vi.fn(async (_url: string, init: RequestInit) => ({
      status: 201,
      headers: { forEach(callback: (value: string, key: string) => void) { callback('application/octet-stream', 'content-type') } },
      async arrayBuffer() { return Uint8Array.from([1, 2, 3]).buffer },
    })) as unknown as typeof fetch
    const transport = new DirectHttpTransport('http://127.0.0.1:1234/api/core', { Authorization: 'Bearer test' }, fetchImpl)
    const response = await transport.request({ kind: 'http', method: 'POST', path: '/sessions', body: Uint8Array.from([9]) })
    expect(response.status).toBe(201)
    expect([...response.body]).toEqual([1, 2, 3])
    expect(fetchImpl).toHaveBeenCalledWith(
      'http://127.0.0.1:1234/api/core/sessions',
      expect.objectContaining({ headers: { Authorization: 'Bearer test' }, method: 'POST' }),
    )
  })

  it('does not publish connected when close races with a direct websocket handshake', async () => {
    const sockets: FakeSocket[] = []
    const transport = new DirectTransport({
      apiBase: 'http://127.0.0.1:5172/api/core',
      webSocketFactory: () => {
        const socket = new FakeSocket()
        sockets.push(socket)
        return socket as unknown as WebSocket
      },
    })
    const states: TransportConnectionState[] = []
    transport.onState((state) => states.push(state))
    const connectPromise = transport.connect()
    await vi.waitFor(() => expect(sockets).toHaveLength(1))

    await transport.close()
    await expect(connectPromise).rejects.toThrow(/closed during connect/)
    expect(transport.getState()).toBe('disconnected')
    expect(states).not.toContain('connected')
  })

  it('can connect again after the previous direct handshake was cancelled', async () => {
    const sockets: FakeSocket[] = []
    const transport = new DirectTransport({
      apiBase: 'http://127.0.0.1:5172/api/core',
      webSocketFactory: () => {
        const socket = new FakeSocket()
        sockets.push(socket)
        return socket as unknown as WebSocket
      },
    })
    const firstConnect = transport.connect()
    await vi.waitFor(() => expect(sockets).toHaveLength(1))
    await transport.close()
    await expect(firstConnect).rejects.toThrow()

    const secondConnect = transport.connect()
    await vi.waitFor(() => expect(sockets).toHaveLength(2))
    sockets[1].open()
    await expect(secondConnect).resolves.toBeUndefined()
    expect(transport.getState()).toBe('connected')
    await transport.close()
  })

  it('retains unexpected websocket close diagnostics on pending RPC failures', async () => {
    const sockets: FakeSocket[] = []
    const warning = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    const transport = new DirectTransport({
      apiBase: 'http://127.0.0.1:5172/api/core',
      webSocketFactory: () => {
        const socket = new FakeSocket()
        sockets.push(socket)
        return socket as unknown as WebSocket
      },
    })
    const connected = transport.connect()
    sockets[0].open()
    await connected

    const pending = transport.request({ method: 'thread/read' })
    await vi.waitFor(() => expect(sockets[0].sent).toHaveLength(1))
    sockets[0].disconnect(1013, 'Event stream overflow; reconnect to resume.')

    const error = await pending.catch((value: unknown) => value)
    expect(error).toBeInstanceOf(TransportDisconnectedError)
    expect(error).toMatchObject({
      name: 'TransportDisconnectedError',
      code: 1013,
      reason: 'Event stream overflow; reconnect to resume.',
      wasClean: false,
    })
    expect(error).toHaveProperty('message', expect.stringMatching(/code=1013.*Event stream overflow/))
    expect(warning).toHaveBeenCalledWith(
      '[LamTools transport] unexpected WebSocket close',
      expect.objectContaining({ code: 1013, wasClean: false }),
    )
    warning.mockRestore()
  })
})
