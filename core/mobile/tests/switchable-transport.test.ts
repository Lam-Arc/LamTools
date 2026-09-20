import { describe, expect, it } from 'vitest'
import type { LamToolsTransport, TransportConnectionState, TransportMessage, TransportRequest } from '@lamtools/ui'
import { SwitchableTransport } from '../src/connection/SwitchableTransport'

class FakeTransport implements LamToolsTransport {
  state: TransportConnectionState = 'disconnected'
  stateHandlers = new Set<(state: TransportConnectionState) => void>()
  messageHandlers = new Set<(message: TransportMessage) => void>()
  constructor(readonly name: string) {}
  async connect() { this.publish('connected') }
  async close() { this.publish('disconnected') }
  async request<TResponse>(_request: TransportRequest): Promise<TResponse> { return { source: this.name } as TResponse }
  send() {}
  subscribe(handler: (message: TransportMessage) => void) { this.messageHandlers.add(handler); return () => this.messageHandlers.delete(handler) }
  onState(handler: (state: TransportConnectionState) => void) { this.stateHandlers.add(handler); handler(this.state); return () => this.stateHandlers.delete(handler) }
  getState() { return this.state }
  publish(state: TransportConnectionState) { this.state = state; for (const handler of this.stateHandlers) handler(state) }
}

describe('SwitchableTransport', () => {
  it('keeps one facade while routing requests to the selected runtime', async () => {
    const local = new FakeTransport('local')
    const remote = new FakeTransport('remote')
    const transport = new SwitchableTransport(local)
    const states: TransportConnectionState[] = []
    transport.onState((state) => states.push(state))

    await transport.connect()
    expect(await transport.request<{ source: string }>({ method: 'ping' })).toEqual({ source: 'local' })
    await transport.use(remote)
    await transport.connect()
    expect(await transport.request<{ source: string }>({ method: 'ping' })).toEqual({ source: 'remote' })
    expect(states).toContain('connected')
  })

  it('serializes overlapping runtime switches so a stale close cannot win', async () => {
    let releaseClose!: () => void
    const closeGate = new Promise<void>((resolve) => { releaseClose = resolve })
    const local = new FakeTransport('local')
    local.close = async () => {
      await closeGate
      local.publish('disconnected')
    }
    const remote = new FakeTransport('remote')
    const transport = new SwitchableTransport(local)

    const toRemote = transport.use(remote)
    const backToLocal = transport.use(local)
    await Promise.resolve()
    expect(transport.current()).toBe(remote)
    releaseClose()
    await Promise.all([toRemote, backToLocal])

    expect(transport.current()).toBe(local)
    expect(await transport.request<{ source: string }>({ method: 'ping' })).toEqual({ source: 'local' })
  })
})
