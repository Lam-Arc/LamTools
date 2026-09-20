import { ref, type Ref } from 'vue'
import type { LamToolsTransport, TransportMessage } from '@lamtools/ui/transport'
import type { CoreAppEvent } from '@lamtools/ui/appServer'
import type { LocalRepository, LocalSyncChange } from '../storage/LocalRepository'

export type SyncConnectionState = 'idle' | 'syncing' | 'synced' | 'offline' | 'error'

export interface SyncEngineOptions {
  transport: LamToolsTransport
  repository: LocalRepository
  requestRpc: (method: string, params?: Record<string, unknown>, timeoutMs?: number) => Promise<Record<string, unknown>>
  onError?: (message: string) => void
  reconnectDelaysMs?: number[]
}

/**
 * Keeps one repository in sync over the already shared App Server transport.
 * It never creates a second socket and never asks the UI to reload a thread.
 */
export class SyncEngine {
  readonly state: Ref<SyncConnectionState> = ref('idle')
  readonly lastError = ref('')

  private removeMessages: (() => void) | null = null
  private removeTransportState: (() => void) | null = null
  private started = false
  private syncing: Promise<void> | null = null
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private reconnectAttempt = 0
  private lifecycleGeneration = 0
  private readonly repositoryWrites = new Set<Promise<unknown>>()
  /**
   * A sync response is a replacement/delta boundary.  Live notifications
   * received while that boundary is being committed must not mutate the old
   * state and then get discarded by an incoming snapshot replacement.
   */
  private synchronizationBarrier = false
  private readonly bufferedMessages: TransportMessage[] = []

  constructor(private readonly options: SyncEngineOptions) {}

  async start(): Promise<void> {
    if (this.started) return await this.syncNow()
    this.started = true
    const generation = ++this.lifecycleGeneration
    await this.options.repository.init()
    if (!this.isCurrent(generation)) return
    this.removeMessages = this.options.transport.subscribe((message) => {
      void this.handleMessage(message, generation).catch((error) => {
        this.reportLiveError(error, generation)
      })
    })
    this.removeTransportState = this.options.transport.onState((connectionState) => {
      if (!this.isCurrent(generation)) return
      if (connectionState === 'connected') {
        this.clearReconnect()
        void this.syncNow().catch((error) => this.reportLiveError(error, generation))
      }
      if (connectionState === 'disconnected') {
        this.state.value = 'offline'
        this.scheduleReconnect()
      }
      if (connectionState === 'failed') {
        this.state.value = 'offline'
        this.scheduleReconnect()
      }
    })
    await this.syncNow()
  }

  async syncNow(): Promise<void> {
    if (!this.started) return
    if (this.syncing) return await this.syncing
    const task = this.runSync(this.lifecycleGeneration)
    this.syncing = task
    try {
      await task
    } finally {
      if (this.syncing === task) this.syncing = null
    }
  }

  async close(): Promise<void> {
    this.lifecycleGeneration += 1
    this.removeMessages?.()
    this.removeMessages = null
    this.removeTransportState?.()
    this.removeTransportState = null
    this.started = false
    this.syncing = null
    this.clearReconnect()
    this.synchronizationBarrier = false
    this.bufferedMessages.length = 0
    this.state.value = 'idle'
    // A repository update may already have passed the generation check when
    // close starts. Wait for those writes before the owner closes the
    // database; later work is fenced by lifecycleGeneration above.
    await Promise.allSettled([...this.repositoryWrites])
  }

  private async runSync(generation: number): Promise<void> {
    if (!this.isCurrent(generation)) return
    this.state.value = 'syncing'
    this.lastError.value = ''
    this.synchronizationBarrier = true
    try {
      let cursor: number | null = this.options.repository.state.value.snapshotRequired
        ? null
        : this.options.repository.state.value.cursor
      let retriedAfterExpiry = false
      while (true) {
        if (!this.isCurrent(generation)) return
        const result = await this.options.requestRpc(
          'sync.start',
          { cursor, limit: 500 },
          60_000,
        )
        if (!this.isCurrent(generation)) return
        if (result.error === 'SYNC_CURSOR_EXPIRED') {
          if (retriedAfterExpiry) throw new Error('同步游标已过期，重新同步仍失败')
          retriedAfterExpiry = true
          cursor = null
          continue
        }
        if (result.ok === false) throw new Error(String(result.error || '同步失败'))
        if (result.mode === 'snapshot') {
          const snapshotCursor = integerCursor(result.cursor)
          if (snapshotCursor == null) throw new Error('同步响应缺少有效游标')
          await this.trackRepositoryWrite(this.options.repository.applySyncSnapshot(result))
          if (!this.isCurrent(generation)) return
          if (this.options.repository.state.value.cursor !== snapshotCursor) {
            throw new Error('同步响应游标不一致')
          }
        } else if (result.mode === 'delta') {
          const deltaCursor = integerCursor(result.cursor)
          if (deltaCursor == null || !Array.isArray(result.changes)) {
            throw new Error('同步响应缺少有效游标或变更列表')
          }
          const changes: LocalSyncChange[] = []
          for (const value of result.changes) {
            if (!isRecord(value)) throw new Error('同步响应包含无效变更')
            changes.push(value as unknown as LocalSyncChange)
          }
          await this.trackRepositoryWrite(this.options.repository.applySyncBatch(changes, deltaCursor))
          if (!this.isCurrent(generation)) return
          if (this.options.repository.state.value.snapshotRequired) {
            // Do not request a delta from a branch that requires replacement.
            // The next request is an atomic full snapshot.
            cursor = null
          }
        } else {
          throw new Error('同步响应包含未知模式')
        }
        if (!this.isCurrent(generation)) return
        if (this.options.repository.state.value.snapshotRequired) {
          cursor = null
          continue
        }
        const previousCursor = cursor
        const nextCursor = integerCursor(result.cursor)
        cursor = nextCursor ?? this.options.repository.state.value.cursor
        if (result.has_more !== true) break
        if (nextCursor == null || (previousCursor !== null && nextCursor <= previousCursor)) {
          throw new Error('同步响应游标未推进')
        }
      }
      await this.flushBufferedMessages(generation)
      if (!this.isCurrent(generation)) return
      if (this.options.repository.state.value.snapshotRequired) {
        // A buffered rollback/branch event arrived after the bootstrap was
        // committed. Defer the replacement sync until this run has released
        // `syncing`; calling syncNow here would await this same Promise.
        this.synchronizationBarrier = false
        this.state.value = 'offline'
        this.scheduleReconnect()
        return
      }
      this.state.value = 'synced'
      this.clearReconnect()
    } catch (error) {
      this.synchronizationBarrier = false
      this.bufferedMessages.length = 0
      if (!this.isCurrent(generation)) return
      this.lastError.value = error instanceof Error ? error.message : String(error)
      // A route/account change intentionally invalidates the previous
      // generation. The connected-state callback immediately starts a fresh
      // sync, so this lifecycle cancellation is not a user-facing failure.
      if (this.lastError.value.includes('连接已取消')) {
        this.state.value = 'offline'
        this.scheduleReconnect()
        return
      }
      // A failed remote sync is an offline condition from the mobile user's
      // perspective, regardless of whether the transport surfaced `failed`
      // or remained nominally connected while the RPC timed out.
      this.state.value = 'offline'
      this.notifyError(this.lastError.value)
      this.scheduleReconnect()
    }
  }

  private scheduleReconnect(): void {
    if (!this.started || this.reconnectTimer) return
    const delays = this.options.reconnectDelaysMs?.length
      ? this.options.reconnectDelaysMs
      : [1_000, 2_000, 5_000, 10_000, 20_000]
    const delay = delays[Math.min(this.reconnectAttempt, delays.length - 1)]
    this.reconnectAttempt += 1
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      void this.syncNow().catch((error) => this.reportLiveError(error, this.lifecycleGeneration))
    }, delay)
  }

  private clearReconnect(): void {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    this.reconnectTimer = null
    this.reconnectAttempt = 0
  }

  private async handleMessage(message: TransportMessage, generation: number): Promise<void> {
    if (!this.isCurrent(generation)) return
    if (this.synchronizationBarrier) {
      this.bufferedMessages.push(message)
      return
    }
    await this.applyLiveMessage(message, generation)
  }

  private async applyLiveMessage(
    message: TransportMessage,
    generation: number,
    allowResync = true,
  ): Promise<void> {
    if (!this.isCurrent(generation)) return
    if (message.channel !== 'rpc' || !message.method || !message.params) return
    if (message.method === 'sync/change') {
      if (isRecord(message.params)) {
        await this.trackRepositoryWrite(
          this.options.repository.applySyncChange(message.params as unknown as LocalSyncChange),
        )
        if (!this.isCurrent(generation)) return
        if (allowResync && this.options.repository.state.value.snapshotRequired) await this.syncNow()
      }
      return
    }
    // Transient runItem deltas are intentionally not journaled. Applying them
    // to the cached snapshot keeps the mobile conversation streaming; the
    // next persisted delta or sync boundary remains authoritative.
    if (message.method === 'core/runItem' || message.method === 'turn/accepted' || message.method === 'item/started') {
      if (isRecord(message.params)) {
        await this.trackRepositoryWrite(
          this.options.repository.applyTransientEvent(message.params as unknown as CoreAppEvent),
        )
      }
      return
    }
    if (message.method === 'session/created' || message.method === 'session/updated' || message.method === 'session/deleted') {
      await this.trackRepositoryWrite(this.options.repository.applySessionEvent(message.method, message.params))
    }
  }

  private reportLiveError(error: unknown, generation: number): void {
    if (!this.isCurrent(generation)) return
    const message = error instanceof Error ? error.message : String(error)
    this.lastError.value = message
    this.state.value = 'error'
    this.notifyError(message)
    this.scheduleReconnect()
  }

  private notifyError(message: string): void {
    try {
      this.options.onError?.(message)
    } catch {
      // Error reporting must not turn a handled sync failure into an
      // unhandled Promise rejection.
    }
  }

  private async flushBufferedMessages(generation: number): Promise<void> {
    // Keep the barrier armed while draining. Notifications delivered while a
    // repository write is in flight are appended and handled in arrival order
    // on the next pass instead of racing the current item.
    while (this.bufferedMessages.length) {
      const messages = this.bufferedMessages.splice(0)
      for (const message of messages) {
        if (!this.isCurrent(generation)) return
        await this.applyLiveMessage(message, generation, false)
      }
    }
    this.synchronizationBarrier = false
  }

  private isCurrent(generation: number): boolean {
    return this.started && this.lifecycleGeneration === generation
  }

  private trackRepositoryWrite<T>(task: Promise<T>): Promise<T> {
    let tracked!: Promise<T>
    tracked = task.then(
      (value) => {
        this.repositoryWrites.delete(tracked)
        return value
      },
      (error) => {
        this.repositoryWrites.delete(tracked)
        throw error
      },
    )
    this.repositoryWrites.add(tracked)
    return tracked
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function integerCursor(value: unknown): number | null {
  const parsed = Number(value)
  return Number.isSafeInteger(parsed) && parsed >= 0 ? parsed : null
}
