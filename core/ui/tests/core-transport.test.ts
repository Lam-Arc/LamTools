import { describe, expect, it, vi } from 'vitest'
import { CoreAppServerClient, CoreRequestAcceptanceUnknownError } from '../src/appServer/client'
import { DirectHttpTransport, DirectTransport } from '../src/transport/directTransport'
import { TransportDisconnectedError, TransportRpcError } from '../src/transport/types'
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

// user:“全修”+(已经发出的请求被断线中断，标记待确认，随后按原编号只查回执)。
it('classifies a socket disconnect as unknown acceptance without retransmitting', async () => {
  const transport = new FakeRpcTransport()
  const write = vi.spyOn(transport, 'request').mockImplementation(async (request) => {
    if (request.kind === 'rpc' && request.method === 'turn/start') throw new TransportDisconnectedError()
    return {} as never
  })
  const client = new CoreAppServerClient({ transport, clientInfo: { name: 'test' } })
  try {
    await expect(client.request('turn/start', { thread_id: 'source', client_message_id: 'send-1' }))
      .rejects.toBeInstanceOf(CoreRequestAcceptanceUnknownError)
    expect(write.mock.calls.filter(([req]) => req.kind === 'rpc' && req.method === 'turn/start')).toHaveLength(1)
  } finally { client.close() }
})

it('keeps a definitive busy rejection available for the queue fallback', async () => {
  const transport = new FakeRpcTransport()
  const busy = new TransportRpcError(undefined, 'session has an active turn')
  vi.spyOn(transport, 'request').mockImplementation(async (request) => {
    if (request.kind === 'rpc' && request.method === 'turn/start') throw busy
    return {} as never
  })
  const client = new CoreAppServerClient({ transport, clientInfo: { name: 'test' } })
  try {
    await expect(client.request('turn/start', { thread_id: 'source', client_message_id: 'send-2' })).rejects.toBe(busy)
  } finally { client.close() }
})

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

class NotInitializedTransport implements LamToolsTransport {
  private messageListeners = new Set<(message: TransportMessage) => void>()
  private stateListeners = new Set<(state: TransportConnectionState) => void>()
  calls: string[] = []
  handshakes = 0
  rejectNextBusiness = true
  rejectEveryBusiness = false

  async connect(): Promise<void> {
    this.emitState('connecting')
    this.emitState('connected')
  }

  async close(): Promise<void> {
    this.emitState('disconnected')
  }

  async request<TResponse = unknown>(request: TransportRequest): Promise<TResponse> {
    this.calls.push(request.method)
    if (request.method === 'initialize') {
      this.handshakes += 1
      return {} as TResponse
    }
    if (this.rejectEveryBusiness || this.rejectNextBusiness) {
      this.rejectNextBusiness = false
      throw new TransportRpcError(-32002, 'Connection is not initialized', {
        reason: 'not_initialized',
        retriable: true,
      })
    }
    return { method: request.method } as TResponse
  }

  send(_message: TransportMessage): void {}

  subscribe(listener: (message: TransportMessage) => void): () => void {
    this.messageListeners.add(listener)
    return () => this.messageListeners.delete(listener)
  }

  onState(listener: (state: TransportConnectionState) => void): () => void {
    this.stateListeners.add(listener)
    return () => this.stateListeners.delete(listener)
  }

  getState(): TransportConnectionState {
    return 'connected'
  }

  private emitState(state: TransportConnectionState): void {
    for (const listener of this.stateListeners) listener(state)
  }
}

describe('Core pre-handshake recovery', () => {
  // user:"界面出现 Connection is not initialized"+(服务器说连接还没握手时，客户端必须
  // 在同一条连接上补一次 initialize 并重试这一帧，而不是把这条拒绝当成失败丢掉)。
  it('re-handshakes and retries once when the server reports not_initialized', async () => {
    const transport = new NotInitializedTransport()
    const client = new CoreAppServerClient({ transport, clientInfo: { name: 'test' } })

    const result = await client.request('goal.list', { thread_id: 'thread-1' })

    expect(result).toEqual({ method: 'goal.list' })
    expect(transport.handshakes).toBe(2)
    expect(transport.calls).toEqual(['initialize', 'goal.list', 'initialize', 'goal.list'])
    client.close()
  })

  // user:"界面出现 Connection is not initialized"+(重握手也失败时，用户看到的是
  // 中文提示，而不是协议英文原句；技术细节留在 error.code 里)。
  it('surfaces a readable message instead of the raw protocol text', async () => {
    const transport = new NotInitializedTransport()
    transport.rejectEveryBusiness = true
    const client = new CoreAppServerClient({ transport, clientInfo: { name: 'test' } })

    await expect(client.request('goal.list', {})).rejects.toMatchObject({ code: 'NOT_READY' })
    await expect(client.request('goal.list', {})).rejects.toThrow('与主程序的连接还没就绪')
    await expect(client.request('goal.list', {})).rejects.not.toThrow('Connection is not initialized')
    client.close()
  })
})

// user:“标注后无法引用”+
// (预览器先用 `<img>` 以 no-cors 缓存了同一个地址，之后 CORS `fetch` 同一 URL 会被浏览器
//  判成“没有 ACAO”；读字节必须显式绕过缓存，否则合成标注图这一步永远失败。)
describe('preview byte reads bypass the http cache', () => {
  it('sends cache: no-store through the direct http transport', async () => {
    const calls: { url: string; init: RequestInit | undefined }[] = []
    const fakeFetch = vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init })
      return new Response(new Uint8Array([1, 2, 3]), { status: 200 })
    })
    const http = new DirectHttpTransport('http://127.0.0.1:9/api/core', {}, fakeFetch as unknown as typeof fetch)
    await http.request({ kind: 'http', method: 'GET', path: '/files/read-reference?path=a.png', cache: 'no-store' })
    expect(calls).toHaveLength(1)
    expect(calls[0]?.init?.cache).toBe('no-store')
  })

  it('keeps the preview transport asking for no-store on every read', async () => {
    const transport = {
      request: async (request: Record<string, unknown>) => {
        expect(request.cache).toBe('no-store')
        return { status: 200, headers: {}, body: new Uint8Array([1]) }
      },
    } as unknown as LamToolsTransport
    const { createPreviewTransport } = await import('../src/preview/transport')
    const bytes = await createPreviewTransport({ transport, origin: 'http://127.0.0.1:9' }).read('/files/read-reference?path=a.png')
    expect(Array.from(bytes)).toEqual([1])
  })
})
