import { hydrateSnapshot as defaultHydrateSnapshot } from './snapshot.ts'
import type {
  CoreAppCommandCatalogItem,
  CoreAppEvent,
  CoreAppInputItem,
  CoreAppRequestState,
  CoreAppSnapshot,
  CoreRuntimeItem,
  CoreRuntimeSnapshot,
  CoreAppThreadStatus,
} from './protocol.ts'
import { TransportRpcError } from '../transport'
import type { CoreSyncChangeNotification } from './client.ts'
import {
  compareSnapshotVersion,
  CoreSessionStateStore,
  snapshotRevision as sessionSnapshotRevision,
  snapshotSequence,
} from './sessionState.ts'

export interface CoreAppServerRuntimeClient {
  connect(params?: { threadId?: string; lastSeenSeq?: number }): Promise<void>
  request(method: string, params?: Record<string, unknown>, timeoutMs?: number): Promise<Record<string, unknown>>
  respondServerRequest(requestId: string, result: Record<string, unknown>): boolean
  close(): void
}

export interface CoreAppServerThreadSwitchOptions {
  lastSeenSeq?: number
  includeSnapshot?: boolean
  preserveState?: boolean
}

export interface CoreAppServerRuntimeState<
  Snapshot extends CoreAppSnapshot = CoreAppSnapshot,
  Client extends CoreAppServerRuntimeClient = CoreAppServerRuntimeClient,
> {
  state: Snapshot | null
  connectionState: 'connecting' | 'open' | 'closed' | 'error'
  client: Client | null
  lastError: string
  activeThreadId: string
  reconnectAttempt: number
  reconnectTimer: ReturnType<typeof setTimeout> | null
  connectionGeneration: number
}

export interface CoreAppServerRuntimeControllerOptions<
  Snapshot extends CoreAppSnapshot = CoreAppSnapshot,
  Client extends CoreAppServerRuntimeClient = CoreAppServerRuntimeClient,
> {
  createClient(params: {
    onEvent: (event: CoreAppEvent) => void
    onSnapshot: (snapshot: Snapshot) => void
    onSyncChange?: (change: CoreSyncChangeNotification) => void
    onConnectionState: (state: CoreAppServerRuntimeState<Snapshot, Client>['connectionState']) => void
  }): Promise<Client> | Client
  hydrateSnapshot?: (snapshot: Snapshot) => Snapshot
  reconnectBaseMs?: number
  reconnectMaxMs?: number
  scheduleFrame?: (callback: () => void) => unknown
  onSessionCreated?: () => void
  onSessionUpdated?: (session: { title?: string }) => void
}

export function createCoreAppServerRuntimeState<
  Snapshot extends CoreAppSnapshot = CoreAppSnapshot,
  Client extends CoreAppServerRuntimeClient = CoreAppServerRuntimeClient,
>(): CoreAppServerRuntimeState<Snapshot, Client> {
  return {
    state: null,
    connectionState: 'closed',
    client: null,
    lastError: '',
    activeThreadId: '',
    reconnectAttempt: 0,
    reconnectTimer: null,
    connectionGeneration: 0,
  }
}

export function createCoreAppServerRuntimeController<
  Snapshot extends CoreAppSnapshot = CoreAppSnapshot,
  InputItem extends CoreAppInputItem = CoreAppInputItem,
  CommandItem extends CoreAppCommandCatalogItem = CoreAppCommandCatalogItem,
  Client extends CoreAppServerRuntimeClient = CoreAppServerRuntimeClient,
>(
  runtime: CoreAppServerRuntimeState<Snapshot, Client>,
  options: CoreAppServerRuntimeControllerOptions<Snapshot, Client>,
) {
  const reconnectBaseMs = options.reconnectBaseMs ?? 25
  const reconnectMaxMs = options.reconnectMaxMs ?? 2_000
  const hydrateSnapshot = options.hydrateSnapshot ?? ((snapshot: Snapshot) => defaultHydrateSnapshot(snapshot) as Snapshot)
  const scheduleFrame = options.scheduleFrame ?? defaultScheduleFrame
  const pendingEvents: CoreAppEvent[] = []
  const sessionStateStore = new CoreSessionStateStore()
  let eventFrameScheduled = false
  // Event ids the client has received on the wire (non-reactive, kept outside
  // the snapshot state on purpose). The snapshot hydrate guard compares an
  // incoming snapshot's seen_event_ids against this set to detect "missed
  // events" without forcing a full state replacement (and full re-render) for
  // snapshots that carry nothing new.
  const receivedEventIds = new Set<string>()
  let threadSwitchQueue: Promise<void> = Promise.resolve()
  let threadSelectionGeneration = 0

  async function connect(threadId?: string) {
    clearReconnectTimer()
    // A live App Server client is connection-scoped, not thread-scoped. A
    // session switch must only move the server subscription and resume the
    // selected thread; closing the client here cancels every in-flight RPC
    // on the shared tunnel.
    if (threadId && runtime.client && runtime.connectionState === 'open') {
      await switchThread(threadId)
      return
    }
    runtime.activeThreadId = threadId || ''
    runtime.reconnectAttempt = 0
    await openClient(threadId)
  }

  function switchThread(
    threadId: string,
    switchOptions: CoreAppServerThreadSwitchOptions = {},
  ): Promise<void> {
    const task = threadSwitchQueue.then(() => switchThreadNow(threadId, switchOptions))
    // A failed stale switch must not poison the next selection.
    threadSwitchQueue = task.catch(() => undefined)
    return task
  }

  async function switchThreadNow(
    threadId: string,
    switchOptions: CoreAppServerThreadSwitchOptions,
  ): Promise<void> {
    if (!threadId) return
    clearReconnectTimer()
    const generation = ++threadSelectionGeneration
    runtime.activeThreadId = threadId
    if (!switchOptions.preserveState) {
      runtime.state = null
      sessionStateStore.clear(threadId)
    }
    pendingEvents.length = 0
    receivedEventIds.clear()

    const client = runtime.client
    if (!client || runtime.connectionState !== 'open') {
      // The physical connection generation is owned by openClient(). This
      // branch only hands the selected thread to that connection lifecycle.
      await connect(threadId)
      return
    }

    const response = await client.request(
      'thread/resume',
      {
        thread_id: threadId,
        last_seen_seq: switchOptions.lastSeenSeq ?? 0,
        ...(switchOptions.includeSnapshot === false ? { include_snapshot: false } : {}),
      },
      60_000,
    )
    if (threadSelectionGeneration !== generation || runtime.client !== client) return
    applyResponse(response)
  }

  async function openClient(threadId?: string) {
    const generation = ++runtime.connectionGeneration
    runtime.client?.close()
    const client = await options.createClient({
      onEvent: (event) => enqueueEvent(event),
      onSnapshot: (snapshot) => hydrate(snapshot),
      onSyncChange: (change) => applySyncChangeRevision(change),
      onConnectionState: (state) => {
        if (runtime.connectionGeneration !== generation) return
        runtime.connectionState = state
        if (state === 'closed' || state === 'error') {
          scheduleReconnect()
        }
      },
    })
    runtime.client = client
    await client.connect({ threadId, lastSeenSeq: lastSeenSeq() })
    if (threadId) {
      const response = await client.request('thread/resume', { thread_id: threadId, last_seen_seq: lastSeenSeq() }, 60_000)
      if (runtime.connectionGeneration !== generation) return
      applyResponse(response)
    }
    runtime.reconnectAttempt = 0
    runtime.lastError = ''
  }

  function disconnect() {
    clearReconnectTimer()
    runtime.activeThreadId = ''
    runtime.connectionGeneration += 1
    threadSelectionGeneration += 1
    runtime.client?.close()
    runtime.client = null
    runtime.state = null
    sessionStateStore.clear()
    pendingEvents.length = 0
    eventFrameScheduled = false
    runtime.connectionState = 'closed'
  }

  function clearReconnectTimer() {
    if (!runtime.reconnectTimer) return
    clearTimeout(runtime.reconnectTimer)
    runtime.reconnectTimer = null
  }

  function scheduleReconnect() {
    if (!runtime.activeThreadId || runtime.reconnectTimer) return
    const delay = Math.min(reconnectMaxMs, reconnectBaseMs * 2 ** runtime.reconnectAttempt)
    runtime.reconnectAttempt += 1
    runtime.reconnectTimer = setTimeout(() => {
      runtime.reconnectTimer = null
      void reconnectActiveThread()
    }, delay)
  }

  async function reconnectActiveThread() {
    if (!runtime.activeThreadId) return
    try {
      await openClient(runtime.activeThreadId || undefined)
    } catch (error) {
      runtime.lastError = error instanceof Error ? error.message : String(error)
      runtime.connectionState = 'error'
      scheduleReconnect()
    }
  }

  function hydrate(snapshot: Snapshot) {
    const incoming = hydrateSnapshot(snapshot as Snapshot) as CoreAppSnapshot
    const currentState = sessionStateStore.get(incoming.thread_id)
    const incomingVersion = {
      revision: sessionSnapshotRevision(incoming),
      snapshotSeq: snapshotSequence(incoming),
    }
    // A delayed cache/snapshot must never roll a completed turn back to
    // running, even when it contains different content.
    if (currentState && compareSnapshotVersion(incomingVersion, currentState) < 0) return
    // The guard must see the received set BEFORE this snapshot's ids are
    // recorded, otherwise "unseen event" would always be satisfied (an
    // incoming snapshot's own ids would count as received).
    const current = runtime.state?.thread_id === incoming.thread_id ? runtime.state : null
    const shouldReplace = !current || shouldHydrateSnapshot(current, incoming, receivedEventIds)
    if (!shouldReplace) {
      // A snapshot can be redundant at the content level while still carrying
      // a newer CAS revision (for example after a remote queue mutation).
      // Advance the stored revision *in place*: `applySnapshot` would adopt the
      // incoming items, and every item identity is the projection's cache key,
      // so the whole thread would be rebuilt for a snapshot the content
      // comparison already rejected (2026-09-25 审计 P2).
      if (currentState && incomingVersion.revision > currentState.revision) {
        currentState.revision = incomingVersion.revision
        currentState.snapshotSeq = Math.max(currentState.snapshotSeq, incomingVersion.snapshotSeq)
        // `runtime.state` is this very snapshot object, so the server's
        // revision also becomes the next CAS `expectedRevision`.
        currentState.snapshot.revision = incomingVersion.revision
        currentState.snapshot.snapshot_seq = incomingVersion.snapshotSeq
      }
      return
    }
    if (!sessionStateStore.applySnapshot(incoming)) return
    for (const id of [
      ...(incoming.core?.seen_event_ids ?? []),
      ...(incoming.seen_event_ids ?? []),
    ]) {
      receivedEventIds.add(id)
    }
    if (receivedEventIds.size > 200_000) {
      receivedEventIds.clear()
    }
    runtime.state = sessionStateStore.get(incoming.thread_id)?.snapshot as Snapshot
  }

  function applyRuntimeEvent(
    event: CoreAppEvent,
    options: { allowSequenceRegression?: boolean } = {},
  ): boolean {
    const current = runtime.state
    if (!current || current.thread_id !== event.thread_id) return false
    if (!sessionStateStore.get(event.thread_id)) sessionStateStore.applySnapshot(current)
    const result = sessionStateStore.applyEvent(
      event,
      (state, value) => (
        value.method === 'core/runItem'
          ? applyCoreRunItemEvent(state, value)
          : applyAppEvent(state, value)
      ),
      options,
    )
    if (!result.applied || !result.state) return false
    runtime.state = result.state.snapshot as Snapshot
    return true
  }

  /**
   * Persisted events arrive twice: as a `core/runItem` projection notification
   * (no revision) and as a `sync/change` journal notification (revision
   * included). Advancing the CAS revision from the latter keeps the tracked
   * revision in step with the server during a turn; without it the next
   * `command.execute` (for example /compact right after a reply) fails with
   * REVISION_CONFLICT. Content itself still arrives via the runItem path.
   */
  function applySyncChangeRevision(change: CoreSyncChangeNotification) {
    const threadId = typeof change?.thread_id === 'string' ? change.thread_id : ''
    if (!threadId) return
    const revision = Number(change.revision ?? change.snapshot_revision)
    if (!Number.isFinite(revision) || revision <= 0) return
    if (!sessionStateStore.advanceRevision(threadId, revision)) return
    const next = sessionStateStore.get(threadId)
    if (next && runtime.state?.thread_id === threadId) {
      runtime.state = next.snapshot as Snapshot
    }
  }

  function enqueueEvent(event: CoreAppEvent) {
    const eventId = runItemEventId(event)
    if (eventId) receivedEventIds.add(eventId)
    if (event.method === 'session/created') {
      options.onSessionCreated?.()
      return
    }
    if (event.method === 'session/updated') {
      applyRuntimeEvent(event, { allowSequenceRegression: true })
      const session = (event.payload as { session?: { title?: string } } | null)?.session || {}
      options.onSessionUpdated?.(session)
      return
    }
    if (event.method === 'core/runItem') {
      pendingEvents.push(event)
      if (eventFrameScheduled) return
      eventFrameScheduled = true
      scheduleFrame(flushFrame)
      return
    }
    // Apply turn/accepted and item/started directly to the top-level snapshot
    if (event.method === 'turn/accepted' || event.method === 'item/started') {
      if (!runtime.state) {
        // Same hold-and-replay rule as flushFrame: never drop events that
        // arrived before the first snapshot (audit 16 S2).
        pendingEvents.push(event)
        if (!eventFrameScheduled) {
          eventFrameScheduled = true
          scheduleFrame(flushFrame)
        }
        return
      }
      applyRuntimeEvent(event)
    }
  }

  function flushFrame() {
    eventFrameScheduled = false
    if (!runtime.state) {
      // Snapshot not hydrated yet (first connect / reconnect): hold the
      // pending events and retry next frame instead of dropping them.  Events
      // arriving in this window — transient stream deltas especially — are
      // not part of any snapshot, so dropping them permanently truncated the
      // running turn and the hydrate skip check could not heal it
      // (audit 16 S2).
      // But with nothing left to hold (e.g. after a disconnect cleared the
      // queue) the retry loop must end instead of waking the main thread
      // forever (2026-09-25 审计 P3).
      if (!pendingEvents.length) return
      eventFrameScheduled = true
      scheduleFrame(flushFrame)
      return
    }
    const events = pendingEvents.splice(0)
    // Coalesce same-frame deltas for the same item. On very large threads
    // (thousands of items) each apply() copies the whole items map — doing
    // that once per frame instead of once per incoming chunk keeps the
    // frame budget flat. (A/B: removing it made big-thread streaming worse.)
    for (const pending of coalesceRunItemEvents(events)) {
      applyRuntimeEvent(pending)
    }
  }

  function applyResponse(response: Record<string, unknown>) {
    const snapshot = response.snapshot
    if (isCoreAppSnapshot(snapshot)) {
      hydrate(snapshot as Snapshot)
    }
    // Local-First switches can ask the server for events only. Apply those
    // events onto the already-hydrated local snapshot without replacing the
    // whole conversation object.
    if (Array.isArray(response.events) && runtime.state) {
      for (const value of response.events) {
        if (!isRecord(value)) continue
        const event = value as unknown as CoreAppEvent
        if (event.thread_id && runtime.activeThreadId && event.thread_id !== runtime.activeThreadId) continue
        applyRuntimeEvent(event, { allowSequenceRegression: true })
      }
    }
  }

  function mergeSnapshotPage(snapshotPage: Snapshot): boolean {
    if (!runtime.state || runtime.state.thread_id !== snapshotPage.thread_id) return false
    const incoming = hydrateSnapshot(snapshotPage)
    const current = runtime.state
    const merged = mergeCoreHistorySnapshot(current, incoming)
    if (!sessionStateStore.applySnapshot(merged)) return false
    runtime.state = merged
    return true
  }

  async function startThread(threadId: string) {
    await ensureClient()
    const response = await requestMutation('thread/start', { thread_id: threadId }, threadId)
    applyResponse(response)
  }

  async function startTurn(
    threadId: string,
    input: string | InputItem[],
    workRoot?: string,
    turnOptions: Record<string, unknown> = {},
  ) {
    await ensureClient()
    const inputItems = typeof input === 'string' ? [{ type: 'text' as const, text: input }] : input
    // The message id is the server-side idempotency key. It stays unchanged
    // if the first CAS check races with a terminal event and we retry once.
    const clientMessageId = crypto.randomUUID()
    const response = await requestMutation('turn/start', {
      thread_id: threadId,
      client_message_id: clientMessageId,
      input: inputItems,
      work_root: workRoot,
      // The turn/accepted + item/started events already carry everything the
      // UI needs; the response snapshot is a 56MB JSON.parse on huge threads
      // (~1s main-thread stall at send time). Skip it — callers can override.
      include_snapshot: false,
      ...turnOptions,
    }, threadId, 60_000, true)
    applyResponse(response)
  }

  async function queueInput(
    threadId: string,
    input: string | InputItem[],
    turnOptions: Record<string, unknown> = {},
  ) {
    await ensureClient()
    const inputItems = typeof input === 'string' ? [{ type: 'text' as const, text: input }] : input
    const response = await requestMutation('queue/create', {
      thread_id: threadId,
      client_message_id: crypto.randomUUID(),
      input: inputItems,
      ...turnOptions,
    }, threadId)
    applyResponse(response)
  }

  async function updateQueueInput(threadId: string, queueItemId: string, text: string) {
    await ensureClient()
    const response = await requestMutation('queue/update', {
      thread_id: threadId,
      queue_item_id: queueItemId,
      text,
    }, threadId)
    applyResponse(response)
  }

  async function deleteQueueInput(threadId: string, queueItemId: string) {
    await ensureClient()
    const response = await requestMutation('queue/delete', {
      thread_id: threadId,
      queue_item_id: queueItemId,
    }, threadId)
    applyResponse(response)
  }

  async function guideQueueInput(threadId: string, turnId: string, queueItemId: string, text?: string) {
    await ensureClient()
    const response = await requestMutation('queue/guide', {
      thread_id: threadId,
      turn_id: turnId,
      queue_item_id: queueItemId,
      client_message_id: `queue-guide:${queueItemId}`,
      ...(text?.trim() ? { text: text.trim() } : {}),
    }, threadId)
    applyResponse(response)
    return {
      applied: response.applied === true,
      reason: String(response.reason || ''),
    }
  }

  async function listCommands(workRoot?: string): Promise<CommandItem[]> {
    await ensureClient()
    const response = await runtime.client!.request('command.catalog', {
      ...(workRoot ? { work_root: workRoot } : {}),
    })
    return Array.isArray(response.commands) ? response.commands as CommandItem[] : []
  }

  async function executeCommand(
    threadId: string,
    command: string,
    workRoot?: string,
    argumentsText = '',
  ): Promise<Record<string, unknown>> {
    await ensureClient()
    const response = await requestMutation('command.execute', {
      thread_id: threadId,
      command,
      arguments: argumentsText,
      ...(workRoot ? { work_root: workRoot } : {}),
    }, threadId, 30 * 60_000, true)
    applyResponse(response)
    return response.result && typeof response.result === 'object'
      ? response.result as Record<string, unknown>
      : {}
  }

  async function steerTurn(threadId: string, turnId: string, input: string | InputItem[]) {
    await ensureClient()
    const inputItems = typeof input === 'string' ? [{ type: 'text' as const, text: input }] : input
    const response = await requestMutation('turn/steer', {
      thread_id: threadId,
      turn_id: turnId,
      client_message_id: crypto.randomUUID(),
      input: inputItems,
    }, threadId)
    applyResponse(response)
    // 后端明确拒绝（这一轮已经结束 / 已不是当前轮）时不能当成已接受：调用方据此
    // 决定是否显示"已发送引导"与待生效气泡，否则用户会以为指令进去了。
    if (response.applied !== true) {
      const reason = String(response.reason || '')
      if (reason === 'run_not_active') throw new Error('这一轮已经结束，引导没有生效')
      if (reason === 'active_turn_mismatch') throw new Error('当前轮次已经变化，引导没有生效')
      throw new Error('引导没有生效')
    }
  }

  async function interruptTurn(threadId: string, turnId?: string) {
    await ensureClient()
    const response = await requestMutation('turn/interrupt', {
      thread_id: threadId,
      ...(turnId ? { turn_id: turnId } : {}),
      include_snapshot: false,
    }, threadId)
    applyResponse(response)
  }

  async function forceResetTurn(threadId: string, turnId?: string) {
    await ensureClient()
    const response = await requestMutation('turn/force_reset', {
      thread_id: threadId,
      ...(turnId ? { turn_id: turnId } : {}),
      include_snapshot: true,
    }, threadId)
    applyResponse(response)
  }

  async function respondApproval(requestId: string, decision: string, guidance?: string) {
    await ensureClient()
    // The backend binds an approval response to the subscribed thread, so the
    // responding thread must be explicit (audit 03 S1: untrusted pages could
    // otherwise answer approvals for other threads).
    const threadId = runtime.activeThreadId || runtime.state?.thread_id || ''
    const response = await requestMutation('approval/respond', {
      request_id: requestId,
      thread_id: threadId,
      decision,
      guidance,
    }, threadId)
    applyResponse(response)
  }

  /**
   * Add the current snapshot revision to every state-changing request. An
   * explicit snake_case or camelCase value is always respected so callers can
   * intentionally opt out or target a known revision.
   */
  async function requestMutation(
    method: string,
    params: Record<string, unknown>,
    threadId: string,
    timeoutMs = 30_000,
    retryOnRevisionConflict = false,
  ): Promise<Record<string, unknown>> {
    await ensureClient()
    const requestParams = withExpectedRevision(
      params,
      runtime.state?.thread_id === threadId ? sessionSnapshotRevision(runtime.state) : 0,
    )
    try {
      return await runtime.client!.request(method, requestParams, timeoutMs)
    } catch (error) {
      if (isRevisionConflict(error)) {
        // Refresh the canonical state first. turn/start is safe to retry once
        // because client_message_id makes acceptance idempotent; other
        // mutations preserve the explicit-retry behavior.
        await refreshAfterRevisionConflict(threadId)
        if (retryOnRevisionConflict && runtime.state?.thread_id === threadId) {
          const retryParams = withExpectedRevision(params, sessionSnapshotRevision(runtime.state))
          return await runtime.client!.request(method, retryParams, timeoutMs)
        }
      }
      throw error
    }
  }

  async function refreshAfterRevisionConflict(threadId: string): Promise<void> {
    if (!threadId || !runtime.client) return
    try {
      const response = await runtime.client.request('thread/read', { thread_id: threadId }, 60_000)
      applyResponse(response)
    } catch {
      // Preserve the original structured conflict for the UI. A secondary
      // refresh failure must not hide the actionable error that caused it.
    }
  }

  async function ensureClient() {
    if (!runtime.client) {
      throw new Error('Core App Server client is not connected')
    }
  }

  function lastSeenSeq(): number {
    return runtime.state?.snapshot_seq ?? 0
  }

  return {
    applyResponse,
    clearReconnectTimer,
    connect,
    deleteQueueInput,
    disconnect,
    executeCommand,
    forceResetTurn,
    guideQueueInput,
    hydrate,
    interruptTurn,
    lastSeenSeq,
    listCommands,
    mergeSnapshotPage,
    openClient,
    queueInput,
    reconnectActiveThread,
    respondApproval,
    scheduleReconnect,
    switchThread,
    startThread,
    startTurn,
    steerTurn,
    updateQueueInput,
  }
}

function defaultScheduleFrame(callback: () => void) {
  if (typeof requestAnimationFrame !== 'function') {
    queueMicrotask(callback)
    return
  }
  // rAF is the primary beat: deltas land right before paint so the DOM
  // reflects at most one batch per frame. But rAF never fires while the
  // main thread is saturated (or the window occluded), which would stall
  // state updates indefinitely — a setTimeout fallback keeps the coalescing
  // window bounded so a late render still shows the final state.
  let fired = false
  let timer: ReturnType<typeof setTimeout> | null = null
  const run = () => {
    if (fired) return
    fired = true
    if (timer !== null) clearTimeout(timer)
    callback()
  }
  timer = setTimeout(run, 50)
  requestAnimationFrame(run)
}

// ── In-frame delta coalescing ──
// The backend emits one core/runItem per model chunk (unthrottled). Within a
// single rAF batch, consecutive delta events for the same item are merged into
// one event so the frame applies O(items) instead of O(chunks × items).
// Non-delta events (content snapshots, status, usage) break the merge chain,
// preserving their replace/override semantics. Coalesced event ids are kept on
// the event payload (never inside item payload) so dedup semantics are
// unchanged and nothing leaks into message metadata.
function runItemEventId(event: CoreAppEvent): string {
  const value = isRecord(event.payload) ? event.payload : {}
  return typeof value.event_id === 'string'
    ? value.event_id
    : typeof event.event_id === 'string'
      ? event.event_id
      : ''
}

function coalesceRunItemEvents(events: CoreAppEvent[]): CoreAppEvent[] {
  const result: CoreAppEvent[] = []
  for (const event of events) {
    const value = isRecord(event.payload) ? event.payload : {}
    const inner = isRecord(value.payload) ? value.payload : {}
    const itemId = typeof value.item_id === 'string' ? value.item_id : event.item_id || ''
    const kind = typeof value.kind === 'string' ? value.kind : ''
    const delta = typeof inner.delta === 'string' ? inner.delta : undefined
    const eventId = typeof value.event_id === 'string' ? value.event_id : event.event_id

    const last = result[result.length - 1]
    const lastValue = last && isRecord(last.payload) ? last.payload : null
    const lastInner = lastValue && isRecord(lastValue.payload) ? lastValue.payload : null
    const mergeable = lastValue !== null
      && lastInner !== null
      && (typeof lastValue.item_id === 'string' ? lastValue.item_id : last.item_id || '') === itemId
      && (typeof lastValue.kind === 'string' ? lastValue.kind : '') === kind
      && typeof lastInner.delta === 'string'

    if (delta !== undefined && eventId !== undefined && mergeable && lastValue && lastInner) {
      lastInner.delta = `${lastInner.delta}${delta}`
      const coalesced = Array.isArray(lastValue._coalesced_event_ids)
        ? lastValue._coalesced_event_ids
        : [lastValue.event_id ?? last.event_id].filter((id): id is string => typeof id === 'string')
      coalesced.push(eventId)
      lastValue._coalesced_event_ids = coalesced
      continue
    }
    result.push(event)
  }
  return result
}

function applyCoreRunItemEvent(snapshot: CoreAppSnapshot, event: CoreAppEvent): CoreAppSnapshot {
  const value = event.payload
  const itemId = typeof value.item_id === 'string' ? value.item_id : event.item_id || ''
  const kind = typeof value.kind === 'string' ? value.kind : ''
  if (!kind) return snapshot
  const eventId = typeof value.event_id === 'string' ? value.event_id : event.event_id
  const coalescedEventIds = Array.isArray(value._coalesced_event_ids)
    ? value._coalesced_event_ids.filter((id): id is string => typeof id === 'string')
    : eventId
      ? [eventId]
      : []
  const currentCore = snapshot.core ?? emptyCoreSnapshot(snapshot.thread_id)
  const seenEventSet = new Set(currentCore.seen_event_ids ?? [])
  // Filter the coalesced batch by id instead of dropping it wholesale when any
  // id is already seen: a replayed persisted event and a live transient delta
  // can share one coalesced batch, and "all or nothing" killed the unseen
  // delta (audit 16 S3).
  const unseenEventIds = coalescedEventIds.filter((id) => !seenEventSet.has(id))
  if (unseenEventIds.length === 0) return snapshot
  const runPayload = isRecord(value.payload) ? value.payload : {}
  const turnId = typeof value.turn_id === 'string' ? value.turn_id : event.turn_id || ''
  const seen = [...(currentCore.seen_event_ids ?? []), ...unseenEventIds].slice(-2000)
  if (kind === 'status') {
    const rawStatus = typeof runPayload.status === 'string'
      ? runPayload.status
      : typeof value.status === 'string'
        ? value.status
        : currentCore.status
    const status = isCoreAppThreadStatus(rawStatus) ? rawStatus : currentCore.status
    // Resume hydrates the current snapshot before replaying old journal
    // events. Closing a previous turn must not close a different active turn.
    const hasOtherActiveTurn = turnId && Object.entries({
      ...(snapshot.turns ?? {}),
      ...(currentCore.turns ?? {}),
    }).some(([id, turn]) => id !== turnId && (turn.status === 'running' || turn.status === 'waiting' || turn.status === 'interrupting'))
    const threadStatus = hasOtherActiveTurn && (status === 'completed' || status === 'failed' || status === 'cancelled')
      ? currentCore.status
      : status
    const turns = { ...(currentCore.turns ?? {}) }
    if (turnId) {
      const turn = turns[turnId] ?? { turn_id: turnId, status: status || 'running', items: [] }
      const runtimeMetrics = isRecord(runPayload.runtime_metrics)
        ? runPayload.runtime_metrics
        : isRecord(value.usage) && isContextMetrics(value.usage)
          ? value.usage
          : undefined
      const durationMs = numericField(runPayload.duration_ms)
      turns[turnId] = {
        ...turn,
        status: status || turn.status,
        ...(durationMs !== undefined ? { duration_ms: Math.max(0, Math.round(durationMs)) } : {}),
        ...(runtimeMetrics ? {
          context_metrics: { ...(turn.context_metrics ?? {}), ...runtimeMetrics },
        } : {}),
      }
    }
    return {
      ...snapshot,
      core: { ...currentCore, seen_event_ids: seen, turns, status: threadStatus },
    }
  }
  if (kind === 'usage') {
    const turns = { ...(currentCore.turns ?? {}) }
    if (turnId) {
      const turn = turns[turnId] ?? { turn_id: turnId, status: 'running', items: [] }
      const usage = isRecord(value.usage) ? value.usage : {}
      if (runPayload.replace === true) {
        // `runtime.metrics` is a replace-style context snapshot, not a
        // per-call provider usage delta. Keep it visible, but out of usage.
        turns[turnId] = { ...turn, context_metrics: { ...usage } }
      } else {
        turns[turnId] = { ...turn, usage: mergeUsageMetrics(turn.usage, usage) }
      }
    }
    return { ...snapshot, core: { ...currentCore, seen_event_ids: seen, turns } }
  }
  if (!itemId) return snapshot

  const items = { ...(currentCore.items ?? {}) }
  const existing = items[itemId] ?? { item_id: itemId, content: '', deltas: [] }
  const delta = typeof runPayload.delta === 'string' ? runPayload.delta : undefined
  const content = typeof runPayload.content === 'string' ? runPayload.content : undefined
  // Transient stream deltas (default_agent `_persist_core_event_live`) are not
  // persisted, so their envelope seq is 0 — a fake anchor that would sort the
  // item BEFORE every outer user message (0 < any real seq). Treat 0 as "no
  // anchor": keep the item's existing seq, or leave it unset (sorts last
  // within the turn) until a real completion event lands.
  const realSeq = typeof event.seq === 'number' && event.seq > 0 ? event.seq : undefined
  const item: CoreRuntimeItem = {
    ...existing,
    item_id: itemId,
    // Anchor on the envelope seq: the payload seq is batch-relative (0/1) and
    // would corrupt cross-item ordering (see snapshot_store payload override).
    seq: realSeq ?? existing.seq,
    turn_id: turnId || existing.turn_id,
    parent_item_id: typeof value.parent_item_id === 'string' ? value.parent_item_id : existing.parent_item_id,
    kind: kind === 'tool_result' ? 'tool_result' : existing.kind || kind,
    last_kind: kind,
    status: typeof value.status === 'string' ? value.status : existing.status,
    payload: { ...(existing.payload ?? {}), ...runPayload },
  }
  if (delta !== undefined) {
    item.deltas = [...(existing.deltas ?? []), delta]
    item.content = `${existing.content ?? ''}${delta}`
  } else if (content !== undefined) {
    item.content = content
  }
  items[itemId] = item

  // Tool results carry artifacts on the runItem event TOP level (RunItemEvent
  // serializes artifacts outside payload — see run_item.py to_dict); merge them
  // into the snapshot-level artifacts map so file/change/image cards render
  // from the event stream instead of waiting for the next full snapshot
  // (snapshots are now only pushed at turn boundaries).
  let artifacts = currentCore.artifacts
  const eventArtifacts = Array.isArray(value.artifacts)
    ? value.artifacts
    : Array.isArray(runPayload.artifacts)
      ? runPayload.artifacts
      : undefined
  if (kind === 'tool_result' && eventArtifacts && eventArtifacts.length > 0) {
    let merged: Record<string, Record<string, unknown>> | null = null
    for (const artifact of eventArtifacts) {
      if (!isRecord(artifact)) continue
      const artifactId = typeof artifact.artifact_id === 'string' ? artifact.artifact_id : ''
      if (!artifactId) continue
      if (!merged) merged = { ...(artifacts ?? {}) }
      merged[artifactId] = artifact
    }
    if (merged) artifacts = merged
  }

  const itemOrder = [...(currentCore.item_order ?? [])]
  if (!itemOrder.includes(itemId)) itemOrder.push(itemId)
  const turns = { ...(currentCore.turns ?? {}) }
  const itemStatus = typeof value.status === 'string' ? value.status : existing.status
  if (turnId) {
    const turn = turns[turnId] ?? { turn_id: turnId, status: 'running', items: [] }
    const turnItems = [...(turn.items ?? [])]
    if (!turnItems.includes(itemId)) turnItems.push(itemId)
    turns[turnId] = {
      ...turn,
      items: turnItems,
      ...(itemStatus === 'waiting' ? { status: 'waiting' } : {}),
    }
  }
  return {
    ...snapshot,
    core: {
      ...currentCore,
      seen_event_ids: seen,
      turns,
      items,
      item_order: itemOrder,
      ...(artifacts !== currentCore.artifacts ? { artifacts } : {}),
      ...(itemStatus === 'waiting' ? { status: 'waiting' } : {}),
    },
  }
}

/** Apply one persisted or transient event to a thread snapshot. Shared by
 * the desktop runtime and the mobile Local-First repository. */
export function applyCoreAppEvent(snapshot: CoreAppSnapshot, event: CoreAppEvent): CoreAppSnapshot {
  return event.method === 'core/runItem'
    ? applyCoreRunItemEvent(snapshot, event)
    : applyAppEvent(snapshot, event)
}

export function mergeCoreHistorySnapshot<T extends CoreAppSnapshot>(current: T, page: T): T {
  const mergeItems = <T>(older: Record<string, T> | undefined, newer: Record<string, T> | undefined) => ({
    ...(older || {}),
    ...(newer || {}),
  })
  const mergedCoreItems = mergeItems(page.core?.items, current.core?.items)
  const mergedTopItems = mergeItems(page.items, current.items)
  const orderBySeq = <T extends { seq?: number; last_seq?: number }>(items: Record<string, T>, ids: string[]) => (
    [...new Set(ids)].filter(id => items[id]).sort((left, right) => {
      const leftItem = items[left]
      const rightItem = items[right]
      return Number(leftItem?.seq || leftItem?.last_seq || 0) - Number(rightItem?.seq || rightItem?.last_seq || 0)
        || left.localeCompare(right)
    })
  )
  const mergeTurns = <T extends { items?: string[] }>(
    older: Record<string, T> | undefined,
    newer: Record<string, T> | undefined,
  ): Record<string, T> => {
    const result = { ...(older || {}), ...(newer || {}) }
    for (const id of Object.keys(result)) {
      const oldTurn = older?.[id]
      const newTurn = newer?.[id]
      if (!oldTurn || !newTurn) continue
      result[id] = {
        ...oldTurn,
        ...newTurn,
        items: [...new Set([...(oldTurn.items || []), ...(newTurn.items || [])])],
      }
    }
    return result
  }
  return {
    ...current,
    history_page: page.history_page,
    items: mergedTopItems,
    item_order: orderBySeq(mergedTopItems, [...(page.item_order || []), ...(current.item_order || [])]),
    turns: mergeTurns(page.turns, current.turns),
    core: current.core ? {
      ...current.core,
      items: mergedCoreItems,
      item_order: orderBySeq(mergedCoreItems, [...(page.core?.item_order || []), ...(current.core.item_order || [])]),
      turns: mergeTurns(page.core?.turns, current.core.turns),
    } : page.core,
  }
}

function applyAppEvent(snapshot: CoreAppSnapshot, event: CoreAppEvent): CoreAppSnapshot {
  const payload = event.payload || {}
  const turnId = event.turn_id || (typeof payload.turn_id === 'string' ? payload.turn_id : '') || ''
  const itemId = event.item_id || (typeof payload.item_id === 'string' ? payload.item_id : '') || ''

  if (event.method === 'turn/accepted') {
    if (!turnId) return snapshot
    const turns = { ...(snapshot.turns ?? {}) }
    const turn = turns[turnId] ?? { turn_id: turnId, items: [] }
    const input = payload.input
    turns[turnId] = {
      ...turn,
      turn_id: turnId,
      status: typeof payload.status === 'string' ? payload.status : 'running',
      created_at: typeof event.created_at === 'string' ? event.created_at : turn.created_at,
      input: input ?? turn.input,
      work_root: payload.work_root || payload.workRoot || turn.work_root || '',
      ...(isRecord(payload.runtime_snapshot)
        ? { runtime_snapshot: payload.runtime_snapshot }
        : {}),
    }
    return { ...snapshot, turns, status: 'running' }
  }

  if (event.method === 'item/started') {
    if (!itemId) return snapshot
    const items = { ...(snapshot.items ?? {}) }
    const item = items[itemId] ?? { item_id: itemId }
    items[itemId] = {
      ...item,
      item_id: itemId,
      seq: event.seq ?? item.seq,
      turn_id: turnId || item.turn_id || null,
      parent_item_id: event.parent_item_id ?? item.parent_item_id ?? null,
      type: typeof payload.type === 'string' ? payload.type : item.type ?? 'item',
      status: typeof payload.status === 'string' ? payload.status : item.status ?? 'running',
      content: payload.content ?? item.content ?? '',
    }
    const itemOrder = [...(snapshot.item_order ?? [])]
    if (!itemOrder.includes(itemId)) itemOrder.push(itemId)
    const turns = { ...(snapshot.turns ?? {}) }
    if (turnId) {
      const turn = turns[turnId] ?? { turn_id: turnId, items: [], status: 'running' }
      const turnItems = [...(turn.items ?? [])]
      if (!turnItems.includes(itemId)) turnItems.push(itemId)
      turns[turnId] = { ...turn, items: turnItems }
    }
    return { ...snapshot, items, item_order: itemOrder, turns }
  }

  return snapshot
}

function emptyCoreSnapshot(threadId: string): CoreRuntimeSnapshot {
  return {
    thread_id: threadId,
    snapshot_seq: 0,
    seen_event_ids: [],
    turns: {},
    items: {},
    item_order: [],
    requests: {},
    artifacts: {},
    status: 'idle',
  }
}

// ── Snapshot hydrate guard ──
// The backend pushes full snapshots at turn boundaries and on state events.
// While streaming, the client already applied every event incrementally
// (core/runItem deltas + turn/accepted + item/started), so a snapshot whose
// events are all already seen carries no new information for the
// event-derived state. Hydrating anyway would REPLACE the whole state with
// fresh JSON.parse objects, busting every object-reference cache in the
// projection layer (projection cache, v-memo) and forcing a full-thread
// re-render — the ~240ms microtask stall observed on 56MB threads. We only
// hydrate when the snapshot contains something the event stream cannot
// derive: unseen events, changed approval requests / queue / user items, or a
// different thread-level status.
function shouldHydrateSnapshot(
  current: CoreAppSnapshot,
  incoming: CoreAppSnapshot,
  receivedEventIds: Set<string>,
): boolean {
  if (incoming.thread_id !== current.thread_id) return true
  const incomingSeen = [
    ...(incoming.core?.seen_event_ids ?? []),
    ...(incoming.seen_event_ids ?? []),
  ]
  if (incomingSeen.some((id) => !receivedEventIds.has(id))) return true
  if (snapshotRequestsChanged(current, incoming)) return true
  if (snapshotQueueChanged(current, incoming)) return true
  if (String(current.status ?? '') !== String(incoming.status ?? '')) return true
  if (String(current.core?.status ?? '') !== String(incoming.core?.status ?? '')) return true
  if (snapshotItemsChanged(current, incoming)) return true
  // The event-derived core.items can diverge from the canonical snapshot
  // (dropped/reordered events, pre-snapshot windows).  Compare item content
  // fingerprints so a divergence forces a hydrate instead of being skipped
  // forever (audit 16 S2 — the missing comparison kept truncated turns
  // un-healable).
  if (snapshotCoreItemsChanged(current, incoming)) return true
  return false
}

// Approval request states (status/decision/guidance) are derived during
// projection and have no event path — the request cards depend on them.
function snapshotRequestsChanged(current: CoreAppSnapshot, incoming: CoreAppSnapshot): boolean {
  const merged = (snapshot: CoreAppSnapshot): Map<string, { status: string; decision: string; guidance: string }> => {
    const map = new Map<string, { status: string; decision: string; guidance: string }>()
    const collect = (src: Record<string, CoreAppRequestState> | undefined) => {
      for (const request of Object.values(src ?? {})) {
        if (!request || typeof request.request_id !== 'string') continue
        map.set(request.request_id, {
          status: String(request.status ?? ''),
          decision: String(request.decision ?? ''),
          guidance: String(request.guidance ?? ''),
        })
      }
    }
    collect(snapshot.core?.requests)
    collect(snapshot.requests)
    return map
  }
  const a = merged(current)
  const b = merged(incoming)
  if (a.size !== b.size) return true
  for (const [id, fields] of a) {
    const other = b.get(id)
    if (!other || other.status !== fields.status || other.decision !== fields.decision || other.guidance !== fields.guidance) {
      return true
    }
  }
  return false
}

// The queue tray has no event path either — it only syncs via snapshots.
function snapshotQueueChanged(current: CoreAppSnapshot, incoming: CoreAppSnapshot): boolean {
  const a = current.queue ?? []
  const b = incoming.queue ?? []
  if (a.length !== b.length) return true
  for (let index = 0; index < a.length; index += 1) {
    const x = a[index]
    const y = b[index]
    if (!x || !y) return true
    if (x.queue_item_id !== y.queue_item_id) return true
    if (String(x.status ?? '') !== String(y.status ?? '')) return true
    if (String(x.mode ?? '') !== String(y.mode ?? '')) return true
    if (JSON.stringify(x.input ?? null) !== JSON.stringify(y.input ?? null)) return true
  }
  return false
}

// Top-level items (user messages created via item/started + snapshots).
function snapshotItemsChanged(current: CoreAppSnapshot, incoming: CoreAppSnapshot): boolean {
  const a = current.items ?? {}
  const b = incoming.items ?? {}
  const aIds = Object.keys(a)
  const bIds = Object.keys(b)
  if (aIds.length !== bIds.length) return true
  for (const id of aIds) {
    const x = a[id]
    const y = b[id]
    if (!x || !y) return true
    if (String(x.status ?? '') !== String(y.status ?? '')) return true
    if (String(x.content ?? '') !== String(y.content ?? '')) return true
  }
  return false
}

// Content fingerprint of the runtime core.items.  The event-derived state
// applies deltas incrementally while snapshots carry canonical full content;
// if the two diverge (e.g. events were dropped before the first snapshot),
// the divergence must force a hydrate — the old check only compared the
// top-level ``items``, never ``core.items`` (audit 16 S2).
function snapshotCoreItemsChanged(current: CoreAppSnapshot, incoming: CoreAppSnapshot): boolean {
  const a = current.core?.items ?? {}
  const b = incoming.core?.items ?? {}
  const aIds = Object.keys(a)
  const bIds = Object.keys(b)
  if (aIds.length !== bIds.length) return true
  for (const id of aIds) {
    const x = a[id] as { content?: unknown; status?: unknown; turn_id?: unknown } | undefined
    const y = b[id] as { content?: unknown; status?: unknown; turn_id?: unknown } | undefined
    if (!x || !y) return true
    if (String(x.content ?? '') !== String(y.content ?? '')) return true
    if (String(x.status ?? '') !== String(y.status ?? '')) return true
    if (String(x.turn_id ?? '') !== String(y.turn_id ?? '')) return true
  }
  return false
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}

function withExpectedRevision(
  params: Record<string, unknown>,
  revision: number,
): Record<string, unknown> {
  if (Object.prototype.hasOwnProperty.call(params, 'expected_revision')
    || Object.prototype.hasOwnProperty.call(params, 'expectedRevision')) {
    return params
  }
  return {
    ...params,
    expected_revision: revision,
  }
}

function isRevisionConflict(error: unknown): boolean {
  if (error instanceof TransportRpcError) {
    if (error.code === 'REVISION_CONFLICT') return true
    return isRecord(error.data) && error.data.code === 'REVISION_CONFLICT'
  }
  if (!isRecord(error)) return false
  if (error.code === 'REVISION_CONFLICT') return true
  const data = isRecord(error.data) ? error.data : undefined
  return data?.code === 'REVISION_CONFLICT'
}

const SUM_USAGE_FIELDS = [
  'input_tokens',
  'output_tokens',
  'total_tokens',
  'cached_tokens',
  'cache_creation_tokens',
  'llm_calls',
] as const

const CONTEXT_METRIC_FIELDS = new Set([
  'estimated_prompt_tokens',
  'estimatedPromptTokens',
  'context_tokens',
  'contextTokens',
  'context_window_tokens',
  'contextWindowTokens',
  'context_compaction_trigger_tokens',
  'contextCompactionTriggerTokens',
  'trigger_tokens',
  'triggerTokens',
  'context_compacted',
  'contextCompacted',
  'context_compaction_status',
  'context_tokens_before_compaction',
  'context_tokens_after_compaction',
  'context_messages_before_compaction',
  'context_messages_after_compaction',
  'steps_total',
  'model_id',
])

function isContextMetrics(value: Record<string, unknown>): boolean {
  return [...CONTEXT_METRIC_FIELDS].some((key) => key in value)
}

function numericField(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return undefined
}

// A turn emits one usage event per model call (multi-step tool turns emit
// several).  Sum the per-call counters instead of letting the last event
// overwrite earlier ones, and recompute the turn-level cache hit rate.
function mergeUsageMetrics(
  prev: Record<string, unknown> | undefined,
  next: Record<string, unknown>,
): Record<string, unknown> {
  if (!prev) return { ...next }
  const merged: Record<string, unknown> = { ...prev, ...next }
  let inputTokens = 0
  let cachedTokens: number | undefined
  for (const field of SUM_USAGE_FIELDS) {
    const a = numericField(prev[field])
    const b = numericField(next[field])
    if (a === undefined && b === undefined) continue
    const sum = (a ?? 0) + (b ?? 0)
    merged[field] = sum
    if (field === 'input_tokens') inputTokens = sum
    if (field === 'cached_tokens') cachedTokens = sum
  }
  if (inputTokens > 0 && cachedTokens !== undefined) {
    merged.cache_hit_rate = cachedTokens / inputTokens
  } else {
    delete merged.cache_hit_rate
  }
  const durationA = numericField(prev.duration_ms)
  const durationB = numericField(next.duration_ms)
  if (durationA !== undefined || durationB !== undefined) {
    merged.duration_ms = Math.max(durationA ?? 0, durationB ?? 0)
  }
  const reported = prev.usage_available === true || next.usage_available === true
  merged.usage_available = reported
  merged.usage_status = reported ? 'reported' : 'missing'
  merged.usage_source = String(next.usage_source || prev.usage_source || 'provider')
  return merged
}

function isCoreAppThreadStatus(value: unknown): value is CoreAppThreadStatus {
  return value === 'idle'
    || value === 'running'
    || value === 'waiting'
    || value === 'completed'
    || value === 'failed'
    || value === 'cancelled'
}

function isCoreAppSnapshot(value: unknown): value is CoreAppSnapshot {
  return Boolean(value)
    && typeof value === 'object'
    && typeof (value as { thread_id?: unknown }).thread_id === 'string'
    && typeof (value as { snapshot_seq?: unknown }).snapshot_seq === 'number'
}
