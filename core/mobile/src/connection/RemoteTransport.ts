import type {
  LamToolsTransport,
  TransportConnectionState,
  TransportMessage,
  TransportRequest,
} from '@lamtools/ui/transport'
import {
  defaultRemoteDiagnosticSink,
  MultiplexedTunnelTransport,
  type RemoteDiagnosticSink,
  type TunnelWire,
} from './TunnelTransport'

export interface RemoteTransportOptions {
  createWire: () => TunnelWire | Promise<TunnelWire>
  diagnosticSink?: RemoteDiagnosticSink
}

/**
 * Stable client-side transport facade.  Route selection and socket details
 * stay behind createWire; Workbench keeps this object and its subscriptions
 * while a failed connection is replaced with a fresh tunnel session.
 */
export class RemoteTransport implements LamToolsTransport {
  private inner: MultiplexedTunnelTransport | null = null
  private createPromise: Promise<MultiplexedTunnelTransport> | null = null
  private state: TransportConnectionState = 'disconnected'
  // Generation fences async wire creation and old inner-transport callbacks.
  private connectionGeneration = 0
  private hasConnected = false
  private readonly messageListeners = new Set<(message: TransportMessage) => void>()
  private readonly stateListeners = new Set<(state: TransportConnectionState) => void>()
  private removeMessages: (() => void) | null = null
  private removeState: (() => void) | null = null

  constructor(private readonly options: RemoteTransportOptions) {}

  async connect(): Promise<void> {
    const inner = await this.ensureInner()
    const generation = this.connectionGeneration
    try {
      await inner.connect()
      if (this.connectionGeneration !== generation || this.inner !== inner) {
        throw new Error('远程传输连接已取消')
      }
    } catch (error) {
      if (this.inner === inner) this.detachInner(inner, true)
      if (this.connectionGeneration === generation) this.setState('failed')
      throw error
    }
  }

  async close(): Promise<void> {
    const generation = ++this.connectionGeneration
    const inner = this.inner
    this.inner = null
    this.createPromise = null
    this.removeMessages?.()
    this.removeMessages = null
    this.removeState?.()
    this.removeState = null
    if (inner) await inner.close()
    if (this.connectionGeneration === generation) this.setState('disconnected')
  }

  async request<TResponse = unknown>(request: TransportRequest): Promise<TResponse> {
    const inner = await this.ensureInner()
    try {
      return await inner.request<TResponse>(request)
    } catch (error) {
      if (this.inner === inner && ['disconnected', 'failed'].includes(inner.getState())) {
        this.detachInner(inner, true)
      }
      throw error
    }
  }

  send(message: TransportMessage): void {
    const inner = this.inner
    if (!inner || inner.getState() !== 'connected') {
      throw new Error('远程传输尚未连接')
    }
    inner.send(message)
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

  getState(): TransportConnectionState {
    return this.state
  }

  private async ensureInner(): Promise<MultiplexedTunnelTransport> {
    const current = this.inner
    if (current && !['disconnected', 'failed'].includes(current.getState())) return current
    if (current) this.detachInner(current, true)
    if (this.createPromise) return await this.createPromise

    const generation = ++this.connectionGeneration
    this.setState(this.hasConnected ? 'reconnecting' : 'connecting')
    const promise = (async () => {
      const wire = await this.options.createWire()
      const diagnosticSink = this.options.diagnosticSink || defaultRemoteDiagnosticSink
      const inner = new MultiplexedTunnelTransport(
        wire,
        (event) => diagnosticSink({
          ...event,
          connection_generation: event.connection_generation ?? generation,
        }),
      )
      if (generation !== this.connectionGeneration) {
        await inner.close()
        throw new Error('远程传输连接已取消')
      }
      this.inner = inner
      this.removeMessages = inner.subscribe((message) => {
        for (const listener of this.messageListeners) listener(message)
      })
      // MultiplexedTunnelTransport invokes onState immediately with its
      // current disconnected state. Ignore that initial snapshot; the
      // facade already published connecting/reconnecting above.
      let initial = true
      this.removeState = inner.onState((state) => {
        if (initial) return
        this.handleInnerState(inner, state)
      })
      initial = false
      return inner
    })()
    this.createPromise = promise
    try {
      return await promise
    } catch (error) {
      if (this.connectionGeneration === generation) this.setState('failed')
      throw error
    } finally {
      if (this.createPromise === promise) this.createPromise = null
    }
  }

  private handleInnerState(inner: MultiplexedTunnelTransport, state: TransportConnectionState): void {
    if (this.inner !== inner) return
    if (state === 'connected') this.hasConnected = true
    this.setState(state)
    if (state === 'disconnected' || state === 'failed') this.detachInner(inner, true)
  }

  private detachInner(inner: MultiplexedTunnelTransport, close: boolean): void {
    if (this.inner !== inner) return
    this.inner = null
    this.removeMessages?.()
    this.removeMessages = null
    this.removeState?.()
    this.removeState = null
    if (close) void inner.close()
  }

  private setState(state: TransportConnectionState): void {
    if (this.state === state) return
    this.state = state
    for (const listener of this.stateListeners) listener(state)
  }
}

export function createRemoteTransport(
  createWire: RemoteTransportOptions['createWire'],
  diagnosticSink?: RemoteDiagnosticSink,
): RemoteTransport {
  return new RemoteTransport({ createWire, diagnosticSink })
}
