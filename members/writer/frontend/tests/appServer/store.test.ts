import assert from 'node:assert/strict'
import test from 'node:test'
import { setTimeout as delay } from 'node:timers/promises'
import { createPinia, setActivePinia } from 'pinia'
import { useWriterAppServerStore } from '../../src/appServer/store.ts'
import type { WriterAppSnapshot } from '../../src/appServer/protocol.ts'

test('response snapshot is authoritative over bundled events', () => {
  setActivePinia(createPinia())
  const store = useWriterAppServerStore()

  store.applyResponse({
    snapshot: snapshot(3, 'idle'),
  })

  assert.equal(store.state?.snapshot_seq, 3)
  assert.equal(store.state?.status, 'idle')
  assert.equal(store.state?.turns?.['turn-1'], undefined)
})

test('event-only responses do not create frontend state', () => {
  setActivePinia(createPinia())
  const store = useWriterAppServerStore()

  store.applyResponse({
    events: [{
      event_id: 'event-1',
      seq: 1,
      thread_id: 'thread-1',
      method: 'turn/started',
      payload: { type: 'turn', status: 'running' },
      created_at: '2026-06-29T00:00:00Z',
      turn_id: 'turn-1',
    }],
  })

  assert.equal(store.state, null)
})

test('startTurn sends text plus attachment input items', async () => {
  setActivePinia(createPinia())
  const store = useWriterAppServerStore()
  const calls: Array<{ method: string; params: Record<string, unknown> }> = []

  store.runtime.client = {
    request: async (method: string, params: Record<string, unknown>) => {
      calls.push({ method, params })
      return { snapshot: snapshot(1, 'running') }
    },
  } as never

  await store.startTurn('thread-1', [
    { type: 'text', text: '看附件' },
    { type: 'attachment', attachment_id: 'att-1', filename: 'note.md' },
  ])

  assert.equal(calls[0].method, 'turn/start')
  assert.deepEqual(calls[0].params.input, [
    { type: 'text', text: '看附件' },
    { type: 'attachment', attachment_id: 'att-1', filename: 'note.md' },
  ])
})

test('startTurn transports shallow thinking mode separately from native thinking', async () => {
  setActivePinia(createPinia())
  const store = useWriterAppServerStore()
  const calls: Array<{ method: string; params: Record<string, unknown> }> = []

  store.runtime.client = {
    request: async (method: string, params: Record<string, unknown>) => {
      calls.push({ method, params })
      return { snapshot: snapshot(1, 'running') }
    },
  } as never

  await store.startTurn('thread-1', '解释这个问题', '', {
    thinking_enabled: true,
    thinking_budget: 10000,
    shallow_thinking_enabled: true,
  })

  assert.equal(calls[0].method, 'turn/start')
  assert.equal(calls[0].params.thinking_enabled, true)
  assert.equal(calls[0].params.thinking_budget, 10000)
  assert.equal(calls[0].params.shallow_thinking_enabled, true)
})

test('store transports skill input items and command operations', async () => {
  setActivePinia(createPinia())
  const store = useWriterAppServerStore()
  const calls: Array<{ method: string; params: Record<string, unknown> }> = []

  store.runtime.client = {
    request: async (method: string, params: Record<string, unknown>) => {
      calls.push({ method, params })
      if (method === 'command.catalog') return { commands: [{ name: 'compact', action: 'run_action' }] }
      if (method === 'command.execute') return { result: { status: 'compacted' }, snapshot: snapshot(2, 'idle') }
      return { snapshot: snapshot(1, 'running') }
    },
  } as never

  await store.startTurn('thread-1', [
    { type: 'text', text: '请 ' },
    { type: 'skill', name: 'reviewer', source_text: '/reviewer' },
  ])
  const commands = await store.listCommands('E:\\LamTools')
  const result = await store.executeCommand('thread-1', 'compact', 'E:\\LamTools')

  assert.equal(calls[0].method, 'turn/start')
  assert.deepEqual(calls[0].params.input, [
    { type: 'text', text: '请 ' },
    { type: 'skill', name: 'reviewer', source_text: '/reviewer' },
  ])
  assert.deepEqual(commands, [{ name: 'compact', action: 'run_action' }])
  assert.equal(calls[2].method, 'command.execute')
  assert.deepEqual(result, { status: 'compacted' })
  assert.equal(store.state?.snapshot_seq, 2)
})

test('queueInput transports skill input items without flattening them to text', async () => {
  setActivePinia(createPinia())
  const store = useWriterAppServerStore()
  const calls: Array<{ method: string; params: Record<string, unknown> }> = []

  store.runtime.client = {
    request: async (method: string, params: Record<string, unknown>) => {
      calls.push({ method, params })
      return { snapshot: snapshot(3, 'running') }
    },
  } as never

  await store.queueInput('thread-1', [
    { type: 'text', text: '请 ' },
    { type: 'skill', name: 'reviewer', source_text: '/reviewer' },
  ])

  assert.equal(calls[0].method, 'queue/create')
  assert.deepEqual(calls[0].params.input, [
    { type: 'text', text: '请 ' },
    { type: 'skill', name: 'reviewer', source_text: '/reviewer' },
  ])
})

test('store reconnects after websocket close and resumes from the last seen snapshot', async () => {
  const previousWebSocket = globalThis.WebSocket
  const previousFetch = globalThis.fetch
  ReconnectingSocket.instances = []
  ReconnectingSocket.requests = []

  try {
    globalThis.WebSocket = ReconnectingSocket as unknown as typeof WebSocket
    globalThis.fetch = async () => ({
      ok: true,
      json: async () => ({ token: 'test-token' }),
    }) as Response

    setActivePinia(createPinia())
    const store = useWriterAppServerStore()

    await store.connect('http://127.0.0.1:6173', 'thread-1')
    assert.equal(store.state?.snapshot_seq, 8)

    ReconnectingSocket.instances[0].close()
    await delay(80)

    assert.ok(ReconnectingSocket.instances.length >= 2)
    const resumes = ReconnectingSocket.requests.filter((request) => request.method === 'thread/resume')
    assert.equal(resumes.length, 2)
    assert.equal(resumes[1].params.last_seen_seq, 8)
    assert.equal(store.state?.snapshot_seq, 12)
  } finally {
    globalThis.WebSocket = previousWebSocket
    globalThis.fetch = previousFetch
  }
})

class ReconnectingSocket {
  static readonly OPEN = 1
  static readonly CLOSED = 3
  static instances: ReconnectingSocket[] = []
  static requests: Array<{ id?: number | string; method: string; params: Record<string, unknown> }> = []

  readyState = ReconnectingSocket.OPEN
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  onclose: (() => void) | null = null
  onmessage: ((message: { data: string }) => void) | null = null

  constructor(readonly url: string) {
    ReconnectingSocket.instances.push(this)
    queueMicrotask(() => this.onopen?.())
  }

  send(raw: string): void {
    const request = JSON.parse(raw) as { id?: number | string; method: string; params?: Record<string, unknown> }
    ReconnectingSocket.requests.push({ ...request, params: request.params ?? {} })
    if (request.id === undefined) return

    const response = request.method === 'thread/resume'
      ? {
          snapshot: snapshot(
            ReconnectingSocket.requests.filter((item) => item.method === 'thread/resume').length === 1 ? 8 : 12,
            'running',
          ),
        }
      : { ok: true }
    this.onmessage?.({ data: JSON.stringify({ id: request.id, result: response }) })
  }

  close(): void {
    this.readyState = ReconnectingSocket.CLOSED
    this.onclose?.()
  }
}

function snapshot(seq: number, status: WriterAppSnapshot['status']): WriterAppSnapshot {
  return {
    thread_id: 'thread-1',
    snapshot_seq: seq,
    status,
    seen_event_ids: [],
    turns: {},
    items: {},
    item_order: [],
    queue: [],
    requests: {},
    artifacts: {},
  }
}
