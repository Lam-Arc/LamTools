import type {
  LamToolsTransport,
  TransportConnectionState,
  TransportHttpResponse,
  TransportMessage,
  TransportRequest,
} from '@/transport/types.ts'
import { TransportRpcError, TransportRequestTimeoutError } from '@/transport/types.ts'

/**
 * The transport used when the core lives inside the same app process.
 *
 * On Android there is deliberately no socket. Every app on the device can dial
 * another app's loopback port, so a listening server would be reachable by
 * anything installed alongside this one. Instead the core is reached through Tauri
 * IPC: `core_rpc` carries the same method and params the socket protocol uses, and
 * events arrive on `core-event` with the same envelope.
 *
 * The point of implementing `LamToolsTransport` rather than a bespoke API is that
 * the workbench does not change. `CoreAppServerClient`, the projection, the
 * composer and the pending-decision panel are the same code that runs on desktop;
 * only the pipe underneath is different. A second frontend would drift within a
 * week.
 */

import { invoke as tauriInvoke } from '@tauri-apps/api/core'
import { listen as tauriListen } from '@tauri-apps/api/event'

type InvokeFn = (command: string, args?: Record<string, unknown>) => Promise<unknown>
type ListenFn = (
  event: string,
  handler: (event: { payload: unknown }) => void,
) => Promise<() => void>

interface TauriBridge {
  invoke: InvokeFn
  listen: ListenFn
}

/**
 * Resolves the IPC bridge.
 *
 * The API is imported as a module rather than read off `window.__TAURI__`: the
 * global only exists when `withGlobalTauri` is enabled, and a UI that silently
 * degrades when that flag is missing is a UI that hangs on a black screen when
 * someone forgets it.
 */
function bridge(): TauriBridge {
  return {
    invoke: tauriInvoke as unknown as InvokeFn,
    listen: tauriListen as unknown as ListenFn,
  }
}

export interface IpcTransportOptions {
  /** Injected by tests so the transport can be exercised without Tauri. */
  invoke?: InvokeFn
  listen?: ListenFn
  /** Reports a JSON-RPC failure the same way the socket transport does. */
  onConnectionState?: (state: TransportConnectionState) => void
}

export class IpcTransport implements LamToolsTransport {
  private state: TransportConnectionState = 'disconnected'
  private readonly subscribers = new Set<(message: TransportMessage) => void>()
  private readonly stateSubscribers = new Set<(state: TransportConnectionState) => void>()
  private unlisten: (() => void) | null = null
  private nextRequestId = 1
  private readonly invoke: InvokeFn
  private readonly listen: ListenFn

  constructor(options: IpcTransportOptions = {}) {
    if (options.invoke && options.listen) {
      this.invoke = options.invoke
      this.listen = options.listen
    } else {
      const resolved = bridge()
      this.invoke = resolved.invoke
      this.listen = resolved.listen
    }
  }

  /** A second connection sharing the same process. Cheap: there is no socket. */
  fork(): IpcTransport {
    return new IpcTransport({ invoke: this.invoke, listen: this.listen })
  }

  async connect(): Promise<void> {
    if (this.state === 'connected') return
    this.setState('connecting')
    // Events must be subscribed before the first call, or a turn that starts
    // immediately would stream into a channel nobody is listening on.
    this.unlisten = await this.listen('core-event', (event) => {
      const payload = event.payload as Record<string, unknown> | undefined
      if (!payload) return
      const method = typeof payload.method === 'string' ? payload.method : undefined
      this.emit({ type: 'notification', channel: 'rpc', method, params: payload })
    })
    this.setState('connected')
  }

  async close(): Promise<void> {
    this.unlisten?.()
    this.unlisten = null
    this.setState('disconnected')
  }

  async request<TResponse = unknown>(request: TransportRequest): Promise<TResponse> {
    if (request.kind === 'http') {
      // The shared UI asks for projects and files over HTTP because that is what the
      // desktop core serves. The in-app core answers the same paths through a command,
      // so the UI does not need a second code path and cannot drift from desktop.
      await this.connect()
      const reply = (await this.invoke('core_http', {
        method: request.method,
        path: request.path,
        body: request.body ? new TextDecoder().decode(request.body) : null,
      })) as {
        status: number
        content_type: string
        body: string | null
        body_base64: string | null
      }
      const bytes = reply.body_base64
        ? decodeBase64(reply.body_base64)
        : new TextEncoder().encode(reply.body ?? '')
      return {
        status: reply.status,
        headers: { 'content-type': reply.content_type },
        body: bytes,
      } as TResponse
    }
    await this.connect()

    const id = `ipc-${this.nextRequestId++}`
    const timeoutMs = request.timeoutMs ?? 30_000
    if (request.signal?.aborted) throw new DOMException('Aborted', 'AbortError')

    const call = this.invoke('core_rpc', {
      method: request.method,
      params: request.params ?? {},
    })

    let timer: ReturnType<typeof setTimeout> | undefined
    const timeout = new Promise<never>((_, reject) => {
      timer = setTimeout(
        () => reject(new TransportRequestTimeoutError(request.method, timeoutMs)),
        Math.max(0, timeoutMs),
      )
    })

    try {
      // A timeout ends local waiting only. The core keeps its own state, so a
      // retry with the same client_message_id is the caller's safe recovery.
      return (await Promise.race([call, timeout])) as TResponse
    } catch (error) {
      throw toRpcError(request.method, id, error)
    } finally {
      if (timer !== undefined) clearTimeout(timer)
    }
  }

  send(message: TransportMessage): void {
    // Responses to server-initiated requests would go here. This core reports
    // approvals as events, so there is nothing to answer.
    if (message.channel === 'rpc' && message.method) {
      void this.invoke('core_rpc', { method: message.method, params: message.params ?? {} })
    }
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

  private setState(state: TransportConnectionState): void {
    this.state = state
    for (const handler of this.stateSubscribers) handler(state)
  }

  private emit(message: TransportMessage): void {
    for (const handler of this.subscribers) handler(message)
  }
}

/** Bytes from base64, for the one endpoint that answers with a file. */
function decodeBase64(text: string): Uint8Array {
  const binary = atob(text)
  const bytes = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index)
  }
  return bytes
}

/**
 * Turns whatever the Rust command returned into the error shape the workbench
 * already understands.
 *
 * `core_rpc` answers `"<code>: <message>"` on failure so the code survives the
 * IPC boundary; without this the UI would show a raw string and lose the ability
 * to distinguish "not authenticated" from "bad request".
 */
function toRpcError(method: string, id: string, error: unknown): Error {
  if (error instanceof TransportRequestTimeoutError) return error
  const text = error instanceof Error ? error.message : String(error)
  const match = /^(-?\d+):\s*(.*)$/s.exec(text)
  if (match) {
    return new TransportRpcError(Number(match[1]), match[2])
  }
  return new TransportRpcError(undefined, `${method} failed over IPC (${id}): ${text}`)
}

export function createIpcTransport(options: IpcTransportOptions = {}): IpcTransport {
  return new IpcTransport(options)
}

export type { TransportHttpResponse }
