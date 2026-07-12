import { hydrateSnapshot as defaultHydrateSnapshot } from './snapshot.ts'
import type { CoreAppCommandCatalogItem, CoreAppInputItem, CoreAppSnapshot } from './protocol.ts'

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
    onSnapshot: (snapshot: Snapshot) => void
    onConnectionState: (state: CoreAppServerRuntimeState<Snapshot, Client>['connectionState']) => void
  }): Promise<Client> | Client
  hydrateSnapshot?: (snapshot: Snapshot) => Snapshot
  reconnectBaseMs?: number
  reconnectMaxMs?: number
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

  async function steerTurn(threadId: string, turnId: string, text: string) {
    await ensureClient()
    const response = await runtime.client!.request('turn/steer', {
      thread_id: threadId,
      turn_id: turnId,
      client_message_id: crypto.randomUUID(),
      input: [{ type: 'text', text }],
    })
    applyResponse(response)
  }

  async function interruptTurn(threadId: string) {
    await ensureClient()
    const response = await runtime.client!.request('turn/interrupt', {
      thread_id: threadId,
    })
    applyResponse(response)
  }

  async function respondApproval(requestId: string, decision: string, guidance?: string) {
    await ensureClient()
    const sentResponse = runtime.client!.respondServerRequest?.(requestId, {
      decision,
      guidance,
    })
    if (sentResponse) return
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

function isCoreAppSnapshot(value: unknown): value is CoreAppSnapshot {
  return Boolean(value)
    && typeof value === 'object'
    && typeof (value as { thread_id?: unknown }).thread_id === 'string'
    && typeof (value as { snapshot_seq?: unknown }).snapshot_seq === 'number'
}
