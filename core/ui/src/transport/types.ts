/**
 * The connection-neutral protocol boundary used by every LamTools client.
 *
 * `request({ kind: 'rpc' })` is JSON-RPC and returns the RPC result. HTTP is
 * kept as a byte-preserving request because attachments and exports are not
 * necessarily JSON. Neither shape contains a desktop/mobile/LAN/relay
 * concept; those belong to the transport implementation.
 */

export type TransportConnectionState =
  | 'disconnected'
  | 'connecting'
  | 'connected'
  | 'reconnecting'
  | 'failed'

export interface TransportHttpRequest {
  kind: 'http'
  method: string
  path: string
  headers?: Record<string, string>
  body?: Uint8Array
  signal?: AbortSignal
  timeoutMs?: number
}

export interface TransportRpcRequest {
  kind?: 'rpc'
  method: string
  params?: Record<string, unknown>
  signal?: AbortSignal
  timeoutMs?: number
}

export type TransportRequest = TransportHttpRequest | TransportRpcRequest

export interface TransportHttpResponse {
  status: number
  headers: Record<string, string>
  body: Uint8Array
}

export type TransportMessageType =
  | 'request'
  | 'response'
  | 'event'
  | 'notification'
  | 'binary'
  | 'control'

/**
 * Messages emitted by a transport. RPC messages carry their original JSON in
 * `payload`; binary/control extensions can use `data` without being decoded
 * by the UI layer.
 */
export interface TransportMessage {
  type: TransportMessageType
  channel: 'rpc' | 'event' | 'binary' | 'control'
  id?: number | string
  method?: string
  params?: Record<string, unknown>
  result?: unknown
  error?: { code?: number | string; message: string; data?: unknown }
  payload?: unknown
  data?: Uint8Array
  sequence?: number
}

export interface LamToolsTransport {
  connect(): Promise<void>
  close(): Promise<void> | void
  request<TResponse = unknown>(request: TransportRequest): Promise<TResponse>
  send(message: TransportMessage): Promise<void> | void
  subscribe(handler: (message: TransportMessage) => void): () => void
  onState(handler: (state: TransportConnectionState) => void): () => void
  getState(): TransportConnectionState
}

/** A JSON-RPC failure that preserves the server's machine-readable contract. */
export class TransportRpcError extends Error {
  readonly code: number | string | undefined
  readonly data: unknown

  constructor(code: number | string | undefined, message: string, data?: unknown) {
    super(message)
    this.name = 'TransportRpcError'
    this.code = code
    this.data = data
    Object.setPrototypeOf(this, new.target.prototype)
  }
}

export function isLamToolsTransport(value: unknown): value is LamToolsTransport {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Partial<LamToolsTransport>
  return typeof candidate.connect === 'function'
    && typeof candidate.close === 'function'
    && typeof candidate.request === 'function'
    && typeof candidate.send === 'function'
    && typeof candidate.subscribe === 'function'
    && typeof candidate.onState === 'function'
    && typeof candidate.getState === 'function'
}
