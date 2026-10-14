import { effectScope, nextTick } from 'vue'
import { describe, expect, it } from 'vitest'
import { createWorkbench } from '../src/workbench/createWorkbench'
import { applyCoreAppEvent } from '../src/appServer/store'
import { selectLatestTurnStatus } from '../src/appServer/selectors'
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
 * Stop is a pause, Continue is the same turn.
 *
 * A single click on the composer's action button parks the running turn
 * (turn/pause); the composer then offers Continue for that same turn, an empty
 * draft continues it, a typed draft continues it with that text as a
 * supplementary input, and the long-press confirm terminates it for good
 * (turn/terminate). A terminated turn offers nothing.
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

function snapshotWithTurn(threadId: string, status: 'running' | 'paused' | 'cancelled'): CoreAppSnapshot {
  return {
    thread_id: threadId,
    snapshot_seq: 4,
    revision: 4,
    turns: { 'turn-1': { turn_id: 'turn-1', status, items: ['answer-1'] } },
    items: {},
    item_order: [],
    queue: [],
    requests: {},
    status,
    core: {
      thread_id: threadId,
      snapshot_seq: 4,
      revision: 4,
      status,
      turns: { 'turn-1': { turn_id: 'turn-1', status, items: ['answer-1'] } },
      items: {
        'answer-1': {
          item_id: 'answer-1',
          turn_id: 'turn-1',
          kind: 'message',
          status: 'completed',
          payload: { type: 'agentMessage', content: '工作中。' },
        },
      },
      item_order: ['answer-1'],
      requests: {},
      artifacts: {},
    },
  }
}

class RecordingClient implements CoreAppServerRuntimeClient {
  readonly methods: string[] = []
  readonly params: Array<{ method: string; params?: Record<string, unknown> }> = []
  constructor(
    private readonly onState: (state: 'connecting' | 'open' | 'closed' | 'error') => void,
    private readonly snapshotOf: () => CoreAppSnapshot,
    readonly capabilities: Record<string, unknown> = { same_turn_resume: true, sub_agent_control: true },
  ) {}
  async connect(): Promise<void> { this.onState('open') }
  async request(method: string, params?: Record<string, unknown>): Promise<Record<string, unknown>> {
    this.methods.push(method)
    this.params.push({ method, params })
    if (method.startsWith('sub_agent.')) return { items: [] }
    return { snapshot: this.snapshotOf() }
  }
  respondServerRequest(): boolean { return false }
  close(): void {}
}

function memberRecord(status: string): CoreSubAgentDurableRecord {
  return {
    name: 'worker',
    type: 'execute',
    status,
    started_at: 1_700_000_000,
    completed_at: status === 'running' ? null : 1_700_000_060,
    elapsed_ms: status === 'running' ? null : 60_000,
    sub_session_id: 'thread-1:sub:worker',
  }
}

async function mountRuntime(status: 'running' | 'paused' | 'cancelled') {
  const sessions: CoreSessionListItem[] = [
    { id: 'thread-1', title: 'One', status: 'idle', createdAt: '' },
  ]
  let client!: RecordingClient
  const scope = effectScope()
  const runtime = scope.run(() => createWorkbench({
    transport: new FakeTransport(),
    sessions: { listSessions: async () => sessions },
    composerDraftStorage: null,
    clientFactory: {
      createClient: ({ onConnectionState }) => {
        client = new RecordingClient(onConnectionState, () => snapshotWithTurn('thread-1', status))
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

describe('the live pause event reaches the client status', () => {
  it('accepts the paused status instead of keeping the previous one', () => {
    // The regression behind "two of three tests ended as 已中断": the client's
    // status guard did not know `paused`, so the live pause event fell back to
    // `running`, the composer still believed the turn was active, and its 3 s
    // stop-grace timer force-reset the turn the user had just paused.
    const running = snapshotWithTurn('thread-1', 'running')
    const paused = applyCoreAppEvent(running, {
      method: 'core/runItem',
      seq: 5,
      event_id: 'event-pause',
      item_id: 'turn-1:exec:paused',
      thread_id: 'thread-1',
      turn_id: 'turn-1',
      created_at: new Date(0).toISOString(),
      payload: {
        item_id: 'turn-1:exec:paused',
        turn_id: 'turn-1',
        kind: 'status',
        status: 'paused',
        payload: { type: 'turn', status: 'paused', raw_end_reason: 'user_pause' },
      },
    })

    expect(selectLatestTurnStatus(paused)).toBe('paused')
    expect(paused.turns?.['turn-1']?.status).toBe('paused')
    expect(paused.status).toBe('paused')
  })
})

describe('an answered request does not revive a paused turn', () => {
  it('keeps the paused status when a member question is answered', () => {
    // The stuck-running defect: the answer flipped the turn back to running
    // although its run had already ended, so the session read as running with
    // nothing running until the user terminated it by hand (2026-10-14).
    const paused = snapshotWithTurn('thread-1', 'paused')
    const answered = applyCoreAppEvent(paused, {
      method: 'core/runItem',
      seq: 6,
      event_id: 'event-answer',
      item_id: 'child-question',
      thread_id: 'thread-1',
      turn_id: 'turn-1',
      created_at: new Date(0).toISOString(),
      payload: {
        item_id: 'child-question',
        turn_id: 'turn-1',
        kind: 'approval_response',
        status: 'completed',
        payload: { type: 'serverRequest', request_id: 'child_question', decision: 'guide', status: 'resolved' },
      },
    })

    expect(answered.turns?.['turn-1']?.status).toBe('paused')
    expect(answered.core?.turns?.['turn-1']?.status).toBe('paused')
    expect(selectLatestTurnStatus(answered)).toBe('paused')
  })
})

describe('the composer treats Stop as a pause', () => {
  it('sends turn/pause for a running turn instead of the terminal interrupt', async () => {
    const { runtime, client, scope } = await mountRuntime('running')

    expect(runtime.composer.actionMode.value).toBe('stop')
    client.methods.length = 0
    client.params.length = 0
    await runtime.send('')

    expect(client.methods).toContain('turn/pause')
    expect(client.methods).not.toContain('turn/interrupt')
    expect(client.methods).not.toContain('turn/terminate')
    expect(client.methods).not.toContain('turn/force_reset')
    expect(client.params[0].params?.reason).toBe('user_pause')
    scope.stop()
  })

  it('offers Continue for a paused turn and continues that same turn', async () => {
    const { runtime, client, scope } = await mountRuntime('paused')

    expect(runtime.composer.actionMode.value).toBe('resume')
    client.methods.length = 0
    client.params.length = 0
    await runtime.send('')

    expect(client.methods).toContain('turn/resume')
    expect(client.methods).not.toContain('turn/start')
    expect(client.methods).not.toContain('turn/interrupt')
    const resume = client.params.find((entry) => entry.method === 'turn/resume')
    expect(resume?.params?.turn_id).toBe('turn-1')
    // An empty composer continues the turn with no new input.
    expect(resume?.params?.input).toBeUndefined()
    scope.stop()
  })

  it('continues the paused turn with the typed text as a supplementary input', async () => {
    const { runtime, client, scope } = await mountRuntime('paused')

    runtime.composerText.value = '先按方案 A 做'
    await nextTick()

    client.methods.length = 0
    client.params.length = 0
    await runtime.send('')

    expect(client.methods).toContain('turn/resume')
    expect(client.methods).not.toContain('turn/start')
    const resume = client.params.find((entry) => entry.method === 'turn/resume')
    expect(resume?.params?.input).toEqual([{ type: 'text', text: '先按方案 A 做' }])
    // The message went into the turn, so the composer is empty again.
    expect(runtime.composerText.value).toBe('')
    scope.stop()
  })

  it('never offers Continue for a terminated turn', async () => {
    const { runtime, scope } = await mountRuntime('cancelled')

    expect(runtime.composer.actionMode.value).toBe('send')
    scope.stop()
  })

  it('terminates the turn and its members when the long-press confirm runs', async () => {
    const { runtime, client, scope } = await mountRuntime('paused')

    client.methods.length = 0
    client.params.length = 0
    const terminated = await runtime.composer.terminate()

    expect(terminated).toBe(true)
    expect(client.methods).toContain('turn/terminate')
    const terminate = client.params.find((entry) => entry.method === 'turn/terminate')
    expect(terminate?.params?.turn_id).toBe('turn-1')
    scope.stop()
  })

  it('keeps the member Continue disabled while the session itself is paused', async () => {
    const { runtime, scope } = await mountRuntime('paused')

    runtime.setSubAgentRecords('thread-1', { worker: memberRecord('suspended') })
    await nextTick()

    // The session's Continue owns the press; a member cannot run on its own.
    expect(runtime.composer.actionMode.value).toBe('resume')
    expect(runtime.sessionActivity.value.resumableSubAgentNames).toEqual([])
    scope.stop()
  })
})
