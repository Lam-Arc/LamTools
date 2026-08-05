<script setup lang="ts">
import {
  computed,
  onMounted,
  onUnmounted,
  reactive,
  ref,
  shallowRef,
  watch,
} from 'vue'
import {
  appServerUrl,
  buildCurrentTurnChecklistGroups,
  ChatThread,
  CoreAppServerClient,
  CoreArrangeManager,
  CoreGoalStrip,
  createCoreAppServerRuntimeController,
  createCoreAppServerRuntimeState,
  hydrateSnapshot,
  RuntimePanel,
  selectLatestActiveTurnId,
  selectLatestTurnStatus,
  SessionSidebar,
  useCoreApprovalController,
  useCoreGoals,
  useCoreWorkbenchProjectionController,
  WorkspaceShell,
  type CoreAppSnapshot,
  type CoreSessionListItem,
} from '@lamtools/ui'
import {
  createCoreSession,
  listCoreSessions,
} from '../api/core'

const showArrangeManager = ref(false)
const sessions = ref<CoreSessionListItem[]>([])
const activeSessionId = ref<string | null>(null)
const composerText = ref('')
const loadError = ref('')
const actionError = ref('')
const sessionLoading = ref(false)
const shallowThinkingPending = ref(false)
const runtime = reactive(createCoreAppServerRuntimeState<CoreAppSnapshot, CoreAppServerClient>())
const snapshot = computed(() => runtime.state)
const activeSession = computed(() => sessions.value.find(session => session.id === activeSessionId.value))
const latestStatus = computed(() => snapshot.value
  ? selectLatestTurnStatus(snapshot.value)
  : activeSession.value?.status || 'idle')
const latestStatusLabel = computed(() => researchStatusLabel(latestStatus.value))
const activeTurnId = computed(() => snapshot.value ? selectLatestActiveTurnId(snapshot.value) : '')
const turnActive = computed(() => ['running', 'waiting'].includes(latestStatus.value))
const composerActionMode = computed(() => turnActive.value ? 'stop' : 'send')
const composerDisabled = computed(() => (
  sessionLoading.value || !activeSessionId.value || !composerText.value.trim()
))

const runtimeController = createCoreAppServerRuntimeController(runtime, {
  hydrateSnapshot,
  onSessionUpdated: () => { void refreshSessions() },
  createClient: ({ apiBase, onEvent, onSnapshot, onConnectionState }) => new CoreAppServerClient({
    url: appServerUrl(apiBase, { path: '/api/core/app-server' }),
    clientInfo: { name: 'sage_frontend', title: 'Sage', version: '0.1.0' },
    onEvent,
    onSnapshot,
    onConnectionState: (state) => {
      onConnectionState(state)
      if (state === 'error') actionError.value = 'Sage 运行通道连接失败'
      if (state === 'open' && actionError.value === 'Sage 运行通道连接失败') actionError.value = ''
    },
  }),
})

const approvalControllerRef = shallowRef<ReturnType<typeof useCoreApprovalController>>()
const projectionController = useCoreWorkbenchProjectionController({
  snapshot,
  activeThreadId: activeSessionId,
  status: latestStatus,
  submittingApprovalRequestIds: computed(() => (
    approvalControllerRef.value?.submittingRequestIds.value ?? new Set<string>()
  )),
  shallowThinkingPending,
  source: 'sage_app_server',
  onStatusChange: ({ status }) => syncActiveSessionStatus(status),
})
const { messages, processExpandedIds, toggleProcess } = projectionController
const stepGroups = computed(() => buildCurrentTurnChecklistGroups(messages.value))

const { activeGoal, goalError, refreshGoal, handleCancelGoal } = useCoreGoals({ activeSessionId })

const approvalController = useCoreApprovalController({
  messages,
  hasActiveThread: computed(() => Boolean(activeSessionId.value)),
  canRespondApproval: computed(() => runtime.connectionState === 'open'),
  ensureApprovalChannel: () => ensureConnected(activeSessionId.value || ''),
  respondApproval: (requestId, decision, guidance) => (
    runtimeController.respondApproval(requestId, decision, guidance)
  ),
  submitText: async (text) => {
    composerText.value = text
    await sendMessage()
  },
  deferText: (text) => {
    composerText.value = text
  },
})
approvalControllerRef.value = approvalController

const projectGroups = computed(() => [{
  id: 'sage-research',
  name: '研究会话',
  sessions: sessions.value.map(session => ({
    id: session.id,
    title: session.title,
    status: session.status,
    createdAt: session.createdAt,
    updatedAt: session.updatedAt,
  })),
}])
const panelGroups = computed(() => [{
  id: 'research-policy',
  label: '研究状态',
  items: [
    { label: '会话', value: activeSession.value ? latestStatusLabel.value : '未选择' },
    { label: '验证', value: '默认交叉核验与反证搜索' },
    { label: '证据', value: '来源、定位、冲突与缺口' },
  ],
}])
const workbenchError = computed(() => (
  loadError.value
  || actionError.value
  || approvalController.lastError.value
  || runtime.lastError
  || goalError.value
))

async function loadInitialData() {
  sessionLoading.value = true
  loadError.value = ''
  try {
    sessions.value = await listCoreSessions()
    if (sessions.value[0]) await selectSession(sessions.value[0].id)
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : String(error)
  } finally {
    sessionLoading.value = false
  }
}

async function refreshSessions() {
  try {
    sessions.value = await listCoreSessions()
  } catch {
    // best-effort refresh; ignore transient errors
  }
}

async function newSession() {
  sessionLoading.value = true
  actionError.value = ''
  try {
    const session = await createCoreSession()
    sessions.value = [session, ...sessions.value.filter(item => item.id !== session.id)]
    await selectSession(session.id)
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : '新建研究会话失败'
  } finally {
    sessionLoading.value = false
  }
}

async function selectSession(id: string) {
  activeSessionId.value = id
  actionError.value = ''
  runtimeController.disconnect()
  try {
    await runtimeController.connect(window.location.origin, id)
    await refreshGoal(id)
  } catch (error) {
    if (activeSessionId.value !== id) return
    actionError.value = error instanceof Error ? error.message : '研究会话连接失败'
  }
}

async function ensureConnected(threadId: string): Promise<boolean> {
  if (!threadId) return false
  if (runtime.connectionState === 'open' && runtime.activeThreadId === threadId) return true
  await runtimeController.connect(window.location.origin, threadId)
  return runtime.connectionState === 'open'
}

async function sendMessage() {
  const threadId = activeSessionId.value
  const text = composerText.value.trim()
  if (!threadId || !text || turnActive.value) return
  actionError.value = ''
  composerText.value = ''
  try {
    if (!await ensureConnected(threadId)) throw new Error('Sage 运行通道不可用')
    await runtimeController.startTurn(threadId, text, undefined, {
      approval_policy: 'require',
      metadata: { member_id: 'sage', source: 'sage_frontend' },
    })
  } catch (error) {
    if (activeSessionId.value === threadId && !composerText.value) composerText.value = text
    actionError.value = error instanceof Error ? error.message : '发送研究任务失败'
  }
}

async function handleComposerSubmit() {
  actionError.value = ''
  if (turnActive.value) {
    try {
      await runtimeController.interruptTurn(activeSessionId.value || '', activeTurnId.value || undefined)
    } catch (error) {
      actionError.value = error instanceof Error ? error.message : '停止任务失败'
    }
    return
  }
  await sendMessage()
}

function syncActiveSessionStatus(status: string) {
  const id = activeSessionId.value
  if (!id) return
  sessions.value = sessions.value.map(session => session.id === id
    ? { ...session, status, updatedAt: new Date().toISOString() }
    : session)
}

function researchStatusLabel(status: string): string {
  return ({
    idle: '空闲',
    active: '空闲',
    running: '运行中',
    waiting: '等待处理',
    pending: '等待开始',
    completed: '已完成',
    done: '已完成',
    failed: '失败',
    error: '失败',
    cancelled: '已取消',
    interrupted: '已停止',
  } as Record<string, string>)[status.toLowerCase()] || status
}

watch([activeSessionId, latestStatus], ([threadId]) => {
  void refreshGoal(threadId)
})
onMounted(loadInitialData)
onUnmounted(runtimeController.disconnect)
</script>

<template>
  <WorkspaceShell
    product-name="Sage"
    sidebar-title="研究"
    storage-key="lamsage.ui"
    density="standard"
    right-panel-title="证据与运行状态"
    composer-placeholder="提出要搜集、核验或持续关注的问题…"
    :composer-action-mode="composerActionMode"
    :composer-disabled="composerDisabled"
    :error-text="workbenchError"
    @new-session="newSession"
    @settings="showGoalManager = true"
    @composer-submit="handleComposerSubmit"
  >
    <template #sidebar-body>
      <SessionSidebar
        :project-groups="projectGroups"
        :active-session-id="activeSessionId ?? undefined"
        :allow-project-new-session="false"
        pin-storage-key="lamsage.sidebar.pinned"
        @select-session="selectSession"
      >
        <template #empty>
          <div class="sage-sidebar-empty">还没有研究会话。点击左上角 + 开始。</div>
        </template>
      </SessionSidebar>
    </template>

    <template #sidebar-footer>
      <button class="sidebar-action" type="button" @click="showArrangeManager = true">
        <span aria-hidden="true">&#x25F7;</span><span>长期安排</span>
      </button>
    </template>

    <template #main-header>
      <div v-if="activeSession" class="thread-header">
        <strong>{{ activeSession.title }}</strong>
        <span>{{ latestStatusLabel }}</span>
      </div>
    </template>

    <template #main-content>
      <section class="thread" aria-label="研究对话" :aria-busy="turnActive">
        <p class="sr-only" role="status" aria-live="polite" aria-atomic="true">运行状态：{{ latestStatusLabel }}</p>
        <div v-if="!activeSessionId" class="sage-empty-state">
          <div class="sage-mark" aria-hidden="true">S</div>
          <div>
            <h1>从一个可核验的问题开始</h1>
            <p>Sage 会搜集来源、处理数据、寻找冲突，并明确哪些结论仍不确定。</p>
            <ul>
              <li>核实一条新闻或数据，并寻找独立来源</li>
              <li>比较多个对象，统一时间、单位与统计口径</li>
              <li>建立长期关注，让 Goal 与 Arrange 持续执行</li>
            </ul>
            <button type="button" @click="newSession">新建研究会话</button>
          </div>
        </div>
        <ChatThread
          v-else
          :messages="messages"
          assistant-label="Sage"
          :process-expanded-ids="processExpandedIds"
          @toggle-process="toggleProcess"
          @decision-select="approvalController.handleDecision"
        />
      </section>
    </template>

    <template #composer-preamble>
      <CoreGoalStrip v-if="activeGoal" :goal="activeGoal" @cancel="handleCancelGoal" />
    </template>

    <template #composer-textarea>
      <textarea
        v-model="composerText"
        rows="1"
        :disabled="sessionLoading || !activeSessionId || turnActive"
        :placeholder="activeSessionId ? '提出要搜集、核验或持续关注的问题…' : '先新建或选择研究会话'"
        @keydown.enter.exact.prevent="handleComposerSubmit"
      ></textarea>
    </template>

    <template #composer-tools>
      <span class="composer-policy">默认保留证据并主动查找反证</span>
    </template>

    <template #right-panel>
      <RuntimePanel
        :panel-groups="panelGroups"
        :step-groups="stepGroups"
      />
    </template>

    <template #modals>
      <div v-if="showArrangeManager" class="modal-overlay" @click.self="showArrangeManager = false">
        <div class="modal-card wide">
          <CoreArrangeManager
            @back="showArrangeManager = false"
          />
        </div>
      </div>
    </template>
  </WorkspaceShell>
</template>

<style scoped>
.thread { height: 100%; overflow-y: auto; }
.thread-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; min-height: 48px; padding: 0 24px; border-bottom: 1px solid var(--line); color: var(--text); }
.thread-header strong { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.thread-header span, .composer-policy { color: var(--muted); font-size: 12px; }
.sage-empty-state { display: flex; align-items: flex-start; gap: 22px; width: min(680px, calc(100% - 40px)); margin: clamp(72px, 16vh, 160px) auto 180px; color: var(--text); }
.sage-mark { display: grid; flex: none; width: 42px; height: 42px; place-items: center; border: 1px solid var(--blue); border-radius: 12px; color: var(--blue); font-weight: 750; }
.sage-empty-state h1 { margin: 0 0 10px; font-size: 26px; letter-spacing: -.025em; text-wrap: balance; }
.sage-empty-state p { max-width: 62ch; margin: 0; color: var(--muted); line-height: 1.65; text-wrap: pretty; }
.sage-empty-state ul { margin: 20px 0; padding-left: 20px; color: var(--muted); line-height: 1.85; }
.sage-empty-state button { border: 0; border-radius: 8px; font: inherit; cursor: pointer; padding: 9px 14px; background: var(--blue); color: var(--bg); font-weight: 650; }
.sage-empty-state button:hover { filter: brightness(1.08); }
.sage-empty-state button:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
.sage-sidebar-empty { padding: 18px 12px; color: var(--muted); font-size: 13px; line-height: 1.55; text-align: center; }
textarea { width: 100%; min-height: 24px; max-height: 180px; resize: none; border: 0; outline: 0; background: transparent; color: var(--text); font: inherit; line-height: 1.55; }
textarea::placeholder { color: var(--muted); opacity: 1; }
textarea:disabled { cursor: not-allowed; opacity: .65; }
@media (max-width: 700px) {
  .sage-empty-state { align-items: stretch; flex-direction: column; margin-top: 52px; }
  .sage-empty-state button { min-height: 44px; }
  .thread-header { padding-inline: 16px; }
}
</style>
