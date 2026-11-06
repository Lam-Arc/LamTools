import { invoke } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'

import {
  TransportRpcError,
  type LamToolsTransport,
  type TransportConnectionState,
  type TransportHttpResponse,
  type TransportMessage,
  type TransportRequest,
} from '@/transport/types.ts'

/**
 * The transport used when the phone is driving the PC's Core.
 *
 * user:“手机可以连接电脑上的 Sunday，访问会话、发送消息……优先复用现有 Core API”+
 * (同一个 method、同一份 params，只是不再走本机 IPC，而是穿过加密隧道到电脑，由那边的
 * Core 执行业务。界面完全不知道自己在说哪一端)。
 *
 * user:“接收实时事件”+(Core 的通知由 PC 侧泵进隧道，宿主再抛成 `p2p-event`；
 * 这里把它接回成与本地 IPC 完全相同形状的 notification，工作台一行都不用改)。
 */
export class RemoteTransport implements LamToolsTransport {
  private state: TransportConnectionState = 'disconnected'
  private readonly subscribers = new Set<(message: TransportMessage) => void>()
  private readonly stateSubscribers = new Set<(state: TransportConnectionState) => void>()
  private unlisten: (() => void) | null = null

  async connect(): Promise<void> {
    if (this.state === 'connected') return
    this.setState('connecting')
    this.unlisten = await listen('p2p-event', (event) => {
      const payload = event.payload as { method?: unknown; params?: unknown } | undefined
      const method = typeof payload?.method === 'string' ? payload.method : undefined
      if (!method) return
      this.emit({
        type: 'notification',
        channel: 'rpc',
        method,
        params: (payload?.params ?? {}) as Record<string, unknown>,
      })
    })
    this.setState('connected')
  }

  async close(): Promise<void> {
    this.unlisten?.()
    this.unlisten = null
    this.setState('disconnected')
  }

  async request<TResponse = unknown>(request: TransportRequest): Promise<TResponse> {
    try {
      if (request.kind === 'http') {
        const body = request.body ? JSON.parse(new TextDecoder().decode(request.body)) : undefined
        const reply = (await invoke('p2p_call', {
          method: 'core_http',
          params: { method: request.method, path: request.path, body },
        })) as { status?: number; body?: unknown }
        return {
          status: reply?.status ?? 0,
          headers: { 'content-type': 'application/json' },
          body: new TextEncoder().encode(JSON.stringify(reply?.body ?? null)),
        } as TResponse
      }
      const result = (await invoke('p2p_call', {
        method: request.method,
        params: request.params ?? {},
      })) as TResponse
      return result
    } catch (error) {
      throw new TransportRpcError(undefined, String(error))
    }
  }

  send(message: TransportMessage): void {
    if (message.channel === 'rpc' && message.method) {
      void invoke('p2p_call', { method: message.method, params: message.params ?? {} })
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

export function createRemoteTransport(): RemoteTransport {
  return new RemoteTransport()
}
