import type {
  LamToolsTransport,
  TransportConnectionState,
  TransportHttpRequest,
  TransportHttpResponse,
  TransportMessage,
  TransportRequest,
} from './types'
import { TransportDisconnectedError, TransportRpcError } from './types'

type FetchLike = typeof fetch

export interface DirectTransportOptions {
  apiBase: string
  wsUrl?: string
  token?: string
  fetchImpl?: FetchLike
  webSocketFactory?: (url: string) => WebSocket
}

/**
 * The only HTTP implementation used by the shared UI. It intentionally
 * returns bytes so exports, previews and attachment uploads share the same
 * request boundary as JSON endpoints.
 */
export class DirectHttpTransport {
  constructor(
    private readonly baseUrl: string,
    private readonly defaultHeaders: Record<string, string> = {},
    private readonly fetchImpl: FetchLike = globalThis.fetch.bind(globalThis),
  ) {}

  async request(input: TransportHttpRequest): Promise<TransportHttpResponse> {
    if (input.signal?.aborted) throw abortError()
    const controller = new AbortController()
    let timedOut = false
    let externallyAborted = false
    let rejectExternalAbort: ((reason?: unknown) => void) | null = null
    const externalAbortPromise = new Promise<never>((_, reject) => {
      rejectExternalAbort = reject
    })
    const onAbort = () => {
      externallyAborted = true
      controller.abort()
      rejectExternalAbort?.(abortError())
    }
    input.signal?.addEventListener('abort', onAbort, { once: true })
    const timeoutMs = input.timeoutMs ?? 30_000
    let timeout: ReturnType<typeof setTimeout> | undefined
    const timeoutPromise = new Promise<never>((_, reject) => {
      timeout = setTimeout(() => {
        timedOut = true
        controller.abort()
        reject(new Error(`LamTools HTTP request timed out: ${input.method} ${input.path} (${timeoutMs}ms)`))
      }, Math.max(0, timeoutMs))
    })

    try {
      const requestPromise = this.fetchImpl(joinHttpPath(this.baseUrl, input.path), {
        method: input.method,
        headers: { ...this.defaultHeaders, ...(input.headers || {}) },
        body: input.body as unknown as BodyInit | undefined,
        signal: controller.signal,
      }).then(async (response) => {
        const buffer = await response.arrayBuffer()
        const headers: Record<string, string> = {}
        response.headers.forEach((value, key) => { headers[key] = value })
        return { status: response.status, headers, body: new Uint8Array(buffer) }
      })
      return await Promise.race([requestPromise, timeoutPromise, externalAbortPromise])
    } catch (error) {
      if (timedOut) {
        throw new Error(`LamTools HTTP request timed out: ${input.method} ${input.path} (${timeoutMs}ms)`)
      }
      if (externallyAborted || input.signal?.aborted) throw abortError()
      throw error
    } finally {
      if (timeout !== undefined) clearTimeout(timeout)
      input.signal?.removeEventListener('abort', onAbort)
    }
  }
}

function abortError(): DOMException {
  return new DOMException('Aborted', 'AbortError')
}

/**
 * Direct implementation of the connection-neutral LamTools transport.
 * JSON-RPC and HTTP share one public object so Workbench never needs to know
 * which protocol is being used for a particular backend operation.
 */
export class DirectTransport implements LamToolsTransport {
  readonly http: DirectHttpTransport
  private socket: WebSocket | null = null
  private state: TransportConnectionState = 'disconnected'
  private connectPromise: Promise<void> | null = null
  private connectReject: ((error: Error) => void) | null = null
  private socketGeneration = 0
  private nextRequestId = 1
  private readonly subscribers = new Set<(message: TransportMessage) => void>()
  private readonly stateSubscribers = new Set<(state: TransportConnectionState) => void>()
  private readonly pending = new Map<string, {
    resolve: (value: unknown) => void
    reject: (error: Error) => void
    cleanup: () => void
  }>()
  private readonly createSocket: (url: string) => WebSocket
  private readonly wsUrl: string

  constructor(private readonly options: DirectTransportOptions) {
    this.wsUrl = options.wsUrl || defaultAppServerWsUrl(options.apiBase, options.token)
    this.http = new DirectHttpTransport(
      options.apiBase,
      options.token ? { Authorization: `Bearer ${options.token}` } : {},
      options.fetchImpl,
    )
    this.createSocket = options.webSocketFactory || ((url) => new WebSocket(url))
  }

  async connect(): Promise<void> {
    if (this.socket?.readyState === WebSocket.OPEN && this.state === 'connected') return
    if (this.connectPromise) return await this.connectPromise

    const generation = ++this.socketGeneration
    this.setState(this.state === 'disconnected' ? 'connecting' : 'reconnecting')
    const rawPromise = new Promise<void>((resolve, reject) => {
      let settled = false
      const socket = this.createSocket(this.wsUrl)
      this.socket = socket
      this.connectReject = reject
      const isCurrent = () => this.socket === socket && this.socketGeneration === generation
      socket.onopen = () => {
        if (!isCurrent()) {
          socket.close()
          if (!settled) {
            settled = true
            reject(new Error('LamTools direct transport connection was superseded'))
          }
          return
        }
        settled = true
        this.connectReject = null
        this.setState('connected')
        resolve()
      }
      socket.onmessage = (event) => {
        if (isCurrent()) void this.handleSocketValue(event.data)
      }
      socket.onerror = () => {
        if (!isCurrent()) return
        this.setState('failed')
        if (!settled) {
          settled = true
          this.connectReject = null
          reject(new Error('LamTools direct transport connection failed'))
        }
      }
      socket.onclose = (event) => {
        if (!isCurrent()) {
          if (!settled) {
            settled = true
            reject(new Error('LamTools direct transport connection was superseded'))
          }
          return
        }
        this.socket = null
        this.connectPromise = null
        this.connectReject = null
        const disconnectError = new TransportDisconnectedError({
          code: Number.isFinite(event?.code) ? event.code : undefined,
          reason: event?.reason || '',
          wasClean: typeof event?.wasClean === 'boolean' ? event.wasClean : undefined,
        })
        // A short reconnect is intentionally silent in the product UI, but
        // keep the browser diagnostic structured so a persistent failure still
        // has an actionable close code/reason instead of one generic string.
        console.warn('[LamTools transport] unexpected WebSocket close', {
          code: disconnectError.code,
          reason: disconnectError.reason,
          wasClean: disconnectError.wasClean,
        })
        this.rejectPending(disconnectError)
        this.setState('disconnected')
        if (!settled) {
          settled = true
          reject(new Error('LamTools direct transport closed during connect'))
        }
      }
    })
    const promise = rawPromise.finally(() => {
      if (this.connectPromise === promise) {
        this.connectPromise = null
        this.connectReject = null
      }
    })
    this.connectPromise = promise
    return await promise
  }

  async close(): Promise<void> {
    this.socketGeneration += 1
    const rejectConnect = this.connectReject
    this.connectReject = null
    this.connectPromise = null
    const socket = this.socket
    this.socket = null
    this.rejectPending(new Error('LamTools transport closed'))
    rejectConnect?.(new Error('LamTools transport closed during connect'))
    if (socket && socket.readyState < WebSocket.CLOSING) socket.close()
    this.setState('disconnected')
  }

  async request<TResponse = unknown>(request: TransportRequest): Promise<TResponse> {
    if (request.kind === 'http') {
      return await this.http.request(request) as TResponse
    }
    await this.connect()
    const id = `direct-${this.nextRequestId++}`
    const timeoutMs = request.timeoutMs ?? 30_000
    if (request.signal?.aborted) throw new DOMException('Aborted', 'AbortError')

    return await new Promise<TResponse>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id)
        request.signal?.removeEventListener('abort', abort)
        reject(new Error(`LamTools transport request timed out: ${request.method} (${timeoutMs}ms)`))
      }, timeoutMs)
      const abort = () => {
        clearTimeout(timer)
        this.pending.delete(id)
        reject(new DOMException('Aborted', 'AbortError'))
      }
      this.pending.set(id, {
        resolve: (value) => {
          clearTimeout(timer)
          request.signal?.removeEventListener('abort', abort)
          resolve(value as TResponse)
        },
        reject: (error) => {
          clearTimeout(timer)
          request.signal?.removeEventListener('abort', abort)
          reject(error)
        },
        cleanup: () => {
          clearTimeout(timer)
          request.signal?.removeEventListener('abort', abort)
        },
      })
      request.signal?.addEventListener('abort', abort, { once: true })
      try {
        this.writeJson({ id, method: request.method, params: request.params || {} })
      } catch (error) {
        const pending = this.pending.get(id)
        this.pending.delete(id)
        pending?.cleanup()
        reject(error instanceof Error ? error : new Error(String(error)))
      }
    })
  }

  send(message: TransportMessage): void {
    if (message.channel === 'rpc') {
      const payload = message.payload
      if (typeof payload === 'string' && !message.method && message.id === undefined) {
        this.writeRaw(payload)
        return
      }
      const body: Record<string, unknown> = {}
      if (message.id !== undefined) body.id = message.id
      if (message.method) body.method = message.method
      if (message.params !== undefined) body.params = message.params
      if (message.result !== undefined) body.result = message.result
      if (message.error !== undefined) body.error = message.error
      if (Object.keys(body).length === 0 && payload !== undefined) {
        this.writeJson(payload)
      } else {
        this.writeJson(body)
      }
      return
    }
    if (message.channel === 'binary') {
      const data = message.data
        || (message.payload instanceof Uint8Array ? message.payload : undefined)
      if (!data) throw new Error('binary transport message has no data')
      this.writeBinary(data)
      return
    }
    this.writeJson(message.payload ?? message)
  }

  subscribe(handler: (message: TransportMessage) => void): () => void {
    this.subscribers.add(handler)
    return () => this.subscribers.delete(handler)
  }

  onState(handler: (state: TransportConnectionState) => void): () => void {
    this.stateSubscribers.add(handler)
    handler(this.state)
    return () => this.stateSubscribers.delete(handler)
  }

  getState(): TransportConnectionState {
    return this.state
  }

  private writeRaw(value: string): void {
    const socket = this.socket
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      throw new Error('LamTools direct transport is not connected')
    }
    socket.send(value)
  }

  private writeJson(value: unknown): void {
    this.writeRaw(JSON.stringify(value))
  }

  private writeBinary(value: Uint8Array): void {
    const socket = this.socket
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      throw new Error('LamTools direct transport is not connected')
    }
    const copy = new Uint8Array(new ArrayBuffer(value.byteLength))
    copy.set(value)
    socket.send(copy.buffer)
  }

  private async handleSocketValue(value: unknown): Promise<void> {
    if (typeof value !== 'string') {
      if (value instanceof ArrayBuffer) {
        this.emit({ type: 'binary', channel: 'binary', data: new Uint8Array(value) })
      } else if (typeof Blob !== 'undefined' && value instanceof Blob) {
        this.emit({ type: 'binary', channel: 'binary', data: new Uint8Array(await value.arrayBuffer()) })
      }
      return
    }

    let parsed: Record<string, unknown>
    try {
      parsed = JSON.parse(value) as Record<string, unknown>
    } catch {
      this.emit({ type: 'control', channel: 'control', payload: value })
      return
    }
    const message = normalizeRpcMessage(parsed, value)
    if (message.type === 'response' && message.id !== undefined) {
      const key = String(message.id)
      const pending = this.pending.get(key)
      if (pending) {
        this.pending.delete(key)
        pending.cleanup()
        if (message.error) {
          pending.reject(new TransportRpcError(message.error.code, message.error.message, message.error.data))
        }
        else pending.resolve(message.result)
      }
    }
    this.emit(message)
  }

  private emit(message: TransportMessage): void {
    for (const subscriber of this.subscribers) subscriber(message)
  }

  private rejectPending(error: Error): void {
    for (const pending of this.pending.values()) {
      pending.cleanup()
      pending.reject(error)
    }
    this.pending.clear()
  }

  private setState(state: TransportConnectionState): void {
    if (this.state === state) return
    this.state = state
    for (const subscriber of this.stateSubscribers) subscriber(state)
  }
}

export function createDirectTransport(options: DirectTransportOptions): DirectTransport {
  return new DirectTransport(options)
}

export function appServerUrl(apiBase: string, options: { path?: string; token?: string } = {}): string {
  const fallbackOrigin = typeof window !== 'undefined' ? window.location.origin : 'http://127.0.0.1'
  const base = apiBase || (typeof window !== 'undefined' && (window as any).__LAMTOOLS_API_BASE__) || fallbackOrigin
  const url = new URL(options.path || '/api/core/app-server', base)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  if (options.token) url.searchParams.set('token', options.token)
  return url.toString()
}

function normalizeRpcMessage(parsed: Record<string, unknown>, raw: string): TransportMessage {
  const id = typeof parsed.id === 'string' || typeof parsed.id === 'number' ? parsed.id : undefined
  const method = typeof parsed.method === 'string' ? parsed.method : undefined
  const type = method ? (id === undefined ? 'notification' : 'request') : (id === undefined ? 'event' : 'response')
  return {
    type,
    channel: 'rpc',
    ...(id === undefined ? {} : { id }),
    ...(method ? { method } : {}),
    ...(isRecord(parsed.params) ? { params: parsed.params } : {}),
    ...(parsed.result !== undefined ? { result: parsed.result } : {}),
    ...(isRecord(parsed.error) && typeof parsed.error.message === 'string'
      ? { error: {
        code: typeof parsed.error.code === 'number' || typeof parsed.error.code === 'string'
          ? parsed.error.code
          : undefined,
        message: parsed.error.message,
        ...(parsed.error.data !== undefined ? { data: parsed.error.data } : {}),
      } }
      : {}),
    payload: raw,
  }
}

function isRecord(value: unknown): value is Record<string, any> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function joinHttpPath(baseUrl: string, path: string): string {
  if (/^https?:\/\//i.test(path)) return path
  return `${baseUrl.replace(/\/$/, '')}/${path.replace(/^\//, '')}`
}

function defaultAppServerWsUrl(apiBase: string, token?: string): string {
  const fallbackOrigin = typeof window !== 'undefined' ? window.location.origin : 'http://127.0.0.1'
  const base = /^https?:\/\//i.test(apiBase)
    ? apiBase
    : new URL(apiBase || '/', fallbackOrigin).toString()
  const normalized = base.replace(/\/$/, '')
  const path = /\/api\/core$/i.test(normalized)
    ? `${normalized}/app-server`
    : `${normalized}/api/core/app-server`
  const url = new URL(path)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  if (token) url.searchParams.set('token', token)
  return url.toString()
}
