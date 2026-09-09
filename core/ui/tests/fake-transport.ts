import type {
  LamToolsTransport,
  TransportConnectionState,
  TransportHttpResponse,
  TransportMessage,
  TransportRequest,
} from '../src/transport'

export function createFakeTransport(
  response: TransportHttpResponse = {
    status: 200,
    headers: { 'content-type': 'application/json' },
    body: new TextEncoder().encode(JSON.stringify({ entries: [] })),
  },
): LamToolsTransport {
  let state: TransportConnectionState = 'connected'
  const listeners = new Set<(message: TransportMessage) => void>()
  const stateListeners = new Set<(value: TransportConnectionState) => void>()
  return {
    async connect() {
      state = 'connected'
      for (const listener of stateListeners) listener(state)
    },
    async close() {
      state = 'disconnected'
      for (const listener of stateListeners) listener(state)
    },
    async request<TResponse = unknown>(_request: TransportRequest): Promise<TResponse> {
      return response as TResponse
    },
    send(_message: TransportMessage) {},
    subscribe(handler) {
      listeners.add(handler)
      return () => listeners.delete(handler)
    },
    onState(handler) {
      stateListeners.add(handler)
      handler(state)
      return () => stateListeners.delete(handler)
    },
    getState() {
      return state
    },
  }
}
