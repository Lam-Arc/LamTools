import { hydrateSnapshot as defaultHydrateSnapshot } from './snapshot.ts'
import type {
  CoreAppCommandCatalogItem,
  CoreAppEvent,
  CoreAppInputItem,
  CoreAppSnapshot,
  CoreRuntimeItem,
  CoreRuntimeSnapshot,
  CoreAppThreadStatus,
} from './protocol.ts'

export interface CoreAppServerRuntimeClient {
  connect(params?: { threadId?: string; lastSeenSeq?: number }): Promise<void>
  request(method: string, params?: Record<string, unknown>): Promise<Record<string, unknown>>
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
      const response = await client.request('thread/resume', { thread_id: threadId, last_seen_seq: lastSeenSeq() })
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
    if (!runtime.activeApiBase || !runtime.activeThreadId || runtime.reconnectTimer) return
    const delay = Math.min(reconnectMaxMs, reconnectBaseMs * 2 ** runtime.reconnectAttempt)
    runtime.reconnectAttempt += 1
    runtime.reconnectTimer = setTimeout(() => {
      runtime.reconnectTimer = null
      void reconnectActiveThread()
    }, delay)
  }

  async function reconnectActiveThread() {
    if (!runtime.activeApiBase || !runtime.activeThreadId) return
    try {
      await openClient(runtime.activeApiBase, runtime.activeThreadId)
    } catch (error) {
      runtime.lastError = error instanceof Error ? error.message : String(error)
      runtime.connectionState = 'error'
      scheduleReconnect()
    }
  }

  function hydrate(snapshot: Snapshot) {
    runtime.state = hydrateSnapshot(snapshot)
  }

  function enqueueEvent(event: CoreAppEvent) {
    if (event.method === 'session/created') {
      options.onSessionCreated?.()
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
        for (const pending of events) {
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
      ...turnOptions,
    })
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
  if (typeof requestAnimationFrame === 'function') {
    requestAnimationFrame(callback)
    return
  }
  queueMicrotask(callback)
}

function applyCoreRunItemEvent(snapshot: CoreAppSnapshot, event: CoreAppEvent): CoreAppSnapshot {
  const value = event.payload
  const itemId = typeof value.item_id === 'string' ? value.item_id : event.item_id || ''
  const kind = typeof value.kind === 'string' ? value.kind : ''
  if (!kind) return snapshot
  const eventId = typeof value.event_id === 'string' ? value.event_id : event.event_id
  const currentCore = snapshot.core ?? emptyCoreSnapshot(snapshot.thread_id)
  if (currentCore.seen_event_ids?.includes(eventId)) return snapshot
  const runPayload = isRecord(value.payload) ? value.payload : {}
  const turnId = typeof value.turn_id === 'string' ? value.turn_id : event.turn_id || ''
  const seen = [...(currentCore.seen_event_ids ?? []), eventId].slice(-2000)
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
      status: payload.status || 'running',
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
      type: payload.type ?? item.type ?? 'item',
      status: payload.status ?? item.status ?? 'running',
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
