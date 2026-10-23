import {
  computed,
  getCurrentScope,
  nextTick,
  onScopeDispose,
  reactive,
  ref,
  shallowRef,
  watch,
  type Ref,
} from 'vue'
import {
  CoreAppServerClient,
  createCoreAppServerRuntimeController,
  createCoreAppServerRuntimeState,
  hydrateSnapshot,
  isCoreActiveTurnStatus,
  selectCoreQueuedInputs,
  selectCoreSessionActivity,
  selectLatestActiveTurnId,
  selectLatestTurnStatus,
  selectTurnControl,
  type CoreAppEvent,
  type CoreAppServerRuntimeClient,
  type CoreAppSnapshot,
  type CoreAppServerThreadSwitchOptions,
  type CoreSyncChangeNotification,
  type CoreWorkbenchTurnStatus,
} from '../appServer'
import {
  useCoreApprovalController,
  useCoreAskAutoContinue,
  useCoreLiveComposerController,
  useCoreQueuedInputController,
  useCorePendingGuidance,
  useCoreWorkbenchProjectionController,
} from '../composables'
import type { CoreInputItem, CoreSessionListItem, CoreSubAgentDurableRecord } from '../types'
import {
  readComposerDraft,
  resolveComposerDraftStorage,
  writeComposerDraft,
  type ComposerDraftStorage,
} from '../composer/drafts'
import {
  isLamToolsTransport,
  type LamToolsTransport,
  type TransportHttpRequest,
  type TransportHttpResponse,
} from '../transport'
import type { WorkbenchComposerCallbacks, WorkbenchRuntimeOptions } from './types'

export interface WorkbenchClientOptions {
  transport: LamToolsTransport
  onEvent?: (event: CoreAppEvent) => void
  onSnapshot?: (snapshot: CoreAppSnapshot) => void
  onSyncChange?: (change: CoreSyncChangeNotification) => void
  onConnectionState?: (state: 'connecting' | 'open' | 'closed' | 'error') => void
  clientInfo?: { name: string; title?: string; version?: string }
}

/** Build the default App Server client used by every shell. */
export function createWorkbenchClient(options: WorkbenchClientOptions): CoreAppServerClient {
  return new CoreAppServerClient({
    transport: options.transport,
    clientInfo: options.clientInfo || {
      name: 'lamtools_workbench',
      title: 'LamTools Shared Workbench',
      version: '0.1.0',
    },
    onEvent: options.onEvent,
    onSnapshot: options.onSnapshot,
    onSyncChange: options.onSyncChange,
    onConnectionState: options.onConnectionState,
  })
}

/**
 * Shared session/turn runtime used by desktop and mobile shells.
 *
 * This is intentionally UI-framework-light: shells provide the surrounding
 * layout while this function owns connection, projection, composer, queue,
 * approval and reconnect semantics. The only backend boundary is the
 * connection-neutral transport supplied by the host runtime.
 */
export function createWorkbench(options: WorkbenchRuntimeOptions) {
  if (!isLamToolsTransport(options.transport)) {
    throw new TypeError('A valid LamTools transport is required')
  }

  const sessions = ref<CoreSessionListItem[]>([])
  const activeSessionId = ref<string | null>(null)
  const composerText = ref('')
  const composerCursor = ref(0)
  const attachments = ref<CoreInputItem[]>([])
  const activeTransport = shallowRef<LamToolsTransport | null>(options.transport)
  const runtime = reactive(createCoreAppServerRuntimeState<CoreAppSnapshot, CoreAppServerRuntimeClient>())
  const snapshot = computed(() => runtime.state)
  const connectionState = computed(() => runtime.connectionState)
  const activeThreadId = computed(() => runtime.activeThreadId)
  const turnState = computed(() => snapshot.value ? selectLatestTurnStatus(snapshot.value) : 'idle')
  const activeTurnId = computed(() => snapshot.value ? selectLatestActiveTurnId(snapshot.value) : '')
  const turnActive = computed(() => isCoreActiveTurnStatus(turnState.value))
  const lastEvent = ref<CoreAppEvent | null>(null)
  const shallowThinking = (options.shallowThinking || ref(false)) as Ref<boolean>
  let turnOptionsProvider = options.getTurnOptions || (() => ({}))
  let composerCallbacks: WorkbenchComposerCallbacks = {
    onError: options.onError,
    onStatusText: options.onStatusText,
    onSubmitStart: options.onSubmitStart,
    onSubmitSettled: options.onSubmitSettled,
    onCommandResult: options.onCommandResult,
  }

  let sessionSelectionGeneration = 0

  async function request(request: TransportHttpRequest): Promise<TransportHttpResponse> {
    await options.transport.connect()
    return await options.transport.request(request)
  }

  async function requestJson<TResponse = unknown>(path: string, init: RequestInit = {}): Promise<TResponse> {
    const headers: Record<string, string> = {}
    new Headers(init.headers).forEach((value, key) => { headers[key] = value })
    const body = encodeRequestBody(init.body)
    const response = await request({
      kind: 'http',
      method: init.method || 'GET',
      path,
      headers,
      ...(body ? { body } : {}),
      signal: init.signal || undefined,
    })
    const text = new TextDecoder().decode(response.body)
    if (response.status < 200 || response.status >= 300) {
      throw new Error(text || `请求失败（${response.status}）`)
    }
    if (!text) return undefined as TResponse
    return JSON.parse(text) as TResponse
  }

  let rpcConnectPromise: Promise<void> | null = null

  async function ensureRpcClient(): Promise<CoreAppServerRuntimeClient> {
    // openClient() installs the client on runtime before its asynchronous
    // initialize handshake completes.  A second caller must wait for the
    // same connection promise instead of treating that half-initialized
    // client as ready (the Core server then answers with
    // "Connection is not initialized").
    if (rpcConnectPromise) await rpcConnectPromise
    if (!runtime.client) {
      if (!rpcConnectPromise) {
        rpcConnectPromise = runtimeController.connect(activeSessionId.value || undefined)
          .finally(() => { rpcConnectPromise = null })
      }
      await rpcConnectPromise
    }
    if (!runtime.client) throw new Error('Core App Server client is not connected')
    return runtime.client
  }

  async function requestRpc(
    method: string,
    params: Record<string, unknown> = {},
    timeoutMs = 30_000,
  ): Promise<Record<string, unknown>> {
    return await (await ensureRpcClient()).request(method, params, timeoutMs)
  }

  let sharedClient: CoreAppServerClient | null = null
  let sharedCallbacks: {
    onEvent: (event: CoreAppEvent) => void
    onSnapshot: (snapshot: CoreAppSnapshot) => void
    onSyncChange?: (change: CoreSyncChangeNotification) => void
    onConnectionState: (state: 'connecting' | 'open' | 'closed' | 'error') => void
  } | null = null

  const sessionApi = options.sessions || {
    async listSessions(): Promise<CoreSessionListItem[]> {
      const rows = await requestJson<unknown>('/sessions')
      const list = Array.isArray(rows)
        ? rows
        : isRecord(rows) && Array.isArray(rows.sessions) ? rows.sessions : []
      return list.flatMap((row) => isRawSession(row) ? [toSession(row)] : [])
    },
    async createSession(input: { title?: string; metadata?: Record<string, unknown> } = {}): Promise<CoreSessionListItem> {
      const created = await requestJson<RawSession>('/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: globalThis.crypto?.randomUUID?.() || `session-${Date.now()}`,
          member_id: 'core',
          title: input.title?.trim() || '新会话',
          status: 'idle',
          metadata: input.metadata || {},
        }),
      })
      return toSession(created)
    },
  }

  async function refreshSessions(): Promise<void> {
    const loaded = await sessionApi.listSessions()
    sessions.value = loaded
  }

  function sessionWorkRoot(id = activeSessionId.value || ''): string | undefined {
    const session = sessions.value.find((candidate) => candidate.id === id)
    if (options.getWorkRoot) return options.getWorkRoot(session)
    const workRoot = session?.metadata?.work_root
    return typeof workRoot === 'string' ? workRoot : undefined
  }

  const runtimeController = createCoreAppServerRuntimeController(runtime, {
    hydrateSnapshot,
    onSessionCreated: () => { void refreshSessions() },
    onSessionUpdated: () => { void refreshSessions() },
    createClient: async ({ onEvent, onSnapshot, onSyncChange, onConnectionState }) => {
      if (options.clientFactory) {
        return await options.clientFactory.createClient({
          transport: options.transport,
          onEvent,
          onSnapshot,
          onSyncChange,
          onConnectionState,
        })
      }
      // One workbench owns one App Server client. Reusing it for settings,
      // commands and the active thread prevents duplicate initialize calls and
      // competing subscriptions when all surfaces share one transport.
      if (!sharedClient) {
        sharedClient = createWorkbenchClient({
          transport: options.transport,
          onEvent: (event) => {
            lastEvent.value = event
            sharedCallbacks?.onEvent(event)
          },
          onSnapshot: (value) => sharedCallbacks?.onSnapshot(value),
          onSyncChange: (change) => sharedCallbacks?.onSyncChange?.(change),
          onConnectionState: (state) => sharedCallbacks?.onConnectionState(state),
        })
      }
      sharedCallbacks = { onEvent, onSnapshot, onSyncChange, onConnectionState }
      return sharedClient
    },
  })

  function syncActiveSessionStatus(): void {
    const activeId = activeSessionId.value
    const activeSnapshot = runtime.state
    if (!activeId || !activeSnapshot || activeSnapshot.thread_id !== activeId) return
    // Sessions list dot: state (b) publishes its own status so the sidebar shows
    // the quieter "waiting on sub-agents" dot instead of the generic running one.
    const status = sessionPhase.value === 'awaiting_sub_agents' ? 'sub_agents' : turnState.value
    sessions.value = sessions.value.map((session) => (
      session.id === activeId && session.status !== status ? { ...session, status } : session
    ))
  }

  // The composer owns a single live draft. Park the outgoing thread's text
  // under that thread and restore the incoming one, so an unsent draft never
  // leaks across sessions and survives a restart (localStorage, per thread).
  const composerDraftStorage: ComposerDraftStorage | null = options.composerDraftStorage !== undefined
    ? options.composerDraftStorage
    : resolveComposerDraftStorage()
  watch(activeSessionId, (threadId, previousThreadId) => {
    if (previousThreadId) writeComposerDraft(composerDraftStorage, previousThreadId, composerText.value)
    composerText.value = readComposerDraft(composerDraftStorage, threadId)
  })
  watch(composerText, (text) => {
    writeComposerDraft(composerDraftStorage, activeSessionId.value, text)
  })

  const approvalControllerRef = shallowRef<ReturnType<typeof useCoreApprovalController>>()
  // 待生效的引导：发出即显示（虚线 + 呼吸），模型接手后撤下；这一轮提前结束则交回用户
  const pendingGuidance = useCorePendingGuidance({
    snapshot,
    activeThreadId: activeSessionId,
    composerText,
    queueInput: (threadId, input) => runtimeController.queueInput(threadId, input),
    onError: options.onError,
  })
  // Snapshot-only member-wait flag (no transcript scan needed) so the
  // projection can tell "main agent working" from "main agent stopped, members
  // running" without depending on the projected messages it is about to build.
  const memberWaitActive = computed(() => (
    snapshot.value ? selectCoreSessionActivity(snapshot.value).awaitingSubAgents : false
  ))
  const projectionController = useCoreWorkbenchProjectionController({
    snapshot,
    activeThreadId: activeSessionId,
    status: turnState,
    awaitingSubAgents: memberWaitActive,
    activeTurnId,
    pendingGuidance: pendingGuidance.guidanceParts,
    submittingApprovalRequestIds: computed(() => (
      approvalControllerRef.value?.submittingRequestIds.value ?? new Set<string>()
    )),
    shallowThinkingPending: shallowThinking,
    source: 'shared_workbench',
  })
  const hasMoreHistory = computed(() => (
    projectionController.hasMoreHistory.value || snapshot.value?.history_page?.has_more === true
  ))

  // Session activity is derived once (see selectCoreSessionActivity): state (a)
  // main agent running, state (b) main stopped with sub-agents still pending.
  // Every busy/disabled decision reads these, never the raw status ad hoc.
  const subAgentRecords = shallowRef<{ threadId: string; records: Record<string, CoreSubAgentDurableRecord> } | null>(null)
  function setSubAgentRecords(threadId: string, records: Record<string, CoreSubAgentDurableRecord>): void {
    if (threadId === activeSessionId.value) subAgentRecords.value = { threadId, records }
  }
  const sessionActivity = computed(() => selectCoreSessionActivity(snapshot.value, {
    messages: projectionController.messages.value,
    memberRecords: subAgentRecords.value?.threadId === activeSessionId.value ? subAgentRecords.value.records : undefined,
  }))
  const sessionPhase = computed(() => sessionActivity.value.phase)

  /** Fold a lifecycle-op response into the same record map the polling fills. */
  function mergeSubAgentRecords(threadId: string, items: unknown): void {
    const existing = subAgentRecords.value?.threadId === threadId ? subAgentRecords.value.records : {}
    const records = { ...existing }
    for (const item of Array.isArray(items) ? items : []) {
      if (!item || typeof item !== 'object') continue
      const name = String((item as { name?: unknown }).name || '').trim().toLowerCase()
      if (name) records[name] = item as CoreSubAgentDurableRecord
    }
    setSubAgentRecords(threadId, records)
  }

  /**
   * Child-directed Stop/Resume. These act on the members themselves: the parent
   * turn is neither restarted nor re-cancelled to control them, so a parent
   * turn that already ended stays ended.
   */
  async function interruptSubAgents(threadId: string): Promise<void> {
    const response = await requestRpc('sub_agent.interrupt', { thread_id: threadId })
    mergeSubAgentRecords(threadId, (response as { items?: unknown })?.items)
  }

  async function resumeSubAgents(threadId: string): Promise<void> {
    const response = await requestRpc('sub_agent.resume', { thread_id: threadId })
    mergeSubAgentRecords(threadId, (response as { items?: unknown })?.items)
  }

  // Sidebar status is a projection of the canonical session snapshot, not a
  // one-time value captured when turn/start is accepted.
  watch([activeSessionId, turnState, sessionPhase], syncActiveSessionStatus, { immediate: true })

  // Composer queue-vs-start decision keys off the turn's own status, not off
  // who is working: while the runtime reports a turn as active the message
  // belongs to that turn (steer or queue), and only a session the server
  // reports as having no active turn starts a new one. The earlier rule
  // (mainRunning) sent a start-turn while the server still had an active turn,
  // which the server refused and the client showed as an error.
  const composerTurnStatus = computed<CoreWorkbenchTurnStatus>(() => (
    isCoreActiveTurnStatus(turnState.value) ? turnState.value : 'idle'
  ))

  const historyBuffered = computed(() => projectionController.hasMoreHistory.value)
  const totalMessages = computed(() => Math.max(
    projectionController.totalMessages.value,
    Number(snapshot.value?.history_page?.total_items || 0),
  ))

  let pendingHistoryPrefetch: {
    key: string
    promise: Promise<boolean>
  } | null = null

  async function prefetchHistoryBuffer(threadId = activeSessionId.value || ''): Promise<boolean> {
    if (!threadId || activeSessionId.value !== threadId || projectionController.hasMoreHistory.value) return false
    const historyPage = snapshot.value?.history_page
    if (!historyPage?.has_more) return false
    const beforeItemId = String(historyPage.next_before_item_id || '')
    const beforeSeq = Number(historyPage.next_before_seq || 0)
    if (!beforeItemId && beforeSeq <= 0) return false
    const key = `${threadId}:${beforeItemId}:${beforeSeq}`
    if (pendingHistoryPrefetch?.key === key) return await pendingHistoryPrefetch.promise

    const promise = (async () => {
      const response = await requestRpc('thread.history', {
        thread_id: threadId,
        ...(beforeItemId ? { before_item_id: beforeItemId } : {}),
        before_seq: beforeSeq,
        turn_limit: 10,
        char_limit: 200_000,
      }, 60_000)
      const page = response.snapshot_page
      return isCoreSnapshot(page) && runtimeController.mergeSnapshotPage(page)
    })()
    pendingHistoryPrefetch = { key, promise }
    try {
      return await promise
    } finally {
      if (pendingHistoryPrefetch?.promise === promise) pendingHistoryPrefetch = null
    }
  }

  function scheduleHistoryPrefetch(threadId = activeSessionId.value || ''): void {
    void nextTick()
      .then(() => prefetchHistoryBuffer(threadId))
      .catch(() => { /* Background history prefetch is best-effort; foreground loading can retry. */ })
  }

  async function loadMoreHistory(): Promise<void> {
    const threadId = activeSessionId.value
    if (!threadId) return
    if (projectionController.hasMoreHistory.value) {
      projectionController.loadMoreHistory()
      scheduleHistoryPrefetch(threadId)
      return
    }
    if (await prefetchHistoryBuffer(threadId)) {
      await nextTick()
      if (activeSessionId.value !== threadId) return
      projectionController.loadMoreHistory()
      scheduleHistoryPrefetch(threadId)
    }
  }

  // One canonical turn-control derivation. The paused turn and the session's
  // paused state come from the same snapshot facts as the action mode, so a
  // delegated member event cannot make them disagree.
  const turnControl = computed(() => (
    snapshot.value ? selectTurnControl(snapshot.value) : null
  ))
  const resumableTurnId = computed(() => (
    runtime.client?.capabilities?.same_turn_resume === true
      ? turnControl.value?.pausedTurnId || ''
      : ''
  ))

  // A paused session owns its members too: their own Continue buttons stay
  // disabled until the session continues as a whole.
  const sessionPaused = computed(() => turnControl.value?.status === 'paused')

  const liveComposerController = useCoreLiveComposerController({
    activeThreadId: activeSessionId,
    activeTurnId,
    resumableTurnId,
    sessionPaused,
    resumeTurn: (threadId, turnId, input) => runtimeController.resumeTurn(threadId, turnId, input),
    interruptibleSubAgents: computed(() => sessionActivity.value.interruptibleSubAgentNames),
    resumableSubAgents: computed(() => sessionActivity.value.resumableSubAgentNames),
    subAgentControl: computed(() => runtime.client?.capabilities?.sub_agent_control === true),
    interruptSubAgents,
    resumeSubAgents,
    connectedThreadId: computed(() => runtime.activeThreadId),
    connectionState,
    text: composerText,
    cursor: composerCursor,
    // The turn's own status decides: while the runtime considers a turn active
    // the message goes to that turn (steer or queue); only a session the server
    // reports as having no active turn starts a new one. Deriving this from
    // "is the main agent working" sent a new turn while the server still had one
    // active, and the refusal surfaced as an error.
    status: composerTurnStatus,
    attachments,
    connect: (threadId) => runtimeController.connect(threadId),
    startTurn: (threadId, input, workRoot, turnOptions, clientMessageId) => (
      runtimeController.startTurn(threadId, input, workRoot, turnOptions, clientMessageId)
    ),
    interruptTurn: (threadId, turnId) => runtimeController.interruptTurn(threadId, turnId),
    pauseTurn: (threadId, turnId) => runtimeController.pauseTurn(threadId, turnId),
    terminateTurn: (threadId, turnId) => runtimeController.terminateTurn(threadId, turnId),
    forceResetTurn: (threadId, turnId) => runtimeController.forceResetTurn(threadId, turnId),
    steerTurn: async (threadId, turnId, input) => {
      const outcome = await runtimeController.steerTurn(threadId, turnId, input)
      if (outcome.applied) {
        pendingGuidance.track(threadId, turnId, input)
        return { ok: true }
      }
      // A refusal is a success response with `applied: false`: there is nothing
      // live to steer, so the caller queues the message. `queued` means the
      // runtime already filed it and it must not be queued twice.
      return { ok: false, queued: outcome.queued }
    },
    queueInput: (threadId, input, turnOptions, clientMessageId) => (
      runtimeController.queueInput(threadId, input, turnOptions, clientMessageId)
    ),
    listCommands: (workRoot) => runtimeController.listCommands(workRoot),
    getWorkRoot: () => sessionWorkRoot() || '',
    executeCommand: async (threadId, command, workRoot, argumentsText) => {
      const result = await runtimeController.executeCommand(threadId, command, workRoot, argumentsText)
      await composerCallbacks.onCommandResult?.(result)
      return true
    },
    turnOptions: () => turnOptionsProvider(),
    onSubmitStart: (submittedText: string) => composerCallbacks.onSubmitStart?.(submittedText),
    onSubmitSettled: () => composerCallbacks.onSubmitSettled?.(),
    clearComposer: () => { composerText.value = '' },
    clearAttachments: () => { attachments.value = [] },
    setStatusText: (text) => composerCallbacks.onStatusText?.(text),
    onError: (error) => composerCallbacks.onError?.(String(error)),
    onTurnStarted: () => {
      void refreshSessions()
      void composerCallbacks.onTurnStarted?.()
    },
    messages: {
      noActiveThread: '请先选择会话',
      queued: '已加入待发送',
      guided: '引导已发送',
      stopping: '正在停止',
      stopFailed: '停止失败',
      sendFailed: '发送失败',
    },
  })

  const approvalController = useCoreApprovalController({
    messages: projectionController.messages,
    hasActiveThread: computed(() => Boolean(activeSessionId.value)),
    canRespondApproval: computed(() => runtime.connectionState === 'open'),
    ensureApprovalChannel: () => liveComposerController.ensureConnected(activeSessionId.value || ''),
    respondApproval: (requestId, decision, guidance) => (
      runtimeController.respondApproval(requestId, decision, guidance)
    ),
    submitText: async (text) => {
      composerText.value = text
      await liveComposerController.submit({ clearComposer: true })
    },
    deferText: (text) => { composerText.value = text },
  })
  approvalControllerRef.value = approvalController

  // 「提问自动继续」（设置 → 通用）：提问卡挂满 5 分钟没人回答就回传「用户跳过」，
  // 本轮继续。权限审批卡不在此列——超时不代表同意，只有人能放行。
  // 偏好在这里才读：只有真的出现待答复提问卡时才问一次后端，不跟着每帧快照走。
  useCoreAskAutoContinue({
    messages: projectionController.messages,
    loadEnabled: async () => {
      // The backend now owns this timer. A second renderer-side timer would
      // race the server's skip; the server's durable claim absorbs the race,
      // but running two timers only produces duplicate requests.
      if (runtime.client?.capabilities?.ask_auto_continue_backend === true) return false
      try {
        const result = await requestRpc('settings.get', { namespace: 'core.askAutoContinue' })
        const value = result && typeof result.value === 'object' && result.value
          ? result.value as Record<string, unknown>
          : {}
        return value.enabled === true
      } catch {
        // 读不到偏好就当没开启：绝不因为一次读取失败替用户跳过提问。
        return false
      }
    },
    respondApproval: (requestId, decision, guidance) => (
      runtimeController.respondApproval(requestId, decision, guidance)
    ),
    onAutoSkipped: () => composerCallbacks.onStatusText?.('提问 5 分钟未回答，已按「用户跳过」继续'),
    onError: (message) => composerCallbacks.onError?.(message),
  })

  const queuedInputs = computed(() => (
    snapshot.value && snapshot.value.thread_id === activeSessionId.value
      ? selectCoreQueuedInputs(snapshot.value)
      : []
  ))
  const queue = useCoreQueuedInputController({
    activeTurnId,
    ensureConnected: async (threadId) => {
      if (!await liveComposerController.ensureConnected(threadId)) {
        throw new Error(liveComposerController.lastError.value || '连接不可用')
      }
    },
    updateQueueInput: (threadId, itemId, text) => runtimeController.updateQueueInput(threadId, itemId, text),
    deleteQueueInput: (threadId, itemId) => runtimeController.deleteQueueInput(threadId, itemId),
    guideQueueInput: async (threadId, turnId, itemId, text) => {
      const result = await runtimeController.guideQueueInput(threadId, turnId, itemId, text)
      if (result.applied) {
        const itemText = text?.trim()
          || queuedInputs.value.find(candidate => candidate.id === itemId)?.text
          || ''
        pendingGuidance.track(threadId, turnId, itemText)
      }
      return result
    },
    onError: options.onError,
  })

  async function selectSession(id: string): Promise<void> {
    if (!id) return
    const generation = ++sessionSelectionGeneration
    activeSessionId.value = id
    liveComposerController.resetForThreadChange()
    // The composer draft is parked/restored by the activeSessionId watcher;
    // clearing it here would both drop the outgoing draft and wipe the
    // incoming thread's own unsent text.
    // A local cache may be used by a host for offline rendering, but it must
    // not become the mutation/revision source. Always resume with the server
    // snapshot before enabling the composer for the selected session.
    // The persisted transcript loads first (`thread/read`) and the live attach
    // (`thread/resume`) resolves in the background: a session whose turn is
    // legitimately non-terminal must never hold the visible thread blank until
    // the resume signal times out.
    await runtimeController.switchThread(id, {
      lastSeenSeq: 0,
      includeSnapshot: true,
      preserveState: false,
      attachInBackground: true,
    })
    if (generation !== sessionSelectionGeneration) return
    // Keep one complete ten-turn page ahead of the rendered window. Normal
    // upward paging then performs no RPC and only reveals already-local data.
    scheduleHistoryPrefetch(id)
    await liveComposerController.loadCommandCatalog(id)
  }

  async function createSession(input: { title?: string; metadata?: Record<string, unknown> } = {}): Promise<CoreSessionListItem | null> {
    if (!sessionApi.createSession) return null
    const created = await sessionApi.createSession(input)
    await refreshSessions()
    await selectSession(created.id)
    return created
  }

  async function send(text = composerText.value): Promise<void> {
    if (text.trim()) composerText.value = text
    await liveComposerController.submit({ clearComposer: true })
  }

  async function stop(): Promise<boolean> {
    return await liveComposerController.stop()
  }

  async function steer(text: string): Promise<void> {
    const threadId = activeSessionId.value
    if (!threadId || !text.trim()) return
    if (!await liveComposerController.ensureConnected(threadId)) {
      throw new Error(liveComposerController.lastError.value || '连接不可用')
    }
    const outcome = await runtimeController.steerTurn(threadId, activeTurnId.value, text.trim())
    if (!outcome.applied) throw new Error(outcome.message || '引导没有生效')
  }

  async function queueInput(text: string): Promise<void> {
    const threadId = activeSessionId.value
    if (!threadId || !text.trim()) return
    await runtimeController.queueInput(threadId, text.trim())
  }

  async function respondApproval(requestId: string, decision: string, guidance = ''): Promise<void> {
    await runtimeController.respondApproval(requestId, decision, guidance)
  }

  async function loadCommandCatalog(): Promise<boolean> {
    return await liveComposerController.loadCommandCatalog(activeSessionId.value || '')
  }

  function close(): void {
    sessionSelectionGeneration += 1
    runtimeController.disconnect()
    sharedCallbacks = null
  }

  // Hosts may construct the workbench before mounting the shared Vue app
  // (Tauri does this while resolving the backend port). Register automatic
  // cleanup only when a Vue scope actually owns the factory; the host still
  // has the explicit `close` method for scope-less construction.
  if (getCurrentScope()) onScopeDispose(close)

  return {
    transport: activeTransport,
    activeThreadId,
    sessions,
    activeSessionId,
    snapshot,
    messages: projectionController.messages,
    connectionState,
    turnState,
    activeTurnId,
    turnActive,
    sessionActivity,
    setSubAgentRecords,
    sessionPhase,
    composerText,
    composerCursor,
    attachments,
    queuedInputs,
    processExpandedIds: projectionController.processExpandedIds,
    toggleProcess: projectionController.toggleProcess,
    hasMoreHistory,
    historyBuffered,
    totalMessages,
    loadMoreHistory,
    lastEvent,
    approval: approvalController,
    queue,
    composer: liveComposerController,
    commandCatalog: liveComposerController.commandCatalog,
    commandPalette: liveComposerController.commandPalette,
    paletteVisible: liveComposerController.paletteVisible,
    actionMode: liveComposerController.actionMode,
    handleComposerKeydown: liveComposerController.handleKeydown,
    handleComposerKeyup: liveComposerController.handleKeyup,
    selectCommand: liveComposerController.selectCommand,
    runCommand: liveComposerController.runCommand,
    connect: (threadId?: string, switchOptions?: CoreAppServerThreadSwitchOptions) => (
      runtimeController.connect(threadId, switchOptions)
    ),
    switchThread: runtimeController.switchThread,
    disconnect: runtimeController.disconnect,
    selectSession,
    createSession,
    refreshSessions,
    send,
    stop,
    steer,
    queueInput,
    respondApproval,
    loadCommandCatalog,
    setTurnOptionsProvider: (provider: () => Record<string, unknown> | Promise<Record<string, unknown>>) => {
      turnOptionsProvider = provider
    },
    setShallowThinking: (value: boolean) => {
      shallowThinking.value = value
    },
    setComposerCallbacks: (callbacks: WorkbenchComposerCallbacks) => {
      composerCallbacks = { ...composerCallbacks, ...callbacks }
    },
    startTurn: runtimeController.startTurn,
    interruptTurn: runtimeController.interruptTurn,
    pauseTurn: runtimeController.pauseTurn,
    terminateTurn: runtimeController.terminateTurn,
    forceResetTurn: runtimeController.forceResetTurn,
    steerTurn: runtimeController.steerTurn,
    updateQueueInput: runtimeController.updateQueueInput,
    deleteQueueInput: runtimeController.deleteQueueInput,
    guideQueueInput: runtimeController.guideQueueInput,
    listCommands: runtimeController.listCommands,
    executeCommand: runtimeController.executeCommand,
    request,
    requestRpc,
    requestJson,
    close,
  }
}

interface RawSession {
  id: string
  title?: string
  status?: string
  created_at?: string
  updated_at?: string
  metadata?: Record<string, unknown>
}

function encodeRequestBody(body: BodyInit | null | undefined): Uint8Array | undefined {
  if (body == null) return undefined
  if (body instanceof Uint8Array) return body
  if (body instanceof ArrayBuffer) return new Uint8Array(body)
  if (typeof body === 'string') return new TextEncoder().encode(body)
  return new TextEncoder().encode(String(body))
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function isCoreSnapshot(value: unknown): value is CoreAppSnapshot {
  return isRecord(value)
    && typeof value.thread_id === 'string'
    && Number.isFinite(Number(value.snapshot_seq))
}

function isRawSession(value: unknown): value is RawSession {
  return isRecord(value) && typeof value.id === 'string'
}

function toSession(raw: RawSession): CoreSessionListItem {
  return {
    id: raw.id,
    title: raw.title || raw.id,
    status: raw.status,
    createdAt: raw.created_at || '',
    updatedAt: raw.updated_at,
    metadata: raw.metadata,
  }
}
