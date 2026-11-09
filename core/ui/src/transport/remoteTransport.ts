import { invoke } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'

import { ensureRemote, remoteStatus } from '@/app/remoteSession.ts'
import { base64ToBytes, bytesToBase64, isReplaySafe } from '@/transport/remoteCodec.ts'

import {
  TransportRpcError,
  type LamToolsTransport,
  type TransportConnectionState,
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
  private progressUnlisten: (() => void) | null = null

  async connect(): Promise<void> {
    if (this.state === 'connected') return
    this.setState('connecting')
    this.unlisten?.()
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
    // user:“显示和电脑断联了”+(宿主发现隧道断了会发 lost；界面必须知道，否则会一直
    // 认为自己在远程，流式输出静默停掉也没有任何提示)。
    this.progressUnlisten?.()
    this.progressUnlisten = await listen<{ phase?: string }>('p2p-progress', (event) => {
      const phase = event.payload?.phase
      if (phase === 'connected') this.setState('connected')
      else if (phase === 'lost' || phase === 'failed' || phase === 'timeout') this.setState('disconnected')
    })
    this.setState('connected')
  }

  async close(): Promise<void> {
    this.unlisten?.()
    this.unlisten = null
    this.progressUnlisten?.()
    this.progressUnlisten = null
    this.setState('disconnected')
  }

  async request<TResponse = unknown>(request: TransportRequest): Promise<TResponse> {
    try {
      return await this.perform<TResponse>(request)
    } catch (error) {
      // user:“网络切换后尽可能恢复连接及会话状态”+(PC 重启或换网之后，先按记住的票据
      // 重连一次；重连成功就把这次请求补上)。
      //
      // 但重连只在隧道真的断了的时候做：Core 自己回的业务错误（比如参数不对）不该触发
      // 一次拨号，否则一个普通失败会被说成「连接断开」，还白等 1.2 秒。
      const status = await remoteStatus()
      if (status?.connected) throw error
      if (!isReplaySafe(request)) {
        throw new TransportRpcError(
          undefined,
          '和电脑的连接断开了，这条操作没有确认送达：在「设备连接」里重连之后再试一次',
        )
      }
      // 单飞之后这里不会再顶掉正在进行的拨号；给它够一次局域网握手的时间。
      const peer = await ensureRemote(8_000)
      if (peer === null) {
        throw new TransportRpcError(undefined, '和电脑的连接断开了：打开抽屉底部的「设备连接」，可以重连或切回本机')
      }
      return await this.perform<TResponse>(request)
    }
  }

  private async perform<TResponse>(request: TransportRequest): Promise<TResponse> {
    try {
      if (request.kind === 'http') {
        // user:“远程模式下附件发不出去、图片预览是坏的”+(隧道这层以前只搬文本，
        // multipart 和图片字节全被毁掉；现在按字节透传，并把 Content-Type 一起带过去)。
        const reply = (await invoke('p2p_call', {
          method: 'core_http',
          params: {
            method: request.method,
            path: request.path,
            headers: request.headers ?? {},
            body_b64: request.body && request.body.length ? bytesToBase64(request.body) : '',
          },
        })) as { status?: number; headers?: Record<string, string>; body_b64?: string } | undefined
        return {
          status: reply?.status ?? 0,
          headers: reply?.headers ?? {},
          body: base64ToBytes(reply?.body_b64),
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
    // 反向 RPC（服务端请求客户端）在远程模式下走不通：应答帧没有 method，
    // 而隧道的每一帧都要一个 Core 方法名。当前只有 `initialized` 这类通知会走这里。
    if (message.channel !== 'rpc' || !message.method) return
    void invoke('p2p_call', { method: message.method, params: message.params ?? {} }).catch(() => undefined)
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
    if (this.state === state) return
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
