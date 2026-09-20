import type {
  LamToolsTransport,
  TransportConnectionState,
  TransportHttpRequest,
  TransportHttpResponse,
  TransportMessage,
  TransportRequest,
} from '@lamtools/ui/transport'
import { TransportRpcError } from '@lamtools/ui/transport'
import {
  TUNNEL_FRAME_TYPES,
  TUNNEL_LIMITS,
  TUNNEL_PROTOCOL_VERSION,
  TUNNEL_STREAMS,
  TunnelFrameDecoder,
  encodeTunnelFrame,
  splitTunnelPayload,
  utf8ByteLength,
  type TunnelFrame,
} from './TunnelProtocol'

export {
  TUNNEL_FRAME_TYPES,
  TUNNEL_LIMITS,
  TUNNEL_PROTOCOL_VERSION,
  TUNNEL_STREAMS,
  TunnelFrameDecoder,
  decodeTunnelFrames,
  encodeTunnelFrame,
  splitTunnelPayload,
  utf8ByteLength,
  type TunnelFrame,
  type TunnelFrameDecoderOptions,
} from './TunnelProtocol'

/** Payload-free trace records used to follow a request through the remote tunnel. */
export interface RemoteDiagnosticEvent {
  component: 'mobile'
  event: string
  request_id?: string
  method?: string
  frame_type?: string
  stream_id?: string
  sequence?: number
  bytes?: number
  status?: number
  state?: TransportConnectionState
  error?: string
  connection_generation?: number
  close_code?: number
  close_reason?: string
  close_was_clean?: boolean
}

export type RemoteDiagnosticSink = (event: RemoteDiagnosticEvent) => void

export function defaultRemoteDiagnosticSink(event: RemoteDiagnosticEvent): void {
  // Keep the record as one JSON string so browser consoles, native WebViews,
  // and log collectors preserve the correlation fields instead of collapsing
  // the object to an unhelpful "Object" placeholder.
  if (typeof console !== 'undefined') console.info('[lamtools-remote]', JSON.stringify(event))
}

/** A byte-oriented authenticated connection used by the tunnel multiplexer. */
export interface TunnelWire {
  connect(): Promise<void>
  send(data: Uint8Array): void
  onData(listener: (data: Uint8Array) => void): () => void
  onState(listener: (state: TransportConnectionState) => void): () => void
  close(): void
}

type HttpResponsePayload = {
  status: number
  headers?: Record<string, string>
  body?: string
}

class TunnelSession {
  private readonly decoder = new TunnelFrameDecoder()
  private readonly rpcListeners = new Set<(message: string, frame: TunnelFrame) => void>()
  private readonly frameListeners = new Set<(frame: TunnelFrame) => void>()
  private readonly stateListeners = new Set<(state: TransportConnectionState) => void>()
  private readonly pendingHttp = new Map<string, {
    resolve: (response: TransportHttpResponse) => void
    reject: (error: Error) => void
    cleanup: () => void
  }>()
  private sequence = 0
  private connectPromise: Promise<void> | null = null
  private readonly removeData: () => void
  private readonly removeState: () => void

  constructor(
    private readonly wire: TunnelWire,
    private readonly diagnosticSink: RemoteDiagnosticSink,
  ) {
    this.removeData = wire.onData((data) => this.handleData(data))
    this.removeState = wire.onState((state) => this.handleState(state))
  }

  connect(): Promise<void> {
    if (!this.connectPromise) {
      this.emitState('connecting')
      this.connectPromise = this.wire.connect()
        .then(() => { this.emitState('connected') })
        .catch((error) => {
          this.connectPromise = null
          this.emitState('failed')
          throw error
        })
    }
    return this.connectPromise
  }

  sendRpc(message: string, requestId?: string): number {
    return this.sendFrame({
      type: TUNNEL_FRAME_TYPES.rpc,
      stream_id: TUNNEL_STREAMS.rpc,
      ...(requestId ? { request_id: requestId } : {}),
      payload: message,
    })
  }

  sendData(frameType: string, streamId: string, payload: string): number {
    return this.sendFrame({ type: frameType, stream_id: streamId, payload })
  }

  onRpc(listener: (message: string, frame: TunnelFrame) => void): () => void {
    this.rpcListeners.add(listener)
    return () => this.rpcListeners.delete(listener)
  }

  onFrame(listener: (frame: TunnelFrame) => void): () => void {
    this.frameListeners.add(listener)
    return () => this.frameListeners.delete(listener)
  }

  onState(listener: (state: TransportConnectionState) => void): () => void {
    this.stateListeners.add(listener)
    return () => this.stateListeners.delete(listener)
  }

  request(input: TransportHttpRequest): Promise<TransportHttpResponse> {
    if (input.signal?.aborted) return Promise.reject(new DOMException('Aborted', 'AbortError'))
    const requestId = globalThis.crypto?.randomUUID?.() || `request-${Date.now()}-${this.sequence + 1}`
    const timeoutMs = input.timeoutMs ?? 30_000
    return new Promise<TransportHttpResponse>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pendingHttp.delete(requestId)
        input.signal?.removeEventListener('abort', abort)
        reject(new Error(`隧道 HTTP 请求超时: ${input.path}`))
      }, timeoutMs)
      const abort = () => {
        clearTimeout(timer)
        this.pendingHttp.delete(requestId)
        input.signal?.removeEventListener('abort', abort)
        try {
          this.sendFrame({
            type: TUNNEL_FRAME_TYPES.httpCancel,
            stream_id: `http:${requestId}`,
            request_id: requestId,
          })
        } catch {
          // Cancellation is best-effort. The caller must still receive the
          // AbortError even when the wire closed at the same time.
        }
        reject(new DOMException('Aborted', 'AbortError'))
      }
      const cleanup = () => {
        clearTimeout(timer)
        input.signal?.removeEventListener('abort', abort)
      }
      this.pendingHttp.set(requestId, {
        resolve: (response) => { cleanup(); resolve(response) },
        reject: (error) => { cleanup(); reject(error) },
        cleanup,
      })
      input.signal?.addEventListener('abort', abort, { once: true })
      try {
        const bytes = this.sendFrame({
          type: TUNNEL_FRAME_TYPES.httpRequest,
          stream_id: `http:${requestId}`,
          request_id: requestId,
          payload: JSON.stringify({
            method: input.method,
            path: input.path,
            headers: input.headers || {},
            body: input.body ? bytesToBase64(input.body) : '',
          }),
        })
        this.report({
          event: 'http_sent',
          request_id: requestId,
          method: input.method,
          bytes,
        })
      } catch (error) {
        this.pendingHttp.delete(requestId)
        cleanup()
        reject(error instanceof Error ? error : new Error(String(error)))
      }
    })
  }

  close(): void {
    this.removeData()
    this.removeState()
    this.wire.close()
    this.connectPromise = null
    this.decoder.reset()
    this.sequence = 0
    this.rejectPendingHttp(new Error('tunnel closed'))
    this.emitState('disconnected')
  }

  private rejectPendingHttp(error: Error): void {
    for (const pending of this.pendingHttp.values()) {
      pending.cleanup()
      pending.reject(error)
    }
    this.pendingHttp.clear()
  }

  private sendFrame(input: Omit<TunnelFrame, 'version' | 'sequence'>): number {
    const nextSequence = this.sequence + 1
    const payloadBytes = input.payload === undefined ? 0 : utf8ByteLength(input.payload)
    if (input.payload === undefined || payloadBytes <= TUNNEL_LIMITS.chunkPayloadBytes) {
      const encoded = encodeTunnelFrame({
        version: TUNNEL_PROTOCOL_VERSION,
        sequence: nextSequence,
        ...input,
      })
      this.sequence = nextSequence
      this.wire.send(encoded)
      this.report({
        event: 'frame_sent',
        frame_type: input.type,
        stream_id: input.stream_id,
        ...(input.request_id ? { request_id: input.request_id } : {}),
        sequence: nextSequence,
        bytes: encoded.byteLength,
      })
      return encoded.byteLength
    }
    if (payloadBytes > TUNNEL_LIMITS.messageBytes) throw new Error('tunnel 消息过大')
    const messageId = `message-${nextSequence}`
    const chunks = splitTunnelPayload(input.payload)
    let bytes = 0
    for (const [index, payload] of chunks.entries()) {
      this.sequence += 1
      const encoded = encodeTunnelFrame({
        version: TUNNEL_PROTOCOL_VERSION,
        sequence: this.sequence,
        ...input,
        payload,
        message_id: messageId,
        chunk_index: index,
        chunk_final: index + 1 === chunks.length,
      })
      this.wire.send(encoded)
      bytes += encoded.byteLength
    }
    this.report({
      event: 'frame_sent',
      frame_type: input.type,
      stream_id: input.stream_id,
      ...(input.request_id ? { request_id: input.request_id } : {}),
      sequence: this.sequence,
      bytes,
    })
    return bytes
  }

  private handleData(data: Uint8Array): void {
    let frames: TunnelFrame[]
    try {
      frames = this.decoder.push(data)
    } catch (error) {
      this.rejectPendingHttp(error instanceof Error ? error : new Error(String(error)))
      this.report({
        event: 'frame_receive_failed',
        error: error instanceof Error ? error.message : String(error),
      })
      this.emitState('failed')
      this.wire.close()
      return
    }
    for (const frame of frames) {
      if (frame.type === TUNNEL_FRAME_TYPES.rpc
        && frame.stream_id === TUNNEL_STREAMS.rpc
        && typeof frame.payload === 'string') {
        for (const listener of this.rpcListeners) listener(frame.payload, frame)
        continue
      }
      if (frame.type === TUNNEL_FRAME_TYPES.httpResponse && frame.request_id) {
        const pending = this.pendingHttp.get(frame.request_id)
        if (!pending) continue
        this.pendingHttp.delete(frame.request_id)
        try {
          const payload = JSON.parse(frame.payload || '{}') as HttpResponsePayload
          if (!Number.isInteger(payload.status)) throw new Error('invalid tunnel HTTP response')
          this.report({
            event: 'http_received',
            request_id: frame.request_id,
            status: payload.status,
            bytes: frame.payload ? utf8ByteLength(frame.payload) : 0,
          })
          pending.resolve({
            status: payload.status,
            headers: payload.headers || {},
            body: payload.body ? base64ToBytes(payload.body) : new Uint8Array(),
          })
        } catch (error) {
          pending.reject(error instanceof Error ? error : new Error(String(error)))
        }
        continue
      }
      try {
        for (const listener of this.frameListeners) listener(frame)
      } catch (error) {
        this.rejectPendingHttp(error instanceof Error ? error : new Error(String(error)))
        this.emitState('failed')
        this.wire.close()
        return
      }
    }
  }

  private handleState(state: TransportConnectionState): void {
    if (state === 'disconnected' || state === 'failed') this.connectPromise = null
    if (state === 'disconnected' || state === 'failed') {
      this.rejectPendingHttp(new Error('tunnel disconnected'))
    }
    this.emitState(state)
  }

  private emitState(state: TransportConnectionState): void {
    this.report({ event: 'state', state })
    for (const listener of this.stateListeners) listener(state)
  }

  private report(event: Omit<RemoteDiagnosticEvent, 'component'>): void {
    try {
      this.diagnosticSink({ component: 'mobile', ...event })
    } catch {
      // Diagnostics must never alter the transport's control flow.
    }
  }
}

/** LamToolsTransport carried over one already-authenticated encrypted wire. */
export class MultiplexedTunnelTransport implements LamToolsTransport {
  private readonly session: TunnelSession
  private readonly messageListeners = new Set<(message: TransportMessage) => void>()
  private readonly stateListeners = new Set<(state: TransportConnectionState) => void>()
  private readonly pendingRpc = new Map<string, {
    resolve: (value: unknown) => void
    reject: (error: Error) => void
    cleanup: () => void
  }>()
  private readonly removeRpc: () => void
  private readonly removeFrame: () => void
  private readonly removeSessionState: () => void
  private state: TransportConnectionState = 'disconnected'
  private nextRpcId = 1

  constructor(
    wire: TunnelWire,
    private readonly diagnosticSink: RemoteDiagnosticSink = () => {},
  ) {
    this.session = new TunnelSession(wire, diagnosticSink)
    this.removeRpc = this.session.onRpc((message, frame) => this.handleRpc(message, frame))
    this.removeFrame = this.session.onFrame((frame) => this.handleFrame(frame))
    this.removeSessionState = this.session.onState((state) => this.setState(state))
  }

  connect(): Promise<void> { return this.session.connect() }

  async close(): Promise<void> {
    this.removeRpc()
    this.removeFrame()
    this.removeSessionState()
    this.session.close()
    this.rejectPendingRpc(new Error('LamTools remote transport closed'))
    this.setState('disconnected')
  }

  async request<TResponse = unknown>(request: TransportRequest): Promise<TResponse> {
    await this.connect()
    if (this.state !== 'connected') throw new Error('LamTools remote transport is not connected')
    if (request.kind === 'http') return await this.session.request(request) as TResponse
    const id = `remote-${this.nextRpcId++}`
    const timeoutMs = request.timeoutMs ?? 30_000
    if (request.signal?.aborted) throw new DOMException('Aborted', 'AbortError')
    return await new Promise<TResponse>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pendingRpc.delete(id)
        request.signal?.removeEventListener('abort', abort)
        reject(new Error(`LamTools remote request timed out: ${request.method} (${timeoutMs}ms)`))
      }, timeoutMs)
      const abort = () => {
        clearTimeout(timer)
        this.pendingRpc.delete(id)
        reject(new DOMException('Aborted', 'AbortError'))
      }
      const pending = {
        resolve: (value: unknown) => {
          clearTimeout(timer)
          request.signal?.removeEventListener('abort', abort)
          resolve(value as TResponse)
        },
        reject: (error: Error) => {
          clearTimeout(timer)
          request.signal?.removeEventListener('abort', abort)
          reject(error)
        },
        cleanup: () => {
          clearTimeout(timer)
          request.signal?.removeEventListener('abort', abort)
        },
      }
      this.pendingRpc.set(id, pending)
      request.signal?.addEventListener('abort', abort, { once: true })
      try {
        const bytes = this.session.sendRpc(
          JSON.stringify({ id, method: request.method, params: request.params || {} }),
          id,
        )
        this.report({ event: 'rpc_sent', request_id: id, method: request.method, bytes })
      } catch (error) {
        this.pendingRpc.delete(id)
        pending.cleanup()
        reject(error instanceof Error ? error : new Error(String(error)))
      }
    })
  }

  send(message: TransportMessage): void {
    if (message.channel === 'rpc') {
      if (typeof message.payload === 'string' && !message.method && message.id === undefined) {
        this.session.sendRpc(message.payload)
        return
      }
      const body: Record<string, unknown> = {}
      if (message.id !== undefined) body.id = message.id
      if (message.method) body.method = message.method
      if (message.params !== undefined) body.params = message.params
      if (message.result !== undefined) body.result = message.result
      if (message.error !== undefined) body.error = message.error
      this.session.sendRpc(JSON.stringify(Object.keys(body).length ? body : message.payload ?? {}))
      return
    }

    if (message.channel === 'binary') {
      const data = message.data
        || (message.payload instanceof Uint8Array ? message.payload : undefined)
      if (!data) throw new Error('binary transport message has no data')
      this.session.sendData(TUNNEL_FRAME_TYPES.binary, TUNNEL_STREAMS.binary, bytesToBase64(data))
      return
    }

    if (message.channel === 'control' || message.channel === 'event') {
      const channel = message.channel
      const payload = typeof message.payload === 'string'
        ? message.payload
        : JSON.stringify(message.payload ?? message)
      const frameType = channel === 'control'
        ? TUNNEL_FRAME_TYPES.control
        : TUNNEL_FRAME_TYPES.event
      const stream = channel === 'control'
        ? TUNNEL_STREAMS.control
        : TUNNEL_STREAMS.event
      this.session.sendData(frameType, stream, payload)
      return
    }

    throw new Error(`unsupported tunnel message channel: ${message.channel}`)
  }

  subscribe(handler: (message: TransportMessage) => void): () => void {
    this.messageListeners.add(handler)
    return () => this.messageListeners.delete(handler)
  }

  onState(handler: (state: TransportConnectionState) => void): () => void {
    this.stateListeners.add(handler)
    handler(this.state)
    return () => this.stateListeners.delete(handler)
  }

  getState(): TransportConnectionState { return this.state }

  private handleRpc(raw: string, frame: TunnelFrame): void {
    let parsed: Record<string, unknown>
    try {
      parsed = JSON.parse(raw) as Record<string, unknown>
    } catch {
      this.emit({ type: 'control', channel: 'control', payload: raw })
      return
    }
    const id = typeof parsed.id === 'string' || typeof parsed.id === 'number' ? parsed.id : undefined
    const method = typeof parsed.method === 'string' ? parsed.method : undefined
    const requestId = frame.request_id || (id === undefined ? undefined : String(id))
    const message: TransportMessage = {
      type: method ? (id === undefined ? 'notification' : 'request') : (id === undefined ? 'event' : 'response'),
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
    if (message.type === 'response' && id !== undefined) {
      const pending = this.pendingRpc.get(String(id))
      if (pending) {
        this.pendingRpc.delete(String(id))
        pending.cleanup()
        if (message.error) {
          pending.reject(new TransportRpcError(message.error.code, message.error.message, message.error.data))
        }
        else pending.resolve(message.result)
        this.report({
          event: 'rpc_received',
          ...(requestId ? { request_id: requestId } : {}),
          ...(method ? { method } : {}),
          bytes: raw.length,
          ...(message.error ? { error: message.error.message } : {}),
        })
      }
    }
    if (message.type === 'notification' && !isStreamingRunItemDelta(parsed)) {
      this.report({
        event: 'event_received',
        ...(method ? { method } : {}),
        ...(requestId ? { request_id: requestId } : {}),
        bytes: raw.length,
      })
    }
    this.emit(message)
  }

  private handleFrame(frame: TunnelFrame): void {
    if (frame.type === TUNNEL_FRAME_TYPES.binary && frame.stream_id === TUNNEL_STREAMS.binary) {
      this.emit({
        type: 'binary',
        channel: 'binary',
        data: base64ToBytes(frame.payload || ''),
        sequence: frame.sequence,
      })
      return
    }
    if (frame.type === TUNNEL_FRAME_TYPES.control && frame.stream_id === TUNNEL_STREAMS.control) {
      this.emit({
        type: 'control',
        channel: 'control',
        payload: parseTunnelPayload(frame.payload || ''),
        sequence: frame.sequence,
      })
      return
    }
    if (frame.type === TUNNEL_FRAME_TYPES.event && frame.stream_id === TUNNEL_STREAMS.event) {
      this.emit({
        type: 'event',
        channel: 'event',
        payload: parseTunnelPayload(frame.payload || ''),
        sequence: frame.sequence,
      })
      return
    }
    this.emit({
      type: 'control',
      channel: 'control',
      payload: { type: frame.type, stream_id: frame.stream_id, payload: frame.payload },
      sequence: frame.sequence,
    })
  }

  private emit(message: TransportMessage): void {
    for (const listener of this.messageListeners) listener(message)
  }

  private report(event: Omit<RemoteDiagnosticEvent, 'component'>): void {
    try {
      this.diagnosticSink({ component: 'mobile', ...event })
    } catch {
      // Diagnostics must never alter the transport's control flow.
    }
  }

  private setState(state: TransportConnectionState): void {
    if (this.state === state) return
    this.state = state
    if (state === 'disconnected' || state === 'failed') {
      this.rejectPendingRpc(new Error('LamTools remote transport disconnected'))
    }
    for (const listener of this.stateListeners) listener(state)
  }

  private rejectPendingRpc(error: Error): void {
    for (const pending of this.pendingRpc.values()) {
      pending.cleanup()
      pending.reject(error)
    }
    this.pendingRpc.clear()
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = ''
  for (const byte of bytes) binary += String.fromCharCode(byte)
  return btoa(binary)
}

function base64ToBytes(value: string): Uint8Array {
  const binary = atob(value)
  return Uint8Array.from(binary, (character) => character.charCodeAt(0))
}

function parseTunnelPayload(value: string): unknown {
  try {
    return JSON.parse(value) as unknown
  } catch {
    return value
  }
}

function isStreamingRunItemDelta(message: Record<string, unknown>): boolean {
  if (message.method !== 'core/runItem' || !isRecord(message.params)) return false
  const payload = message.params.payload
  if (!isRecord(payload) || !isRecord(payload.payload)) return false
  return typeof payload.payload.delta === 'string'
}
