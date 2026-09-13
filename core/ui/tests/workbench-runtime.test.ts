import { effectScope, nextTick } from 'vue'
import { describe, expect, it } from 'vitest'
import { createWorkbench } from '../src/workbench/createWorkbench'
import type { CoreAppEvent, CoreAppSnapshot } from '../src/appServer/protocol'
import type { CoreAppServerRuntimeClient } from '../src/appServer/store'
import type { CoreSessionListItem } from '../src/types'
import type {
  LamToolsTransport,
  TransportConnectionState,
  TransportMessage,
  TransportRequest,
} from '../src/transport'

function snapshot(threadId: string): CoreAppSnapshot {
  return {
    thread_id: threadId,
    snapshot_seq: 1,
    turns: {},
    items: {},
    item_order: [],
    queue: [],
    requests: {},
    status: 'idle',
    core: {
      thread_id: threadId,
      snapshot_seq: 1,
      turns: {},
      items: {},
      item_order: [],
      requests: {},
      artifacts: {},
      status: 'idle',
    },
  }
}

function pagedSnapshot(
  threadId: string,
  firstTurn: number,
  lastTurn: number,
  hasMore: boolean,
): CoreAppSnapshot {
  const turns: NonNullable<CoreAppSnapshot['turns']> = {}
  const items: NonNullable<CoreAppSnapshot['core']>['items'] = {}
  const itemOrder: string[] = []
  for (let index = firstTurn; index <= lastTurn; index += 1) {
    const turnId = `turn-${index}`
    const itemId = `assistant-${index}`
    itemOrder.push(itemId)
    turns[turnId] = { turn_id: turnId, status: 'completed', items: [itemId] }
    items[itemId] = {
      item_id: itemId,
      turn_id: turnId,
      seq: index,
      kind: 'message',
      type: 'agentMessage',
      status: 'completed',
      content: `answer ${index}`,
      payload: { type: 'agentMessage' },
    }
  }
  return {
    thread_id: threadId,
    snapshot_seq: 20,
    turns,
    items: {},
    item_order: [],
    queue: [],
    requests: {},
    status: 'idle',
    history_page: {
      char_limit: 200_000,
      character_count: 0,
      turn_limit: 10,
      turn_count: lastTurn - firstTurn + 1,
      item_count: itemOrder.length,
      total_items: 20,
      has_more: hasMore,
      next_before_item_id: hasMore ? itemOrder[0] : null,
      next_before_seq: hasMore ? firstTurn : null,
    },
    core: {
      thread_id: threadId,
      snapshot_seq: 20,
      turns,
      items,
      item_order: itemOrder,
      requests: {},
      artifacts: {},
      status: 'idle',
    },
  }
}

class FakeClient implements CoreAppServerRuntimeClient {
  constructor(
    private readonly threadId: string,
    private readonly calls: string[],
    private readonly onState: (state: 'connecting' | 'open' | 'closed' | 'error') => void,
  ) {}
  async connect(): Promise<void> { this.calls.push('connect'); this.onState('open') }
  async request(method: string): Promise<Record<string, unknown>> {
    this.calls.push(method)
    return { snapshot: snapshot(this.threadId) }
  }
  respondServerRequest(): boolean { return false }
  close(): void { this.calls.push('close') }
}

class FakeTransport implements LamToolsTransport {
  private state: TransportConnectionState = 'disconnected'
  private readonly stateListeners = new Set<(state: TransportConnectionState) => void>()
  async connect(): Promise<void> { this.state = 'connected' }
  async close(): Promise<void> {
    this.state = 'disconnected'
    for (const listener of this.stateListeners) listener(this.state)
  }
  async request<TResponse = unknown>(_request: TransportRequest): Promise<TResponse> {
    return {} as TResponse
  }
  send(_message: TransportMessage): void {}
  subscribe(_handler: (message: TransportMessage) => void): () => void { return () => {} }
  onState(handler: (state: TransportConnectionState) => void): () => void {
    this.stateListeners.add(handler)
    handler(this.state)
    return () => this.stateListeners.delete(handler)
  }
  getState() { return this.state }
}

class GatedClient implements CoreAppServerRuntimeClient {
  connected = false
  constructor(
    private readonly gate: Promise<void>,
    private readonly threadId: string,
    private readonly onState: (state: 'connecting' | 'open' | 'closed' | 'error') => void,
  ) {}
  async connect(): Promise<void> {
    await this.gate
    this.connected = true
    this.onState('open')
  }
  async request(): Promise<Record<string, unknown>> {
    if (!this.connected) throw new Error('request sent before initialize')
    return { snapshot: snapshot(this.threadId) }
  }
  respondServerRequest(): boolean { return false }
  close(): void { this.connected = false }
}

class HistoryPrefetchClient implements CoreAppServerRuntimeClient {
  readonly calls: Array<{ method: string; params?: Record<string, unknown> }> = []

  constructor(
    private readonly threadId: string,
    private readonly onState: (state: 'connecting' | 'open' | 'closed' | 'error') => void,
  ) {}

  async connect(): Promise<void> { this.onState('open') }
  async request(method: string, params?: Record<string, unknown>): Promise<Record<string, unknown>> {
    this.calls.push({ method, params })
    if (method === 'thread/resume') return { snapshot: pagedSnapshot(this.threadId, 11, 20, true) }
    if (method === 'thread.history') return { snapshot_page: pagedSnapshot(this.threadId, 1, 10, false) }
    return {}
  }
  respondServerRequest(): boolean { return false }
  close(): void {}
}

describe('shared Workbench runtime', () => {
  it('owns session selection while shells only provide presentation', async () => {
    const sessions: CoreSessionListItem[] = [
      { id: 'thread-1', title: 'One', createdAt: '' },
      { id: 'thread-2', title: 'Two', createdAt: '' },
    ]
    const calls: string[] = []
    const scope = effectScope()
    const runtime = scope.run(() => createWorkbench({
      transport: new FakeTransport(),
      sessions: { listSessions: async () => sessions },
      clientFactory: {
        createClient: ({ onConnectionState }) => new FakeClient('thread-1', calls, onConnectionState),
      },
    }))!

    await runtime.refreshSessions()
    await runtime.selectSession('thread-1')
    expect(runtime.activeSessionId.value).toBe('thread-1')
    expect(runtime.connectionState.value).toBe('open')
    expect(calls).toContain('thread/resume')

    await runtime.selectSession('thread-2')
    expect(runtime.activeSessionId.value).toBe('thread-2')
    expect(calls.filter((call) => call === 'connect')).toHaveLength(1)
    expect(calls.filter((call) => call === 'close')).toHaveLength(0)
    scope.stop()
  })

  it('waits for an in-flight initialize before concurrent RPC requests', async () => {
    let release!: () => void
    const gate = new Promise<void>((resolve) => { release = resolve })
    const scope = effectScope()
    const runtime = scope.run(() => createWorkbench({
      transport: new FakeTransport(),
      clientFactory: {
        createClient: ({ onConnectionState }) => new GatedClient(gate, 'thread-1', onConnectionState),
      },
    }))!

    const first = runtime.requestRpc('sync.start')
    await Promise.resolve()
    const second = runtime.requestRpc('sync.start')
    release()

    await expect(Promise.all([first, second])).resolves.toHaveLength(2)
    scope.stop()
  })

  it('updates the active sidebar session when the canonical turn reaches terminal state', async () => {
    const sessions: CoreSessionListItem[] = [
      { id: 'thread-1', title: 'One', status: 'idle', createdAt: '' },
    ]
    let onEvent: ((event: CoreAppEvent) => void) | undefined
    const scope = effectScope()
    const runtime = scope.run(() => createWorkbench({
      transport: new FakeTransport(),
      sessions: { listSessions: async () => sessions },
      clientFactory: {
        createClient: ({ onEvent: eventHandler, onConnectionState }) => {
          onEvent = eventHandler
          return new FakeClient('thread-1', [], onConnectionState)
        },
      },
    }))!

    await runtime.refreshSessions()
    await runtime.selectSession('thread-1')
    onEvent?.({
      event_id: 'terminal-1',
      thread_id: 'thread-1',
      seq: 2,
      revision: 2,
      method: 'core/runItem',
      created_at: '2026-07-15T00:00:00Z',
      turn_id: 'turn-1',
      payload: {
        event_id: 'terminal-1',
        thread_id: 'thread-1',
        turn_id: 'turn-1',
        kind: 'status',
        status: 'completed',
        payload: { type: 'turn', status: 'completed' },
      },
    })
    await new Promise((resolve) => setTimeout(resolve, 70))

    expect(runtime.sessions.value[0]?.status).toBe('completed')
    scope.stop()
  })

  it('prefetches one complete history page and reveals it without a foreground RPC', async () => {
    const sessions: CoreSessionListItem[] = [
      { id: 'thread-history', title: 'History', status: 'idle', createdAt: '' },
    ]
    let client!: HistoryPrefetchClient
    const scope = effectScope()
    const runtime = scope.run(() => createWorkbench({
      transport: new FakeTransport(),
      sessions: { listSessions: async () => sessions },
      clientFactory: {
        createClient: ({ onConnectionState }) => {
          client = new HistoryPrefetchClient('thread-history', onConnectionState)
          return client
        },
      },
    }))!

    await runtime.refreshSessions()
    await runtime.selectSession('thread-history')
    await nextTick()
    await nextTick()

    const prefetchedCalls = client.calls.filter(call => call.method === 'thread.history')
    expect(prefetchedCalls).toHaveLength(1)
    expect(prefetchedCalls[0]?.params?.turn_limit).toBe(10)
    expect(runtime.historyBuffered.value).toBe(true)
    expect(runtime.messages.value).toHaveLength(10)

    await runtime.loadMoreHistory()
    expect(client.calls.filter(call => call.method === 'thread.history')).toHaveLength(1)
    await nextTick()
    expect(runtime.messages.value).toHaveLength(20)
    expect(runtime.hasMoreHistory.value).toBe(false)
    scope.stop()
  })
})
