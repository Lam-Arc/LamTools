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

export interface CoreAppServerRuntimeClient {
  connect(params?: { threadId?: string; lastSeenSeq?: number }): Promise<void>
  request(method: string, params?: Record<string, unknown>, timeoutMs?: number): Promise<Record<string, unknown>>
  respondServerRequest?(requestId: string, result: Record<string, unknown>): boolean
  close(): void
}

export interface CoreAppServerRuntimeState<
  Snapshot extends CoreAppSnapshot = CoreAppSnapshot,
  Client extends CoreAppServerRuntimeClient = CoreAppServerRuntimeClient,
> {
  state: Snapshot | null
  connectionState: 'connecting' | 'open' | 'closed' | 'error'
  client: Client | null
  lastError: string
  activeApiBase: string
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
    apiBase: string
    onEvent: (event: CoreAppEvent) => void
    onSnapshot: (snapshot: Snapshot) => void
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
    activeApiBase: '',
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
  let eventFrameScheduled = false
  // Event ids the client has received on the wire (non-reactive, kept outside
  // the snapshot state on purpose). The snapshot hydrate guard compares an
  // incoming snapshot's seen_event_ids against this set to detect "missed
  // events" without forcing a full state replacement (and full re-render) for
  // snapshots that carry nothing new.
  const receivedEventIds = new Set<string>()

  async function connect(apiBase: string, threadId?: string) {
    clearReconnectTimer()
    runtime.activeApiBase = apiBase
    runtime.activeThreadId = threadId || ''
    runtime.reconnectAttempt = 0
    await openClient(apiBase, threadId)
  }

  async function openClient(apiBase: string, threadId?: string) {
    const generation = ++runtime.connectionGeneration
    runtime.client?.close()
    const client = await options.createClient({
      apiBase,
      onEvent: (event) => enqueueEvent(event),
      onSnapshot: (snapshot) => hydrate(snapshot),
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
  }

  function disconnect() {
    clearReconnectTimer()
    runtime.activeApiBase = ''
    runtime.activeThreadId = ''
    runtime.connectionGeneration += 1
    runtime.client?.close()
    runtime.client = null
    runtime.state = null
    pendingEvents.length = 0
    runtime.connectionState = 'closed'
  }

  function clearReconnectTimer() {
    if (!runtime.reconnectTimer) return
    clearTimeout(runtime.reconnectTimer)
    runtime.reconnectTimer = null
  }

  function scheduleReconnect() {
    if (!runtime.activeApiBase || runtime.reconnectTimer) return
    const delay = Math.min(reconnectMaxMs, reconnectBaseMs * 2 ** runtime.reconnectAttempt)
    runtime.reconnectAttempt += 1
    runtime.reconnectTimer = setTimeout(() => {
      runtime.reconnectTimer = null
      void reconnectActiveThread()
    }, delay)
  }

  async function reconnectActiveThread() {
    if (!runtime.activeApiBase) return
    try {
      await openClient(runtime.activeApiBase, runtime.activeThreadId || undefined)
    } catch (error) {
      runtime.lastError = error instanceof Error ? error.message : String(error)
      runtime.connectionState = 'error'
      scheduleReconnect()
    }
  }

  function hydrate(snapshot: Snapshot) {
    const incoming = snapshot as CoreAppSnapshot
    // The guard must see the received set BEFORE this snapshot's ids are
    // recorded, otherwise "unseen event" would always be satisfied (an
    // incoming snapshot's own ids would count as received).
    const current = runtime.state
    const shouldReplace = !current || shouldHydrateSnapshot(current, incoming, receivedEventIds)
    for (const id of [
      ...(incoming.core?.seen_event_ids ?? []),
      ...(incoming.seen_event_ids ?? []),
    ]) {
      receivedEventIds.add(id)
    }
    if (receivedEventIds.size > 200_000) {
      receivedEventIds.clear()
    }
    if (!shouldReplace) {
      return
    }
    runtime.state = hydrateSnapshot(snapshot)
  }

  function enqueueEvent(event: CoreAppEvent) {
    const eventId = runItemEventId(event)
    if (eventId) receivedEventIds.add(eventId)
    if (event.method === 'session/created') {
      options.onSessionCreated?.()
      return
    }
    if (event.method === 'session/updated') {
      const session = (event.payload as { session?: { title?: string } } | null)?.session || {}
      options.onSessionUpdated?.(session)
      return
    }
    if (event.method === 'core/runItem') {
      pendingEvents.push(event)
      if (eventFrameScheduled) return
      eventFrameScheduled = true
      scheduleFrame(() => {
        eventFrameScheduled = false
        const events = pendingEvents.splice(0)
        if (!runtime.state) return
        let next = runtime.state as CoreAppSnapshot
        // Coalesce same-frame deltas for the same item. On very large threads
        // (thousands of items) each apply() copies the whole items map — doing
        // that once per frame instead of once per incoming chunk keeps the
        // frame budget flat. (A/B: removing it made big-thread streaming worse.)
        for (const pending of coalesceRunItemEvents(events)) {
          next = applyCoreRunItemEvent(next, pending)
        }
        runtime.state = next as Snapshot
      })
      return
    }
    // Apply turn/accepted and item/started directly to the top-level snapshot
    if (event.method === 'turn/accepted' || event.method === 'item/started') {
      if (!runtime.state) return
      runtime.state = applyAppEvent(runtime.state as CoreAppSnapshot, event) as Snapshot
    }
  }

  function applyResponse(response: Record<string, unknown>) {
    const snapshot = response.snapshot
    if (isCoreAppSnapshot(snapshot)) {
      hydrate(snapshot as Snapshot)
    }
  }

  async function startThread(threadId: string) {
    await ensureClient()
    const response = await runtime.client!.request('thread/start', { thread_id: threadId })
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
    const response = await runtime.client!.request('turn/start', {
      thread_id: threadId,
      client_message_id: crypto.randomUUID(),
      input: inputItems,
      work_root: workRoot,
      // The turn/accepted + item/started events already carry everything the
      // UI needs; the response snapshot is a 56MB JSON.parse on huge threads
      // (~1s main-thread stall at send time). Skip it — callers can override.
      include_snapshot: false,
      ...turnOptions,
    }, 60_000)
    applyResponse(response)
  }

  async function queueInput(threadId: string, input: string | InputItem[]) {
    await ensureClient()
    const inputItems = typeof input === 'string' ? [{ type: 'text' as const, text: input }] : input
    const response = await runtime.client!.request('queue/create', {
      thread_id: threadId,
      client_message_id: crypto.randomUUID(),
      input: inputItems,
    })
    applyResponse(response)
  }

  async function updateQueueInput(threadId: string, queueItemId: string, text: string) {
    await ensureClient()
    const response = await runtime.client!.request('queue/update', {
      thread_id: threadId,
      queue_item_id: queueItemId,
      text,
    })
    applyResponse(response)
  }

  async function deleteQueueInput(threadId: string, queueItemId: string) {
    await ensureClient()
    const response = await runtime.client!.request('queue/delete', {
      thread_id: threadId,
      queue_item_id: queueItemId,
    })
    applyResponse(response)
  }

  async function guideQueueInput(threadId: string, turnId: string, queueItemId: string, text?: string) {
    await ensureClient()
    const response = await runtime.client!.request('queue/guide', {
      thread_id: threadId,
      turn_id: turnId,
      queue_item_id: queueItemId,
      client_message_id: `queue-guide:${queueItemId}`,
      ...(text?.trim() ? { text: text.trim() } : {}),
    })
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

  async function executeCommand(threadId: string, command: string, workRoot?: string): Promise<Record<string, unknown>> {
    await ensureClient()
    const response = await runtime.client!.request('command.execute', {
      thread_id: threadId,
      command,
      ...(workRoot ? { work_root: workRoot } : {}),
    })
    applyResponse(response)
    return response.result && typeof response.result === 'object'
      ? response.result as Record<string, unknown>
      : {}
  }

  async function steerTurn(threadId: string, turnId: string, input: string | InputItem[]) {
    await ensureClient()
    const inputItems = typeof input === 'string' ? [{ type: 'text' as const, text: input }] : input
    const response = await runtime.client!.request('turn/steer', {
      thread_id: threadId,
      turn_id: turnId,
      client_message_id: crypto.randomUUID(),
      input: inputItems,
    })
    applyResponse(response)
  }

  async function interruptTurn(threadId: string, turnId?: string) {
    await ensureClient()
    const response = await runtime.client!.request('turn/interrupt', {
      thread_id: threadId,
      ...(turnId ? { turn_id: turnId } : {}),
      include_snapshot: false,
    })
    applyResponse(response)
  }

  async function forceResetTurn(threadId: string, turnId?: string) {
    await ensureClient()
    const response = await runtime.client!.request('turn/force_reset', {
      thread_id: threadId,
      ...(turnId ? { turn_id: turnId } : {}),
      include_snapshot: true,
    })
    applyResponse(response)
  }

  async function respondApproval(requestId: string, decision: string, guidance?: string) {
    await ensureClient()
    const response = await runtime.client!.request('approval/respond', {
      request_id: requestId,
      decision,
      guidance,
    })
    applyResponse(response)
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
    openClient,
    queueInput,
    reconnectActiveThread,
    respondApproval,
    scheduleReconnect,
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
  if (coalescedEventIds.some((id) => seenEventSet.has(id))) return snapshot
  const runPayload = isRecord(value.payload) ? value.payload : {}
  const turnId = typeof value.turn_id === 'string' ? value.turn_id : event.turn_id || ''
  const seen = [...(currentCore.seen_event_ids ?? []), ...coalescedEventIds].slice(-2000)
  if (kind === 'status') {
    const rawStatus = typeof runPayload.status === 'string'
      ? runPayload.status
      : typeof value.status === 'string'
        ? value.status
        : currentCore.status
    const status = isCoreAppThreadStatus(rawStatus) ? rawStatus : currentCore.status
    const turns = { ...(currentCore.turns ?? {}) }
    if (turnId) {
      const turn = turns[turnId] ?? { turn_id: turnId, status: status || 'running', items: [] }
      turns[turnId] = { ...turn, status: status || turn.status }
    }
    return {
      ...snapshot,
      core: { ...currentCore, seen_event_ids: seen, turns, status },
    }
  }
  if (kind === 'usage') {
    const turns = { ...(currentCore.turns ?? {}) }
    if (turnId) {
      const turn = turns[turnId] ?? { turn_id: turnId, status: 'running', items: [] }
      const usage = isRecord(value.usage) ? value.usage : {}
      turns[turnId] = { ...turn, usage: { ...(turn.usage ?? {}), ...usage } }
    }
    return { ...snapshot, core: { ...currentCore, seen_event_ids: seen, turns } }
  }
  if (!itemId) return snapshot

  const items = { ...(currentCore.items ?? {}) }
  const existing = items[itemId] ?? { item_id: itemId, content: '', deltas: [] }
  const delta = typeof runPayload.delta === 'string' ? runPayload.delta : undefined
  const content = typeof runPayload.content === 'string' ? runPayload.content : undefined
  const item: CoreRuntimeItem = {
    ...existing,
    item_id: itemId,
    turn_id: typeof value.turn_id === 'string' ? value.turn_id : existing.turn_id,
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

  // Tool results carry artifacts in the runItem payload; merge them into the
  // snapshot-level artifacts map so file/change cards render from the event
  // stream instead of waiting for the next full snapshot (snapshots are now
  // only pushed at turn boundaries).
  let artifacts = currentCore.artifacts
  if (kind === 'tool_result' && Array.isArray(runPayload.artifacts) && runPayload.artifacts.length > 0) {
    let merged: Record<string, Record<string, unknown>> | null = null
    for (const artifact of runPayload.artifacts) {
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
      input: input ?? turn.input,
      work_root: payload.work_root || payload.workRoot || turn.work_root || '',
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
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
