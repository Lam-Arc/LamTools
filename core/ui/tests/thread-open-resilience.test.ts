import { effectScope, nextTick } from 'vue'
import { describe, expect, it } from 'vitest'
import { createWorkbench } from '../src/workbench/createWorkbench'
import type { CoreAppServerRuntimeClient } from '../src/appServer/store'
import type { CoreAppSnapshot } from '../src/appServer/protocol'
import type { CoreSessionListItem } from '../src/types'
import { TransportRequestTimeoutError } from '../src/transport'
import type {
  LamToolsTransport,
  TransportConnectionState,
  TransportMessage,
  TransportRequest,
} from '../src/transport'

/**
 * Opening a session must survive a slow snapshot: a timeout is retried once, and
 * the shell's attach path paints the persisted transcript before the live attach
 * resolves. A failed open used to leave the thread blank for a minute.
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

function snapshotWithAnswer(threadId: string, text: string): CoreAppSnapshot {
  return {
    thread_id: threadId,
    snapshot_seq: 3,
    revision: 3,
    status: 'completed',
    turns: { 'turn-1': { turn_id: 'turn-1', status: 'completed', items: ['answer-1'] } },
    items: {},
    item_order: [],
    queue: [],
    requests: {},
    core: {
      thread_id: threadId,
      snapshot_seq: 3,
      revision: 3,
      status: 'completed',
      turns: { 'turn-1': { turn_id: 'turn-1', status: 'completed', items: ['answer-1'] } },
      items: {
        'answer-1': {
          item_id: 'answer-1',
          turn_id: 'turn-1',
          kind: 'message',
          status: 'completed',
          payload: { type: 'agentMessage', content: text },
        },
      },
      item_order: ['answer-1'],
      requests: {},
      artifacts: {},
    },
  }
}

class SlowResumeClient implements CoreAppServerRuntimeClient {
  readonly methods: string[] = []
  private resumeAttempts = 0
  constructor(
    private readonly threadId: string,
    private readonly onState: (state: 'connecting' | 'open' | 'closed' | 'error') => void,
    private readonly timeoutsBeforeSuccess: number,
  ) {}
  async connect(): Promise<void> { this.onState('open') }
  async request(method: string): Promise<Record<string, unknown>> {
    this.methods.push(method)
    if (method === 'thread/resume') {
      this.resumeAttempts += 1
      if (this.resumeAttempts <= this.timeoutsBeforeSuccess) {
        throw new TransportRequestTimeoutError(method, 60_000)
      }
    }
    return { snapshot: snapshotWithAnswer(this.threadId, '已恢复的会话内容') }
  }
  respondServerRequest(): boolean { return false }
  close(): void {}
}

async function mount(client: SlowResumeClient) {
  const sessions: CoreSessionListItem[] = [
    { id: 'thread-1', title: 'One', status: 'idle', createdAt: '' },
  ]
  const scope = effectScope()
  const runtime = scope.run(() => createWorkbench({
    transport: new FakeTransport(),
    sessions: { listSessions: async () => sessions },
    composerDraftStorage: null,
    clientFactory: { createClient: ({ onConnectionState }) => client },
  }))!
  return { runtime, scope }
}

describe('session open resilience', () => {
  it('retries a timed-out resume once instead of leaving the thread blank', async () => {
    const client = new SlowResumeClient('thread-1', () => undefined, 1)
    const { runtime, scope } = await mount(client)
    try {
      await runtime.refreshSessions()
      await runtime.selectSession('thread-1')
      await nextTick()
      await nextTick()

      // One timeout plus its retry, from the attach path the shell uses.
      expect(client.methods.filter(method => method === 'thread/resume').length).toBeGreaterThan(1)
      const rendered = JSON.stringify(runtime.messages.value)
      expect(rendered).toContain('已恢复的会话内容')
    } finally { scope.stop() }
  })

  it('paints the persisted transcript before the live attach answers', async () => {
    const client = new SlowResumeClient('thread-1', () => undefined, 0)
    const { runtime, scope } = await mount(client)
    try {
      await runtime.refreshSessions()
      await runtime.selectSession('thread-1')
      await nextTick()
      await nextTick()
      // The shell's path reads the persisted thread first and attaches after.
      expect(client.methods).toContain('thread/read')
      expect(JSON.stringify(runtime.messages.value)).toContain('已恢复的会话内容')
    } finally { scope.stop() }
  })
})
