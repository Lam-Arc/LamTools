import { effectScope, nextTick } from 'vue'
import { describe, expect, it } from 'vitest'
import { createWorkbench } from '../src/workbench/createWorkbench'
import type { CoreAppEvent, CoreAppSnapshot } from '../src/appServer/protocol'
import type { CoreAppServerRuntimeClient } from '../src/appServer/store'
import type { CoreSessionListItem } from '../src/types'
import { TransportRpcError } from '../src/transport'
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

/** Terminal main turn whose transcript still carries a running delegated sub-agent. */
function awaitingSubAgentSnapshot(threadId: string): CoreAppSnapshot {
  return {
    thread_id: threadId,
    snapshot_seq: 5,
    revision: 5,
    turns: {
      'turn-1': { turn_id: 'turn-1', status: 'completed', items: ['answer-1', 'agent-1'] },
    },
    items: {},
    item_order: [],
    queue: [],
    requests: {},
    status: 'completed',
    core: {
      thread_id: threadId,
      snapshot_seq: 5,
      revision: 5,
      status: 'completed',
      turns: {
        'turn-1': { turn_id: 'turn-1', status: 'completed', items: ['answer-1', 'agent-1'] },
      },
      items: {
        'answer-1': {
          item_id: 'answer-1',
          turn_id: 'turn-1',
          kind: 'message',
          status: 'completed',
          payload: { type: 'agentMessage', content: '已派出子代理。' },
        },
        'agent-1': {
          item_id: 'agent-1',
          turn_id: 'turn-1',
          kind: 'tool_call',
          status: 'running',
          payload: {
            type: 'dynamicToolCall',
            tool_name: 'sub_agent',
            arguments: { action: 'run', prompt: '后台任务' },
            metadata: { sub_session_id: 'sub-1', agent_name: 'worker' },
          },
        },
      },
      item_order: ['answer-1', 'agent-1'],
      requests: {},
      artifacts: {},
    },
  }
}

class AwaitingSubAgentClient implements CoreAppServerRuntimeClient {
  constructor(
    private readonly threadId: string,
    private readonly onState: (state: 'connecting' | 'open' | 'closed' | 'error') => void,
  ) {}
  async connect(): Promise<void> { this.onState('open') }
  async request(): Promise<Record<string, unknown>> {
    return { snapshot: awaitingSubAgentSnapshot(this.threadId) }
  }
  respondServerRequest(): boolean { return false }
  close(): void {}
}

/** A turn the runtime holds open for background members (or a genuinely running
 *  one, when `waiting` is false). */
function memberWaitSnapshot(threadId: string, waiting: boolean): CoreAppSnapshot {
  const turn = {
    turn_id: 'turn-1',
    status: 'running',
    items: [],
    ...(waiting ? { waiting_on_members: true, running_members: ['worker'] } : {}),
  }
  return {
    thread_id: threadId,
    snapshot_seq: 5,
    revision: 5,
    status: 'running',
    turns: { 'turn-1': { ...turn } },
    items: {},
    item_order: [],
    queue: [],
    requests: {},
    core: {
      thread_id: threadId,
      snapshot_seq: 5,
      revision: 5,
      status: 'running',
      turns: { 'turn-1': { ...turn } },
      items: {},
      item_order: [],
      requests: {},
      artifacts: {},
    },
  }
}

class RecordingClient implements CoreAppServerRuntimeClient {
  readonly methods: string[] = []
  constructor(
    private readonly threadId: string,
    private readonly state: CoreAppSnapshot,
    private readonly onState: (state: 'connecting' | 'open' | 'closed' | 'error') => void,
  ) {}
  async connect(): Promise<void> { this.onState('open') }
  async request(method: string): Promise<Record<string, unknown>> {
    this.methods.push(method)
    if (method === 'thread/read' || method === 'thread/resume') return { snapshot: this.state }
    return {}
  }
  respondServerRequest(): boolean { return false }
  close(): void {}
}

/** No active turn on the client, so a send tries to start one; the server then
 *  refuses it as busy, and the queue path is recorded. */
class BusyStartClient implements CoreAppServerRuntimeClient {
  readonly methods: string[] = []
  readonly queueIds: string[] = []
  readonly queueTexts: string[] = []
  constructor(
    private readonly state: CoreAppSnapshot,
    private readonly onState: (state: 'connecting' | 'open' | 'closed' | 'error') => void,
    private readonly queueFails = false,
  ) {}
  async connect(): Promise<void> { this.onState('open') }
  async request(method: string, params: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
    this.methods.push(method)
    if (method === 'thread/read' || method === 'thread/resume') return { snapshot: this.state }
    if (method === 'turn/start') {
      throw new TransportRpcError('INVALID_REQUEST', 'session has an active turn', {
        code: 'SESSION_BUSY',
        reason: 'active_turn_exists',
        active_run_id: 'run-1',
      })
    }
    if (method === 'queue/create') {
      if (this.queueFails) throw new Error('queue unavailable')
      const id = `q${this.queueIds.length + 1}`
      this.queueIds.push(String(params.client_message_id ?? ''))
      this.queueTexts.push(JSON.stringify(params.input))
      // The real runtime answers with the accepted event; the client reduces it
      // into the local queue, which is what makes the row visible.
      return {
        events: [{
          event_id: `queue/itemAccepted:${id}`,
          thread_id: 'thread-1',
          seq: 5,
          method: 'queue/itemAccepted',
          created_at: '2026-10-12T00:00:00Z',
          item_id: id,
          payload: { queue_item_id: id, status: 'queued', mode: 'next_turn', input: params.input },
        }],
      }
    }
    return {}
  }
  respondServerRequest(): boolean { return false }
  close(): void {}
}

/** An active turn on the client, with a steer the runtime refuses as
 *  `applied: false` (no live run to steer). */
class SteerRefusedClient implements CoreAppServerRuntimeClient {
  readonly methods: string[] = []
  readonly queueIds: string[] = []
  constructor(
    private readonly state: CoreAppSnapshot,
    private readonly onState: (state: 'connecting' | 'open' | 'closed' | 'error') => void,
  ) {}
  async connect(): Promise<void> { this.onState('open') }
  async request(method: string, params: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
    this.methods.push(method)
    if (method === 'thread/read' || method === 'thread/resume') return { snapshot: this.state }
    if (method === 'turn/steer') return { applied: false, reason: 'run_not_active' }
    if (method === 'queue/create') {
      this.queueIds.push(String(params.client_message_id ?? ''))
      return { events: [] }
    }
    return {}
  }
  respondServerRequest(): boolean { return false }
  close(): void {}
}

/** A session whose turn is already over. */
function finishedSnapshot(threadId: string): CoreAppSnapshot {
  const turn = { turn_id: 'turn-0', status: 'completed', items: [] }
  return {
    thread_id: threadId,
    snapshot_seq: 2,
    revision: 2,
    status: 'completed',
    turns: { 'turn-0': { ...turn } },
    items: {},
    item_order: [],
    queue: [],
    requests: {},
    core: {
      thread_id: threadId,
      snapshot_seq: 2,
      revision: 2,
      status: 'completed',
      turns: { 'turn-0': { ...turn } },
      items: {},
      item_order: [],
      requests: {},
      artifacts: {},
    },
  }
}

/** A session whose turn map holds a running turn while the thread-level status
 *  still reads the previous turn's terminal value (the state right after a new
 *  turn is accepted). */
function runningTurnWithStaleThreadStatus(threadId: string): CoreAppSnapshot {
  const turn = { turn_id: 'turn-1', status: 'running', items: [], seq: 4 }
  return {
    thread_id: threadId,
    snapshot_seq: 5,
    revision: 5,
    status: 'completed',
    turns: { 'turn-1': { ...turn } },
    items: {},
    item_order: [],
    queue: [],
    requests: {},
    core: {
      thread_id: threadId,
      snapshot_seq: 5,
      revision: 5,
      status: 'completed',
      turns: { 'turn-1': { ...turn } },
      items: {},
      item_order: [],
      requests: {},
      artifacts: {},
    },
  }
}

describe('shared Workbench runtime', () => {
  it.each([true, false])('offers Resume only when the runtime supports it (%s)', async (supported) => {
    const calls: string[] = []
    const stopped = snapshot('thread-1')
    // A pause is what offers Continue now; a terminated turn is final.
    stopped.status = 'paused'
    stopped.turns = { 'turn-1': { turn_id: 'turn-1', status: 'paused', items: [] } }
    stopped.core!.status = 'paused'
    stopped.core!.turns = stopped.turns
    const scope = effectScope()
    const runtime = scope.run(() => createWorkbench({
      transport: new FakeTransport(),
      sessions: { listSessions: async () => [{ id: 'thread-1', title: 'One', createdAt: '' }] },
      clientFactory: { createClient: ({ onConnectionState }) => ({
        capabilities: { same_turn_resume: supported },
        connect: async () => { onConnectionState('open') },
        request: async (method, params) => {
          calls.push(method)
          if (method === 'turn/resume') {
            expect(params?.turn_id).toBe('turn-1')
            expect(params?.input).toBeUndefined()
            return {}
          }
          return { snapshot: stopped }
        },
        respondServerRequest: () => false, close: () => undefined,
      }) },
    }))!
    try {
      await runtime.refreshSessions()
      await runtime.selectSession('thread-1')
      expect(runtime.actionMode.value).toBe(supported ? 'resume' : 'send')
      if (supported) {
        await runtime.composer.submit()
        expect(calls).toContain('turn/resume')
        expect(calls).not.toContain('turn/start')
      }
    } finally { scope.stop() }
  })

  it('shares registry lifecycle status with background indicators and rejects another thread record', async () => {
    const scope = effectScope()
    const runtime = scope.run(() => createWorkbench({ transport: new FakeTransport(),
      sessions: { listSessions: async () => [{ id: 'thread-1', title: 'One', createdAt: '' }] },
      clientFactory: { createClient: ({ onConnectionState }) => new AwaitingSubAgentClient('thread-1', onConnectionState) },
    }))!
    try {
      await runtime.refreshSessions()
      await runtime.selectSession('thread-1')
      expect(runtime.sessionActivity.value.awaitingSubAgents).toBe(true)
      runtime.setSubAgentRecords('other-thread', { worker: { name: 'worker', status: 'interrupted' } })
      expect(runtime.sessionActivity.value.awaitingSubAgents).toBe(true)
      runtime.setSubAgentRecords('thread-1', { worker: { name: 'worker', status: 'interrupted' } })
      expect(runtime.sessionActivity.value.awaitingSubAgents).toBe(false)
      expect(runtime.sessionActivity.value.memberStatuses.worker).toBe('interrupted')
      expect(runtime.sessionActivity.value.pendingSubAgentNames).toEqual([])
      await nextTick()
      expect(runtime.sessions.value[0].status).toBe('completed')
      runtime.setSubAgentRecords('thread-1', { worker: { name: 'worker', status: 'running', started_at: 1791897188 } })
      expect(runtime.sessionActivity.value.awaitingSubAgents).toBe(true)
      expect(runtime.sessionActivity.value.pendingSubAgentNames).toEqual(['worker'])
    } finally { scope.stop() }
  })

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

  it('reads state (b) when the main turn ended but a sub-agent is still running', async () => {
    const sessions: CoreSessionListItem[] = [
      { id: 'thread-1', title: 'One', status: 'idle', createdAt: '' },
    ]
    const scope = effectScope()
    const runtime = scope.run(() => createWorkbench({
      transport: new FakeTransport(),
      sessions: { listSessions: async () => sessions },
      clientFactory: {
        createClient: ({ onConnectionState }) => new AwaitingSubAgentClient('thread-1', onConnectionState),
      },
    }))!

    await runtime.refreshSessions()
    await runtime.selectSession('thread-1')
    await nextTick()
    await nextTick()

    // Raw thread status is terminal (the main agent stopped)...
    expect(runtime.turnState.value).toBe('completed')
    // ...but the delegated sub-agent is still running, so the session is busy in
    // the quiet state (b), not the generic running state.
    expect(runtime.sessionActivity.value.phase).toBe('awaiting_sub_agents')
    expect(runtime.sessionActivity.value.mainRunning).toBe(false)
    expect(runtime.sessionActivity.value.pendingSubAgentCount).toBe(1)
    // The sidebar publishes the distinct status instead of "running".
    expect(runtime.sessions.value[0]?.status).toBe('sub_agents')
    // The composer stays usable: send (not stop), so a new turn can start.
    expect(runtime.composer.actionMode.value).toBe('send')
    scope.stop()
  })

  it('routes a send to the open turn, never to a new one, while the main agent waits on members', async () => {    const sessions: CoreSessionListItem[] = [
      { id: 'thread-1', title: 'One', status: 'running', createdAt: '' },
    ]
    let client!: RecordingClient
    const scope = effectScope()
    const runtime = scope.run(() => createWorkbench({
      transport: new FakeTransport(),
      sessions: { listSessions: async () => sessions },
      clientFactory: {
        createClient: ({ onConnectionState }) => {
          client = new RecordingClient('thread-1', memberWaitSnapshot('thread-1', true), onConnectionState)
          return client
        },
      },
    }))!

    await runtime.refreshSessions()
    await runtime.selectSession('thread-1')
    await nextTick()

    // The display reads state (b), but the server still considers the turn
    // open, so the send path must use that turn rather than start a new one
    // (which the server would refuse as busy).
    expect(runtime.turnState.value).toBe('running')
    expect(runtime.sessionActivity.value.mainRunning).toBe(false)
    expect(runtime.sessionActivity.value.phase).toBe('awaiting_sub_agents')
    expect(runtime.composer.actionMode.value).toBe('stop')

    client.methods.length = 0
    await runtime.send('新的任务')

    expect(client.methods).toContain('queue/create')
    expect(client.methods).not.toContain('turn/start')
    scope.stop()
  })

  it('still queues onto a genuinely running turn, as before', async () => {
    const sessions: CoreSessionListItem[] = [
      { id: 'thread-1', title: 'One', status: 'running', createdAt: '' },
    ]
    let client!: RecordingClient
    const scope = effectScope()
    const runtime = scope.run(() => createWorkbench({
      transport: new FakeTransport(),
      sessions: { listSessions: async () => sessions },
      clientFactory: {
        createClient: ({ onConnectionState }) => {
          client = new RecordingClient('thread-1', memberWaitSnapshot('thread-1', false), onConnectionState)
          return client
        },
      },
    }))!

    await runtime.refreshSessions()
    await runtime.selectSession('thread-1')
    await nextTick()

    // Genuinely running: the stop affordance is offered while the box is empty,
    // and a typed message is queued onto the open turn.
    expect(runtime.sessionActivity.value.mainRunning).toBe(true)
    expect(runtime.composer.actionMode.value).toBe('stop')

    client.methods.length = 0
    await runtime.send('插一句')
    expect(client.methods).toContain('queue/create')
    expect(client.methods).not.toContain('turn/start')
    scope.stop()
  })

  it('queues the message when a turn start is refused as busy, with no error and no lost text', async () => {
    const sessions: CoreSessionListItem[] = [
      { id: 'thread-1', title: 'One', status: 'idle', createdAt: '' },
    ]
    let client!: BusyStartClient
    const errors: string[] = []
    const statuses: string[] = []
    const scope = effectScope()
    const runtime = scope.run(() => createWorkbench({
      transport: new FakeTransport(),
      sessions: { listSessions: async () => sessions },
      clientFactory: {
        createClient: ({ onConnectionState }) => {
          client = new BusyStartClient(finishedSnapshot('thread-1'), onConnectionState)
          return client
        },
      },
    }))!

    await runtime.refreshSessions()
    await runtime.selectSession('thread-1')
    await nextTick()
    runtime.setComposerCallbacks({
      onError: (message) => errors.push(message),
      onStatusText: (message) => statuses.push(message),
    })

    await runtime.send('要发的话')

    // A start was attempted, the server refused it as busy, and the fallback
    // actually issued the queue write instead of only suppressing the error.
    expect(client.methods).toContain('turn/start')
    expect(client.methods).toContain('queue/create')
    expect(client.queueIds).toHaveLength(1)
    expect(client.queueIds[0]).not.toBe('')
    expect(client.queueTexts[0]).toContain('要发的话')
    // No user-visible failure, and the item is shown as queued.
    expect(errors).toEqual([])
    expect(statuses).toContain('已加入待发送')
    // ...and it is actually visible in the queue tray, not silently dropped.
    expect(runtime.queuedInputs.value.map(item => item.text)).toEqual(['要发的话'])
    scope.stop()
  })

  it('keeps the typed text and reports when the busy fallback itself fails', async () => {
    const sessions: CoreSessionListItem[] = [
      { id: 'thread-1', title: 'One', status: 'idle', createdAt: '' },
    ]
    let client!: BusyStartClient
    const errors: string[] = []
    const scope = effectScope()
    const runtime = scope.run(() => createWorkbench({
      transport: new FakeTransport(),
      sessions: { listSessions: async () => sessions },
      clientFactory: {
        createClient: ({ onConnectionState }) => {
          client = new BusyStartClient(finishedSnapshot('thread-1'), onConnectionState, true)
          return client
        },
      },
    }))!

    await runtime.refreshSessions()
    await runtime.selectSession('thread-1')
    await nextTick()
    runtime.setComposerCallbacks({ onError: (message) => errors.push(message) })

    await runtime.send('要发的话')

    expect(client.methods).toContain('queue/create')
    expect(errors).toHaveLength(1)
    // Losing what the user typed is the worst outcome: it stays in the box.
    expect(runtime.composerText.value).toBe('要发的话')
    scope.stop()
  })

  it('queues a refused steer in guidance mode instead of dropping the message', async () => {
    const sessions: CoreSessionListItem[] = [
      { id: 'thread-1', title: 'One', status: 'running', createdAt: '' },
    ]
    let client!: SteerRefusedClient
    const errors: string[] = []
    const statuses: string[] = []
    const scope = effectScope()
    const runtime = scope.run(() => createWorkbench({
      transport: new FakeTransport(),
      sessions: { listSessions: async () => sessions },
      clientFactory: {
        createClient: ({ onConnectionState }) => {
          client = new SteerRefusedClient(memberWaitSnapshot('thread-1', false), onConnectionState)
          return client
        },
      },
    }))!

    await runtime.refreshSessions()
    await runtime.selectSession('thread-1')
    await nextTick()
    runtime.setComposerCallbacks({
      onError: (message) => errors.push(message),
      onStatusText: (message) => statuses.push(message),
    })

    runtime.composerText.value = '改成只读'
    await runtime.composer.submit({ clearComposer: true, forceGuide: true })

    expect(client.methods).toContain('turn/steer')
    expect(client.methods).toContain('queue/create')
    expect(client.queueIds).toHaveLength(1)
    expect(errors).toEqual([])
    expect(statuses).toContain('已加入待发送')
    scope.stop()
  })

  it('keeps the stop affordance and does not start a new turn while a running turn sits behind a stale thread status', async () => {
    const sessions: CoreSessionListItem[] = [
      { id: 'thread-1', title: 'One', status: 'completed', createdAt: '' },
    ]
    let client!: RecordingClient
    const scope = effectScope()
    const runtime = scope.run(() => createWorkbench({
      transport: new FakeTransport(),
      sessions: { listSessions: async () => sessions },
      clientFactory: {
        createClient: ({ onConnectionState }) => {
          client = new RecordingClient('thread-1', runningTurnWithStaleThreadStatus('thread-1'), onConnectionState)
          return client
        },
      },
    }))!

    await runtime.refreshSessions()
    await runtime.selectSession('thread-1')
    await nextTick()

    // The turn map is authoritative: a running turn is running even when the
    // thread status has not caught up yet.
    expect(runtime.turnState.value).toBe('running')
    expect(runtime.turnState.value).not.toBe('completed')
    // Stop affordance present (empty composer + running turn), never a new send.
    expect(runtime.composer.actionMode.value).toBe('stop')

    client.methods.length = 0
    await runtime.send('插一句')
    expect(client.methods).toContain('queue/create')
    expect(client.methods).not.toContain('turn/start')
    scope.stop()
  })

  it('offers the send affordance when the session has no active turn', async () => {
    const sessions: CoreSessionListItem[] = [
      { id: 'thread-1', title: 'One', status: 'completed', createdAt: '' },
    ]
    const scope = effectScope()
    const runtime = scope.run(() => createWorkbench({
      transport: new FakeTransport(),
      sessions: { listSessions: async () => sessions },
      clientFactory: {
        createClient: ({ onConnectionState }) => new RecordingClient('thread-1', finishedSnapshot('thread-1'), onConnectionState),
      },
    }))!

    await runtime.refreshSessions()
    await runtime.selectSession('thread-1')
    await nextTick()

    expect(runtime.turnState.value).toBe('completed')
    expect(runtime.composer.actionMode.value).toBe('send')
    scope.stop()
  })
})
