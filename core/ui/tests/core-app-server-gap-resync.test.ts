import { describe, expect, it, vi } from 'vitest'
import { CoreAppServerClient } from '../src/appServer/client'
import {
  createCoreAppServerRuntimeController,
  createCoreAppServerRuntimeState,
  selectChatMessages,
  type CoreAppEvent,
  type CoreAppSnapshot,
} from '../src/appServer'
import type {
  LamToolsTransport,
  TransportConnectionState,
  TransportMessage,
  TransportRequest,
} from '../src/transport'

/**
 * `thread/gap` is the server's reliable-lane notice that its lossy outbound lane
 * dropped frames. The reaction must mirror the backend's reference client:
 * resume from the sequence we have actually applied, coalesce a burst into one
 * resume, and never surface the gap itself as an event.
 */
describe('app-server gap resync', () => {
  it('resumes from its own applied sequence and converges after a dropped-frame gap', async () => {
    const transport = new GapRpcTransport()
    let resumes = 0
    transport.handler = async (method) => {
      if (method !== 'thread/resume') return {}
      resumes += 1
      // First resume is the attach; the gap resync redelivers the canonical page
      // for the thread, which now contains the frame the lossy lane dropped.
      return resumes === 1 ? { snapshot: snapshot(1, 'running') } : { snapshot: resumedSnapshot() }
    }
    const { runtime, controller, frames } = harness(transport)
    await controller.connect('thread-1')
    expect(transport.resumeParams()).toEqual([{ thread_id: 'thread-1', last_seen_seq: 0 }])

    // A frame that did arrive moves our own applied cursor to 5.
    transport.notify('core/runItem', runItemFrame('live-5', 5, 5, '第一段'))
    flushFrames(frames)
    expect(runtime.state?.snapshot_seq).toBe(5)

    transport.notify('thread/gap', { thread_id: 'thread-1', reason: 'outbound_dropped', dropped: 3 })
    // The gap is a control signal: it must not enter the event queue.
    expect(frames).toHaveLength(0)

    await vi.waitFor(() => expect(transport.resumeParams()).toHaveLength(2))
    // Resumed from our own revision (5), not from scratch.
    expect(transport.resumeParams()[1]).toEqual({ thread_id: 'thread-1', last_seen_seq: 5 })
    // The view converges on what the drop lost instead of waiting for a snapshot.
    await vi.waitFor(() => {
      expect(runtime.state?.core?.items?.['response-2']?.content).toBe('（掉队的那一段）')
    })
    // One gap, one resume: converging must not trigger another.
    expect(transport.resumeParams()).toHaveLength(2)
    const projected = projectedText(runtime.state!)
    expect(projected).toContain('第一段')
    expect(projected).toContain('（掉队的那一段）')
  })

  it('coalesces a burst of gaps into one in-flight resume', async () => {
    const transport = new GapRpcTransport()
    const held = deferred<Record<string, unknown>>()
    let resumes = 0
    transport.handler = async (method) => {
      if (method !== 'thread/resume') return {}
      resumes += 1
      return resumes === 1 ? { snapshot: snapshot(1, 'running') } : await held.promise
    }
    const { runtime, controller } = harness(transport)
    await controller.connect('thread-1')

    transport.notify('thread/gap', { thread_id: 'thread-1', reason: 'outbound_dropped', dropped: 1 })
    transport.notify('thread/gap', { thread_id: 'thread-1', reason: 'outbound_dropped', dropped: 2 })
    transport.notify('thread/gap', { thread_id: 'thread-1', reason: 'outbound_dropped', dropped: 3 })
    await vi.waitFor(() => expect(resumes).toBe(2))
    await Promise.resolve()
    // The server rate-limits its own notice, but a burst inside one resume must
    // not stack duplicates: the running resume already covers the newest seq.
    expect(resumes).toBe(2)

    held.resolve({ snapshot: resumedSnapshot() })
    await vi.waitFor(() => expect(runtime.state?.snapshot_seq).toBe(6))
    expect(resumes).toBe(2)
  })

  it('ignores a gap for another thread and still resumes for an unaddressed one', async () => {
    const transport = new GapRpcTransport()
    let resumes = 0
    transport.handler = async (method) => {
      if (method !== 'thread/resume') return {}
      resumes += 1
      return resumes === 1 ? { snapshot: snapshot(1, 'running') } : { snapshot: resumedSnapshot() }
    }
    const { controller } = harness(transport)
    await controller.connect('thread-1')

    // A report about a thread we are not subscribed to says nothing about this one.
    transport.notify('thread/gap', { thread_id: 'thread-2', reason: 'outbound_dropped', dropped: 1 })
    await Promise.resolve()
    expect(resumes).toBe(1)

    // The server publishes an empty id when it has no subscription; that still
    // means "resume the thread you are on".
    transport.notify('thread/gap', { thread_id: '', reason: 'outbound_dropped', dropped: 1 })
    await vi.waitFor(() => expect(resumes).toBe(2))
  })

  it('keeps ignoring unknown notification methods', async () => {
    const transport = new GapRpcTransport()
    let resumes = 0
    transport.handler = async (method) => {
      if (method !== 'thread/resume') return {}
      resumes += 1
      return { snapshot: snapshot(1, 'running') }
    }
    const { runtime, controller } = harness(transport)
    await controller.connect('thread-1')
    const before = runtime.state

    expect(() => transport.notify('core/somethingNew', { thread_id: 'thread-1', payload: {} }))
      .not.toThrow()
    await Promise.resolve()
    expect(resumes).toBe(1)
    expect(runtime.state).toBe(before)
    expect(runtime.state?.snapshot_seq).toBe(1)
  })
})

function harness(transport: GapRpcTransport) {
  const runtime = createCoreAppServerRuntimeState()
  const frames: Array<() => void> = []
  const controller = createCoreAppServerRuntimeController(runtime, {
    createClient: (callbacks) => new CoreAppServerClient({
      transport,
      clientInfo: { name: 'gap-resync-test' },
      ...callbacks,
    }),
    scheduleFrame: (callback) => frames.push(callback),
  })
  return { runtime, controller, frames }
}

function flushFrames(frames: Array<() => void>): void {
  frames.splice(0).forEach((frame) => frame())
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((resolvePromise) => { resolve = resolvePromise })
  return { promise, resolve }
}

/** An RPC transport the test drives: it records requests and injects notifications. */
class GapRpcTransport implements LamToolsTransport {
  readonly requests: Array<{ method: string; params: Record<string, unknown> }> = []
  handler: (method: string, params: Record<string, unknown>) => Promise<Record<string, unknown>> =
    async () => ({})
  private readonly messageListeners = new Set<(message: TransportMessage) => void>()
  private readonly stateListeners = new Set<(state: TransportConnectionState) => void>()

  async connect(): Promise<void> {
    for (const listener of this.stateListeners) listener('connected')
  }

  async close(): Promise<void> {
    for (const listener of this.stateListeners) listener('disconnected')
  }

  async request<TResponse = unknown>(request: TransportRequest): Promise<TResponse> {
    if (request.kind === 'http') throw new Error('the gap resync must stay on the RPC lane')
    const params = (request.params || {}) as Record<string, unknown>
    this.requests.push({ method: request.method, params })
    return await this.handler(request.method, params) as TResponse
  }

  send(_message: TransportMessage): void {}

  subscribe(listener: (message: TransportMessage) => void): () => void {
    this.messageListeners.add(listener)
    return () => this.messageListeners.delete(listener)
  }

  onState(listener: (state: TransportConnectionState) => void): () => void {
    this.stateListeners.add(listener)
    listener('connected')
    return () => this.stateListeners.delete(listener)
  }

  getState(): TransportConnectionState {
    return 'connected'
  }

  /** Deliver a server notification exactly as the wire carries it. */
  notify(method: string, params: Record<string, unknown>): void {
    const message: TransportMessage = { type: 'notification', channel: 'rpc', method, params }
    for (const listener of [...this.messageListeners]) listener(message)
  }

  resumeParams(): Array<Record<string, unknown>> {
    return this.requests.filter((request) => request.method === 'thread/resume').map((request) => request.params)
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
    core: {
      thread_id: 'thread-1',
      snapshot_seq: seq,
      seen_event_ids: [],
      turns: {},
      items: {},
      item_order: [],
      requests: {},
      artifacts: {},
      status,
    },
  }
}

function resumedSnapshot(): CoreAppSnapshot {
  const value = snapshot(6, 'running')
  value.revision = 6
  value.core!.revision = 6
  // A real resume page carries both levels: the user side in the top-level
  // items/turns and the runtime transcript in core.items/core.turns.
  value.items = { 'user-1': userItem('user-1', 4, '把这段补完') }
  value.item_order = ['user-1']
  value.turns = { 'turn-1': { turn_id: 'turn-1', status: 'running', items: ['user-1'] } }
  value.core!.items = {
    'response-1': messageItem('response-1', 5, '第一段'),
    'response-2': messageItem('response-2', 6, '（掉队的那一段）'),
  }
  value.core!.item_order = ['response-1', 'response-2']
  value.core!.turns = { 'turn-1': { turn_id: 'turn-1', status: 'running', items: ['response-1', 'response-2'] } }
  return value
}

/** Everything the transcript currently shows, message text and part text. */
function projectedText(state: CoreAppSnapshot): string {
  return selectChatMessages(state)
    .map((message) => [message.content, ...message.parts.map((part) => String(part.content ?? ''))].join('\n'))
    .join('\n')
}

function userItem(itemId: string, seq: number, content: string) {
  return {
    item_id: itemId,
    thread_id: 'thread-1',
    turn_id: 'turn-1',
    seq,
    kind: 'message',
    status: 'completed',
    content,
    payload: { type: 'userMessage', content },
  }
}

function messageItem(itemId: string, seq: number, content: string) {
  return {
    item_id: itemId,
    thread_id: 'thread-1',
    turn_id: 'turn-1',
    seq,
    kind: 'message',
    status: 'completed',
    content,
    payload: { type: 'agentMessage', content, final_response: false, has_tool_calls: false },
  }
}

/** A live run-item notification envelope, carrying its own method (as the wire does). */
function runItemFrame(eventId: string, revision: number, seq: number, delta: string): Record<string, unknown> {
  return {
    event_id: eventId,
    thread_id: 'thread-1',
    seq,
    revision,
    method: 'core/runItem',
    created_at: '2026-10-12T00:00:00Z',
    item_id: 'response-1',
    turn_id: 'turn-1',
    payload: {
      event_id: eventId,
      thread_id: 'thread-1',
      item_id: 'response-1',
      turn_id: 'turn-1',
      seq,
      revision,
      kind: 'message',
      status: 'running',
      payload: { type: 'agentMessage', delta },
    },
  } satisfies CoreAppEvent
}
