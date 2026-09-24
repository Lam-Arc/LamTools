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
  it('does not publish a project when durable storage rejects the write', async () => {
    class FailingDatabase extends FakeDatabase {
      rejectNextWrite = true
      override async write(state: LocalState): Promise<void> {
        if (this.rejectNextWrite) {
          this.rejectNextWrite = false
          throw new Error('disk full')
        }
        await super.write(state)
      }
    }
    const database = new FailingDatabase()
    const repository = createLocalRepository(database)
    await repository.init()
    let published = 0
    repository.subscribe(() => { published += 1 })

    await expect(repository.createLocalProject({ name: '未持久化项目' })).rejects.toThrow('disk full')
    expect(repository.state.value.projects).toEqual({})
    expect(await repository.listProjects()).toEqual([])
    expect(database.value).toBeNull()
    expect(published).toBe(0)

    await repository.createLocalProject({ name: '已持久化项目' })
    expect((await repository.listProjects())[0]?.name).toBe('已持久化项目')
    expect(published).toBe(1)
  })

  it('imports a legacy Capacitor state once without overwriting Tauri data', async () => {
    const repository = createLocalRepository(new FakeDatabase())
    await repository.init()
    const legacy = JSON.parse(JSON.stringify(repository.state.value)) as LocalState
    legacy.projects['legacy-project'] = {
      id: 'legacy-project', name: '旧项目', path: 'mobile://legacy-project', workRoot: 'mobile://legacy-project',
      iconKey: '', colorKey: '', revision: 1, createdAt: '2026-09-01T00:00:00Z', updatedAt: '2026-09-01T00:00:00Z', deleted: false,
    }

    await expect(repository.importLegacyState(legacy)).resolves.toBe(true)
    await expect(repository.listProjects()).resolves.toEqual([expect.objectContaining({ id: 'legacy-project' })])
    await expect(repository.importLegacyState({ ...legacy, projects: {} })).resolves.toBe(false)
    await expect(repository.listProjects()).resolves.toEqual([expect.objectContaining({ id: 'legacy-project' })])
  })

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

  it('isolates the same Workspace id across accounts and clears scope on logout', async () => {
    const database = new ScopedFakeDatabase()
    const first = createLocalRepository(database, { serverId: 'server-a', accountId: 'alice' })
    await first.setWorkspaceId('shared-workspace')
    await first.applySyncSnapshot({
      workspace_id: 'core-shared',
      cursor: 1,
      snapshotVersion: 1,
      projects: [{ id: 'project-1', name: 'Alice cache', path: '/alice' }],
    })

    const otherAccount = createLocalRepository(database, { serverId: 'server-b', accountId: 'alice' })
    await otherAccount.setWorkspaceId('shared-workspace')
    expect(await otherAccount.listProjects()).toEqual([])

    await first.setAccountScope('', '')
    expect(await first.listProjects()).toEqual([])
    await first.setAccountScope('server-a', 'alice')
    expect((await first.listProjects())[0]?.name).toBe('Alice cache')
  })

  it('rejects a gapped sync batch without partially importing changes', async () => {
    const repository = createLocalRepository(new FakeDatabase())
    await repository.applySyncSnapshot({
      cursor: 1,
      snapshotVersion: 1,
      projects: [{ id: 'project-1', name: 'Before', path: '/before' }],
    })

    await expect(repository.applySyncBatch([{
      seq: 3,
      type: 'project',
      operation: 'upsert',
      entity_id: 'project-1',
      entity: { id: 'project-1', name: 'After', path: '/after' },
    }], 3)).rejects.toThrow('游标不连续')
    expect(repository.state.value.cursor).toBe(1)
    expect((await repository.listProjects())[0]?.name).toBe('Before')
  })

  it('imports a remote project as an independent local copy and remaps session snapshot identity', async () => {
    const repository = createLocalRepository(new FakeDatabase())
    const imported = await repository.importLocalProject({
      id: 'remote-project',
      name: '桌面项目',
      path: 'E:\\desktop-project',
      workRoot: 'E:\\desktop-project',
      iconKey: 'code',
      colorKey: 'blue',
      revision: 9,
      createdAt: '2026-01-01T00:00:00.000Z',
      updatedAt: '2026-01-02T00:00:00.000Z',
      deleted: false,
    }, [{
      id: 'remote-thread',
      projectId: 'remote-project',
      title: '桌面会话',
      status: 'completed',
      revision: 7,
      createdAt: '2026-01-01T00:00:00.000Z',
      updatedAt: '2026-01-02T00:00:00.000Z',
      metadata: { project_id: 'remote-project', work_root: 'E:\\desktop-project' },
      deleted: false,
    }], [{
      thread_id: 'remote-thread',
      status: 'completed',
      revision: 7,
      session: { id: 'remote-thread', metadata: { project_id: 'remote-project' } },
      core: { thread_id: 'remote-thread', status: 'completed', revision: 7 },
    } as any])

    expect(imported.id).not.toBe('remote-project')
    expect(imported.workRoot).toBe(`mobile://${imported.id}`)
    const [session] = await repository.listSessions(imported.id)
    expect(session?.id).not.toBe('remote-thread')
    expect(session?.metadata).toMatchObject({
      project_id: imported.id,
      work_root: imported.workRoot,
      imported_from: 'remote-thread',
    })
    const snapshot = await repository.loadThreadSnapshot(session!.id)
    expect(snapshot?.thread_id).toBe(session?.id)
    expect(snapshot?.core?.thread_id).toBe(session?.id)
    expect((snapshot as any)?.session).toMatchObject({
      id: session?.id,
      metadata: { project_id: imported.id, work_root: imported.workRoot },
    })
  })
})
