import { describe, expect, it } from 'vitest'
import type { LocalDatabase, LocalState } from '../src/storage'
import { createLocalRepository } from '../src/storage'

class FakeDatabase implements LocalDatabase<LocalState> {
  value: LocalState | null = null
  async open(): Promise<void> {}
  async read(): Promise<LocalState | null> { return this.value }
  async write(state: LocalState): Promise<void> { this.value = JSON.parse(JSON.stringify(state)) as LocalState }
  async close(): Promise<void> {}
}

class ScopedFakeDatabase extends FakeDatabase {
  readonly scopes = new Map<string, LocalState>()

  async readScope(scope: string): Promise<LocalState | null> {
    return this.scopes.get(scope) || null
  }

  async writeScope(scope: string, state: LocalState): Promise<void> {
    const copy = JSON.parse(JSON.stringify(state)) as LocalState
    this.scopes.set(scope, copy)
    this.value = copy
  }
}

describe('LocalRepository', () => {
  it('applies snapshot, buffers out-of-order deltas, and keeps tombstones idempotently', async () => {
    const database = new FakeDatabase()
    const repository = createLocalRepository(database)
    await repository.applySyncSnapshot({
      cursor: 10,
      snapshotVersion: 10,
      projects: [{
        id: 'project-1',
        name: 'Workspace',
        work_root: '/workspace',
        created_at: '2026-01-01T00:00:00.000Z',
        updated_at: '2026-01-01T00:00:00.000Z',
      }],
      threads: [{
        id: 'thread-1',
        project_id: 'project-1',
        title: 'First',
        status: 'idle',
        created_at: '2026-01-01T00:00:00.000Z',
        updated_at: '2026-01-01T00:00:00.000Z',
        metadata: {},
      }],
      snapshots: [{
        thread_id: 'thread-1',
        snapshot: { thread_id: 'thread-1', status: 'idle' },
      }],
    })

    expect(await repository.listProjects()).toHaveLength(1)
    expect((await repository.listSessions('project-1'))[0]?.title).toBe('First')
    expect(repository.state.value.cursor).toBe(10)

    await repository.applySyncChange({
      seq: 12,
      type: 'thread',
      operation: 'delete',
      entity_id: 'thread-1',
      entity: { id: 'thread-1', deleted: true },
    })
    expect(repository.state.value.cursor).toBe(10)

    await repository.applySyncChange({
      seq: 11,
      type: 'thread',
      operation: 'upsert',
      entity_id: 'thread-1',
      entity: {
        id: 'thread-1',
        project_id: 'project-1',
        title: 'Renamed',
        status: 'idle',
        metadata: {},
      },
    })
    expect(repository.state.value.cursor).toBe(12)
    expect(repository.state.value.threads['thread-1']?.deleted).toBe(true)
    expect(await repository.listSessions('project-1')).toEqual([])

    await repository.applySyncChange({
      seq: 12,
      type: 'thread',
      operation: 'upsert',
      entity_id: 'thread-1',
      entity: { id: 'thread-1', title: 'Stale replay' },
    })
    expect(repository.state.value.threads['thread-1']?.deleted).toBe(true)

    await repository.applySyncChange({
      seq: 13,
      type: 'project',
      operation: 'delete',
      entity_id: 'project-1',
      entity: { id: 'project-1', deleted: true },
    })
    expect(await repository.listProjects()).toEqual([])
    expect(database.value?.syncBuffer).toEqual({})
  })

  it('restores the atomic materialized state after reopening', async () => {
    const database = new FakeDatabase()
    const first = createLocalRepository(database)
    await first.applySyncSnapshot({
      cursor: 4,
      snapshotVersion: 4,
      projects: [{
        id: 'project-1',
        name: 'Workspace',
        path: '/workspace',
        icon_key: 'rocket',
        color_key: 'aurora',
      }],
    })
    await first.close()

    const second = createLocalRepository(database)
    await second.init()
    expect((await second.listProjects())[0]).toMatchObject({
      id: 'project-1',
      name: 'Workspace',
      iconKey: 'rocket',
      colorKey: 'aurora',
    })
    expect(second.state.value.cursor).toBe(4)
  })

  it('marks rollback changes for authoritative snapshot recovery', async () => {
    const database = new FakeDatabase()
    const repository = createLocalRepository(database)
    await repository.applySyncSnapshot({
      cursor: 3,
      snapshotVersion: 3,
      threads: [{ id: 'thread-1', title: 'stale', status: 'idle' }],
    })

    await repository.applySyncChange({
      seq: 4,
      type: 'thread.event',
      operation: 'upsert',
      entity_id: 'thread-1',
      snapshot_required: true,
      entity: {
        snapshot_required: true,
        event: {
          method: 'session/rollback',
          thread_id: 'thread-1',
          payload: { snapshot_required: true },
        },
      },
    })

    expect(repository.state.value.cursor).toBe(4)
    expect(repository.state.value.snapshotRequired).toBe(true)
    expect((await repository.listSessions())[0]?.title).toBe('stale')

    await repository.applySyncSnapshot({
      cursor: 5,
      snapshotVersion: 5,
      threads: [{ id: 'thread-1', title: 'authoritative', status: 'idle' }],
    })
    expect(repository.state.value.snapshotRequired).toBe(false)
    expect((await repository.listSessions())[0]?.title).toBe('authoritative')
  })

  it('keeps independent caches when switching Workspaces and after restart', async () => {
    const database = new ScopedFakeDatabase()
    const repository = createLocalRepository(database)

    await repository.setWorkspaceId('workspace-a')
    await repository.applySyncSnapshot({
      workspace_id: 'workspace-a',
      cursor: 1,
      snapshotVersion: 1,
      projects: [{ id: 'same-project-id', name: '电脑 A', path: '/a' }],
    })
    await repository.setWorkspaceId('workspace-b')
    await repository.applySyncSnapshot({
      workspace_id: 'workspace-b',
      cursor: 2,
      snapshotVersion: 2,
      projects: [{ id: 'same-project-id', name: '电脑 B', path: '/b' }],
    })

    expect((await repository.listProjects())[0]?.name).toBe('电脑 B')
    await repository.setWorkspaceId('workspace-a')
    expect((await repository.listProjects())[0]?.name).toBe('电脑 A')

    await repository.setWorkspaceId('workspace-b')
    await repository.close()
    const restarted = createLocalRepository(database)
    await restarted.init()
    expect(restarted.state.value.workspaceId).toBe('workspace-b')
    expect((await restarted.listProjects())[0]?.name).toBe('电脑 B')

    await restarted.setWorkspaceId('workspace-a')
    expect((await restarted.listProjects())[0]?.name).toBe('电脑 A')
  })

  it('keeps the Relay Workspace scope separate from the Core Workspace identity', async () => {
    const database = new ScopedFakeDatabase()
    const repository = createLocalRepository(database)

    await repository.setWorkspaceId('relay-workspace-1')
    await repository.applySyncSnapshot({
      workspace_id: 'core-workspace-1',
      cursor: 4,
      snapshotVersion: 4,
      projects: [{ id: 'project-1', name: '桌面项目', path: 'E:\\LamTools\\e2e-test' }],
    })

    expect(repository.state.value.workspaceId).toBe('relay-workspace-1')
    expect(repository.state.value.hostWorkspaceId).toBe('core-workspace-1')
    expect((await repository.listProjects())[0]?.path).toBe('E:\\LamTools\\e2e-test')

    await expect(repository.applySyncSnapshot({
      workspace_id: 'core-workspace-2',
      cursor: 5,
      snapshotVersion: 5,
      projects: [],
    })).rejects.toThrow('同步响应属于其他工作环境')

    await repository.close()
    const restarted = createLocalRepository(database)
    await restarted.init()
    expect(restarted.state.value.workspaceId).toBe('relay-workspace-1')
    expect(restarted.state.value.hostWorkspaceId).toBe('core-workspace-1')
  })
})
