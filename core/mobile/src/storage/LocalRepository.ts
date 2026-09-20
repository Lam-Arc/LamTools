import { ref, type Ref } from 'vue'
import { applyCoreAppEvent } from '@lamtools/ui/appServer/store'
import type { CoreAppEvent, CoreAppSnapshot } from '@lamtools/ui/appServer/protocol'
import type { CoreSessionListItem } from '@lamtools/ui/types'
import { createLocalDatabase, type LocalDatabase } from './Database'

export interface LocalProject {
  id: string
  name: string
  path: string
  workRoot: string
  iconKey: string
  colorKey: string
  revision: number
  createdAt: string
  updatedAt: string
  deleted: boolean
}

export interface LocalThread {
  id: string
  projectId?: string
  title: string
  status: string
  /** Host-authoritative session revision used for CAS writes. */
  revision: number
  createdAt: string
  updatedAt: string
  metadata: Record<string, unknown>
  deleted: boolean
}

export interface LocalMessage {
  id: string
  threadId: string
  seq: number
  /** Revision at which this message was accepted/changed on the Host. */
  revision: number
  role: string
  content: string
  createdAt: string
  updatedAt: string
  deleted: boolean
  payload: Record<string, unknown>
}

export interface LocalPendingOperation {
  localOpId: string
  operation: string
  payload: Record<string, unknown>
  state: 'pending' | 'sending' | 'sent' | 'failed'
  createdAt: string
}

export interface LocalSyncChange {
  seq: number
  change_id?: string
  workspace_id?: string
  workspaceId?: string
  type?: string
  operation?: string
  entity_id?: string
  thread_id?: string
  revision?: number
  workspace_revision?: number
  workspaceRevision?: number
  snapshot_revision?: number
  snapshotRevision?: number
  snapshot_required?: boolean
  snapshotRequired?: boolean
  entity?: Record<string, unknown>
}

export interface LocalState {
  desktopId: string
  /** Stable server/account identity that owns this cache. */
  accountScope: string
  /** The Relay/account Workspace scope for the cached state, when known. */
  workspaceId: string
  /** The desktop Core Workspace identity returned inside sync payloads. */
  hostWorkspaceId: string
  cursor: number | null
  snapshotVersion: number
  /** Monotonic global revision/cursor for this Workspace cache. */
  workspaceRevision: number
  /** Highest per-thread snapshot revision present in this cache. */
  snapshotRevision: number
  /** A rollback or branch replacement requires a fresh Host snapshot. */
  snapshotRequired: boolean
  lastSyncAt: string
  projects: Record<string, LocalProject>
  threads: Record<string, LocalThread>
  messages: Record<string, LocalMessage>
  runtimeState: Record<string, Record<string, unknown>>
  snapshots: Record<string, CoreAppSnapshot>
  pendingOperations: Record<string, LocalPendingOperation>
  /** Out-of-order push changes wait here until the cursor becomes contiguous. */
  syncBuffer: Record<string, LocalSyncChange>
}

export interface LocalRepository {
  readonly state: Ref<LocalState>
  init(): Promise<void>
  setAccountScope(serverId: string, accountId: string): Promise<void>
  setDesktopId(desktopId: string): Promise<void>
  setWorkspaceId(workspaceId: string): Promise<void>
  listProjects(): Promise<LocalProject[]>
  listSessions(projectId?: string): Promise<CoreSessionListItem[]>
  loadThreadSnapshot(threadId: string): Promise<CoreAppSnapshot | null>
  createLocalProject(input: {
    name: string
    workRoot?: string
    iconKey?: string
    colorKey?: string
  }): Promise<{ project: LocalProject; thread: LocalThread }>
  getLocalProject(projectId: string): Promise<LocalProject | null>
  updateLocalProject(projectId: string, input: { name?: string; iconKey?: string; colorKey?: string }): Promise<LocalProject>
  deleteLocalProject(projectId: string): Promise<void>
  createLocalSession(projectId?: string, title?: string): Promise<LocalThread>
  updateLocalSession(threadId: string, input: { title?: string; metadata?: Record<string, unknown>; status?: string }): Promise<LocalThread>
  deleteLocalSession(threadId: string): Promise<void>
  saveLocalSnapshot(snapshot: CoreAppSnapshot): Promise<void>
  importLocalProject(project: LocalProject, threads: LocalThread[], snapshots: CoreAppSnapshot[]): Promise<LocalProject>
  applySyncSnapshot(payload: Record<string, unknown>): Promise<void>
  applySyncChange(change: LocalSyncChange): Promise<void>
  /** Atomically applies one sync page; rejects gaps or cursor mismatches. */
  applySyncBatch(changes: LocalSyncChange[], expectedCursor?: number | null): Promise<void>
  applyTransientEvent(event: CoreAppEvent): Promise<void>
  applySessionEvent(method: string, params: Record<string, unknown>): Promise<void>
  close(): Promise<void>
  subscribe(listener: (state: LocalState) => void): () => void
}

export function createLocalRepository(
  database: LocalDatabase<LocalState> = createLocalDatabase<LocalState>(),
  options: { workspaceId?: string; serverId?: string; accountId?: string } = {},
): LocalRepository {
  const state = ref(emptyLocalState())
  const listeners = new Set<(value: LocalState) => void>()
  let initialized = false
  let writeQueue: Promise<void> = Promise.resolve()
  let desiredAccountScope = accountScopeFor(options.serverId || '', options.accountId || '')
  let desiredWorkspaceId = String(options.workspaceId || '').trim()
  let activeScope = 'default'
  const localScopes = new Map<string, LocalState>()

  async function init(): Promise<void> {
    if (initialized) return
    await database.open()
    const targetScope = desiredWorkspaceId
      ? scopeFor(desiredAccountScope, '', desiredWorkspaceId)
      : ''
    const saved = targetScope && database.readScope
      ? await database.readScope(targetScope)
      : await database.read()
    const normalized = normalizeState(saved)
    if (normalized.accountScope !== desiredAccountScope) {
      state.value = emptyLocalState()
      state.value.accountScope = desiredAccountScope
      state.value.workspaceId = desiredWorkspaceId
    } else if (desiredWorkspaceId && normalized.workspaceId && normalized.workspaceId !== desiredWorkspaceId) {
      state.value = emptyLocalState()
      state.value.accountScope = desiredAccountScope
      state.value.workspaceId = desiredWorkspaceId
    } else {
      state.value = normalized
      if (desiredAccountScope) state.value.accountScope = desiredAccountScope
      if (desiredWorkspaceId) state.value.workspaceId = desiredWorkspaceId
    }
    activeScope = scopeFor(state.value.accountScope, state.value.desktopId, state.value.workspaceId)
    localScopes.set(activeScope, clone(state.value))
    initialized = true
  }

  async function setAccountScope(serverId: string, accountId: string): Promise<void> {
    desiredAccountScope = accountScopeFor(serverId, accountId)
    await init()
    if (state.value.accountScope === desiredAccountScope) return
    await switchScope(state.value.workspaceId, state.value.desktopId, desiredAccountScope)
  }

  async function setDesktopId(desktopId: string): Promise<void> {
    await init()
    const normalized = desktopId.trim()
    if (!normalized || state.value.desktopId === normalized) return
    // Anonymous pairing is scoped by desktop until the Host tells us its
    // stable Workspace id. Never copy another desktop's cache into this one.
    if (!state.value.workspaceId && state.value.desktopId) {
      await switchScope('', normalized)
      return
    }
    await update((next) => { next.desktopId = normalized })
  }

  async function setWorkspaceId(workspaceId: string): Promise<void> {
    desiredWorkspaceId = workspaceId.trim()
    await init()
    const targetScope = scopeFor(state.value.accountScope, state.value.desktopId, desiredWorkspaceId)
    if (state.value.workspaceId === desiredWorkspaceId && activeScope === targetScope) return
    await switchScope(desiredWorkspaceId, state.value.desktopId)
  }

  async function listProjects(): Promise<LocalProject[]> {
    await init()
    return Object.values(state.value.projects)
      .filter((project) => !project.deleted)
      .sort((a, b) => a.createdAt.localeCompare(b.createdAt) || a.id.localeCompare(b.id))
  }

  async function listSessions(projectId?: string): Promise<CoreSessionListItem[]> {
    await init()
    return Object.values(state.value.threads)
      .filter((thread) => !thread.deleted && (!projectId || thread.projectId === projectId))
      .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt) || a.id.localeCompare(b.id))
      .map((thread) => ({
        id: thread.id,
        title: thread.title || thread.id,
        createdAt: thread.createdAt,
        updatedAt: thread.updatedAt,
        status: thread.status,
        metadata: thread.metadata,
      }))
  }

  async function loadThreadSnapshot(threadId: string): Promise<CoreAppSnapshot | null> {
    await init()
    return state.value.snapshots[threadId] || null
  }

  async function createLocalProject(input: {
    name: string
    workRoot?: string
    iconKey?: string
    colorKey?: string
  }): Promise<{ project: LocalProject; thread: LocalThread }> {
    await init()
    const now = new Date().toISOString()
    const projectId = globalThis.crypto?.randomUUID?.() || `project-${Date.now()}`
    const workRoot = input.workRoot?.trim() || `mobile://${projectId}`
    const project: LocalProject = {
      id: projectId,
      name: input.name.trim() || '未命名项目',
      path: workRoot,
      workRoot,
      iconKey: input.iconKey || 'folder',
      colorKey: input.colorKey || 'gray',
      revision: 1,
      createdAt: now,
      updatedAt: now,
      deleted: false,
    }
    const thread = localThread(project, '新会话', now)
    await update((next) => {
      next.projects[project.id] = project
      next.threads[thread.id] = thread
      next.snapshots[thread.id] = emptySnapshot(thread.id)
    })
    return { project, thread }
  }

  async function getLocalProject(projectId: string): Promise<LocalProject | null> {
    await init()
    const project = state.value.projects[projectId]
    return project && !project.deleted ? clone(project) : null
  }

  async function updateLocalProject(
    projectId: string,
    input: { name?: string; iconKey?: string; colorKey?: string },
  ): Promise<LocalProject> {
    await init()
    let result: LocalProject | null = null
    await update((next) => {
      const current = next.projects[projectId]
      if (!current || current.deleted) throw new Error('项目不存在')
      result = {
        ...current,
        ...(input.name?.trim() ? { name: input.name.trim() } : {}),
        ...(input.iconKey ? { iconKey: input.iconKey } : {}),
        ...(input.colorKey ? { colorKey: input.colorKey } : {}),
        revision: current.revision + 1,
        updatedAt: new Date().toISOString(),
      }
      next.projects[projectId] = result
    })
    return clone(result!)
  }

  async function deleteLocalProject(projectId: string): Promise<void> {
    await init()
    await update((next) => {
      const project = next.projects[projectId]
      if (project) next.projects[projectId] = { ...project, deleted: true, revision: project.revision + 1 }
      for (const thread of Object.values(next.threads)) {
        if (thread.projectId !== projectId) continue
        next.threads[thread.id] = { ...thread, deleted: true, revision: thread.revision + 1 }
        delete next.snapshots[thread.id]
      }
    })
  }

  async function createLocalSession(projectId?: string, title = '新会话'): Promise<LocalThread> {
    await init()
    const project = projectId ? state.value.projects[projectId] : undefined
    if (projectId && (!project || project.deleted)) throw new Error('项目不存在')
    const thread = localThread(project, title, new Date().toISOString())
    await update((next) => {
      next.threads[thread.id] = thread
      next.snapshots[thread.id] = emptySnapshot(thread.id)
    })
    return thread
  }

  async function updateLocalSession(
    threadId: string,
    input: { title?: string; metadata?: Record<string, unknown>; status?: string },
  ): Promise<LocalThread> {
    await init()
    let result: LocalThread | null = null
    await update((next) => {
      const current = next.threads[threadId]
      if (!current || current.deleted) throw new Error('会话不存在')
      result = {
        ...current,
        ...(input.title?.trim() ? { title: input.title.trim() } : {}),
        ...(input.status ? { status: input.status } : {}),
        ...(input.metadata ? { metadata: { ...current.metadata, ...input.metadata } } : {}),
        revision: current.revision + 1,
        updatedAt: new Date().toISOString(),
      }
      next.threads[threadId] = result
    })
    return clone(result!)
  }

  async function deleteLocalSession(threadId: string): Promise<void> {
    await init()
    await update((next) => {
      const current = next.threads[threadId]
      if (current) next.threads[threadId] = { ...current, deleted: true, revision: current.revision + 1 }
      delete next.snapshots[threadId]
    })
  }

  async function saveLocalSnapshot(snapshot: CoreAppSnapshot): Promise<void> {
    await init()
    await update((next) => {
      const normalized = normalizeSnapshot(snapshot, snapshot.thread_id)
      next.snapshots[snapshot.thread_id] = normalized
      next.snapshotRevision = Math.max(next.snapshotRevision, numberOrZero(normalized.revision))
      updateThreadFromSnapshot(next, normalized)
    })
  }

  async function importLocalProject(
    sourceProject: LocalProject,
    sourceThreads: LocalThread[],
    snapshots: CoreAppSnapshot[],
  ): Promise<LocalProject> {
    await init()
    const now = new Date().toISOString()
    const projectId = globalThis.crypto?.randomUUID?.() || `project-${Date.now()}`
    const workRoot = `mobile://${projectId}`
    const imported: LocalProject = {
      ...sourceProject,
      id: projectId,
      name: sourceProject.name,
      path: workRoot,
      workRoot,
      revision: 1,
      createdAt: now,
      updatedAt: now,
      deleted: false,
    }
    const snapshotByThread = new Map(snapshots.map((snapshot) => [snapshot.thread_id, snapshot]))
    await update((next) => {
      next.projects[projectId] = imported
      for (const sourceThread of sourceThreads) {
        const threadId = globalThis.crypto?.randomUUID?.() || `thread-${Date.now()}-${Math.random()}`
        const thread: LocalThread = {
          ...sourceThread,
          id: threadId,
          projectId,
          revision: 1,
          createdAt: now,
          updatedAt: now,
          metadata: { ...sourceThread.metadata, project_id: projectId, work_root: workRoot, imported_from: sourceThread.id },
          deleted: false,
        }
        next.threads[threadId] = thread
        const sourceSnapshot = snapshotByThread.get(sourceThread.id)
        next.snapshots[threadId] = sourceSnapshot
          ? remapSnapshotThread(sourceSnapshot, threadId, projectId, workRoot)
          : emptySnapshot(threadId)
      }
    })
    return imported
  }

  async function applySyncSnapshot(payload: Record<string, unknown>): Promise<void> {
    await init()
    await enqueue(async () => {
      const next = emptyLocalState()
      next.desktopId = state.value.desktopId
      next.accountScope = state.value.accountScope
      const snapshotCursor = integerCursor(payload.cursor)
      if (snapshotCursor == null) throw new Error('同步响应缺少有效游标')
      const payloadWorkspaceId = stringValue(payload.workspace_id || payload.workspaceId)
      if (payloadWorkspaceId && state.value.hostWorkspaceId && payloadWorkspaceId !== state.value.hostWorkspaceId) {
        throw new Error('同步响应属于其他工作环境，已拒绝写入本地缓存')
      }
      // Relay's account Workspace id and the desktop Core's local Workspace
      // id are different namespaces.  Keep the former as the cache scope and
      // remember the latter only for response/source validation.
      next.workspaceId = state.value.workspaceId
      next.hostWorkspaceId = payloadWorkspaceId || state.value.hostWorkspaceId
      next.cursor = snapshotCursor
      next.snapshotVersion = numberOrZero(payload.snapshotVersion)
      next.workspaceRevision = numberOrZero(
        payload.workspace_revision || payload.workspaceRevision || payload.cursor,
      )
      next.snapshotRevision = numberOrZero(payload.snapshot_revision || payload.snapshotRevision)
      next.snapshotRequired = false
      next.lastSyncAt = new Date().toISOString()
      for (const value of arrayOfRecords(payload.projects)) {
        const project = toProject(value)
        if (project) next.projects[project.id] = project
      }
      for (const value of arrayOfRecords(payload.threads)) {
        const thread = toThread(value)
        if (thread) {
          next.threads[thread.id] = {
            ...thread,
            projectId: thread.projectId || projectIdForThread(next, thread),
          }
        }
      }
      for (const value of arrayOfRecords(payload.snapshots)) {
        const snapshot = value.snapshot
        const id = String(value.thread_id || value.id || (isRecord(snapshot) ? snapshot.thread_id : '') || '')
        if (!id || value.deleted === true || !isRecord(snapshot)) continue
        const normalizedSnapshot = normalizeSnapshot(snapshot as CoreAppSnapshot, id)
        next.snapshots[id] = normalizedSnapshot
        next.snapshotRevision = Math.max(next.snapshotRevision, normalizedSnapshot.revision || 0)
        if (!next.threads[id]) updateThreadFromSnapshot(next, normalizedSnapshot)
      }
      for (const value of arrayOfRecords(payload.messages)) {
        const message = toMessage(value)
        if (message) next.messages[`${message.threadId}:${message.seq}:${message.id}`] = message
      }
      next.snapshotRevision = Math.max(
        next.snapshotRevision,
        ...Object.values(next.snapshots).map((snapshot) => numberOrZero(snapshot.revision)),
      )
      await replaceState(next)
    })
  }

  async function applySyncChange(change: LocalSyncChange): Promise<void> {
    await init()
    await enqueue(async () => {
      const next = clone(state.value)
      const changeWorkspaceId = stringValue(change.workspace_id || change.workspaceId)
      if (changeWorkspaceId && next.hostWorkspaceId && changeWorkspaceId !== next.hostWorkspaceId) return
      if (changeWorkspaceId && !next.hostWorkspaceId) next.hostWorkspaceId = changeWorkspaceId
      const seq = Number(change.seq)
      if (!Number.isFinite(seq) || seq <= (next.cursor || 0)) return
      next.workspaceRevision = Math.max(
        next.workspaceRevision,
        numberOrZero(change.workspace_revision || change.workspaceRevision || seq),
      )
      next.snapshotRevision = Math.max(
        next.snapshotRevision,
        numberOrZero(change.snapshot_revision || change.snapshotRevision || change.revision),
      )
      next.syncBuffer[String(seq)] = change
      let cursor = next.cursor || 0
      while (next.syncBuffer[String(cursor + 1)]) {
        const current = next.syncBuffer[String(cursor + 1)]
        delete next.syncBuffer[String(cursor + 1)]
        applyOneChange(next, current)
        cursor += 1
      }
      next.cursor = cursor
      next.snapshotVersion = Math.max(next.snapshotVersion, cursor)
      next.lastSyncAt = new Date().toISOString()
      await replaceState(next)
    })
  }

  async function applySyncBatch(changes: LocalSyncChange[], expectedCursor?: number | null): Promise<void> {
    await init()
    await enqueue(async () => {
      const next = clone(state.value)
      const initialCursor = next.cursor || 0
      const seen = new Set<number>()
      const sequences: number[] = []
      for (const change of changes) {
        const seq = integerCursor(change.seq)
        if (seq == null || seq <= initialCursor || seen.has(seq) || next.syncBuffer[String(seq)]) {
          throw new Error('同步响应包含无效或重复游标')
        }
        seen.add(seq)
        sequences.push(seq)
        const changeWorkspaceId = stringValue(change.workspace_id || change.workspaceId)
        if (changeWorkspaceId && next.hostWorkspaceId && changeWorkspaceId !== next.hostWorkspaceId) {
          throw new Error('同步响应属于其他工作环境，已拒绝写入本地缓存')
        }
        if (changeWorkspaceId && !next.hostWorkspaceId) next.hostWorkspaceId = changeWorkspaceId
        next.workspaceRevision = Math.max(
          next.workspaceRevision,
          numberOrZero(change.workspace_revision || change.workspaceRevision || seq),
        )
        next.snapshotRevision = Math.max(
          next.snapshotRevision,
          numberOrZero(change.snapshot_revision || change.snapshotRevision || change.revision),
        )
        next.syncBuffer[String(seq)] = change
      }

      let cursor = initialCursor
      while (next.syncBuffer[String(cursor + 1)]) {
        const current = next.syncBuffer[String(cursor + 1)]
        delete next.syncBuffer[String(cursor + 1)]
        applyOneChange(next, current)
        cursor += 1
      }
      const targetCursor = expectedCursor == null
        ? (sequences.length ? Math.max(...sequences) : cursor)
        : integerCursor(expectedCursor)
      if (targetCursor == null || targetCursor < initialCursor || cursor !== targetCursor) {
        throw new Error('同步响应游标不连续')
      }
      next.cursor = cursor
      next.snapshotVersion = Math.max(next.snapshotVersion, cursor)
      if (changes.length) next.lastSyncAt = new Date().toISOString()
      await replaceState(next)
    })
  }

  async function applyTransientEvent(event: CoreAppEvent): Promise<void> {
    await init()
    await update((next) => applyEventToState(next, event))
  }

  async function applySessionEvent(method: string, params: Record<string, unknown>): Promise<void> {
    await init()
    await update((next) => {
      const session = isRecord(params.session) ? params.session : params
      const id = String(session.id || params.session_id || params.thread_id || '').trim()
      if (!id) return
      const current = next.threads[id] || {
        id,
        title: id,
        status: 'idle',
        revision: 0,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        metadata: {},
        deleted: false,
      }
      if (method === 'session/deleted') {
        next.threads[id] = {
          ...current,
          revision: Math.max(current.revision, numberOrZero(session.revision)),
          deleted: true,
          updatedAt: new Date().toISOString(),
        }
        return
      }
      next.threads[id] = {
        ...current,
        title: String(session.title || current.title || id),
        status: String(session.status || current.status || 'idle'),
        revision: Math.max(current.revision, numberOrZero(session.revision)),
        updatedAt: String(session.updated_at || session.updatedAt || new Date().toISOString()),
        metadata: isRecord(session.metadata) ? session.metadata : current.metadata,
        deleted: false,
      }
    })
  }

  async function update(mutator: (next: LocalState) => void): Promise<void> {
    await enqueue(async () => {
      const next = clone(state.value)
      mutator(next)
      await replaceState(next)
    })
  }

  async function replaceState(next: LocalState): Promise<void> {
    state.value = normalizeState(next)
    activeScope = scopeFor(state.value.accountScope, state.value.desktopId, state.value.workspaceId)
    localScopes.set(activeScope, clone(state.value))
    if (database.writeScope) await database.writeScope(activeScope, state.value)
    else await database.write(state.value)
    for (const listener of listeners) listener(state.value)
  }

  async function switchScope(
    workspaceId: string,
    desktopId: string,
    accountScope = desiredAccountScope,
  ): Promise<void> {
    await enqueue(async () => {
      const normalizedWorkspaceId = workspaceId.trim()
      const normalizedDesktopId = desktopId.trim()
      const targetScope = scopeFor(accountScope, normalizedDesktopId, normalizedWorkspaceId)
      if (activeScope === targetScope
        && state.value.workspaceId === normalizedWorkspaceId
        && state.value.desktopId === normalizedDesktopId) return

      localScopes.set(activeScope, clone(state.value))
      let saved: LocalState | null = null
      if (database.readScope) saved = await database.readScope(targetScope)
      else saved = localScopes.get(targetScope) || null
      const next = normalizeState(saved)
      next.accountScope = accountScope
      next.workspaceId = normalizedWorkspaceId
      next.desktopId = normalizedDesktopId || next.desktopId
      await replaceState(next)
    })
  }

  function enqueue(task: () => Promise<void>): Promise<void> {
    const next = writeQueue.then(task)
    writeQueue = next.catch(() => undefined)
    return next
  }

  return {
    state,
    init,
    setAccountScope,
    setDesktopId,
    setWorkspaceId,
    listProjects,
    listSessions,
    loadThreadSnapshot,
    createLocalProject,
    getLocalProject,
    updateLocalProject,
    deleteLocalProject,
    createLocalSession,
    updateLocalSession,
    deleteLocalSession,
    saveLocalSnapshot,
    importLocalProject,
    applySyncSnapshot,
    applySyncChange,
    applySyncBatch,
    applyTransientEvent,
    applySessionEvent,
    close: async () => { await writeQueue; await database.close() },
    subscribe: (listener: (value: LocalState) => void) => {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
  }
}

function localThread(project: LocalProject | undefined, title: string, now: string): LocalThread {
  const id = globalThis.crypto?.randomUUID?.() || `thread-${Date.now()}`
  return {
    id,
    projectId: project?.id,
    title: title.trim() || '新会话',
    status: 'idle',
    revision: 1,
    createdAt: now,
    updatedAt: now,
    metadata: project ? { project_id: project.id, work_root: project.workRoot } : {},
    deleted: false,
  }
}

function remapSnapshotThread(
  snapshot: CoreAppSnapshot,
  threadId: string,
  projectId: string,
  workRoot: string,
): CoreAppSnapshot {
  const next = clone(snapshot)
  next.thread_id = threadId
  if (next.core) next.core.thread_id = threadId
  const withSession = next as CoreAppSnapshot & {
    session?: { id?: string; metadata?: Record<string, unknown> }
  }
  if (withSession.session) {
    withSession.session.id = threadId
    withSession.session.metadata = {
      ...(withSession.session.metadata || {}),
      project_id: projectId,
      work_root: workRoot,
    }
  }
  return normalizeSnapshot(next, threadId)
}

function applyOneChange(state: LocalState, change: LocalSyncChange): void {
  const entity = isRecord(change.entity) ? change.entity : {}
  const type = String(change.type || '')
  const operation = String(change.operation || 'upsert')
  if (type === 'thread.event') {
    const event = isRecord(entity.event) ? entity.event as unknown as CoreAppEvent : null
    const eventPayload = event && isRecord(event.payload) ? event.payload : {}
    if (
      change.snapshot_required === true
      || change.snapshotRequired === true
      || entity.snapshot_required === true
      || entity.snapshotRequired === true
      || event?.method === 'session/rollback'
      || eventPayload.snapshot_required === true
      || eventPayload.snapshotRequired === true
    ) {
      // A rollback can remove an arbitrary event tail and can replace the
      // branch entirely. Applying the control event as a normal incremental
      // event would leave deleted messages in the cache.
      state.snapshotRequired = true
      return
    }
    if (event) {
      if (event.revision == null && change.revision != null) event.revision = change.revision
      applyEventToState(state, event)
    }
    return
  }
  if (type === 'project') {
    const id = String(change.entity_id || entity.id || '').trim()
    if (!id) return
    const current = state.projects[id]
    if (operation === 'delete') {
      state.projects[id] = {
        ...(current || emptyProject(id)),
        revision: Math.max(current?.revision || 0, numberOrZero(change.revision)),
        deleted: true,
      }
    } else {
      const project = toProject({ ...entity, id })
      if (project) state.projects[id] = project
    }
    return
  }
  if (type === 'thread') {
    if (operation === 'delete' || entity.deleted === true) {
      const id = String(change.entity_id || entity.id || '').trim()
      if (id) {
        const current = state.threads[id] || emptyThread(id)
        state.threads[id] = {
          ...current,
          revision: Math.max(current.revision, numberOrZero(change.revision)),
          deleted: true,
        }
      }
      return
    }
    const thread = toThread({ ...entity, id: change.entity_id || entity.id })
    if (thread) {
      const current = state.threads[thread.id]
      state.threads[thread.id] = {
        ...(current || {}),
        ...thread,
        projectId: thread.projectId || current?.projectId || projectIdForThread(state, thread),
      }
    }
    const snapshot = entity.snapshot
    if (thread && isRecord(snapshot)) {
      const normalizedSnapshot = normalizeSnapshot(snapshot as CoreAppSnapshot, thread.id)
      state.snapshots[thread.id] = normalizedSnapshot
      state.snapshotRevision = Math.max(state.snapshotRevision, numberOrZero(normalizedSnapshot.revision))
    }
    return
  }
  if (type === 'message') {
    const message = toMessage({ ...entity, id: change.entity_id || entity.id })
    if (!message) return
    const key = `${message.threadId}:${message.seq}:${message.id}`
    state.messages[key] = operation === 'delete'
      ? { ...message, revision: Math.max(message.revision, numberOrZero(change.revision)), deleted: true }
      : message
    return
  }
  if (type === 'runtime') {
    const id = String(change.entity_id || entity.thread_id || '').trim()
    if (id) state.runtimeState[id] = {
      ...entity,
      thread_id: id,
      revision: Math.max(numberOrZero(state.runtimeState[id]?.revision), numberOrZero(change.revision)),
    }
  }
}

function applyEventToState(state: LocalState, event: CoreAppEvent): void {
  const threadId = String(event.thread_id || '').trim()
  if (!threadId) return
  const current = state.snapshots[threadId] || emptySnapshot(threadId)
  const next = normalizeSnapshot(applyCoreAppEvent(current, event), threadId)
  next.revision = Math.max(numberOrZero(next.revision), numberOrZero(event.revision))
  if (next.core) next.core.revision = Math.max(numberOrZero(next.core.revision), next.revision)
  if (event.seq > 0) {
    next.snapshot_seq = Math.max(Number(next.snapshot_seq || 0), event.seq)
    if (next.core) next.core.snapshot_seq = Math.max(Number(next.core.snapshot_seq || 0), event.seq)
  }
  state.snapshots[threadId] = next
  state.snapshotRevision = Math.max(state.snapshotRevision, next.revision)
  updateThreadFromSnapshot(state, next)
}

function updateThreadFromSnapshot(state: LocalState, snapshot: CoreAppSnapshot): void {
  const id = snapshot.thread_id
  const session = isRecord((snapshot as CoreAppSnapshot & { session?: unknown }).session)
    ? (snapshot as CoreAppSnapshot & { session?: Record<string, unknown> }).session!
    : {}
  const metadata = isRecord(session.metadata) ? session.metadata : {}
  const current = state.threads[id] || emptyThread(id)
  state.threads[id] = {
    ...current,
    projectId: current.projectId || projectIdForThread(state, { metadata }),
    title: String(session.title || current.title || id),
    status: String(snapshot.status || snapshot.core?.status || current.status || 'idle'),
    revision: Math.max(current.revision, numberOrZero(snapshot.revision)),
    createdAt: String(session.created_at || current.createdAt),
    updatedAt: new Date().toISOString(),
    metadata,
    deleted: false,
  }
}

function projectIdForThread(state: LocalState, thread: { metadata?: Record<string, unknown> }): string | undefined {
  const explicit = thread.metadata?.project_id
  if (typeof explicit === 'string' && explicit) return explicit
  const workRoot = typeof thread.metadata?.work_root === 'string' ? thread.metadata.work_root : ''
  if (!workRoot) return undefined
  return Object.values(state.projects).find((project) => project.workRoot === workRoot || project.path === workRoot)?.id
}

function toProject(value: Record<string, unknown>): LocalProject | null {
  const id = String(value.id || '').trim()
  if (!id) return null
  return {
    id,
    name: String(value.name || id),
    path: String(value.path || value.work_root || ''),
    workRoot: String(value.work_root || value.path || ''),
    iconKey: String(value.icon_key || value.iconKey || ''),
    colorKey: String(value.color_key || value.colorKey || ''),
    revision: numberOrZero(value.revision || value.project_revision),
    createdAt: String(value.created_at || value.createdAt || ''),
    updatedAt: String(value.updated_at || value.updatedAt || ''),
    deleted: value.deleted === true,
  }
}

function toThread(value: Record<string, unknown>): LocalThread | null {
  const id = String(value.id || value.thread_id || '').trim()
  if (!id) return null
  return {
    id,
    projectId: typeof value.project_id === 'string' ? value.project_id : undefined,
    title: String(value.title || id),
    status: String(value.status || 'idle'),
    revision: numberOrZero(value.revision || value.session_revision || value.thread_revision),
    createdAt: String(value.created_at || value.createdAt || ''),
    updatedAt: String(value.updated_at || value.updatedAt || ''),
    metadata: isRecord(value.metadata) ? value.metadata : {},
    deleted: value.deleted === true,
  }
}

function toMessage(value: Record<string, unknown>): LocalMessage | null {
  const message = isRecord(value.message) ? value.message : value
  const threadId = String(value.thread_id || message.session_id || message.thread_id || '').trim()
  if (!threadId) return null
  const seq = numberOrZero(value.seq || message.seq)
  const id = String(value.id || message.id || `${threadId}:${seq}`)
  return {
    id,
    threadId,
    seq,
    revision: numberOrZero(value.revision || value.message_revision || message.revision),
    role: String(message.role || 'assistant'),
    content: String(message.content || ''),
    createdAt: String(message.created_at || message.createdAt || ''),
    updatedAt: String(message.updated_at || message.updatedAt || ''),
    deleted: value.deleted === true,
    payload: message,
  }
}

function emptyLocalState(): LocalState {
  return {
    desktopId: '',
    accountScope: '',
    workspaceId: '',
    hostWorkspaceId: '',
    cursor: null,
    snapshotVersion: 0,
    workspaceRevision: 0,
    snapshotRevision: 0,
    snapshotRequired: false,
    lastSyncAt: '',
    projects: {},
    threads: {},
    messages: {},
    runtimeState: {},
    snapshots: {},
    pendingOperations: {},
    syncBuffer: {},
  }
}

function emptySnapshot(threadId: string): CoreAppSnapshot {
  return {
    thread_id: threadId,
    snapshot_seq: 0,
    revision: 0,
    seen_event_ids: [],
    turns: {},
    items: {},
    item_order: [],
    requests: {},
    artifacts: {},
    queue: [],
    status: 'idle',
    core: {
      thread_id: threadId,
      snapshot_seq: 0,
      revision: 0,
      seen_event_ids: [],
      turns: {},
      items: {},
      item_order: [],
      requests: {},
      artifacts: {},
      status: 'idle',
    },
  }
}

function emptyProject(id: string): LocalProject {
  return {
    id,
    name: id,
    path: '',
    workRoot: '',
    iconKey: '',
    colorKey: '',
    revision: 0,
    createdAt: '',
    updatedAt: '',
    deleted: false,
  }
}

function emptyThread(id: string): LocalThread {
  return { id, title: id, status: 'idle', revision: 0, createdAt: '', updatedAt: '', metadata: {}, deleted: false }
}

function normalizeState(value: LocalState | null | undefined): LocalState {
  const base = emptyLocalState()
  if (!value || typeof value !== 'object') return base
  const legacy = value as LocalState & {
    workspace_revision?: unknown
    snapshot_revision?: unknown
    snapshot_required?: unknown
  }
  const projects = normalizeRecord(value.projects, (raw, id) => ({
    ...raw,
    id: stringValue(raw.id || id),
    iconKey: stringValue(raw.iconKey || raw.icon_key),
    colorKey: stringValue(raw.colorKey || raw.color_key),
    revision: numberOrZero(raw.revision || raw.project_revision),
  })) as Record<string, LocalProject>
  const threads = normalizeRecord(value.threads, (raw, id) => ({
    ...raw,
    id: stringValue(raw.id || id),
    revision: numberOrZero(raw.revision || raw.session_revision || raw.thread_revision),
  })) as Record<string, LocalThread>
  const messages = normalizeRecord(value.messages, (raw, id) => ({
    ...raw,
    id: stringValue(raw.id || id),
    revision: numberOrZero(raw.revision || raw.message_revision),
  })) as Record<string, LocalMessage>
  const snapshots = normalizeRecord(value.snapshots, (raw, id) =>
    normalizeSnapshot(raw as CoreAppSnapshot, String(raw.thread_id || id)),
  ) as Record<string, CoreAppSnapshot>
  return {
    ...base,
    ...value,
    accountScope: stringValue(
      value.accountScope
      || (value as LocalState & { account_scope?: unknown }).account_scope,
    ),
    workspaceId: stringValue(value.workspaceId),
    hostWorkspaceId: stringValue(
      value.hostWorkspaceId
      || (value as LocalState & { host_workspace_id?: unknown }).host_workspace_id,
    ),
    cursor: value.cursor == null ? null : numberOrZero(value.cursor),
    snapshotVersion: numberOrZero(value.snapshotVersion),
    workspaceRevision: numberOrZero(
      value.workspaceRevision || legacy.workspace_revision || value.cursor,
    ),
    snapshotRevision: Math.max(
      numberOrZero(value.snapshotRevision || legacy.snapshot_revision),
      ...Object.values(snapshots).map((snapshot) => numberOrZero(snapshot.revision)),
    ),
    snapshotRequired: value.snapshotRequired === true || legacy.snapshot_required === true,
    projects,
    threads,
    messages,
    runtimeState: value.runtimeState || {},
    snapshots,
    pendingOperations: value.pendingOperations || {},
    syncBuffer: value.syncBuffer || {},
  }
}

function normalizeRecord(
  value: unknown,
  mapper: (raw: Record<string, any>, id: string) => Record<string, any>,
): Record<string, Record<string, any>> {
  if (!isRecord(value)) return {}
  return Object.fromEntries(
    Object.entries(value)
      .filter(([, raw]) => isRecord(raw))
      .map(([id, raw]) => [id, mapper(raw, id)]),
  )
}

function normalizeSnapshot(snapshot: CoreAppSnapshot, threadId: string): CoreAppSnapshot {
  const revision = numberOrZero(snapshot.revision)
  const core = isRecord(snapshot.core)
    ? { ...snapshot.core, revision: Math.max(revision, numberOrZero(snapshot.core.revision)) }
    : undefined
  return {
    ...snapshot,
    thread_id: String(snapshot.thread_id || threadId),
    revision: Math.max(revision, numberOrZero(core?.revision)),
    ...(core ? { core } : {}),
  }
}

function accountScopeFor(serverId: string, accountId: string): string {
  const server = serverId.trim()
  const account = accountId.trim().toLowerCase()
  if (!server && !account) return ''
  return `${encodeURIComponent(server)}:${encodeURIComponent(account)}`
}

function scopeFor(accountScope: string, desktopId: string, workspaceId: string): string {
  const prefix = accountScope ? `account:${accountScope}` : 'account:anonymous'
  const normalizedWorkspaceId = workspaceId.trim()
  if (normalizedWorkspaceId) return `${prefix}:workspace:${encodeURIComponent(normalizedWorkspaceId)}`
  const normalizedDesktopId = desktopId.trim()
  if (normalizedDesktopId) return `${prefix}:desktop:${encodeURIComponent(normalizedDesktopId)}`
  return `${prefix}:default`
}

function integerCursor(value: unknown): number | null {
  const number = Number(value)
  return Number.isSafeInteger(number) && number >= 0 ? number : null
}

function clone<T>(value: T): T {
  if (typeof structuredClone === 'function') {
    try {
      return structuredClone(value)
    } catch {
      // Vue refs expose reactive proxies that structuredClone cannot accept.
      // The persisted state is JSON by contract, so serialization is a safe
      // and deterministic fallback for those proxies.
    }
  }
  return JSON.parse(JSON.stringify(value)) as T
}

function arrayOfRecords(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter(isRecord) : []
}

function isRecord(value: unknown): value is Record<string, any> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function numberOrZero(value: unknown): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}

function stringValue(value: unknown): string {
  return value == null ? '' : String(value).trim()
}
