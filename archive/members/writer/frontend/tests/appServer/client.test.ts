import assert from 'node:assert/strict'
import test from 'node:test'
import { WriterAppServerClient } from '../../src/appServer/client.ts'

class ImmediateResponseSocket {
  static readonly OPEN = 1
  static instances: ImmediateResponseSocket[] = []

  readyState = ImmediateResponseSocket.OPEN
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  onclose: (() => void) | null = null
  onmessage: ((message: { data: string }) => void) | null = null

  constructor(readonly url: string) {
    ImmediateResponseSocket.instances.push(this)
    queueMicrotask(() => this.onopen?.())
  }

  send(raw: string): void {
    ;(this as unknown as { lastSent?: string }).lastSent = raw
    const request = JSON.parse(raw) as { id?: number | string; method: string }
    if (request.id !== undefined) {
      this.onmessage?.({
        data: JSON.stringify({ id: request.id, result: { ok: true, method: request.method } }),
      })
    }
  }

  close(): void {
    this.readyState = 3
    this.onclose?.()
  }
}

test('request registers pending response before sending websocket payload', async () => {
  const previous = globalThis.WebSocket
  try {
    globalThis.WebSocket = ImmediateResponseSocket as unknown as typeof WebSocket
    const client = new WriterAppServerClient({
      url: 'ws://127.0.0.1/app-server',
      clientInfo: { name: 'test' },
    })

    await client.connect()
    const response = await client.request('turn/start', { thread_id: 'thread-1' })

    assert.deepEqual(response, { ok: true, method: 'turn/start' })
  } finally {
    globalThis.WebSocket = previous
  }
})

test('server initiated approval request is answered with the same json-rpc id', async () => {
  const previous = globalThis.WebSocket
  const events: unknown[] = []
  try {
    globalThis.WebSocket = ImmediateResponseSocket as unknown as typeof WebSocket
    const client = new WriterAppServerClient({
      url: 'ws://127.0.0.1/app-server',
      clientInfo: { name: 'test' },
      onEvent: (event) => events.push(event),
    })

    await client.connect()
    const socket = ImmediateResponseSocket.instances.at(-1)!
    socket.onmessage?.({
      data: JSON.stringify({
        id: 'request-1',
        method: 'item/requestApproval',
        params: {
          event_id: 'event-1',
          seq: 1,
          thread_id: 'thread-1',
          method: 'item/requestApproval',
          payload: { type: 'serverRequest', request_id: 'request-1' },
          created_at: '2026-06-24T00:00:00Z',
          turn_id: 'turn-1',
          item_id: 'item-1',
        },
      }),
    })

    const sent = client.respondServerRequest('request-1', { decision: 'approve_once' })

    assert.equal(sent, true)
    assert.equal(events.length, 1)
    const response = JSON.parse((socket as unknown as { lastSent?: string }).lastSent || '{}')
    assert.deepEqual(response, { id: 'request-1', result: { decision: 'approve_once' } })
  } finally {
    globalThis.WebSocket = previous
  }
})

test('thread snapshot notification is routed separately from events', async () => {
  const previous = globalThis.WebSocket
  const events: unknown[] = []
  const snapshots: unknown[] = []
  try {
    globalThis.WebSocket = ImmediateResponseSocket as unknown as typeof WebSocket
    const client = new WriterAppServerClient({
      url: 'ws://127.0.0.1/app-server',
      clientInfo: { name: 'test' },
      onEvent: (event) => events.push(event),
      onSnapshot: (snapshot) => snapshots.push(snapshot),
    })

    await client.connect()
    const socket = ImmediateResponseSocket.instances.at(-1)!
    socket.onmessage?.({
      data: JSON.stringify({
        method: 'thread/snapshot',
        params: {
          thread_id: 'thread-1',
          snapshot_seq: 7,
          status: 'running',
        },
      }),
    })

    assert.equal(events.length, 0)
    assert.deepEqual(snapshots, [{
      thread_id: 'thread-1',
      snapshot_seq: 7,
      status: 'running',
    }])
  } finally {
    globalThis.WebSocket = previous
  }
})
