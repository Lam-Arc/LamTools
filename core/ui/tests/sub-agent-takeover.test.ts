import { effectScope, nextTick } from 'vue'
import { describe, expect, it } from 'vitest'
import { createWorkbench } from '../src/workbench/createWorkbench'
import type { CoreAppServerRuntimeClient } from '../src/appServer/store'
import type { CoreAppSnapshot } from '../src/appServer/protocol'
import type { CoreSessionListItem, CoreSubAgentDurableRecord } from '../src/types'
import type {
  LamToolsTransport,
  TransportConnectionState,
  TransportMessage,
  TransportRequest,
} from '../src/transport'

/**
 * Core Task 1C: with the parent turn already terminal, the composer's Stop and
 * Resume controls address the delegated members instead of the parent turn.
 * They must never restart (or re-cancel) the parent.
 */

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

/** Snapshot whose main turn ended; only the transcript still shows the members. */
function terminalParentSnapshot(threadId: string, parentStatus: 'completed' | 'cancelled' | 'paused' = 'completed'): CoreAppSnapshot {
  return {
    thread_id: threadId,
    snapshot_seq: 4,
    revision: 4,
    turns: {
      'turn-1': {
        turn_id: 'turn-1',
        status: parentStatus,
        items: ['answer-1'],
        ...(parentStatus === 'completed' ? { waiting_on_members: false, running_members: [] } : {}),
      },
    },
    items: {},
    item_order: [],
    queue: [],
    requests: {},
    status: parentStatus,
    core: {
      thread_id: threadId,
      snapshot_seq: 4,
      revision: 4,
      status: parentStatus,
      turns: { 'turn-1': { turn_id: 'turn-1', status: parentStatus, items: ['answer-1'] } },
      items: {
        'answer-1': {
          item_id: 'answer-1',
          turn_id: 'turn-1',
          kind: 'message',
          status: 'completed',
          payload: { type: 'agentMessage', content: '已派出子代理。' },
        },
      },
      item_order: ['answer-1'],
      requests: {},
      artifacts: {},
    },
  }
}

class TakeoverClient implements CoreAppServerRuntimeClient {
  readonly methods: string[] = []
  readonly params: Array<{ method: string; params?: Record<string, unknown> }> = []
  constructor(
    private readonly threadId: string,
    private readonly onState: (state: 'connecting' | 'open' | 'closed' | 'error') => void,
    private readonly snapshotOf: () => CoreAppSnapshot,
    private readonly opResults: Record<string, Record<string, unknown>> = {},
    readonly capabilities: Record<string, unknown> = { same_turn_resume: true, sub_agent_control: true },
  ) {}
  async connect(): Promise<void> { this.onState('open') }
  async request(method: string, params?: Record<string, unknown>): Promise<Record<string, unknown>> {
    this.methods.push(method)
    this.params.push({ method, params })
    if (this.opResults[method]) return this.opResults[method]
    if (method.startsWith('sub_agent.')) return { items: [] }
    return { snapshot: this.snapshotOf() }
  }
  respondServerRequest(): boolean { return false }
  close(): void {}
}

function memberRecord(status: string, extra: Partial<CoreSubAgentDurableRecord> = {}): CoreSubAgentDurableRecord {
  return {
    name: 'worker',
    type: 'execute',
    status,
    started_at: 1_700_000_000,
    completed_at: status === 'running' ? null : 1_700_000_060,
    elapsed_ms: status === 'running' ? null : 60_000,
    sub_session_id: 'thread-1:sub:worker',
    ...extra,
  }
}

async function mountRuntime(
  snapshotOf: () => CoreAppSnapshot,
  opResults: Record<string, Record<string, unknown>> = {},
  capabilities: Record<string, unknown> = { same_turn_resume: true, sub_agent_control: true },
) {
  const sessions: CoreSessionListItem[] = [
    { id: 'thread-1', title: 'One', status: 'idle', createdAt: '' },
  ]
  let client!: TakeoverClient
  const scope = effectScope()
  const runtime = scope.run(() => createWorkbench({
    transport: new FakeTransport(),
    sessions: { listSessions: async () => sessions },
    // No cross-test draft leakage: the composer mode depends on an empty draft.
    composerDraftStorage: null,
    clientFactory: {
      createClient: ({ onConnectionState }) => {
        client = new TakeoverClient('thread-1', onConnectionState, snapshotOf, opResults, capabilities)
        return client
      },
    },
  }))!
  await runtime.refreshSessions()
  await runtime.selectSession('thread-1')
  await nextTick()
  await nextTick()
  return { runtime, client, scope }
}

describe('child-directed composer takeover (Core Task 1C)', () => {
  it('offers Stop for a running member after the parent turn ended and stops only the member', async () => {
    const { runtime, client, scope } = await mountRuntime(
      () => terminalParentSnapshot('thread-1'),
      { 'sub_agent.interrupt': { items: [memberRecord('interrupted')], lifecycle_action: 'members_interrupted' } },
    )
    runtime.setSubAgentRecords('thread-1', { worker: memberRecord('running') })
    await nextTick()

    expect(runtime.turnState.value).toBe('completed')
    expect(runtime.sessionActivity.value.awaitingSubAgents).toBe(true)
    expect(runtime.sessionActivity.value.interruptibleSubAgentNames).toEqual(['worker'])
    expect(runtime.composer.actionMode.value).toBe('stop')

    client.methods.length = 0
    client.params.length = 0
    await runtime.send('')

    expect(client.methods).toContain('sub_agent.interrupt')
    expect(client.methods).not.toContain('turn/interrupt')
    expect(client.methods).not.toContain('turn/force_reset')
    expect(client.methods).not.toContain('turn/start')
    expect(client.methods).not.toContain('turn/resume')
    expect(client.params[0].params).toEqual({ thread_id: 'thread-1' })
    // The response folds back into the same record map the poll fills.
    expect(runtime.sessionActivity.value.memberStatusRecords.worker.status).toBe('interrupted')
    scope.stop()
  })

  it('offers Resume for an interrupted member and resumes only the member', async () => {
    const { runtime, client, scope } = await mountRuntime(
      () => terminalParentSnapshot('thread-1'),
      { 'sub_agent.resume': { items: [memberRecord('running', { completed_at: null, elapsed_ms: null })], lifecycle_action: 'members_resumed' } },
    )
    runtime.setSubAgentRecords('thread-1', { worker: memberRecord('interrupted') })
    await nextTick()

    expect(runtime.composer.actionMode.value).toBe('resume')
    client.methods.length = 0
    await runtime.send('')

    expect(client.methods).toContain('sub_agent.resume')
    expect(client.methods).not.toContain('turn/resume')
    expect(client.methods).not.toContain('turn/start')
    expect(client.methods).not.toContain('turn/interrupt')
    expect(runtime.sessionActivity.value.memberStatusRecords.worker.status).toBe('running')
    scope.stop()
  })

  it('keeps Send for a real draft even while members are running', async () => {
    const { runtime, scope } = await mountRuntime(() => terminalParentSnapshot('thread-1'))
    runtime.setSubAgentRecords('thread-1', { worker: memberRecord('running') })
    await nextTick()

    runtime.composerText.value = '新的任务'
    await nextTick()
    expect(runtime.composer.actionMode.value).toBe('send')
    scope.stop()
  })

  it('still targets the parent turn while that turn is active, as a pause', async () => {
    const running = terminalParentSnapshot('thread-1')
    const runningTurn = { turn_id: 'turn-1', status: 'running', items: ['answer-1'], seq: 2 }
    running.status = 'running'
    running.turns = { 'turn-1': { ...runningTurn } }
    running.core!.status = 'running'
    running.core!.turns = { 'turn-1': { ...runningTurn } }
    const { runtime, client, scope } = await mountRuntime(() => running)
    runtime.setSubAgentRecords('thread-1', { worker: memberRecord('running') })
    await nextTick()

    expect(runtime.turnState.value).toBe('running')
    expect(runtime.composer.actionMode.value).toBe('stop')
    client.methods.length = 0
    await runtime.send('')

    expect(client.methods).toContain('turn/pause')
    expect(client.methods).not.toContain('sub_agent.interrupt')
    expect(client.methods).not.toContain('turn/interrupt')
    scope.stop()
  })

  it('keeps the same-turn Continue for a paused parent turn and also resumes interrupted members', async () => {
    const { runtime, client, scope } = await mountRuntime(
      () => terminalParentSnapshot('thread-1', 'paused'),
      { 'sub_agent.resume': { items: [memberRecord('running', { completed_at: null, elapsed_ms: null })], lifecycle_action: 'members_resumed' } },
    )
    runtime.setSubAgentRecords('thread-1', { worker: memberRecord('interrupted') })
    await nextTick()

    expect(runtime.composer.actionMode.value).toBe('resume')
    client.methods.length = 0
    await runtime.send('')

    expect(client.methods).toContain('turn/resume')
    expect(client.methods).toContain('sub_agent.resume')
    expect(client.methods).not.toContain('turn/start')
    scope.stop()
  })

  it('stays Send when no member evidence exists at all', async () => {
    const { runtime, scope } = await mountRuntime(() => terminalParentSnapshot('thread-1'))
    expect(runtime.sessionActivity.value.interruptibleSubAgentNames).toEqual([])
    expect(runtime.sessionActivity.value.resumableSubAgentNames).toEqual([])
    expect(runtime.composer.actionMode.value).toBe('send')
    scope.stop()
  })

  it('does not offer a child control the server cannot execute', async () => {
    const { runtime, scope } = await mountRuntime(
      () => terminalParentSnapshot('thread-1'),
      {},
      // Embedded mobile standalone: no child-directed operations.
      { standalone: true },
    )
    runtime.setSubAgentRecords('thread-1', { worker: memberRecord('interrupted') })
    runtime.composerText.value = ''
    await nextTick()

    expect(runtime.sessionActivity.value.resumableSubAgentNames).toEqual(['worker'])
    expect(runtime.composer.actionMode.value).toBe('send')
    scope.stop()
  })
})
