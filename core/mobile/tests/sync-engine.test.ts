import { describe, expect, it } from 'vitest'
import type {
  LamToolsTransport,
  TransportConnectionState,
  TransportMessage,
  TransportRequest,
} from '@lamtools/ui/transport'
import { createLocalRepository, type LocalState } from '../src/storage'
import { SyncEngine } from '../src/sync'

class FakeDatabase {
  value: LocalState | null = null
  async open(): Promise<void> {}
  async read(): Promise<LocalState | null> { return this.value }
  async write(state: LocalState): Promise<void> { this.value = JSON.parse(JSON.stringify(state)) as LocalState }
  async close(): Promise<void> {}
}

class BlockingDatabase extends FakeDatabase {
  readonly writeStarted: Promise<void>
  private readonly resolveWriteStarted!: () => void
  readonly releaseWrite: Promise<void>
  private readonly resolveReleaseWrite!: () => void

  constructor() {
    super()
    this.writeStarted = new Promise<void>((resolve) => { this.resolveWriteStarted = resolve })
    this.releaseWrite = new Promise<void>((resolve) => { this.resolveReleaseWrite = resolve })
  }

  override async write(state: LocalState): Promise<void> {
    await super.write(state)
    this.resolveWriteStarted()
    await this.releaseWrite
  }

  release(): void { this.resolveReleaseWrite() }
}

class FakeTransport implements LamToolsTransport {
  private readonly messageListeners = new Set<(message: TransportMessage) => void>()
  private readonly stateListeners = new Set<(state: TransportConnectionState) => void>()
  private state: TransportConnectionState = 'connected'

  constructor(private readonly handler: (request: TransportRequest) => Promise<unknown>) {}

  async connect(): Promise<void> {}
  async close(): Promise<void> { this.setState('disconnected') }
  async request<TResponse = unknown>(request: TransportRequest): Promise<TResponse> {
    return await this.handler(request) as TResponse
  }
  send(): void {}
  subscribe(listener: (message: TransportMessage) => void): () => void {
    this.messageListeners.add(listener)
    return () => this.messageListeners.delete(listener)
  }
  onState(listener: (state: TransportConnectionState) => void): () => void {
    this.stateListeners.add(listener)
    listener(this.state)
    return () => this.stateListeners.delete(listener)
  }
  getState(): TransportConnectionState { return this.state }
  emit(message: TransportMessage): void {
    for (const listener of this.messageListeners) listener(message)
  }
  emitState(state: TransportConnectionState): void { this.setState(state) }
  private setState(state: TransportConnectionState): void {
    this.state = state
    for (const listener of this.stateListeners) listener(state)
  }
}

describe('SyncEngine', () => {
  it('uses one sync request for the snapshot, then applies push deltas', async () => {
    const database = new FakeDatabase()
    const repository = createLocalRepository(database)
    const requests: unknown[] = []
    const transport = new FakeTransport(async (request) => {
      requests.push(request)
      return {
        ok: true,
        mode: 'snapshot',
        cursor: 3,
        snapshotVersion: 3,
        projects: [{ id: 'project-1', name: 'Workspace', path: '/workspace' }],
      }
    })
    const engine = new SyncEngine({
      transport,
      repository,
      requestRpc: (method, params) => transport.request({ kind: 'rpc', method, params }),
    })

    await engine.start()
    expect(requests).toHaveLength(1)
    expect(requests[0]).toMatchObject({
      method: 'sync.start',
      params: { cursor: null, limit: 500 },
    })
    expect(engine.state.value).toBe('synced')
    expect(repository.state.value.cursor).toBe(3)

    transport.emit({
      type: 'notification',
      channel: 'rpc',
      method: 'sync/change',
      params: {
        seq: 4,
        type: 'project',
        operation: 'upsert',
        entity_id: 'project-1',
        entity: { id: 'project-1', name: 'Renamed', path: '/workspace' },
      },
    })
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(repository.state.value.cursor).toBe(4)
    expect((await repository.listProjects())[0]?.name).toBe('Renamed')

    await engine.close()
  })

  it('restarts from a snapshot when the stored cursor expires', async () => {
    const database = new FakeDatabase()
    const repository = createLocalRepository(database)
    await repository.applySyncSnapshot({ cursor: 7, snapshotVersion: 7 })
    const cursors: unknown[] = []
    const transport = new FakeTransport(async (request) => {
      const cursor = request.kind === 'rpc' ? request.params?.cursor : undefined
      cursors.push(cursor)
      if (cursor === 7) return { ok: false, error: 'SYNC_CURSOR_EXPIRED' }
      return { ok: true, mode: 'snapshot', cursor: 9, snapshotVersion: 9, projects: [] }
    })
    const engine = new SyncEngine({
      transport,
      repository,
      requestRpc: (method, params) => transport.request({ kind: 'rpc', method, params }),
    })

    await engine.start()
    expect(cursors).toEqual([7, null])
    expect(repository.state.value.cursor).toBe(9)
    expect(engine.state.value).toBe('synced')
    await engine.close()
  })

  it('immediately replaces the local branch after a rollback push', async () => {
    const database = new FakeDatabase()
    const repository = createLocalRepository(database)
    const cursors: unknown[] = []
    const transport = new FakeTransport(async (request) => {
      const cursor = request.kind === 'rpc' ? request.params?.cursor : undefined
      cursors.push(cursor)
      if (cursor == null) {
        return {
          ok: true,
          mode: cursors.length === 1 ? 'snapshot' : 'snapshot',
          cursor: cursors.length === 1 ? 3 : 8,
          snapshotVersion: cursors.length === 1 ? 3 : 8,
          threads: [{
            id: 'thread-1',
            title: cursors.length === 1 ? 'before rollback' : 'after rollback',
            status: 'idle',
          }],
        }
      }
      return {
        ok: true,
        mode: 'delta',
        cursor: 4,
        has_more: false,
        changes: [{
          seq: 4,
          type: 'thread.event',
          operation: 'upsert',
          entity_id: 'thread-1',
          snapshot_required: true,
          entity: {
            snapshot_required: true,
            event: { method: 'session/rollback', thread_id: 'thread-1', payload: {} },
          },
        }],
      }
    })
    const engine = new SyncEngine({
      transport,
      repository,
      requestRpc: (method, params) => transport.request({ kind: 'rpc', method, params }),
    })

    await engine.start()
    transport.emit({
      type: 'notification',
      channel: 'rpc',
      method: 'sync/change',
      params: {
        seq: 4,
        type: 'thread.event',
        operation: 'upsert',
        entity_id: 'thread-1',
        snapshot_required: true,
        entity: {
          snapshot_required: true,
          event: { method: 'session/rollback', thread_id: 'thread-1', payload: {} },
        },
      },
    })
    await new Promise((resolve) => setTimeout(resolve, 10))

    expect(cursors).toEqual([null, null])
    expect(repository.state.value.snapshotRequired).toBe(false)
    expect((await repository.listSessions())[0]?.title).toBe('after rollback')
    await engine.close()
  })

  it('retries synchronization after an unexpected disconnect', async () => {
    const repository = createLocalRepository(new FakeDatabase())
    let requests = 0
    const transport = new FakeTransport(async () => {
      requests += 1
      return { ok: true, mode: 'snapshot', cursor: requests, snapshotVersion: requests }
    })
    const engine = new SyncEngine({
      transport,
      repository,
      reconnectDelaysMs: [1],
      requestRpc: (method, params) => transport.request({ kind: 'rpc', method, params }),
    })

    await engine.start()
    transport.emitState('disconnected')
    await new Promise((resolve) => setTimeout(resolve, 10))

    expect(requests).toBeGreaterThanOrEqual(2)
    expect(engine.state.value).toBe('synced')
    await engine.close()
  })

  it('keeps failed transport offline until a connected event completes a new sync', async () => {
    const repository = createLocalRepository(new FakeDatabase())
    let requests = 0
    const transport = new FakeTransport(async () => {
      requests += 1
      return { ok: true, mode: 'snapshot', cursor: requests, snapshotVersion: requests }
    })
    const engine = new SyncEngine({
      transport,
      repository,
      reconnectDelaysMs: [60_000],
      requestRpc: (method, params) => transport.request({ kind: 'rpc', method, params }),
    })

    await engine.start()
    expect(engine.state.value).toBe('synced')
    transport.emitState('failed')
    expect(engine.state.value).toBe('offline')
    transport.emitState('reconnecting')
    expect(engine.state.value).toBe('offline')

    transport.emitState('connected')
    await new Promise<void>((resolve) => setTimeout(resolve, 0))
    expect(requests).toBeGreaterThanOrEqual(2)
    expect(engine.state.value).toBe('synced')
    await engine.close()
  })

  it('does not apply a late sync response after close', async () => {
    const repository = createLocalRepository(new FakeDatabase())
    let requestCount = 0
    let resolveRequest!: (value: unknown) => void
    const pendingRequest = new Promise<unknown>((resolve) => { resolveRequest = resolve })
    const transport = new FakeTransport(async () => {
      requestCount += 1
      return await pendingRequest
    })
    const engine = new SyncEngine({
      transport,
      repository,
      requestRpc: (method, params) => transport.request({ kind: 'rpc', method, params }),
    })

    const start = engine.start()
    await new Promise<void>((resolve) => {
      const check = () => requestCount > 0 ? resolve() : setTimeout(check, 0)
      check()
    })
    await engine.close()
    resolveRequest({ ok: true, mode: 'snapshot', cursor: 42, snapshotVersion: 42, projects: [] })
    await start

    expect(repository.state.value.cursor).toBeNull()
    expect(engine.state.value).toBe('idle')
  })

  it('waits for an active repository write before close resolves', async () => {
    const database = new BlockingDatabase()
    const repository = createLocalRepository(database)
    const transport = new FakeTransport(async () => ({
      ok: true,
      mode: 'snapshot',
      cursor: 1,
      snapshotVersion: 1,
      projects: [],
    }))
    const engine = new SyncEngine({
      transport,
      repository,
      requestRpc: (method, params) => transport.request({ kind: 'rpc', method, params }),
    })

    const start = engine.start()
    await database.writeStarted
    let closed = false
    const close = engine.close().then(() => { closed = true })
    await Promise.resolve()
    expect(closed).toBe(false)

    database.release()
    await close
    await start
    expect(closed).toBe(true)
  })
})
