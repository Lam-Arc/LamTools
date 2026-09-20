import { Capacitor } from '@capacitor/core'
import { CapacitorSQLite, SQLiteConnection, type SQLiteDBConnection } from '@capacitor-community/sqlite'

export interface LocalDatabase<TState> {
  open(): Promise<void>
  read(): Promise<TState | null>
  write(state: TState): Promise<void>
  /** Optional scoped persistence used by multi-Workspace mobile clients. */
  readScope?(scope: string): Promise<TState | null>
  writeScope?(scope: string, state: TState): Promise<void>
  close(): Promise<void>
}

const SQLITE_SCHEMA = `
CREATE TABLE IF NOT EXISTS sync_state (
  desktop_id TEXT PRIMARY KEY NOT NULL,
  cursor INTEGER,
  snapshot_version INTEGER NOT NULL DEFAULT 0,
  workspace_revision INTEGER NOT NULL DEFAULT 0,
  snapshot_revision INTEGER NOT NULL DEFAULT 0,
  last_sync_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY NOT NULL,
  name TEXT NOT NULL,
  path TEXT NOT NULL DEFAULT '',
  revision INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL DEFAULT '',
  deleted INTEGER NOT NULL DEFAULT 0,
  payload TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS threads (
  id TEXT PRIMARY KEY NOT NULL,
  project_id TEXT,
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'idle',
  revision INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL DEFAULT '',
  deleted INTEGER NOT NULL DEFAULT 0,
  payload TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY NOT NULL,
  thread_id TEXT NOT NULL,
  seq INTEGER NOT NULL DEFAULT 0,
  role TEXT NOT NULL DEFAULT 'assistant',
  content TEXT NOT NULL DEFAULT '',
  revision INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL DEFAULT '',
  deleted INTEGER NOT NULL DEFAULT 0,
  payload TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS runtime_state (
  thread_id TEXT PRIMARY KEY NOT NULL,
  status TEXT NOT NULL DEFAULT 'idle',
  model TEXT,
  mode TEXT,
  revision INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL DEFAULT '',
  payload TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS pending_operations (
  local_op_id TEXT PRIMARY KEY NOT NULL,
  operation TEXT NOT NULL,
  payload TEXT NOT NULL DEFAULT '{}',
  state TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS local_state (
  id INTEGER PRIMARY KEY NOT NULL CHECK (id = 1),
  state_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS local_state_scopes (
  scope TEXT PRIMARY KEY NOT NULL,
  state_json TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT ''
);

-- The legacy tables above remain for installed databases. These materialized
-- tables use a composite key so identical project/thread ids from two remote
-- Workspaces can never overwrite one another.
CREATE TABLE IF NOT EXISTS projects_scoped (
  workspace_id TEXT NOT NULL,
  id TEXT NOT NULL,
  name TEXT NOT NULL,
  path TEXT NOT NULL DEFAULT '',
  revision INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL DEFAULT '',
  deleted INTEGER NOT NULL DEFAULT 0,
  payload TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (workspace_id, id)
);
CREATE TABLE IF NOT EXISTS threads_scoped (
  workspace_id TEXT NOT NULL,
  id TEXT NOT NULL,
  project_id TEXT,
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'idle',
  revision INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL DEFAULT '',
  deleted INTEGER NOT NULL DEFAULT 0,
  payload TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (workspace_id, id)
);
CREATE TABLE IF NOT EXISTS messages_scoped (
  workspace_id TEXT NOT NULL,
  id TEXT NOT NULL,
  thread_id TEXT NOT NULL,
  seq INTEGER NOT NULL DEFAULT 0,
  role TEXT NOT NULL DEFAULT 'assistant',
  content TEXT NOT NULL DEFAULT '',
  revision INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL DEFAULT '',
  deleted INTEGER NOT NULL DEFAULT 0,
  payload TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (workspace_id, id, thread_id, seq)
);
CREATE TABLE IF NOT EXISTS runtime_state_scoped (
  workspace_id TEXT NOT NULL,
  thread_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'idle',
  model TEXT,
  mode TEXT,
  revision INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL DEFAULT '',
  payload TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (workspace_id, thread_id)
);
CREATE TABLE IF NOT EXISTS pending_operations_scoped (
  workspace_id TEXT NOT NULL,
  local_op_id TEXT NOT NULL,
  operation TEXT NOT NULL,
  payload TEXT NOT NULL DEFAULT '{}',
  state TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (workspace_id, local_op_id)
);
CREATE TABLE IF NOT EXISTS sync_state_scoped (
  workspace_id TEXT NOT NULL,
  desktop_id TEXT NOT NULL DEFAULT '',
  cursor INTEGER,
  snapshot_version INTEGER NOT NULL DEFAULT 0,
  workspace_revision INTEGER NOT NULL DEFAULT 0,
  snapshot_revision INTEGER NOT NULL DEFAULT 0,
  last_sync_at TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (workspace_id, desktop_id)
);
CREATE TABLE IF NOT EXISTS snapshots_scoped (
  workspace_id TEXT NOT NULL,
  thread_id TEXT NOT NULL,
  snapshot_seq INTEGER NOT NULL DEFAULT 0,
  revision INTEGER NOT NULL DEFAULT 0,
  deleted INTEGER NOT NULL DEFAULT 0,
  snapshot_json TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (workspace_id, thread_id)
);`

/** SQLite on iOS/Android. The normalized tables are the durable contract;
 * local_state is an atomic materialized copy used to restore the reactive
 * repository without a partial snapshot after process death. */
class CapacitorLocalDatabase<TState> implements LocalDatabase<TState> {
  private readonly connection = new SQLiteConnection(CapacitorSQLite)
  private db: SQLiteDBConnection | null = null

  constructor(private readonly name: string) {}

  async open(): Promise<void> {
    this.db = await this.connection.createConnection(this.name, false, 'no-encryption', 1, false)
    await this.db.open()
    await this.db.execute(SQLITE_SCHEMA)
    await this.migrateSchema()
  }

  async read(): Promise<TState | null> {
    if (!this.db) throw new Error('Local database is not open')
    const result = await this.db.query('SELECT state_json FROM local_state WHERE id = 1')
    const value = result.values?.[0]?.state_json
    if (typeof value !== 'string') return null
    return JSON.parse(value) as TState
  }

  async write(state: TState): Promise<void> {
    await this.writeScope(localStateScope(state), state)
  }

  async readScope(scope: string): Promise<TState | null> {
    if (!this.db) throw new Error('Local database is not open')
    const result = await this.db.query(
      'SELECT state_json FROM local_state_scopes WHERE scope = ?',
      [scope],
    )
    const value = result.values?.[0]?.state_json
    if (typeof value === 'string') return JSON.parse(value) as TState
    // A database created before scoped persistence has one recoverable active
    // state. It is safe to expose it only to the unscoped legacy namespace.
    return scope === 'default' ? await this.read() : null
  }

  async writeScope(scope: string, state: TState): Promise<void> {
    if (!this.db) throw new Error('Local database is not open')
    const value = JSON.stringify(state)
    await this.db.beginTransaction()
    try {
      await this.writeNormalizedState(scope, state)
      await this.db.run(
        'INSERT OR REPLACE INTO local_state_scopes (scope, state_json, updated_at) VALUES (?, ?, ?)',
        [scope, value, new Date().toISOString()],
      )
      await this.db.run('INSERT OR REPLACE INTO local_state (id, state_json) VALUES (1, ?)', [value])
      await this.db.commitTransaction()
    } catch (error) {
      await this.db.rollbackTransaction().catch(() => undefined)
      throw error
    }
  }

  private async writeNormalizedState(scope: string, state: TState): Promise<void> {
    if (!this.db || !isRecord(state)) return

    // Keep the normalized tables as an atomic materialized view of the
    // repository state.  local_state remains the recovery source, while the
    // tables make the mobile storage contract queryable by native code.
    for (const table of [
      'projects_scoped',
      'threads_scoped',
      'messages_scoped',
      'runtime_state_scoped',
      'pending_operations_scoped',
      'sync_state_scoped',
      'snapshots_scoped',
    ]) {
      await this.db.run(`DELETE FROM ${table} WHERE workspace_id = ?`, [scope])
    }

    for (const project of objectValues(state.projects)) {
      await this.db.run(
        'INSERT OR REPLACE INTO projects_scoped (workspace_id, id, name, path, revision, updated_at, deleted, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        [
          scope,
          stringValue(project.id),
          stringValue(project.name),
          stringValue(project.path),
          numberValue(project.revision),
          stringValue(project.updatedAt),
          project.deleted === true ? 1 : 0,
          JSON.stringify(project),
        ],
      )
    }
    for (const thread of objectValues(state.threads)) {
      await this.db.run(
        'INSERT OR REPLACE INTO threads_scoped (workspace_id, id, project_id, title, status, revision, updated_at, deleted, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
        [
          scope,
          stringValue(thread.id),
          stringValue(thread.projectId),
          stringValue(thread.title),
          stringValue(thread.status || 'idle'),
          numberValue(thread.revision),
          stringValue(thread.updatedAt),
          thread.deleted === true ? 1 : 0,
          JSON.stringify(thread),
        ],
      )
    }
    for (const message of objectValues(state.messages)) {
      await this.db.run(
        'INSERT OR REPLACE INTO messages_scoped (workspace_id, id, thread_id, seq, role, content, revision, created_at, updated_at, deleted, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        [
          scope,
          stringValue(message.id),
          stringValue(message.threadId),
          numberValue(message.seq),
          stringValue(message.role || 'assistant'),
          stringValue(message.content),
          numberValue(message.revision),
          stringValue(message.createdAt),
          stringValue(message.updatedAt),
          message.deleted === true ? 1 : 0,
          JSON.stringify(message),
        ],
      )
    }
    for (const runtime of objectValues(state.runtimeState)) {
      const threadId = stringValue(runtime.thread_id || runtime.threadId)
      if (!threadId) continue
      await this.db.run(
        'INSERT OR REPLACE INTO runtime_state_scoped (workspace_id, thread_id, status, model, mode, revision, updated_at, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        [
          scope,
          threadId,
          stringValue(runtime.status || 'idle'),
          stringValue(runtime.model),
          stringValue(runtime.mode),
          numberValue(runtime.revision),
          stringValue(runtime.updated_at || runtime.updatedAt),
          JSON.stringify(runtime),
        ],
      )
    }
    for (const pending of objectValues(state.pendingOperations)) {
      await this.db.run(
        'INSERT OR REPLACE INTO pending_operations_scoped (workspace_id, local_op_id, operation, payload, state, created_at) VALUES (?, ?, ?, ?, ?, ?)',
        [
          scope,
          stringValue(pending.localOpId),
          stringValue(pending.operation),
          JSON.stringify(pending.payload || {}),
          stringValue(pending.state || 'pending'),
          stringValue(pending.createdAt),
        ],
      )
    }
    await this.db.run(
      'INSERT OR REPLACE INTO sync_state_scoped (workspace_id, desktop_id, cursor, snapshot_version, workspace_revision, snapshot_revision, last_sync_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
      [
        scope,
        stringValue(state.desktopId),
        state.cursor == null ? null : numberValue(state.cursor),
        numberValue(state.snapshotVersion),
        numberValue(state.workspaceRevision),
        numberValue(state.snapshotRevision),
        stringValue(state.lastSyncAt),
      ],
    )
    for (const snapshot of objectValues(state.snapshots)) {
      const threadId = stringValue(snapshot.thread_id)
      if (!threadId) continue
      await this.db.run(
        'INSERT OR REPLACE INTO snapshots_scoped (workspace_id, thread_id, snapshot_seq, revision, deleted, snapshot_json, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
        [
          scope,
          threadId,
          numberValue(snapshot.snapshot_seq),
          numberValue(snapshot.revision),
          0,
          JSON.stringify(snapshot),
          new Date().toISOString(),
        ],
      )
    }
  }

  private async migrateSchema(): Promise<void> {
    if (!this.db) throw new Error('Local database is not open')
    const additions: Record<string, Record<string, string>> = {
      sync_state: {
        workspace_revision: 'INTEGER NOT NULL DEFAULT 0',
        snapshot_revision: 'INTEGER NOT NULL DEFAULT 0',
      },
      projects: { revision: 'INTEGER NOT NULL DEFAULT 0' },
      threads: { revision: 'INTEGER NOT NULL DEFAULT 0' },
      messages: { revision: 'INTEGER NOT NULL DEFAULT 0' },
      runtime_state: { revision: 'INTEGER NOT NULL DEFAULT 0' },
      projects_scoped: { revision: 'INTEGER NOT NULL DEFAULT 0' },
      threads_scoped: { revision: 'INTEGER NOT NULL DEFAULT 0' },
      messages_scoped: { revision: 'INTEGER NOT NULL DEFAULT 0' },
      runtime_state_scoped: { revision: 'INTEGER NOT NULL DEFAULT 0' },
      sync_state_scoped: {
        workspace_revision: 'INTEGER NOT NULL DEFAULT 0',
        snapshot_revision: 'INTEGER NOT NULL DEFAULT 0',
      },
    }
    for (const [table, columns] of Object.entries(additions)) {
      const result = await this.db.query(`PRAGMA table_info(${table})`)
      const existing = new Set((result.values || []).map((row) => String(row.name || row[1] || '')))
      for (const [column, definition] of Object.entries(columns)) {
        if (!existing.has(column)) {
          await this.db.run(`ALTER TABLE ${table} ADD COLUMN ${column} ${definition}`)
        }
      }
    }
  }

  async close(): Promise<void> {
    if (!this.db) return
    await this.db.close().catch(() => undefined)
    await this.connection.closeConnection(this.name, false).catch(() => undefined)
    this.db = null
  }
}

class IndexedDbLocalDatabase<TState> implements LocalDatabase<TState> {
  private database: IDBDatabase | null = null

  constructor(private readonly name: string) {}

  async open(): Promise<void> {
    if (typeof indexedDB === 'undefined') return
    this.database = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open(this.name, 1)
      request.onupgradeneeded = () => request.result.createObjectStore('local_state')
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => reject(request.error || new Error('IndexedDB open failed'))
    })
  }

  async read(): Promise<TState | null> {
    if (!this.database) return readMemoryState<TState>(this.name)
    const value = await this.request<TState | undefined>('readonly', (store) => store.get('state'))
    return value ?? null
  }

  async write(state: TState): Promise<void> {
    await this.writeScope(localStateScope(state), state)
  }

  async readScope(scope: string): Promise<TState | null> {
    if (!this.database) {
      return readMemoryState<TState>(`${this.name}::${scope}`)
    }
    const value = await this.request<TState | undefined>('readonly', (store) => store.get(`scope:${scope}`))
    if (value != null) return value
    return scope === 'default'
      ? await this.read()
      : null
  }

  async writeScope(scope: string, state: TState): Promise<void> {
    if (!this.database) {
      writeMemoryState(`${this.name}::${scope}`, state)
      writeMemoryState(this.name, state)
      return
    }
    await this.request('readwrite', (store) => {
      store.put(state, `scope:${scope}`)
      return store.put(state, 'state')
    })
  }

  async close(): Promise<void> {
    this.database?.close()
    this.database = null
  }

  private request<TResult>(
    mode: IDBTransactionMode,
    operation: (store: IDBObjectStore) => IDBRequest,
  ): Promise<TResult> {
    return new Promise<TResult>((resolve, reject) => {
      if (!this.database) return reject(new Error('IndexedDB is not open'))
      const transaction = this.database.transaction('local_state', mode)
      const request = operation(transaction.objectStore('local_state'))
      request.onsuccess = () => resolve(request.result as TResult)
      request.onerror = () => reject(request.error || new Error('IndexedDB request failed'))
    })
  }
}

class MemoryLocalDatabase<TState> implements LocalDatabase<TState> {
  private static readonly values = new Map<string, unknown>()
  constructor(private readonly name: string) {}
  async open(): Promise<void> {}
  async read(): Promise<TState | null> {
    const value = MemoryLocalDatabase.values.get(this.name)
    if (isScopedBucket<TState>(value)) return value.active
    return (value as TState | undefined) ?? null
  }
  async write(state: TState): Promise<void> {
    await this.writeScope(localStateScope(state), state)
  }
  async readScope(scope: string): Promise<TState | null> {
    const bucket = MemoryLocalDatabase.values.get(this.name)
    if (isScopedBucket<TState>(bucket)) return bucket.scopes[scope] ?? null
    return scope === 'default' ? (bucket as TState | undefined) ?? null : null
  }
  async writeScope(scope: string, state: TState): Promise<void> {
    const current = MemoryLocalDatabase.values.get(this.name)
    const bucket = isScopedBucket<TState>(current)
      ? current
      : { active: null, scopes: {} as Record<string, TState> }
    bucket.scopes[scope] = state
    bucket.active = state
    MemoryLocalDatabase.values.set(this.name, bucket)
  }
  async close(): Promise<void> {}
}

/** Keeps the app usable when the native SQLite plugin is unavailable during
 * startup (for example in an unsupported WebView or before Capacitor bridge
 * initialization). The active backend is switched only after a real failure;
 * callers keep the same LocalDatabase object and repository state. */
class ResilientLocalDatabase<TState> implements LocalDatabase<TState> {
  private active: LocalDatabase<TState>
  private usingFallback = false

  constructor(
    private readonly primary: LocalDatabase<TState>,
    private readonly fallback: LocalDatabase<TState>,
  ) {
    this.active = primary
  }

  async open(): Promise<void> {
    try {
      await this.primary.open()
      this.active = this.primary
    } catch {
      await this.primary.close().catch(() => undefined)
      await this.fallback.open()
      this.active = this.fallback
      this.usingFallback = true
    }
  }

  async read(): Promise<TState | null> {
    try {
      return await this.active.read()
    } catch {
      await this.switchToFallback()
      return await this.active.read()
    }
  }

  async write(state: TState): Promise<void> {
    try {
      await this.active.write(state)
    } catch {
      await this.switchToFallback()
      await this.active.write(state)
    }
  }

  async readScope(scope: string): Promise<TState | null> {
    try {
      if (this.active.readScope) return await this.active.readScope(scope)
      return scope === 'default' ? await this.active.read() : null
    } catch {
      await this.switchToFallback()
      return this.fallback.readScope
        ? await this.fallback.readScope(scope)
        : (scope === 'default' ? await this.fallback.read() : null)
    }
  }

  async writeScope(scope: string, state: TState): Promise<void> {
    try {
      if (this.active.writeScope) {
        await this.active.writeScope(scope, state)
      } else if (scope === 'default') {
        await this.active.write(state)
      }
    } catch {
      await this.switchToFallback()
      if (this.fallback.writeScope) await this.fallback.writeScope(scope, state)
      else if (scope === 'default') await this.fallback.write(state)
    }
  }

  async close(): Promise<void> {
    await this.active.close()
  }

  private async switchToFallback(): Promise<void> {
    if (this.usingFallback) return
    await this.primary.close().catch(() => undefined)
    await this.fallback.open()
    this.active = this.fallback
    this.usingFallback = true
  }
}

function objectValues(value: unknown): Record<string, any>[] {
  if (!isRecord(value)) return []
  return Object.values(value).filter(isRecord)
}

function isRecord(value: unknown): value is Record<string, any> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function stringValue(value: unknown): string {
  return value == null ? '' : String(value)
}

function numberValue(value: unknown): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}

const memoryFallback = new Map<string, unknown>()
function readMemoryState<TState>(name: string): TState | null {
  return (memoryFallback.get(name) as TState | undefined) ?? null
}
function writeMemoryState<TState>(name: string, state: TState): void {
  memoryFallback.set(name, state)
}

function localStateScope(value: unknown): string {
  if (isRecord(value)) {
    const workspaceId = stringValue(value.workspaceId || value.workspace_id)
    if (workspaceId) return `workspace:${workspaceId}`
    const desktopId = stringValue(value.desktopId || value.desktop_id)
    if (desktopId) return `desktop:${desktopId}`
  }
  return 'default'
}

function isScopedBucket<TState>(value: unknown): value is { active: TState | null; scopes: Record<string, TState> } {
  return isRecord(value) && isRecord(value.scopes)
}

export function createLocalDatabase<TState>(name = 'lamtools-mobile'): LocalDatabase<TState> {
  const fallback = new MemoryLocalDatabase<TState>(name)
  if (Capacitor.isNativePlatform()) {
    return new ResilientLocalDatabase(new CapacitorLocalDatabase<TState>(name), fallback)
  }
  if (typeof indexedDB !== 'undefined') {
    return new ResilientLocalDatabase(new IndexedDbLocalDatabase<TState>(name), fallback)
  }
  return new MemoryLocalDatabase<TState>(name)
}
