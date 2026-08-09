import { setTimeout as delay } from 'node:timers/promises'
import { describe, expect, it } from 'vitest'
import {
  createCoreAppServerRuntimeController,
  createCoreAppServerRuntimeState,
  selectChatMessages,
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

  it('interrupts without requesting a potentially large thread snapshot', async () => {
    const runtime = createCoreAppServerRuntimeState()
    const calls: Array<{ method: string; params: Record<string, unknown> }> = []
    runtime.client = fakeClient(async (method, params) => {
      calls.push({ method, params })
      return { events: [] }
    })
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: () => fakeClient(),
    })

    await controller.interruptTurn('thread-large', 'turn-active')

    expect(calls).toEqual([{
      method: 'turn/interrupt',
      params: {
        thread_id: 'thread-large',
        turn_id: 'turn-active',
        include_snapshot: false,
      },
    }])
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

  it('skips hydrating a snapshot that carries nothing new', async () => {
    const runtime = createCoreAppServerRuntimeState()
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: () => fakeClient(),
    })

    const initial = snapshot(1, 'running')
    initial.seen_event_ids = ['e1']
    controller.hydrate(initial)
    expect(runtime.state?.snapshot_seq).toBe(1)

    // Newer seq, but every event is already seen and no derived state
    // (requests / queue / status / items) differs — the state must NOT be
    // replaced (that would bust projection caches and force a full re-render).
    const redundant = snapshot(5, 'running')
    redundant.seen_event_ids = ['e1']
    controller.hydrate(redundant)
    expect(runtime.state?.snapshot_seq).toBe(1)
  })

  it('hydrates when the snapshot contains events not seen on the wire', async () => {
    const runtime = createCoreAppServerRuntimeState()
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: () => fakeClient(),
    })

    const initial = snapshot(1, 'running')
    initial.seen_event_ids = ['e1']
    controller.hydrate(initial)

    const missed = snapshot(5, 'running')
    missed.seen_event_ids = ['e1', 'e2']
    controller.hydrate(missed)
    expect(runtime.state?.snapshot_seq).toBe(5)
  })

  it('skips a snapshot whose events were all received on the wire mid-session', async () => {
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

    onEvent?.(runItemDelta('wire-1', 'hel'))

    const redundant = snapshot(5, 'running')
    redundant.seen_event_ids = ['wire-1']
    controller.hydrate(redundant)
    expect(runtime.state?.snapshot_seq).toBe(1)
  })

  it('hydrates when approval request states changed', async () => {
    const runtime = createCoreAppServerRuntimeState()
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: () => fakeClient(),
    })

    const initial = snapshot(1, 'running')
    initial.seen_event_ids = ['e1']
    controller.hydrate(initial)

    const withDecision = snapshot(5, 'running')
    withDecision.seen_event_ids = ['e1']
    withDecision.requests = {
      'functions.write_file:0': {
        request_id: 'functions.write_file:0',
        status: 'resolved',
        decision: 'approve_once',
      },
    }
    controller.hydrate(withDecision)
    expect(runtime.state?.snapshot_seq).toBe(5)
    expect(runtime.state?.requests?.['functions.write_file:0']?.status).toBe('resolved')
  })

  it('merges tool_result artifacts from the runItem top level into chat parts', async () => {
    // RunItemEvent serializes artifacts OUTSIDE payload (run_item.py to_dict);
    // the store must merge value.artifacts so image cards render from the
    // event stream without waiting for the turn-boundary snapshot.
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

    onEvent?.(runItemToolResult('tr-1', 'img-1'))
    frames[0]()

    // Artifacts merged into the snapshot-level core artifacts map.
    expect(runtime.state?.core?.artifacts?.['art-1']?.uri).toBe('.lam/artifacts/images/x.png')

    // Chat parts carry artifacts (image preview rendering prerequisite).
    const messages = selectChatMessages(runtime.state!)
    const part = messages.flatMap((message) => message.parts).find((p) => p.artifacts?.length)
    expect(part?.artifacts).toHaveLength(1)
    expect(part?.artifacts?.[0]?.kind).toBe('image')
    expect(part?.artifacts?.[0]?.artifact_id).toBe('art-1')
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
      const first = ReconnectingClient.requests.filter((item) => item.method === 'thread/resume').length === 1
      const seq = first ? 8 : 12
      const resumed = snapshot(seq, 'running')
      // The second resume snapshot carries an event the client has not seen
      // (it happened while disconnected), so it must be hydrated.
      resumed.seen_event_ids = first ? ['s1'] : ['s1', 's2']
      return { snapshot: resumed }
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
    core: coreState(seq, status),
  }
}

function coreState(seq: number, status: CoreAppSnapshot['status']): NonNullable<CoreAppSnapshot['core']> {
  return {
    thread_id: 'thread-1',
    snapshot_seq: seq,
    seen_event_ids: [],
    turns: {},
    items: {},
    item_order: [],
    requests: {},
    artifacts: {},
    status,
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

function runItemToolResult(eventId: string, itemId: string): CoreAppEvent {
  return {
    event_id: eventId,
    thread_id: 'thread-1',
    seq: 3,
    method: 'core/runItem',
    created_at: '2026-07-15T00:00:02Z',
    transient: true,
    item_id: itemId,
    turn_id: 'turn-1',
    payload: {
      event_id: eventId,
      thread_id: 'thread-1',
      item_id: itemId,
      turn_id: 'turn-1',
      kind: 'tool_result',
      status: 'completed',
      payload: {
        type: 'dynamicToolCall',
        tool_name: 'generate_image',
        tool_result: '[generate_image] 已生成 1 张图片',
        status: 'ok',
      },
      artifacts: [{
        artifact_id: 'art-1',
        item_id: itemId,
        kind: 'image',
        name: 'x.png',
        uri: '.lam/artifacts/images/x.png',
      }],
    },
  }
}
