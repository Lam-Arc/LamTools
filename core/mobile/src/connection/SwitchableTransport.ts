import type {
  LamToolsTransport,
  TransportConnectionState,
  TransportMessage,
  TransportRequest,
} from '@lamtools/ui/transport'

/** Stable facade used by the shared Workbench while mobile changes between
 * its local runtime and a selected remote device. */
export class SwitchableTransport implements LamToolsTransport {
  private active: LamToolsTransport
  private generation = 0
  private state: TransportConnectionState = 'disconnected'
  private readonly messages = new Set<(message: TransportMessage) => void>()
  private readonly states = new Set<(state: TransportConnectionState) => void>()
  private removeMessages: (() => void) | null = null
  private removeState: (() => void) | null = null
  private switchQueue: Promise<void> = Promise.resolve()

  constructor(initial: LamToolsTransport) {
    this.active = initial
    this.attach(initial)
  }

  current(): LamToolsTransport { return this.active }

  use(next: LamToolsTransport): Promise<void> {
    const operation = this.switchQueue.then(() => this.useNow(next))
    this.switchQueue = operation.catch(() => undefined)
    return operation
  }

  private async useNow(next: LamToolsTransport): Promise<void> {
    if (this.active === next) return
    const previous = this.active
    this.generation += 1
    const generation = this.generation
    this.detach()
    this.active = next
    this.attach(next)
    await previous.close()
    if (generation !== this.generation || this.active !== next) return
    this.publishState(next.getState())
  }

  connect(): Promise<void> { return this.active.connect() }
  close(): Promise<void> | void { return this.active.close() }
  request<TResponse = unknown>(request: TransportRequest): Promise<TResponse> { return this.active.request<TResponse>(request) }
  send(message: TransportMessage): Promise<void> | void { return this.active.send(message) }

  subscribe(handler: (message: TransportMessage) => void): () => void {
    this.messages.add(handler)
    return () => this.messages.delete(handler)
  }

  onState(handler: (state: TransportConnectionState) => void): () => void {
    this.states.add(handler)
    handler(this.state)
    return () => this.states.delete(handler)
  }

  getState(): TransportConnectionState { return this.state }

  private attach(transport: LamToolsTransport): void {
    const generation = this.generation
    this.removeMessages = transport.subscribe((message) => {
      if (generation !== this.generation || transport !== this.active) return
      for (const listener of this.messages) listener(message)
    })
    this.removeState = transport.onState((state) => {
      if (generation !== this.generation || transport !== this.active) return
      this.publishState(state)
    })
  }

  private detach(): void {
    this.removeMessages?.()
    this.removeState?.()
    this.removeMessages = null
    this.removeState = null
  }

  private publishState(state: TransportConnectionState): void {
    if (this.state === state) return
    this.state = state
    for (const listener of this.states) listener(state)
  }
}
