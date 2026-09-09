import type { CoreAppEvent, CoreAppSnapshot } from './protocol'
import type { LamToolsTransport, TransportConnectionState, TransportMessage } from '../transport'

export interface JsonRpcRequest {
  id?: number | string
  method: string
  params?: Record<string, unknown>
}

export interface JsonRpcResponse {
  id?: number | string
  result?: Record<string, unknown>
  error?: { code: number; message: string; data?: unknown }
}

export interface JsonRpcClientResponse {
  id: number | string
  result: Record<string, unknown>
}

export interface CoreAppServerClientOptions {
  transport: LamToolsTransport
  clientInfo: { name: string; title?: string; version?: string }
  onEvent?: (event: CoreAppEvent) => void
  onSnapshot?: (snapshot: CoreAppSnapshot) => void
  onConnectionState?: (state: 'connecting' | 'open' | 'closed' | 'error') => void
}

export class CoreAppServerClosedError extends Error {
  constructor() {
    super('Core App Server transport closed')
    this.name = 'AbortError'
  }
}

export class CoreAppServerClient {
  private readonly transport: LamToolsTransport
  private removeMessageListener: (() => void) | null = null
  private removeStateListener: (() => void) | null = null
  private readonly serverRequestIds = new Map<string, number | string>()
  private closed = false
  private initialized = false
  private connectionGeneration = 0
  private connectPromise: Promise<void> | null = null
  private lastConnectParams: { threadId?: string; lastSeenSeq?: number } = {}
  private lastNotifiedConnectionState: 'connecting' | 'open' | 'closed' | 'error' | undefined

  constructor(private readonly options: CoreAppServerClientOptions) {
    this.transport = options.transport
  }

  async connect(params: { threadId?: string; lastSeenSeq?: number } = {}): Promise<void> {
    this.lastConnectParams = params
    if (this.connectPromise) return await this.connectPromise

    this.closed = false
    this.installListeners()
    const generation = ++this.connectionGeneration
    const operation = (async () => {
      await this.transport.connect()
      if (this.closed || this.connectionGeneration !== generation) {
        throw new CoreAppServerClosedError()
      }
      if (this.initialized) return

      await this.requestRaw('initialize', {
        clientInfo: this.options.clientInfo,
        threadId: params.threadId,
        lastSeenSeq: params.lastSeenSeq,
      })
      if (this.closed || this.connectionGeneration !== generation) {
        throw new CoreAppServerClosedError()
      }
      this.initialized = true
      this.notifyConnectionState('open')
      this.notify('initialized', {})
    })()
    const pending = operation.finally(() => {
      if (this.connectPromise === pending) this.connectPromise = null
    })
    this.connectPromise = pending
    return await pending
  }

  close(): void {
    const wasClosed = this.closed
    this.closed = true
    this.initialized = false
    this.connectionGeneration += 1
    this.connectPromise = null
    this.removeMessageListener?.()
    this.removeMessageListener = null
    this.removeStateListener?.()
    this.removeStateListener = null
    void this.transport.close()
    this.serverRequestIds.clear()
    if (!wasClosed) this.notifyConnectionState('closed')
  }

  async request(method: string, params: Record<string, unknown> = {}, timeoutMs = 30_000): Promise<Record<string, unknown>> {
    if (this.closed) throw new CoreAppServerClosedError()
    // A transport can publish `connected` before this protocol client has
    // completed initialize. Every business RPC shares the current initialize
    // promise so reconnect callbacks cannot overtake the handshake.
    if (method !== 'initialize' && !this.initialized) {
      await this.connect(this.lastConnectParams)
      if (this.closed || !this.initialized) throw new CoreAppServerClosedError()
    }
    return await this.requestRaw(method, params, timeoutMs)
  }

  private async requestRaw(method: string, params: Record<string, unknown>, timeoutMs = 30_000): Promise<Record<string, unknown>> {
    const result = await this.transport.request<Record<string, unknown>>({
      kind: 'rpc',
      method,
      params,
      timeoutMs,
    })
    return result && typeof result === 'object' ? result : {}
  }

  notify(method: string, params: Record<string, unknown> = {}): void {
    this.transport.send({ type: 'notification', channel: 'rpc', method, params })
  }

  respondServerRequest(requestId: string, result: Record<string, unknown>): boolean {
    const rpcId = this.serverRequestIds.get(requestId)
    if (rpcId === undefined) return false
    this.serverRequestIds.delete(requestId)
    this.transport.send({ type: 'response', channel: 'rpc', id: rpcId, result })
    return true
  }

  private installListeners(): void {
    this.removeMessageListener?.()
    this.removeStateListener?.()
    this.removeMessageListener = this.transport.subscribe((message) => this.handleMessage(message))

    // Some transports invoke onState synchronously while registering; that is
    // only an initial snapshot, not a transition. Track registration explicitly
    // so a transport without an immediate callback still reports its first real
    // connecting transition.
    let registering = true
    this.removeStateListener = this.transport.onState((state) => {
      if (registering) return
      const normalized = mapTransportState(state)
      if (normalized === 'closed' || normalized === 'error') this.initialized = false
      // Socket-open is only a transport state. The App Server connection is
      // ready after initialize succeeds below in connect().
      this.notifyConnectionState(normalized === 'open' && !this.initialized ? 'connecting' : normalized)
    })
    registering = false
    this.lastNotifiedConnectionState = undefined
    this.notifyConnectionState(this.initialized ? 'open' : 'connecting')
  }

  private notifyConnectionState(state: 'connecting' | 'open' | 'closed' | 'error'): void {
    if (this.lastNotifiedConnectionState === state) return
    this.lastNotifiedConnectionState = state
    this.options.onConnectionState?.(state)
  }

  private handleMessage(message: TransportMessage): void {
    if (message.channel !== 'rpc') return
    if (message.type === 'response') return

    const params = message.params
    if (message.type === 'request' && message.id !== undefined && params) {
      const event = params as unknown as CoreAppEvent
      const requestId = typeof event.payload?.request_id === 'string'
        ? event.payload.request_id
        : String(message.id)
      this.serverRequestIds.set(requestId, message.id)
      this.options.onEvent?.(event)
      return
    }

    if ((message.type === 'notification' || message.type === 'event') && params) {
      if (message.method === 'thread/snapshot') {
        this.options.onSnapshot?.(params as unknown as CoreAppSnapshot)
        return
      }
      this.options.onEvent?.(params as unknown as CoreAppEvent)
    }
  }
}

function mapTransportState(state: TransportConnectionState): 'connecting' | 'open' | 'closed' | 'error' {
  if (state === 'connected') return 'open'
  if (state === 'failed') return 'error'
  if (state === 'disconnected') return 'closed'
  return 'connecting'
}
