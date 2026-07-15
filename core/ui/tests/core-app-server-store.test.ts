import { setTimeout as delay } from 'node:timers/promises'
import { describe, expect, it } from 'vitest'
import {
  createCoreAppServerRuntimeController,
  createCoreAppServerRuntimeState,
  type CoreAppServerRuntimeClient,
  type CoreAppEvent,
  type CoreAppSnapshot,
} from '../src/appServer'

describe('core appServer runtime store', () => {
  it('applies native run-item deltas in order with one render-frame flush', async () => {
    const runtime = createCoreAppServerRuntimeState()
    const frames: Array<() => void> = []
    let onEvent: ((event: CoreAppEvent) => void) | undefined
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: (callbacks) => {
        onEvent = callbacks.onEvent
        return fakeClient(async (method) => method === 'thread/resume'
          ? { snapshot: snapshot(1, 'running') }
          : {})
      },
      scheduleFrame: (callback) => frames.push(callback),
    })
    await controller.connect('http://127.0.0.1:6173', 'thread-1')

    onEvent?.(runItemDelta('delta-1', 'hel'))
    onEvent?.(runItemDelta('delta-2', 'lo'))

    expect(frames).toHaveLength(1)
    expect(runtime.state?.core?.items?.['response-1']).toBeUndefined()
    frames[0]()
    expect(runtime.state?.core?.items?.['response-1']?.content).toBe('hello')
  })

  it('applies a run-item turn terminal state without requiring an item id', async () => {
    const runtime = createCoreAppServerRuntimeState()
    const frames: Array<() => void> = []
    let onEvent: ((event: CoreAppEvent) => void) | undefined
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: (callbacks) => {
        onEvent = callbacks.onEvent
        return fakeClient(async (method) => method === 'thread/resume'
          ? { snapshot: snapshot(1, 'running') }
          : {})
      },
      scheduleFrame: (callback) => frames.push(callback),
    })
    await controller.connect('http://127.0.0.1:6173', 'thread-1')

    onEvent?.(runStatusEvent('done-1', 'completed'))
    frames[0]()

    expect(runtime.state?.core?.turns?.['turn-1']?.status).toBe('completed')
    expect(runtime.state?.core?.status).toBe('completed')
  })

  it('uses response snapshots as the authoritative frontend state', () => {
    const runtime = createCoreAppServerRuntimeState()
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: () => fakeClient(),
    })

    controller.applyResponse({ snapshot: snapshot(3, 'idle') })

    expect(runtime.state?.snapshot_seq).toBe(3)
    expect(runtime.state?.status).toBe('idle')
  })

  it('transports text, structured input items, and command operations', async () => {
    const runtime = createCoreAppServerRuntimeState()
    const calls: Array<{ method: string; params: Record<string, unknown> }> = []
    runtime.client = fakeClient(async (method, params) => {
      calls.push({ method, params })
      if (method === 'command.catalog') return { commands: [{ name: 'compact', action: 'run_action' }] }
      if (method === 'command.execute') return { result: { status: 'compacted' }, snapshot: snapshot(2, 'idle') }
      if (method === 'queue/guide') return { applied: true, reason: '', snapshot: snapshot(3, 'running') }
      return { snapshot: snapshot(1, 'running') }
    })
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: () => fakeClient(),
    })

    await controller.startTurn('thread-1', [
      { type: 'text', text: '请 ' },
      { type: 'skill', name: 'reviewer', source_text: '/reviewer' },
    ])
    const commands = await controller.listCommands('E:\\LamTools')
    const result = await controller.executeCommand('thread-1', 'compact', 'E:\\LamTools')
    const guided = await controller.guideQueueInput('thread-1', 'turn-1', 'queue-1', 'updated guidance')

    expect(calls[0].method).toBe('turn/start')
    expect(calls[0].params.input).toEqual([
      { type: 'text', text: '请 ' },
      { type: 'skill', name: 'reviewer', source_text: '/reviewer' },
    ])
    expect(commands).toEqual([{ name: 'compact', action: 'run_action' }])
    expect(result).toEqual({ status: 'compacted' })
    expect(guided).toEqual({ applied: true, reason: '' })
    expect(calls[3]).toMatchObject({
      method: 'queue/guide',
      params: {
        thread_id: 'thread-1',
        turn_id: 'turn-1',
        queue_item_id: 'queue-1',
        client_message_id: 'queue-guide:queue-1',
        text: 'updated guidance',
      },
    })
    expect(runtime.state?.snapshot_seq).toBe(3)
  })

  it('responds through the explicit approval operation with the logical request id', async () => {
    const runtime = createCoreAppServerRuntimeState()
    const calls: Array<{ method: string; params: Record<string, unknown> }> = []
    runtime.client = fakeClient(async (method, params) => {
      calls.push({ method, params })
      return { snapshot: snapshot(4, 'running') }
    })
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: () => fakeClient(),
    })

    await controller.respondApproval('functions.write_file:0', 'approve_once', '')

    expect(calls).toEqual([
      {
        method: 'approval/respond',
        params: {
          request_id: 'functions.write_file:0',
          decision: 'approve_once',
          guidance: '',
        },
      },
    ])
    expect(runtime.state?.snapshot_seq).toBe(4)
  })

  it('reconnects after socket close and resumes from last snapshot sequence', async () => {
    const runtime = createCoreAppServerRuntimeState<CoreAppSnapshot, ReconnectingClient>()
    ReconnectingClient.instances = []
    ReconnectingClient.requests = []
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: ({ onSnapshot, onConnectionState }) => new ReconnectingClient(onSnapshot, onConnectionState),
      reconnectBaseMs: 25,
      reconnectMaxMs: 2_000,
    })

    await controller.connect('http://127.0.0.1:6173', 'thread-1')
    expect(runtime.state?.snapshot_seq).toBe(8)

    ReconnectingClient.instances[0].close()
    await delay(80)

    expect(ReconnectingClient.instances.length).toBeGreaterThanOrEqual(2)
    const resumes = ReconnectingClient.requests.filter((request) => request.method === 'thread/resume')
    expect(resumes).toHaveLength(2)
    expect(resumes[1].params.last_seen_seq).toBe(8)
    expect(runtime.state?.snapshot_seq).toBe(12)
  })
})

function fakeClient(
  request: (method: string, params: Record<string, unknown>) => Promise<Record<string, unknown>> = async () => ({}),
): CoreAppServerRuntimeClient {
  return {
    async connect() {},
    request,
    close() {},
  }
}

class ReconnectingClient implements CoreAppServerRuntimeClient {
  static instances: ReconnectingClient[] = []
  static requests: Array<{ method: string; params: Record<string, unknown> }> = []

  constructor(
    private readonly onSnapshot: (snapshot: CoreAppSnapshot) => void,
    private readonly onConnectionState: (state: 'connecting' | 'open' | 'closed' | 'error') => void,
  ) {
    ReconnectingClient.instances.push(this)
  }

  async connect() {
    this.onConnectionState('open')
  }

  async request(method: string, params: Record<string, unknown> = {}) {
    ReconnectingClient.requests.push({ method, params })
    if (method === 'thread/resume') {
      const seq = ReconnectingClient.requests.filter((item) => item.method === 'thread/resume').length === 1 ? 8 : 12
      return { snapshot: snapshot(seq, 'running') }
    }
    return { ok: true }
  }

  close() {
    this.onConnectionState('closed')
  }
}

function snapshot(seq: number, status: CoreAppSnapshot['status']): CoreAppSnapshot {
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

function runItemDelta(eventId: string, delta: string): CoreAppEvent {
  return {
    event_id: eventId,
    thread_id: 'thread-1',
    seq: 0,
    method: 'core/runItem',
    created_at: '2026-07-15T00:00:00Z',
    transient: true,
    item_id: 'response-1',
    turn_id: 'turn-1',
    payload: {
      event_id: eventId,
      thread_id: 'thread-1',
      item_id: 'response-1',
      turn_id: 'turn-1',
      kind: 'message',
      status: 'running',
      payload: { type: 'agentMessage', delta },
    },
  }
}

function runStatusEvent(eventId: string, status: string): CoreAppEvent {
  return {
    event_id: eventId,
    thread_id: 'thread-1',
    seq: 2,
    method: 'core/runItem',
    created_at: '2026-07-15T00:00:01Z',
    turn_id: 'turn-1',
    payload: {
      event_id: eventId,
      thread_id: 'thread-1',
      turn_id: 'turn-1',
      kind: 'status',
      status,
      payload: { type: 'turn', status },
    },
  }
}
