import type { CoreAppEvent, CoreAppSnapshot } from '@/appServer/protocol.ts'
import type { LamToolsTransport, TransportConnectionState, TransportMessage } from '@/transport/index.ts'
import { TransportRequestTimeoutError, TransportRpcError } from '@/transport/index.ts'

export class CoreRequestAcceptanceUnknownError extends Error {
  readonly code = 'ACCEPTANCE_UNKNOWN'
  constructor(readonly clientMessageId: string, readonly cause: unknown) {
    super('Message acceptance could not be confirmed. Retry the same submission to check its status.')
    this.name = 'CoreRequestAcceptanceUnknownError'
  }
}

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

/** Persisted-change notification from the sync journal (`sync/change`). */
export interface CoreSyncChangeNotification {
  change_id?: string
  thread_id?: string
  entity_id?: string
  entity_type?: string
  operation?: string
  revision?: number
  snapshot_revision?: number
  seq?: number
  payload?: unknown
  entity?: unknown
}

/**
 * Gap notification from the server's reliable lane (`thread/gap`): the lossy
 * outbound lane dropped frames for a thread, so the client must resynchronize
 * from its own revision instead of waiting for the next full snapshot. Like
 * `sync/change` it is a notification whose params carry the report (thread id,
 * reason, dropped count), not an event envelope.
 */
export interface CoreThreadGapNotification {
  thread_id?: string
  reason?: string
  dropped?: number
}

export interface CoreAppServerClientOptions {
  transport: LamToolsTransport
  clientInfo: { name: string; title?: string; version?: string }
  onEvent?: (event: CoreAppEvent) => void
  onSnapshot?: (snapshot: CoreAppSnapshot) => void
  onSyncChange?: (change: CoreSyncChangeNotification) => void
  onConnectionState?: (state: 'connecting' | 'open' | 'closed' | 'error') => void
}

export class CoreAppServerClosedError extends Error {
  constructor() {
    super('Core App Server transport closed')
    this.name = 'AbortError'
  }
}

/**
 * The server refused a business call because this connection never completed
 * the initialize handshake, and one automatic re-handshake did not fix it.
 * user:"界面出现 Connection is not initialized"+(不要把英文协议原句丢给用户：
 * 面向用户的文案只说清「连接正在重连、稍后再试」，技术原因留在 code 里)。
 */
export class CoreAppServerNotReadyError extends Error {
  readonly code = 'NOT_READY'
  constructor() {
    super('与主程序的连接还没就绪，正在重新连接，请稍后再试。')
    this.name = 'CoreAppServerNotReadyError'
  }
}

export class CoreAppServerClient {
  capabilities: Record<string, unknown> = {}
  private readonly transport: LamToolsTransport
  private removeMessageListener: (() => void) | null = null
  private removeStateListener: (() => void) | null = null
  private readonly serverRequestIds = new Map<string, number | string>()
  private readonly acceptanceWaiters = new Set<{
    method: string; threadId: string; clientId: string
    resolve(value: Record<string, unknown>): void
  }>()
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

      const initialized = await this.requestRaw('initialize', {
        clientInfo: this.options.clientInfo,
        threadId: params.threadId,
        lastSeenSeq: params.lastSeenSeq,
      })
      if (this.closed || this.connectionGeneration !== generation) {
        throw new CoreAppServerClosedError()
      }
      this.capabilities = initialized.capabilities && typeof initialized.capabilities === 'object'
        ? initialized.capabilities as Record<string, unknown> : {}
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
    await this.ensureHandshake(method)
    try {
      return await this.performRequest(method, params, timeoutMs)
    } catch (error) {
      // user:"界面出现 Connection is not initialized"+(服务器这条可重试错误是唯一的
      // 自愈信号：说明当前 socket 换过、但客户端还认为握过手。把标记重置后在当前连接上
      // 补一次 initialize，再重试一次；否则按秒轮询会永远静默地撞在同一个拒绝上。)
      if (method === 'initialize' || !isNotInitializedError(error)) throw error
      this.initialized = false
      await this.ensureHandshake(method)
      try {
        return await this.performRequest(method, params, timeoutMs)
      } catch (retryError) {
        if (!isNotInitializedError(retryError)) throw retryError
        throw new CoreAppServerNotReadyError()
      }
    }
  }

  private async ensureHandshake(method: string): Promise<void> {
    if (this.closed) throw new CoreAppServerClosedError()
    if (method === 'initialize') return
    // A transport can publish `connected` before this protocol client has
    // completed initialize. Every business RPC shares the current initialize
    // promise so reconnect callbacks cannot overtake the handshake.
    if (this.initialized) return
    await this.connect(this.lastConnectParams)
    if (this.closed || !this.initialized) throw new CoreAppServerClosedError()
  }

  private async performRequest(method: string, params: Record<string, unknown>, timeoutMs: number): Promise<Record<string, unknown>> {
    const clientId = String(params.client_message_id || '')
    if (!clientId || (method !== 'turn/start' && method !== 'turn/resume')) {
      return await this.requestRaw(method, params, timeoutMs)
    }
    // A committed, correlated acceptance event is as authoritative as the RPC
    // reply. Agent completion is deliberately not part of this acknowledgement.
    const abort = new AbortController()
    let resolve!: (value: Record<string, unknown>) => void
    const accepted = new Promise<Record<string, unknown>>((done) => { resolve = done })
    const waiter = { method, threadId: String(params.thread_id || ''), clientId, resolve }
    this.acceptanceWaiters.add(waiter)
    const acknowledgement = this.requestRaw(method, params, timeoutMs, abort.signal).catch(async (error) => {
      if (!(error instanceof TransportRequestTimeoutError)) throw error
      // Reconcile once using the SAME idempotency key, not a new submission.
      // Keep the original deadline; this separate bounded lookup can recover
      // a lost reply after durable acceptance. No execution wait or timeout bump.
      try {
        return await this.requestRaw(method, params, 5_000, abort.signal)
      } catch (recoveryError) {
        throw new CoreRequestAcceptanceUnknownError(clientId, recoveryError)
      }
    })
    try {
      return await Promise.race([acknowledgement, accepted])
    } finally {
      this.acceptanceWaiters.delete(waiter)
      abort.abort() // removes local pending RPC state; does not cancel Core work
    }
  }

  private async requestRaw(method: string, params: Record<string, unknown>, timeoutMs = 30_000, signal?: AbortSignal): Promise<Record<string, unknown>> {
    const result = await this.transport.request<Record<string, unknown>>({
      kind: 'rpc',
      method,
      params,
      timeoutMs,
      signal,
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
      if (message.method === 'sync/change') {
        this.options.onSyncChange?.(params as unknown as CoreSyncChangeNotification)
        return
      }
      const event = asEventEnvelope(message.method, params)
      for (const waiter of this.acceptanceWaiters) {
        const expected = waiter.method === 'turn/start' ? 'turn/accepted' : 'turn/started'
        if (event.method === expected && event.thread_id === waiter.threadId
            && event.client_message_id === waiter.clientId) {
          waiter.resolve({ events: [event], ...(waiter.method === 'turn/resume' ? { turn_id: event.turn_id } : {}) })
        }
      }
      this.options.onEvent?.(event)
    }
  }
}

/**
 * Event notifications carry their own envelope (including its `method`) as the
 * params, but a control report such as `thread/gap` does not: its payload is
 * the report itself and the method lives only on the notification. Attach it so
 * consumers dispatch by method instead of mistaking the report for an event
 * envelope (and silently dropping it).
 */
function asEventEnvelope(method: string | undefined, params: Record<string, unknown>): CoreAppEvent {
  if (typeof params.method === 'string') return params as unknown as CoreAppEvent
  return { ...params, method: method ?? '' } as unknown as CoreAppEvent
}

// Dedicated server code for "business frame before initialize".
const NOT_INITIALIZED_CODE = -32002

/**
 * Recognize the pre-handshake rejection. Newer Core builds send the dedicated
 * code plus `data.reason`; older builds reused INVALID_REQUEST for the same
 * meaning, so the reason string is the fallback.
 */
function isNotInitializedError(error: unknown): boolean {
  if (!(error instanceof TransportRpcError)) return false
  if (error.code === NOT_INITIALIZED_CODE) return true
  const data = error.data
  return Boolean(
    data
    && typeof data === 'object'
    && (data as { reason?: unknown }).reason === 'not_initialized',
  )
}

function mapTransportState(state: TransportConnectionState): 'connecting' | 'open' | 'closed' | 'error' {
  if (state === 'connected') return 'open'
  if (state === 'failed') return 'error'
  if (state === 'disconnected') return 'closed'
  return 'connecting'
}
