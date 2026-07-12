<script setup lang="ts">
/**
 * CoreWorkbenchView — LamWriter powered by @lamtools/ui WorkspaceShell
 *
 * Uses the real project store + session store for project→session grouping.
 * Project-level actions (new session, delete, AGENTS.md) wired through sidebar.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  WorkspaceShell,
  SessionSidebar,
  ChatThread,
  AttachmentTray,
  CommandPalette,
  CoreAgentsEditor,
  CoreExecutionControls,
  CoreProjectCreate,
  CoreQueuedInputTray,
  buildCoreComposerHighlightSegments,
  coreInputToText,
  isCoreGuidableTurnStatus,
  normalizeCoreSessionStatus,
  selectCoreQueuedInputs,
  selectLatestActiveTurnId,
  updateCoreSessionListStatus,
  useCoreAutoFollowScroll,
  useCoreApprovalController,
  useCoreExecutionControlsState,
  useCoreLiveComposerController,
  useCoreWorkbenchProjectionController,
  useCoreQueuedInputController,
  useCoreWorkbenchController,
  usePendingAttachments,
  buildCoreProjectGroups,
  type CoreAttachment,
  type CoreInputItem,
  type CoreMessage,
  type CoreQueuedInput,
  type CoreWorkbenchApi,
  type CoreSessionListItem,
} from '@lamtools/ui'
import { useWorkspaceStore } from '@/stores/workspace'
import { useConfigStore } from '@/stores/config'
import { useWriterAppServerStore } from '@/appServer/store'
import { selectLatestTurnStatus } from '@/appServer/selectors'
import { workbenchSessionRouteQuery, type WorkbenchRouteQuery } from '@/utils/workbenchRoute'
import { pickProjectDirectory } from '@/lib/project-directory-picker'
import { createWriterProjectWorkspace } from '@/lib/project-workspace'
import {
  createWriterProjectAgentsSaveHandler,
  shouldApplyWriterProjectAgents,
  type WriterProjectAgents,
} from '@/lib/project-agents-editor'
import {
  listCoreSessions,
  createCoreSession,
  listCoreProviders,
} from '@/api/core'
import * as api from '@/api'
import { removeSessionsByIds } from '@/lib/session-list'
import type { Project, Session, Model, SessionChanges, SessionCheckpoint, CommitReview, AgentBranch } from '@/types'

const router = useRouter()
const requestedSessionIdFromUrl = new URLSearchParams(window.location.search).get('session')
const workspaceStore = useWorkspaceStore()
const projectStore = workspaceStore
const sessionStore = workspaceStore
const configStore = useConfigStore()
const appServerStore = useWriterAppServerStore()
const runtimeStatusText = ref('')
const composerErrorText = ref('')

// --- Execution model selection ---
const defaultModel = computed(() => {
  const resolvedId = configStore.resolvedConfig?.model?.id
  if (resolvedId) {
    const resolved = configStore.models.find((model) => model.id === resolvedId)
    if (resolved) return resolved
  }
  return configStore.models[0] || null
})

const {
  activeModel: activeExecutionModel,
  modelOptions,
  selectedModelId,
  selectedThinkingMode,
  selectModel,
  selectThinkingMode,
  shallowThinkingEnabled,
  thinkingModeOptions,
  turnOptions: currentThinkingOptions,
} = useCoreExecutionControlsState({
  models: computed(() => configStore.models),
  providers: computed(() => configStore.providers),
  defaultModel,
  storage: window.localStorage,
  storageKeys: {
    thinkingMode: 'lamwriter.composer.thinkingMode',
    shallowThinking: 'lamwriter.composer.shallowThinking',
  },
  labels: {
    currentModelPrefix: '当前：',
    thinking: {
      none: '无思考',
      low: '低思考',
      medium: '中思考',
      high: '高思考',
      max: 'Max 思考',
    },
  },
  onModelSelected: async (model) => {
    try {
      const setting = await configStore.fetchAppSetting('lamwriter.modelRouting')
      const existingRoutes = setting.value?.routes
      const routes = existingRoutes && typeof existingRoutes === 'object'
        ? { ...(existingRoutes as Record<string, unknown>) }
        : {}
      routes.writer = { mode: 'model', model_id: model.id }
      await configStore.saveAppSetting('lamwriter.modelRouting', { routes })
      await Promise.all([
        configStore.fetchResolvedConfig('writer'),
        configStore.fetchModels(),
      ])
    } catch (err) {
      console.error('Failed to set execution model:', err)
      runtimeStatusText.value = '执行模型更新失败'
    }
  },
})

// --- Core controller ---
const coreApi: CoreWorkbenchApi = {
  listSessions: listCoreSessions,
  createSession: createCoreSession,
  listProviders: listCoreProviders,
}

const {
  sessions,
  activeSessionId,
  composerText,
  loading,
  selectSession,
  newSession,
  loadInitialData,
} = useCoreWorkbenchController({ api: coreApi, initialSessionId: requestedSessionIdFromUrl })

const queuedInputs = computed<CoreQueuedInput[]>(() => appServerQueuedInputs())
const editingActiveSessionTitle = ref(false)
const activeSessionTitleDraft = ref('')
const composerTextareaEl = ref<HTMLTextAreaElement | null>(null)
const composerCursor = ref(0)
const attachmentFileInput = ref<HTMLInputElement | null>(null)
const threadScrollEl = ref<HTMLElement | null>(null)
const threadScroll = useCoreAutoFollowScroll(threadScrollEl)
let threadResizeObserver: ResizeObserver | null = null
const COMPOSER_MAX_ROWS = 5
const isAppServerActive = computed(() => (
  activeSessionId.value !== null
  && appServerStore.activeThreadId === activeSessionId.value
  && appServerStore.connectionState === 'open'
))
const {
  pendingAttachments,
  hasBlockingFailure,
  attachmentInputItems,
  addUploaded,
  markFailed,
  removeAttachment,
  clearAttachments,
} = usePendingAttachments()

function resizeComposerTextarea() {
  const el = composerTextareaEl.value
  if (!el) return
  el.style.height = 'auto'
  const style = window.getComputedStyle(el)
  const lineHeight = Number.parseFloat(style.lineHeight) || 22
  const paddingTop = Number.parseFloat(style.paddingTop) || 0
  const paddingBottom = Number.parseFloat(style.paddingBottom) || 0
  const maxHeight = lineHeight * COMPOSER_MAX_ROWS + paddingTop + paddingBottom
  const nextHeight = Math.min(el.scrollHeight, maxHeight)
  el.style.height = `${nextHeight}px`
  el.style.overflowY = el.scrollHeight > maxHeight ? 'auto' : 'hidden'
}

function updateComposerCursor() {
  composerCursor.value = composerTextareaEl.value?.selectionStart ?? composerText.value.length
}

function setComposerError(message: string) {
  composerErrorText.value = message
  runtimeStatusText.value = message
}

function clearComposerError() {
  composerErrorText.value = ''
}

function handleComposerInput() {
  clearComposerError()
  resizeComposerTextarea()
  updateComposerCursor()
}

watch(composerText, () => {
  void nextTick(resizeComposerTextarea)
})

const activeSessionStatus = computed(() => {
  if (isAppServerActive.value && appServerStore.state) {
    return selectLatestTurnStatus(appServerStore.state)
  }
  if (appServerStore.connectionState === 'error') return 'failed'
  const active = sessions.value.find(session => session.id === activeSessionId.value)
  return normalizeCoreSessionStatus(active?.status || 'idle')
})

const liveComposerController = useCoreLiveComposerController({
  activeThreadId: activeSessionId,
  connectedThreadId: computed(() => appServerStore.activeThreadId),
  connectionState: computed(() => appServerStore.connectionState),
  text: composerText,
  cursor: composerCursor,
  status: activeSessionStatus,
  attachments: attachmentInputItems,
  connect: (threadId) => appServerStore.connect(api.API_BASE, threadId),
  startTurn: (threadId, input, workRoot, options) => appServerStore.startTurn(threadId, input, workRoot, options),
  interruptTurn: (threadId) => appServerStore.interruptTurn(threadId),
  queueInput: (threadId, input) => appServerStore.queueInput(threadId, input),
  listCommands: (workRoot) => appServerStore.listCommands(workRoot),
  getWorkRoot: currentSessionWorkRoot,
  executeCommand: executeWriterCommand,
  canExecuteCommand: () => !composerIsRunning.value,
  commandUnavailableMessage: '当前正在运行，请等本轮结束后再执行命令',
  turnOptions: currentThinkingOptions,
  clearComposer: clearComposerAfterPersisted,
  clearAttachments,
  focusComposer: (cursor) => {
    void nextTick(() => {
      composerTextareaEl.value?.focus()
      composerTextareaEl.value?.setSelectionRange(cursor, cursor)
      resizeComposerTextarea()
    })
  },
  setStatusText: (text) => {
    runtimeStatusText.value = text
  },
  onError: setComposerError,
  onTurnStarted: async () => {
    sessions.value = await listCoreSessions()
  },
  onTurnStartedError: (error) => console.error('Failed to refresh Writer sessions after turn start:', error),
  messages: {
    commandCatalogLoadFailed: (error) => `命令列表加载失败：${error}`,
    noActiveThread: '请先选择会话',
    queued: '已加入待发送',
    sent: '已发送',
    stopping: '正在停止',
    stopFailed: '停止失败',
    sendFailed: '发送失败',
  },
})
const {
  actionMode: composerActionMode,
  commandCatalog,
  commandError,
  commandPalette,
  paletteVisible: commandPaletteVisible,
} = liveComposerController
const composerHighlightSegments = computed(() => buildCoreComposerHighlightSegments(composerText.value, commandCatalog.value))
const hasComposerCommandTokens = computed(() => composerHighlightSegments.value.some(segment => segment.command))

const approvalControllerRef = shallowRef<ReturnType<typeof useCoreApprovalController>>()
const projectionController = useCoreWorkbenchProjectionController({
  snapshot: computed(() => appServerStore.state),
  activeThreadId: activeSessionId,
  status: activeSessionStatus,
  submittingApprovalRequestIds: computed(() => (
    approvalControllerRef.value?.submittingRequestIds.value ?? new Set<string>()
  )),
  shallowThinkingPending: shallowThinkingEnabled,
  source: 'writer_app_server',
  systemMessages: computed(buildSystemMessages),
  onStatusChange: ({ status }) => syncActiveSessionListStatus(status),
  onTurnFinished: () => {
    void loadReviewChanges()
  },
})
const {
  messages,
  processExpandedIds,
  toggleProcess,
} = projectionController

const approvalController = useCoreApprovalController({
  messages,
  hasActiveThread: computed(() => Boolean(activeSessionId.value)),
  canRespondApproval: isAppServerActive,
  ensureApprovalChannel: () => liveComposerController.ensureConnected(activeSessionId.value || ''),
  respondApproval: (requestId, decision, guidance) => appServerStore.respondApproval(requestId, decision, guidance),
  submitText: submitWriterText,
  deferText: (text) => {
    composerText.value = text
  },
})
approvalControllerRef.value = approvalController

const activeSession = computed(() => (
  sessions.value.find(session => session.id === activeSessionId.value) || null
))

const activeSessionTitle = computed(() => (
  activeSession.value?.title || 'Session'
))

watch([activeSessionId, activeSessionTitle], () => {
  if (!editingActiveSessionTitle.value) {
    activeSessionTitleDraft.value = activeSessionTitle.value
  }
}, { immediate: true })

const composerIsRunning = computed(() =>
  activeSessionStatus.value === 'running' || activeSessionStatus.value === 'waiting',
)
const activeSteerTurnId = computed(() => {
  if (!isCoreGuidableTurnStatus(activeSessionStatus.value) || !appServerStore.state) return ''
  return selectLatestActiveTurnId(appServerStore.state)
})
const queueController = useCoreQueuedInputController({
  activeTurnId: activeSteerTurnId,
  ensureConnected: async (threadId) => {
    if (!await liveComposerController.ensureConnected(threadId)) {
      throw new Error(liveComposerController.lastError.value)
    }
  },
  updateQueueInput: (threadId, itemId, text) => appServerStore.updateQueueInput(threadId, itemId, text),
  deleteQueueInput: (threadId, itemId) => appServerStore.deleteQueueInput(threadId, itemId),
  guideQueueInput: (threadId, turnId, itemId, text) => appServerStore.guideQueueInput(threadId, turnId, itemId, text),
  onError: (error) => console.error('Failed to operate queued input:', error),
})
const editingQueuedInputId = queueController.editingId
const queuedInputDraft = queueController.draft
const canGuideQueuedInput = queueController.canGuide

interface DecisionSelectPayload {
  partId: string
  option: {
    id: string
    label: string
    description?: string
    response?: string
  }
  response: string
}
const reviewChanges = ref<SessionChanges | null>(null)
const reviewLoading = ref(false)
const reviewError = ref('')
const reviewExpandedFiles = ref<Set<string>>(new Set())
const reviewAllFilesVisible = ref(false)
const reviewAllDiffsVisible = ref(false)
const checkpoints = ref<SessionCheckpoint[]>([])
const checkpointLoading = ref(false)
const checkpointError = ref('')
const agentBranches = ref<AgentBranch[]>([])
const agentBranchLoading = ref(false)
const agentBranchError = ref('')
const selectedAgentBranch = ref('')
const selectedAgentBranchDiff = ref('')
const commitReview = ref<CommitReview | null>(null)
const commitReviewLoading = ref(false)
const commitReviewError = ref('')
const commitReviewFeedback = ref('')
const commitMessageDraft = ref('')
const commitFeedbackOpen = ref(false)
const REVIEW_PREVIEW_LIMIT = 3

interface RunningAgentItem {
  id: string
  name: string
  status: string
  task: string
  model: string
  tools: string[]
  branch: string
  worktree: string
  at: string
}

function syncActiveSessionListStatus(status = activeSessionStatus.value) {
  const sessionId = activeSessionId.value
  if (!sessionId) return
  const nextStatus = normalizeCoreSessionStatus(status)
  const now = new Date().toISOString()
  sessions.value = updateCoreSessionListStatus(sessions.value, sessionId, nextStatus, now)
  const storeIndex = sessionStore.sessions.findIndex(item => item.id === sessionId)
  if (storeIndex >= 0 && sessionStore.sessions[storeIndex].status !== nextStatus) {
    sessionStore.sessions[storeIndex] = {
      ...sessionStore.sessions[storeIndex],
      status: nextStatus,
      updated_at: now,
    }
  }
}

function appServerQueuedInputs(): CoreQueuedInput[] {
  if (!appServerStore.state) return []
  if (!activeSessionId.value || appServerStore.state.thread_id !== activeSessionId.value) return []
  return selectCoreQueuedInputs(appServerStore.state)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}

function syncThreadResizeObserver() {
  if (typeof ResizeObserver === 'undefined') return
  threadResizeObserver?.disconnect()
  threadResizeObserver = new ResizeObserver(() => {
    void threadScroll.scrollToBottom()
  })
  const el = threadScrollEl.value
  if (!el) return
  threadResizeObserver.observe(el)
  for (const child of Array.from(el.children)) {
    if (child instanceof HTMLElement) threadResizeObserver.observe(child)
  }
}

async function refreshThreadResizeObserver() {
  await nextTick()
  syncThreadResizeObserver()
}

const latestUserMessageId = computed(() => {
  for (let index = messages.value.length - 1; index >= 0; index--) {
    const message = messages.value[index]
    if (message.role === 'user') return message.id
  }
  return ''
})

watch(
  messages,
  () => {
    void refreshThreadResizeObserver()
    void threadScroll.scrollToBottom()
  },
  { flush: 'post' },
)

watch(
  latestUserMessageId,
  (newId, oldId) => {
    if (!newId || oldId === undefined || newId === oldId) return
    threadScroll.autoFollow.value = true
    void threadScroll.scrollToBottom(true, 'smooth')
  },
  { flush: 'post' },
)

onMounted(() => {
  void refreshThreadResizeObserver()
  void threadScroll.scrollToBottom(true)
})

onBeforeUnmount(() => {
  threadResizeObserver?.disconnect()
  threadResizeObserver = null
})

function buildSystemMessages(): CoreMessage[] {
  return []
}

const projectGroups = computed(() => buildCoreProjectGroups(
  projectStore.projects.map((project) => ({
    id: project.id,
    name: project.name,
    workRoot: project.work_root,
    createdAt: project.created_at,
    updatedAt: project.updated_at,
  })),
  sessions.value,
))

// --- Actions ---
async function handleNewSession(projectGroupId: string) {
  const group = projectGroups.value.find((g) => g.id === projectGroupId)
  if (!group?.canManage) return
  const project = projectStore.projects.find((item) => item.id === projectGroupId)
  if (!project) return

  try {
    const session = await projectStore.createProjectSession(project.id)
    upsertCreatedProjectSession(project, session)
    await selectSession(session.id)
  } catch (err) {
    console.error('Failed to create session:', err)
  }
}

async function handleRenameSession(sessionId: string, title: string) {
  const cleaned = title.trim()
  if (!cleaned) return
  try {
    const updated = await sessionStore.updateSession(sessionId, { title: cleaned })
    sessions.value = sessions.value.map((session) =>
      session.id === sessionId
        ? {
            ...session,
            title: updated.title || cleaned,
            updatedAt: updated.updated_at || session.updatedAt,
          }
        : session,
    )
  } catch (err) {
    console.error('Failed to rename session:', err)
    runtimeStatusText.value = '重命名失败'
  }
}

function handleActiveSessionTitleFocus() {
  if (!activeSessionId.value) return
  editingActiveSessionTitle.value = true
}

function handleActiveSessionTitleInput(event: Event) {
  editingActiveSessionTitle.value = true
  activeSessionTitleDraft.value = (event.target as HTMLInputElement).value
}

function cancelActiveSessionTitleEdit() {
  editingActiveSessionTitle.value = false
  activeSessionTitleDraft.value = activeSessionTitle.value
}

async function submitActiveSessionTitle() {
  if (!activeSessionId.value) return
  const sessionId = activeSessionId.value
  const title = activeSessionTitleDraft.value.trim()
  if (!title || title === activeSessionTitle.value) {
    cancelActiveSessionTitleEdit()
    return
  }
  editingActiveSessionTitle.value = false
  await handleRenameSession(sessionId, title)
}

async function handleDeleteSession(sessionId: string) {
  const session = sessions.value.find((item) => item.id === sessionId)
  const label = session?.title || `Session ${sessionId.slice(0, 8)}`
  const confirmed = window.confirm(`确定删除对话「${label}」？此操作不可撤销。`)
  if (!confirmed) return
  try {
    await sessionStore.deleteSession(sessionId)
    const deleted = new Set([sessionId])
    sessions.value = removeSessionsByIds(sessions.value, deleted)
    if (activeSessionId.value === sessionId) {
      appServerStore.disconnect()
      const nextSession = sessions.value[0]
      if (nextSession) {
        await selectSession(nextSession.id)
      } else {
        sessionStore.selectSession(null)
        await syncSessionUrl(null)
      }
    }
  } catch (err) {
    console.error('Failed to delete session:', err)
    runtimeStatusText.value = '删除对话失败'
  }
}

async function ensureActiveSession(title: string): Promise<string | null> {
  if (activeSessionId.value) return activeSessionId.value
  // No session selected and no projects exist — user must create a project first
  return null
}

async function uploadFiles(files: FileList | File[]) {
  const items = Array.from(files)
  if (items.length === 0) return
  clearComposerError()
  const sessionId = await ensureActiveSession('附件消息')
  if (!sessionId) {
    setComposerError('请先新建项目并选择一个会话')
    return
  }
  for (const file of items) {
    const failedId = `failed:${file.name}:${Date.now()}`
    try {
      const uploaded = await api.uploadAttachment(sessionId, file)
      addUploaded(uploaded as CoreAttachment)
    } catch (err) {
      markFailed(failedId, file.name, err instanceof Error ? err.message : '上传失败')
      setComposerError(`附件上传失败：${file.name}`)
      return
    }
  }
}

function handleAttachmentInputChange(event: Event) {
  const input = event.target as HTMLInputElement
  const files = input.files
  if (files && files.length > 0) {
    void uploadFiles(files)
  }
  input.value = ''
}

function handleComposerDrop(event: DragEvent) {
  const files = event.dataTransfer?.files
  if (files && files.length > 0) {
    void uploadFiles(files)
  }
}

function retryPendingAttachment(id: string) {
  removeAttachment(id)
  runtimeStatusText.value = '请重新选择该附件'
  attachmentFileInput.value?.click()
}

async function previewPendingAttachment(id: string) {
  if (id.startsWith('failed:')) return
  try {
    await api.previewAttachment(id)
    runtimeStatusText.value = '附件预览已读取'
  } catch (err) {
    runtimeStatusText.value = err instanceof Error ? err.message : '预览失败'
  }
}

async function openPendingAttachment(id: string) {
  if (id.startsWith('failed:')) return
  try {
    await api.openAttachment(id)
  } catch (err) {
    runtimeStatusText.value = err instanceof Error ? err.message : '打开附件失败'
  }
}

function modelAllowsPendingImages(): boolean {
  const hasImage = pendingAttachments.value.some(item =>
    item.preview_type === 'image' || item.mime_type.toLowerCase().startsWith('image/'),
  )
  if (!hasImage) return true
  const modalities = activeExecutionModel.value?.extra?.input_modalities
  if (!Array.isArray(modalities)) return true
  return modalities.map(item => String(item).toLowerCase()).includes('image')
}

async function sendWriterTask() {
  const text = composerText.value.trim()
  await submitWriterText(text, { clearComposer: true, attachments: attachmentInputItems.value })
}

async function executeWriterCommand(threadId: string, command: string, workRoot?: string): Promise<boolean> {
  clearComposerError()
  try {
    const result = await appServerStore.executeCommand(threadId, command, workRoot)
    if (command === 'fork') {
      const session = result.session as Session | undefined
      if (session?.id) {
        upsertForkedSession(session)
        await selectSession(session.id)
      }
    }
    if (command !== 'compact') runtimeStatusText.value = '命令已执行'
    return true
  } catch (err) {
    console.warn('Failed to execute composer command:', err)
    setComposerError(err instanceof Error ? err.message : String(err))
    return false
  }
}

async function handleComposerKeydown(event: KeyboardEvent) {
  updateComposerCursor()
  await liveComposerController.handleKeydown(event)
}

async function handleComposerKeyup(event: KeyboardEvent) {
  updateComposerCursor()
  await liveComposerController.handleKeyup(event)
}

function clearComposerAfterPersisted(expectedText: string) {
  if (composerText.value.trim() === expectedText) {
    composerText.value = ''
    void nextTick(resizeComposerTextarea)
  }
}

function coreSessionWorkRoot(s: CoreSessionListItem): string {
  const raw = s.metadata?.work_root
  return typeof raw === 'string' ? raw : ''
}

async function submitWriterText(
  text: string,
  options: { clearComposer?: boolean; attachments?: CoreInputItem[] } = {},
) {
  const cleaned = text.trim()
  const attachments = options.attachments || attachmentInputItems.value
  if (!cleaned && attachments.length === 0) {
    await liveComposerController.submit({ clearComposer: options.clearComposer })
    return
  }
  clearComposerError()

  if (!await ensureActiveSession(cleaned.slice(0, 48))) {
    setComposerError('请先新建项目并选择一个会话')
    composerText.value = cleaned
    return
  }

  if (hasBlockingFailure.value) {
    setComposerError('附件上传失败，请重试或移除失败附件后再发送')
    composerText.value = cleaned
    return
  }
  if (attachments.length > 0 && !modelAllowsPendingImages()) {
    setComposerError('当前模型明确不支持图片输入，请切换支持图片的模型后再发送')
    composerText.value = cleaned
    return
  }
  if (composerIsRunning.value && attachments.length > 0) {
    setComposerError('当前正在运行，带附件的消息请等本轮结束后再发送')
    composerText.value = cleaned
    return
  }

  await liveComposerController.submit({ clearComposer: options.clearComposer })
}

async function handleDecisionSelect(payload: DecisionSelectPayload) {
  const pending = approvalController.handleDecision(payload)
  const result = await pending
  if (result === 'failed') {
    console.error('Failed to respond approval:', approvalController.lastError.value)
    runtimeStatusText.value = '授权处理失败'
  }
}

function currentSessionWorkRoot(): string {
  const active = sessions.value.find(session => session.id === activeSessionId.value)
  return active ? coreSessionWorkRoot(active) : ''
}

async function handleDeleteProject(projectGroupId: string) {
  const group = projectGroups.value.find((item) => item.id === projectGroupId)
  if (!group?.canManage) return
  const project = projectStore.projects.find((item) => item.id === projectGroupId)
  if (!project) return
  const confirmed = window.confirm(`确定删除项目「${project.name || project.work_root}」？此操作不可撤销。`)
  if (!confirmed) return
  try {
    const deletedSessionIds = new Set((group?.sessions || []).map((session) => session.id))
    await projectStore.deleteProject(project.id)
    sessions.value = removeSessionsByIds(sessions.value, deletedSessionIds)
    sessionStore.removeSessions(deletedSessionIds)
    if (activeSessionId.value && deletedSessionIds.has(activeSessionId.value)) {
      appServerStore.disconnect()
      const nextSession = sessions.value[0]
      if (nextSession) {
        await selectSession(nextSession.id)
      } else {
        await loadInitialData()
      }
    }
  } catch (err) {
    console.error('Failed to delete project:', err)
  }
}

async function handleProjectContextMenu(projectGroupId: string) {
  const group = projectGroups.value.find((item) => item.id === projectGroupId)
  if (!group?.canManage) return
  const targetProjectId = group.id
  agentsMdProjectId.value = targetProjectId
  agentsContent.value = ''
  const requestToken = ++agentsRequestToken.value
  agentsReadyToken.value = 0
  agentsSaveHandler.value = createWriterProjectAgentsSaveHandler(
    targetProjectId,
    (projectId, content) => saveAgentsMdForProject(projectId, requestToken, content),
  )
  agentsError.value = ''
  agentsLoading.value = true
  showAgentsMd.value = true
  try {
    const agents = await projectStore.fetchAgents(targetProjectId)
    if (shouldApplyWriterProjectAgents(targetProjectId, requestToken, agentsMdProjectId.value, agentsRequestToken.value)) {
      agentsContent.value = agents.content
      agentsReadyToken.value = requestToken
    }
  } catch (err) {
    console.error('Failed to load AGENTS.md:', err)
    if (shouldApplyWriterProjectAgents(targetProjectId, requestToken, agentsMdProjectId.value, agentsRequestToken.value)) {
      agentsError.value = '读取 AGENTS.md 失败'
    }
  } finally {
    if (shouldApplyWriterProjectAgents(targetProjectId, requestToken, agentsMdProjectId.value, agentsRequestToken.value)) {
      agentsLoading.value = false
    }
  }
}

const showAgentsMd = ref(false)
const agentsMdProjectId = ref('')
const agentsContent = ref('')
const agentsRequestToken = ref(0)
const agentsReadyToken = ref(0)
const agentsLoading = ref(false)
const agentsError = ref('')
const agentsSaveHandler = ref<(content: string) => Promise<WriterProjectAgents>>(async () => ({ content: '', exists: false }))

interface DiffFileBlock {
  path: string
  lines: string[]
}

interface DiffMetaItem {
  label: string
  value: string
}

const reviewDiffFiles = computed<DiffFileBlock[]>(() => parseDiffFiles(reviewChanges.value?.diff || ''))
const visibleReviewFiles = computed(() => {
  const files = reviewChanges.value?.files || []
  return reviewAllFilesVisible.value ? files : files.slice(0, REVIEW_PREVIEW_LIMIT)
})
const hiddenReviewFileCount = computed(() => Math.max(0, (reviewChanges.value?.files.length || 0) - REVIEW_PREVIEW_LIMIT))
const visibleReviewDiffFiles = computed(() => (
  reviewAllDiffsVisible.value ? reviewDiffFiles.value : reviewDiffFiles.value.slice(0, REVIEW_PREVIEW_LIMIT)
))
const hiddenReviewDiffCount = computed(() => Math.max(0, reviewDiffFiles.value.length - REVIEW_PREVIEW_LIMIT))
const reviewHasChanges = computed(() => {
  const changes = reviewChanges.value
  if (!changes) return false
  return changes.files.length > 0 || Boolean(changes.diff.trim())
})
const activeCommitReview = computed(() => {
  const review = commitReview.value
  if (!review || review.status === 'none') return null
  return review
})
const commitReviewPending = computed(() => {
  const status = activeCommitReview.value?.status || ''
  return status === 'pending' || status === 'changes_requested' || status === 'postponed'
})
const commitReviewFilesText = computed(() => {
  const review = activeCommitReview.value
  if (!review) return ''
  const fileCount = review.files.length
  const additions = review.total_additions
  const deletions = review.total_deletions
  return `${fileCount} 个文件 · +${additions} / -${deletions}`
})
const latestCheckpoints = computed(() => checkpoints.value.slice(0, 3))

const runningAgentItems = computed<RunningAgentItem[]>(() => {
  const byRun = new Map<string, RunningAgentItem>()
  const items = appServerStore.state?.items || {}
  for (const item of Object.values(items)) {
    const meta = isRecord(item.metadata) ? item.metadata : {}
    if (String(meta.group || '') !== 'agent' && item.type !== 'agent') continue
    const runId = String(meta.run_id || item.item_id)
    const name = String(meta.agent || item.label || item.tool_name || 'Agent')
    const rawTools = Array.isArray(meta.tools) ? meta.tools : []
    byRun.set(runId, {
      id: runId,
      name,
      status: String(meta.status || item.status || ''),
      task: String(meta.task || item.detail || item.content || ''),
      model: String(meta.model || ''),
      tools: rawTools.map((tool) => String(tool)).filter(Boolean),
      branch: String(meta.branch || ''),
      worktree: String(meta.worktree || ''),
      at: String(item.last_seq || item.seq || ''),
    })
  }
  return [...byRun.values()]
    .sort((a, b) => Date.parse(b.at) - Date.parse(a.at))
    .slice(0, 6)
})
const visibleAgentBranches = computed(() => {
  const known = new Map<string, AgentBranch>()
  for (const branch of agentBranches.value) known.set(branch.branch, branch)
  for (const run of runningAgentItems.value) {
    if (!run.branch || known.has(run.branch)) continue
    known.set(run.branch, {
      branch: run.branch,
      head: null,
      worktree: run.worktree,
      dirty: false,
      files: [],
    })
  }
  return [...known.values()]
})
const latestRuntimeMetrics = computed<Record<string, unknown>>(() => {
  for (const message of [...messages.value].reverse()) {
    const meta = (message.metadata || {}) as Record<string, unknown>
    const metrics = meta.processMetrics
    if (metrics && typeof metrics === 'object') return metrics as Record<string, unknown>
  }
  return {}
})
const runtimeMetricRecords = computed<Record<string, unknown>[]>(() => {
  const records: Record<string, unknown>[] = []
  for (const message of messages.value) {
    const meta = (message.metadata || {}) as Record<string, unknown>
    const metrics = meta.processMetrics
    if (metrics && typeof metrics === 'object') records.push(metrics as Record<string, unknown>)
  }
  return records
})
const DEFAULT_CONTEXT_COMPACTION_TRIGGER_RATIO = 0.8
const contextResourceStats = computed(() => {
  const metrics = latestRuntimeMetrics.value
  const current = firstNumberMetric(
    metrics.estimated_prompt_tokens,
    metrics.estimatedPromptTokens,
    metrics.context_tokens,
    metrics.contextTokens,
  )
  const max = firstNumberMetric(
    metrics.context_window_tokens,
    metrics.contextWindowTokens,
    activeExecutionModel.value?.context_window,
  )
  const threshold = firstNumberMetric(
    metrics.context_compaction_trigger_tokens,
    metrics.contextCompactionTriggerTokens,
    metrics.trigger_tokens,
    metrics.triggerTokens,
  )
  if (current < 0 || max <= 0) return null
  const currentPct = Math.round((current / max) * 100)
  const thresholdPct = threshold > 0
    ? Math.round((threshold / max) * 100)
    : Math.round(DEFAULT_CONTEXT_COMPACTION_TRIGGER_RATIO * 100)
  const currentRatio = clampRatio(current / max)
  const thresholdRatio = threshold > 0
    ? clampRatio(threshold / max)
    : DEFAULT_CONTEXT_COMPACTION_TRIGGER_RATIO
  return {
    current,
    max,
    currentPct,
    thresholdPct,
    currentRatio,
    thresholdRatio,
    contextCompacted: metrics.context_compacted === true || metrics.contextCompacted === true,
    contextLabel: `${formatTokenCompact(current)} / ${formatTokenCompact(max)}`,
  }
})
const callStats = computed(() => {
  let calls = 0
  let inputTokens = 0
  let outputTokens = 0
  let hasCalls = false
  let hasInput = false
  let hasOutput = false
  for (const metrics of runtimeMetricRecords.value) {
    const callCount = firstNumberMetric(metrics.llm_calls, metrics.llmCalls, metrics.model_calls, metrics.modelCalls)
    const input = firstNumberMetric(metrics.input_tokens, metrics.inputTokens, metrics.prompt_tokens, metrics.promptTokens)
    const output = firstNumberMetric(metrics.output_tokens, metrics.outputTokens, metrics.completion_tokens, metrics.completionTokens)
    if (callCount >= 0) {
      calls += callCount
      hasCalls = true
    }
    if (input >= 0) {
      inputTokens += input
      hasInput = true
    }
    if (output >= 0) {
      outputTokens += output
      hasOutput = true
    }
  }
  if (!hasCalls && !hasInput && !hasOutput) return null
  return {
    calls: hasCalls ? calls : null,
    inputTokens: hasInput ? inputTokens : null,
    outputTokens: hasOutput ? outputTokens : null,
  }
})
const runtimeResourceSummary = computed(() => {
  const context = contextResourceStats.value
  const calls = callStats.value
  if (!context && !calls) return null
  const currentPct = context?.currentPct ?? 0
  const thresholdPct = context?.thresholdPct ?? Math.round(DEFAULT_CONTEXT_COMPACTION_TRIGGER_RATIO * 100)
  const contextCompacted = context?.contextCompacted === true
  return {
    currentPct,
    thresholdPct,
    contextLabel: context?.contextLabel || '暂无上下文',
    percentLabel: context ? `${currentPct}%` : '--',
    statusLabel: contextCompacted ? '已压缩' : (context && currentPct >= thresholdPct ? '需压缩' : '正常'),
    style: {
      '--runtime-resource-used': String(context?.currentRatio ?? 0),
      '--runtime-resource-blocked-left': `${((context?.thresholdRatio ?? DEFAULT_CONTEXT_COMPACTION_TRIGGER_RATIO) * 100).toFixed(2)}%`,
    } as Record<string, string>,
    callItems: [
      { label: '调用', value: calls?.calls !== null && calls?.calls !== undefined ? String(calls.calls) : '--' },
      { label: '输入', value: calls?.inputTokens !== null && calls?.inputTokens !== undefined ? formatCompactNumber(calls.inputTokens) : '--' },
      { label: '输出', value: calls?.outputTokens !== null && calls?.outputTokens !== undefined ? formatCompactNumber(calls.outputTokens) : '--' },
    ],
  }
})
const gitRuntimeItems = computed(() => {
  const items = [
    { label: '来源', value: reviewChanges.value ? reviewSourceLabel(reviewChanges.value.source) : '等待审查' },
  ]
  if (reviewChanges.value?.ref) items.push({ label: '基准', value: reviewChanges.value.ref.slice(0, 8) })
  if (reviewChanges.value) items.push({ label: '文件', value: `${reviewChanges.value.files.length}` })
  return items
})

function parseDiffFiles(diff: string): DiffFileBlock[] {
  const blocks: DiffFileBlock[] = []
  let current: DiffFileBlock | null = null
  for (const line of diff.split('\n')) {
    if (line.startsWith('diff --git ')) {
      if (current) blocks.push(current)
      const match = line.match(/^diff --git a\/(.+?) b\/(.+)$/)
      current = { path: match?.[2] || match?.[1] || line.replace(/^diff --git\s+/, ''), lines: [line] }
      continue
    }
    if (!current) {
      if (!line.trim()) continue
      current = { path: 'diff', lines: [] }
    }
    current.lines.push(line)
  }
  if (current) blocks.push(current)
  return blocks
}

function diffLineClass(line: string): string {
  if (line.startsWith('+++') || line.startsWith('---')) return 'review-diff-line--meta'
  if (line.startsWith('+')) return 'review-diff-line--add'
  if (line.startsWith('-')) return 'review-diff-line--del'
  if (line.startsWith('@@')) return 'review-diff-line--hunk'
  if (line.startsWith('diff --git') || line.startsWith('index ') || line.startsWith('new file') || line.startsWith('deleted file')) return 'review-diff-line--meta'
  return ''
}

function diffLineMarker(line: string): string {
  if (line.startsWith('+') && !line.startsWith('+++')) return '+'
  if (line.startsWith('-') && !line.startsWith('---')) return '-'
  return ''
}

function diffLineText(line: string): string {
  if (line.startsWith('@@')) return humanizeReviewHunk(line)
  if (line.startsWith('+') && !line.startsWith('+++')) return line.slice(1) || ' '
  if (line.startsWith('-') && !line.startsWith('---')) return line.slice(1) || ' '
  if (line.startsWith(' ')) return line.slice(1) || ' '
  return line || ' '
}

function visibleReviewDiffLines(block: DiffFileBlock): string[] {
  return block.lines.filter(line => !isReviewDiffFixedInfo(line))
}

function isReviewDiffFixedInfo(line: string): boolean {
  return (
    line.startsWith('diff --git ')
    || line.startsWith('index ')
    || line.startsWith('new file mode ')
    || line.startsWith('deleted file mode ')
    || line.startsWith('--- ')
    || line.startsWith('+++ ')
  )
}

function reviewDiffMetaItems(block: DiffFileBlock): DiffMetaItem[] {
  const items: DiffMetaItem[] = []
  const oldPath = block.lines.find(line => line.startsWith('--- '))?.replace(/^---\s+/, '') || ''
  const newPath = block.lines.find(line => line.startsWith('+++ '))?.replace(/^\+\+\+\s+/, '') || ''
  const newMode = block.lines.find(line => line.startsWith('new file mode '))?.replace(/^new file mode\s+/, '') || ''
  const deletedMode = block.lines.find(line => line.startsWith('deleted file mode '))?.replace(/^deleted file mode\s+/, '') || ''

  if (newMode || oldPath === '/dev/null') {
    items.push({ label: '类型', value: '新增文件' })
    if (newMode) items.push({ label: '权限', value: newMode })
  } else if (deletedMode || newPath === '/dev/null') {
    items.push({ label: '类型', value: '删除文件' })
    if (deletedMode) items.push({ label: '权限', value: deletedMode })
  }

  return items
}

function humanizeReviewHunk(line: string): string {
  const match = line.match(/^@@\s+-(\d+),?(\d*)\s+\+(\d+),?(\d*)\s+@@/)
  if (!match) return '变更片段'
  const oldStart = Number(match[1] || 0)
  const oldCount = Number(match[2] || 1)
  const newStart = Number(match[3] || 0)
  const newCount = Number(match[4] || 1)
  if (oldStart === 0 && newCount > 0) return `新增 ${newCount} 行`
  if (newStart === 0 && oldCount > 0) return `删除 ${oldCount} 行`
  return `第 ${newStart} 行附近 · +${newCount} / -${oldCount}`
}

function toggleReviewFile(path: string) {
  const next = new Set(reviewExpandedFiles.value)
  if (next.has(path)) {
    next.delete(path)
  } else {
    next.add(path)
  }
  reviewExpandedFiles.value = next
}

function isReviewFileExpanded(path: string): boolean {
  return reviewExpandedFiles.value.has(path)
}

async function openReviewFile(path: string) {
  if (!activeSessionId.value) return
  try {
    await api.openSessionChangeFile(activeSessionId.value, path)
    runtimeStatusText.value = `已打开 ${baseName(path)}`
  } catch (err) {
    runtimeStatusText.value = `无法打开 ${baseName(path)}：${err instanceof Error ? err.message : String(err)}`
  }
}

function baseName(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).pop() || path
}

function reviewSourceLabel(source: string): string {
  if (source === 'working_tree') return '工作区'
  if (source === 'checkpoint') return '上次提交'
  if (source === 'not_git') return '非 Git 目录'
  if (source === 'none') return '无工作区'
  return '改动'
}

function blockSummary(block: DiffFileBlock): string {
  let additions = 0
  let deletions = 0
  for (const line of block.lines) {
    if (line.startsWith('+') && !line.startsWith('+++')) additions++
    if (line.startsWith('-') && !line.startsWith('---')) deletions++
  }
  if (additions === 0 && deletions === 0) return '无文本差异'
  return `+${additions} / -${deletions}`
}

function numberMetric(value: unknown): number {
  const numberValue = Number(value)
  return Number.isFinite(numberValue) ? numberValue : -1
}

function firstNumberMetric(...values: unknown[]): number {
  for (const value of values) {
    const metric = numberMetric(value)
    if (metric >= 0) return metric
  }
  return -1
}

function clampRatio(value: number): number {
  if (!Number.isFinite(value)) return 0
  return Math.min(1, Math.max(0, value))
}

function formatTokenCompact(tokens: number): string {
  const value = tokens / 1000
  const rounded = value >= 10 ? Math.round(value) : Math.round(value * 10) / 10
  return `${rounded}k`
}

function formatCompactNumber(value: number): string {
  if (value >= 1_000_000) {
    const rounded = Math.round((value / 1_000_000) * 100) / 100
    return `${rounded}M`
  }
  if (value >= 1_000) {
    const rounded = value >= 10_000 ? Math.round(value / 1_000) : Math.round((value / 1_000) * 10) / 10
    return `${rounded}k`
  }
  return formatWholeNumber(value)
}

function formatWholeNumber(value: number): string {
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 0 }).format(value)
}

function runtimeCacheHitRate(metrics: Record<string, unknown>, inputTokens: number): number {
  const direct = numberMetric(metrics.cache_hit_rate ?? metrics.cacheHitRate)
  if (direct >= 0) return direct
  const cachedTokens = numberMetric(metrics.cached_tokens ?? metrics.cachedTokens)
  if (cachedTokens >= 0 && inputTokens > 0) return cachedTokens / inputTokens
  if (inputTokens >= 0) return 0
  return -1
}

function formatRuntimeSeconds(durationMs: number): string {
  if (durationMs <= 0) return '0'
  return String(Math.max(1, Math.round(durationMs / 1000)))
}

function shortCommit(value: string | null | undefined): string {
  return value ? value.slice(0, 8) : ''
}

function formatCheckpointTime(value: string | null | undefined): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

async function loadCommitReview(sessionId = activeSessionId.value || '') {
  if (!sessionId) {
    commitReview.value = null
    return
  }
  commitReviewLoading.value = true
  commitReviewError.value = ''
  try {
    const review = await api.getCommitReview(sessionId)
    commitReview.value = review
    commitMessageDraft.value = review.commit_message || ''
  } catch (err) {
    commitReviewError.value = err instanceof Error ? err.message : String(err)
  } finally {
    commitReviewLoading.value = false
  }
}

async function loadCheckpoints(sessionId = activeSessionId.value || '') {
  if (!sessionId) {
    checkpoints.value = []
    return
  }
  checkpointLoading.value = true
  checkpointError.value = ''
  try {
    checkpoints.value = await api.listSessionCheckpoints(sessionId)
  } catch (err) {
    checkpointError.value = err instanceof Error ? err.message : String(err)
  } finally {
    checkpointLoading.value = false
  }
}

async function loadGitAutomationState(sessionId = activeSessionId.value || '') {
  if (!sessionId) {
    commitReview.value = null
    checkpoints.value = []
    return
  }
  await Promise.all([
    loadCommitReview(sessionId),
    loadCheckpoints(sessionId),
  ])
}

async function loadReviewChanges(sessionId = activeSessionId.value || '') {
  if (!sessionId) {
    reviewChanges.value = null
    return
  }
  reviewLoading.value = true
  reviewError.value = ''
  try {
    const changes = await api.getSessionChanges(sessionId)
    reviewChanges.value = changes
    reviewAllFilesVisible.value = false
    reviewAllDiffsVisible.value = false
    const nextExpanded = new Set(reviewExpandedFiles.value)
    for (const file of changes.files.slice(0, 3)) nextExpanded.add(file.path)
    reviewExpandedFiles.value = nextExpanded
  } catch (err) {
    reviewError.value = err instanceof Error ? err.message : String(err)
  } finally {
    reviewLoading.value = false
  }
}

async function approveCommitReview() {
  if (!activeSessionId.value || !activeCommitReview.value) return
  commitReviewLoading.value = true
  commitReviewError.value = ''
  try {
    commitReview.value = await api.decideCommitReview(activeSessionId.value, {
      action: 'approve',
      feedback: '',
      commit_message: commitMessageDraft.value.trim() || activeCommitReview.value.commit_message,
    })
    commitFeedbackOpen.value = false
    await Promise.all([loadReviewChanges(activeSessionId.value), loadCheckpoints(activeSessionId.value)])
  } catch (err) {
    commitReviewError.value = err instanceof Error ? err.message : String(err)
  } finally {
    commitReviewLoading.value = false
  }
}

async function requestCommitChanges() {
  if (!activeSessionId.value || !activeCommitReview.value) return
  const feedback = commitReviewFeedback.value.trim()
  if (!feedback) {
    commitFeedbackOpen.value = true
    return
  }
  commitReviewLoading.value = true
  commitReviewError.value = ''
  try {
    commitReview.value = await api.decideCommitReview(activeSessionId.value, {
      action: 'request_changes',
      feedback,
    })
    commitReviewFeedback.value = ''
  } catch (err) {
    commitReviewError.value = err instanceof Error ? err.message : String(err)
  } finally {
    commitReviewLoading.value = false
  }
}

async function postponeCommitReview() {
  if (!activeSessionId.value || !activeCommitReview.value) return
  commitReviewLoading.value = true
  commitReviewError.value = ''
  try {
    commitReview.value = await api.decideCommitReview(activeSessionId.value, {
      action: 'postpone',
      feedback: commitReviewFeedback.value.trim(),
    })
    commitFeedbackOpen.value = false
  } catch (err) {
    commitReviewError.value = err instanceof Error ? err.message : String(err)
  } finally {
    commitReviewLoading.value = false
  }
}

async function saveCheckpoint() {
  if (!activeSessionId.value) return
  checkpointLoading.value = true
  checkpointError.value = ''
  try {
    await api.createSessionCheckpoint(activeSessionId.value, '用户手动保存检查点')
    await Promise.all([loadCheckpoints(activeSessionId.value), loadReviewChanges(activeSessionId.value)])
  } catch (err) {
    checkpointError.value = err instanceof Error ? err.message : String(err)
  } finally {
    checkpointLoading.value = false
  }
}

async function restoreCheckpoint(checkpoint: SessionCheckpoint) {
  if (!activeSessionId.value || !checkpoint.commit) return
  const label = checkpoint.reason || formatCheckpointTime(checkpoint.created_at) || shortCommit(checkpoint.commit)
  const confirmed = window.confirm(`回退到「${label}」？当前未保存改动会先自动存一份，再回到这个节点。`)
  if (!confirmed) return
  checkpointLoading.value = true
  checkpointError.value = ''
  try {
    await api.restoreSessionCheckpoint(activeSessionId.value, checkpoint.commit)
    await Promise.all([
      loadReviewChanges(activeSessionId.value),
      loadCheckpoints(activeSessionId.value),
      loadCommitReview(activeSessionId.value),
    ])
  } catch (err) {
    checkpointError.value = err instanceof Error ? err.message : String(err)
  } finally {
    checkpointLoading.value = false
  }
}

async function rollbackLatestTurn() {
  if (!activeSessionId.value) return
  const confirmed = window.confirm('回退上一轮任务？该轮及之后的聊天过程会从当前会话隐藏，工作区会尽量恢复到绑定的检查点。')
  if (!confirmed) return
  checkpointLoading.value = true
  checkpointError.value = ''
  try {
    const result = await api.rollbackSessionTurn(activeSessionId.value, undefined, '用户从界面回退上一轮')
    if (result.snapshot) {
      appServerStore.applyResponse({ snapshot: result.snapshot })
    }
    await Promise.all([
      loadReviewChanges(activeSessionId.value),
      loadCheckpoints(activeSessionId.value),
      loadCommitReview(activeSessionId.value),
      sessionStore.fetchSessions(),
    ])
  } catch (err) {
    checkpointError.value = err instanceof Error ? err.message : String(err)
  } finally {
    checkpointLoading.value = false
  }
}

function upsertForkedSession(session: Session) {
  sessions.value = [
    {
      id: session.id,
      title: session.title || `Session ${session.id.slice(0, 8)}`,
      status: normalizeCoreSessionStatus(session.status || 'idle'),
      createdAt: session.created_at,
      updatedAt: session.updated_at,
      metadata: {
        work_root: session.work_root,
        branch: session.branch || '',
        phase: session.phase,
        mode: session.mode,
        project_id: session.project_id || '',
      },
    },
    ...sessions.value.filter(item => item.id !== session.id),
  ]
  sessionStore.sessions = [
    session,
    ...sessionStore.sessions.filter(item => item.id !== session.id),
  ]
}

async function forkActiveSession() {
  if (!activeSessionId.value) return
  const activeTitle = sessions.value.find(session => session.id === activeSessionId.value)?.title || 'Session'
  const confirmed = window.confirm('从当前会话派生一个新会话？新会话会继承当前上下文，并创建独立 Git worktree。')
  if (!confirmed) return
  checkpointLoading.value = true
  checkpointError.value = ''
  try {
    const forked = await api.forkSession(activeSessionId.value, {
      title: `${activeTitle} fork`,
      isolated_worktree: true,
    })
    upsertForkedSession(forked)
    await selectSession(forked.id)
  } catch (err) {
    checkpointError.value = err instanceof Error ? err.message : String(err)
  } finally {
    checkpointLoading.value = false
  }
}

async function loadAgentBranches(sessionId = activeSessionId.value || '') {
  if (!sessionId) {
    agentBranches.value = []
    return
  }
  agentBranchLoading.value = true
  agentBranchError.value = ''
  try {
    agentBranches.value = await api.listAgentBranches(sessionId)
  } catch (err) {
    agentBranchError.value = err instanceof Error ? err.message : String(err)
  } finally {
    agentBranchLoading.value = false
  }
}

async function viewAgentBranchDiff(branch: string) {
  if (!activeSessionId.value || !branch) return
  agentBranchLoading.value = true
  agentBranchError.value = ''
  try {
    const result = await api.getAgentBranchDiff(activeSessionId.value, branch)
    selectedAgentBranch.value = branch
    selectedAgentBranchDiff.value = result.diff || '暂无差异。'
  } catch (err) {
    agentBranchError.value = err instanceof Error ? err.message : String(err)
  } finally {
    agentBranchLoading.value = false
  }
}

async function mergeAgentBranch(branch: string) {
  if (!activeSessionId.value || !branch) return
  const confirmed = window.confirm(`合并子任务「${branch}」的结果？合并前请先看改动。`)
  if (!confirmed) return
  agentBranchLoading.value = true
  agentBranchError.value = ''
  try {
    await api.mergeAgentBranch(activeSessionId.value, branch)
    selectedAgentBranch.value = ''
    selectedAgentBranchDiff.value = ''
    await Promise.all([
      loadAgentBranches(activeSessionId.value),
      loadReviewChanges(activeSessionId.value),
      loadCommitReview(activeSessionId.value),
    ])
  } catch (err) {
    agentBranchError.value = err instanceof Error ? err.message : String(err)
  } finally {
    agentBranchLoading.value = false
  }
}

async function abandonAgentBranch(branch: string) {
  if (!activeSessionId.value || !branch) return
  const confirmed = window.confirm(`放弃子任务「${branch}」？对应隔离工作区和分支会被删除。`)
  if (!confirmed) return
  agentBranchLoading.value = true
  agentBranchError.value = ''
  try {
    await api.abandonAgentBranch(activeSessionId.value, branch)
    if (selectedAgentBranch.value === branch) {
      selectedAgentBranch.value = ''
      selectedAgentBranchDiff.value = ''
    }
    await loadAgentBranches(activeSessionId.value)
  } catch (err) {
    agentBranchError.value = err instanceof Error ? err.message : String(err)
  } finally {
    agentBranchLoading.value = false
  }
}

async function undoReviewChanges() {
  if (!activeSessionId.value || !reviewHasChanges.value) return
  const confirmed = window.confirm('撤销当前会话的工作区改动？此操作会还原当前 Review 面板展示的改动。')
  if (!confirmed) return
  reviewLoading.value = true
  reviewError.value = ''
  try {
    await api.undoSessionChanges(activeSessionId.value)
    await loadReviewChanges(activeSessionId.value)
  } catch (err) {
    reviewError.value = err instanceof Error ? err.message : String(err)
  } finally {
    reviewLoading.value = false
  }
}

async function undoReviewFile(path: string) {
  if (!activeSessionId.value || !path) return
  const confirmed = window.confirm(`撤销 ${path} 的改动？`)
  if (!confirmed) return
  reviewLoading.value = true
  reviewError.value = ''
  try {
    await api.undoSessionFileChange(activeSessionId.value, path)
    await loadReviewChanges(activeSessionId.value)
  } catch (err) {
    reviewError.value = err instanceof Error ? err.message : String(err)
  } finally {
    reviewLoading.value = false
  }
}

async function syncSessionUrl(sessionId: string | null) {
  const route = router.currentRoute.value
  if (route.name !== 'workbench') return
  const currentSession = Array.isArray(route.query.session) ? route.query.session[0] : route.query.session
  if ((sessionId && currentSession === sessionId) || (!sessionId && !('session' in route.query))) return
  await router.replace({
    name: 'workbench',
    query: workbenchSessionRouteQuery(route.query as WorkbenchRouteQuery, sessionId),
  }).catch(() => undefined)
}

watch(activeSessionId, (newId) => {
  void syncSessionUrl(newId ?? null)
  reviewExpandedFiles.value = new Set()
  reviewAllFilesVisible.value = false
  reviewAllDiffsVisible.value = false
  clearAttachments()
  reviewChanges.value = null
  commitReview.value = null
  checkpoints.value = []
  agentBranches.value = []
  selectedAgentBranch.value = ''
  selectedAgentBranchDiff.value = ''
  commitReviewFeedback.value = ''
  commitFeedbackOpen.value = false
  liveComposerController.resetForThreadChange()
  if (newId) {
    appServerStore.disconnect()
    // Reset session store messages
    // Reset step store
    void appServerStore.connect(api.API_BASE, newId)
      .then(() => liveComposerController.loadCommandCatalog(newId))
      .catch((err) => {
        if (err instanceof Error && err.name === 'AbortError') return
        console.error('Failed to connect Writer App Server:', err)
        runtimeStatusText.value = '实时连接失败'
      })
    void loadReviewChanges(newId)
  }
})

function syncLoadedSessionStatus(session: Session | null) {
  if (!session) return
  if (!sessions.value.some(item => item.id === session.id)) return
  sessions.value = updateCoreSessionListStatus(
    sessions.value,
    session.id,
    normalizeCoreSessionStatus(session.status || 'idle'),
    session.updated_at || new Date().toISOString(),
  )
  const storeIndex = sessionStore.sessions.findIndex(item => item.id === session.id)
  if (storeIndex >= 0) {
    sessionStore.sessions[storeIndex] = {
      ...sessionStore.sessions[storeIndex],
      status: normalizeCoreSessionStatus(session.status || 'idle'),
      updated_at: session.updated_at || sessionStore.sessions[storeIndex].updated_at,
    }
  }
}

function upsertCreatedProjectSession(
  project: Pick<Project, 'id' | 'name' | 'work_root'>,
  session: Pick<Session, 'id' | 'title' | 'work_root'> & Partial<Session>,
) {
  const createdAt = session.created_at || new Date().toISOString()
  const updatedAt = session.updated_at || createdAt
  const coreSession: CoreSessionListItem = {
    id: session.id,
    title: session.title,
    createdAt,
    updatedAt,
    groupId: 'writer-sessions',
    status: session.status,
    metadata: { project_id: project.id, work_root: project.work_root },
  }

  const coreIndex = sessions.value.findIndex(item => item.id === coreSession.id)
  if (coreIndex >= 0) {
    const updated = [...sessions.value]
    updated[coreIndex] = { ...updated[coreIndex], ...coreSession }
    sessions.value = updated
  } else {
    sessions.value = [coreSession, ...sessions.value]
  }

  const storeSession: Session = {
    id: session.id,
    title: session.title || 'New Session',
    work_root: session.work_root || project.work_root,
    branch: session.branch ?? null,
    phase: session.phase ?? 'idle',
    mode: session.mode ?? 'EXECUTE',
    status: normalizeCoreSessionStatus(session.status || 'idle'),
    project_id: session.project_id || project.id,
    created_at: createdAt,
    updated_at: updatedAt,
  }
  const storeIndex = sessionStore.sessions.findIndex(item => item.id === session.id)
  if (storeIndex >= 0) {
    sessionStore.sessions[storeIndex] = { ...sessionStore.sessions[storeIndex], ...storeSession }
  } else {
    sessionStore.sessions.unshift(storeSession)
  }
}

async function saveAgentsMdForProject(
  projectId: string,
  requestToken: number,
  content: string,
): Promise<WriterProjectAgents> {
  if (!shouldApplyWriterProjectAgents(projectId, requestToken, agentsMdProjectId.value, agentsRequestToken.value)) {
    throw new Error('AGENTS.md target changed')
  }
  agentsLoading.value = true
  agentsError.value = ''
  try {
    const saved = await projectStore.saveAgents(projectId, content)
    if (shouldApplyWriterProjectAgents(projectId, requestToken, agentsMdProjectId.value, agentsRequestToken.value)) {
      agentsContent.value = saved.content
      showAgentsMd.value = false
    }
    return saved
  } catch (err) {
    console.error('Failed to save AGENTS.md:', err)
    if (shouldApplyWriterProjectAgents(projectId, requestToken, agentsMdProjectId.value, agentsRequestToken.value)) {
      agentsError.value = '保存 AGENTS.md 失败'
    }
    throw err
  } finally {
    if (shouldApplyWriterProjectAgents(projectId, requestToken, agentsMdProjectId.value, agentsRequestToken.value)) {
      agentsLoading.value = false
    }
  }
}

const showNewProject = ref(false)
const projectActionLoading = ref(false)
const projectActionError = ref('')

function closeNewProject() {
  showNewProject.value = false
  projectActionError.value = ''
}

async function selectProjectDirectory() {
  const selected = await pickProjectDirectory({
    desktop: window.lamwriterDesktop,
    appServerPickDirectory: api.pickProjectDirectory,
  })
  if (selected.message) window.alert(selected.message)
  return selected.path
}

async function handleNewProject(payload: { name: string; work_root: string }) {
  if (!payload.work_root.trim() || projectActionLoading.value) return
  projectActionLoading.value = true
  projectActionError.value = ''
  try {
    await createWriterProjectWorkspace(payload, {
      createProject: projectStore.createProject,
      onCreated: ({ project, session }) => upsertCreatedProjectSession(project, session),
      selectSession: async (sessionId) => {
        await router.push({ name: 'workbench' }).catch(() => undefined)
        await selectSession(sessionId)
      },
      refresh: async () => {
        await Promise.all([sessionStore.fetchSessions(), projectStore.fetchProjects()])
      },
    })
    closeNewProject()
  } catch (err) {
    console.error('Failed to create project:', err)
    projectActionError.value = '创建项目失败'
  } finally {
    projectActionLoading.value = false
  }
}

// --- Load ---
onMounted(async () => {
  await Promise.all([
    projectStore.fetchProjects(),
    sessionStore.fetchSessions(),
    configStore.fetchProviders(),
    configStore.fetchModels(),
    configStore.fetchResolvedConfig('writer').catch(() => undefined),
    loadInitialData(),
  ])
})
</script>

<template>
  <WorkspaceShell
    product-name="LamWriter"
    storage-key="lamwriter.ui"
    density="standard"
    right-panel-title="运行状态"
    :show-right-panel="true"
    :composer-placeholder="'输入任务描述...'"
    :composer-disabled="composerActionMode === 'send' && !composerText.trim() && pendingAttachments.length === 0"
    :composer-action-mode="composerActionMode"
    @new-session="newSession"
    @settings="router.push('/settings')"
    @composer-submit="sendWriterTask"
    @composer-drop="handleComposerDrop"
  >
    <!-- Header action: replace default "+" with project-aware menu -->
    <template #sidebar-header-action>
      <div class="header-new-menu">
        <button class="icon-btn" title="新建项目" @click="showNewProject = !showNewProject">+</button>
        <CoreProjectCreate
          v-if="showNewProject"
          :loading="projectActionLoading"
          :error="projectActionError"
          :select-work-root="selectProjectDirectory"
          @submit="handleNewProject"
          @cancel="closeNewProject"
        />
      </div>
    </template>

    <!-- Left sidebar body -->
    <template #sidebar-body>
      <SessionSidebar
        :project-groups="projectGroups"
        :active-session-id="activeSessionId ?? undefined"
        :project-session-limit="8"
        :allow-project-delete="true"
        :allow-session-delete="true"
        :allow-project-click="true"
        :allow-project-context-menu="true"
        :allow-rename="false"
        @select-session="selectSession"
        @new-session="handleNewSession"
        @delete-project="handleDeleteProject"
        @delete-session="handleDeleteSession"
        @select-project="(id) => { /* select first session in project */ }"
        @project-context-menu="handleProjectContextMenu"
      >
        <template #empty>
          <div style="text-align:center;padding:18px 12px;color:var(--muted);font-size:13px">
            暂无项目。<br />点击左上角 + 新建项目。
          </div>
        </template>
      </SessionSidebar>
    </template>

    <!-- Main header -->
    <template #main-header>
      <div v-if="activeSessionId" class="thread-header">
        <div class="session-title-editor">
          <h1>
            <input
              v-model="activeSessionTitleDraft"
              class="session-title-input"
              aria-label="会话标题"
              spellcheck="false"
              @focus="handleActiveSessionTitleFocus"
              @input="handleActiveSessionTitleInput"
              @blur="submitActiveSessionTitle"
              @keydown.enter.prevent="submitActiveSessionTitle"
              @keydown.esc.prevent="cancelActiveSessionTitleEdit"
            />
          </h1>
          <span>#{{ activeSessionId?.slice(0, 8) }}</span>
        </div>
      </div>
    </template>

    <!-- Main content -->
    <template #main-content>
      <section
        ref="threadScrollEl"
        class="thread"
        @scroll.passive="threadScroll.handleScroll"
        @wheel.passive="threadScroll.handleWheel"
      >
        <template v-if="!activeSessionId">
        <div class="sidebar-empty" style="flex:1;display:flex;align-items:center;justify-content:center">
          选择一个会话或创建新项目开始。
        </div>
        </template>
        <template v-else>
          <ChatThread
            :messages="messages"
            assistant-label="Writer"
            :process-expanded-ids="processExpandedIds"
            @toggle-process="toggleProcess"
            @decision-select="handleDecisionSelect"
          />
        </template>
      </section>
    </template>

    <!-- Composer tools -->
    <template #composer-textarea>
      <input
        ref="attachmentFileInput"
        class="sr-only"
        type="file"
        multiple
        @change="handleAttachmentInputChange"
      />
      <CoreQueuedInputTray
        v-model:draft="queuedInputDraft"
        :items="queuedInputs"
        :editing-id="editingQueuedInputId"
        :can-guide="canGuideQueuedInput"
        :submitting-ids="queueController.submittingItemIds.value"
        @edit="(item) => queueController.beginEdit(item as CoreQueuedInput)"
        @save="(item) => queueController.save(item as CoreQueuedInput)"
        @cancel="queueController.cancelEdit"
        @delete="(item) => queueController.remove(item as CoreQueuedInput)"
        @guide="(item) => queueController.guide(item as CoreQueuedInput)"
      />
      <AttachmentTray
        :attachments="pendingAttachments"
        @remove="removeAttachment"
        @retry="retryPendingAttachment"
        @preview="previewPendingAttachment"
        @open="openPendingAttachment"
      />
      <div v-if="composerErrorText" class="composer-feedback composer-feedback--error">
        {{ composerErrorText }}
      </div>
      <div class="composer-input-wrap" :class="{ 'has-command-tokens': hasComposerCommandTokens }">
        <CommandPalette
          v-if="commandPaletteVisible"
          :commands="commandPalette.filteredCommands.value"
          :active-index="commandPalette.activeIndex.value"
          @select="liveComposerController.selectCommand"
        />
        <div
          v-if="hasComposerCommandTokens"
          class="composer-syntax-overlay"
          aria-hidden="true"
        >
          <span
            v-for="(segment, index) in composerHighlightSegments"
            :key="index"
            :class="{ 'composer-skill-token': segment.command }"
          >{{ segment.text }}</span>
        </div>
        <textarea
          ref="composerTextareaEl"
          v-model="composerText"
          placeholder="输入任务描述..."
          rows="1"
          @input="handleComposerInput"
          @click="updateComposerCursor"
          @keyup="handleComposerKeyup"
          @keydown="handleComposerKeydown"
        />
      </div>
    </template>

    <template #composer-tools>
      <CoreExecutionControls
        :model-value="selectedModelId"
        :thinking-mode="selectedThinkingMode"
        :shallow-thinking-enabled="shallowThinkingEnabled"
        :model-options="modelOptions"
        :thinking-mode-options="thinkingModeOptions"
        model-aria-label="模型"
        thinking-aria-label="思考模式"
        shallow-label="Shallow"
        @update:model-value="selectModel"
        @update:thinking-mode="selectThinkingMode"
        @update:shallow-thinking-enabled="(enabled) => { shallowThinkingEnabled = enabled }"
      >
        <template #leading>
          <button
            class="composer-attachment-button"
            type="button"
            title="添加附件"
            aria-label="添加附件"
            @click="attachmentFileInput?.click()"
          >
            +
          </button>
        </template>
      </CoreExecutionControls>
    </template>

    <template #right-panel>
      <div class="runtime-toolbar">
        <section class="runtime-widget runtime-resource-widget">
          <div class="runtime-widget-head">
            <div>
              <h3>资源</h3>
            </div>
            <strong v-if="runtimeResourceSummary" class="runtime-resource-state">{{ runtimeResourceSummary.statusLabel }}</strong>
          </div>
          <template v-if="runtimeResourceSummary">
            <div class="runtime-resource-main">
              <div class="runtime-resource-values">
                <Transition name="runtime-resource-value" mode="out-in">
                  <strong :key="runtimeResourceSummary.contextLabel">{{ runtimeResourceSummary.contextLabel }}</strong>
                </Transition>
                <Transition name="runtime-resource-value" mode="out-in">
                  <strong :key="runtimeResourceSummary.percentLabel">{{ runtimeResourceSummary.percentLabel }}</strong>
                </Transition>
              </div>
              <div
                class="runtime-resource-bar"
                :style="runtimeResourceSummary.style"
                tabindex="0"
                :aria-label="`当前 ${runtimeResourceSummary.currentPct}%，${runtimeResourceSummary.thresholdPct}% 后自动压缩`"
              >
                <span class="runtime-resource-used"></span>
                <span class="runtime-resource-blocked"></span>
              </div>
              <div class="runtime-resource-hint">
                当前 {{ runtimeResourceSummary.currentPct }}% · {{ runtimeResourceSummary.thresholdPct }}% 后自动压缩
              </div>
            </div>
            <div class="runtime-resource-legend">
              <span>可用至 {{ runtimeResourceSummary.thresholdPct }}%</span>
              <span>灰色区压缩</span>
            </div>
            <div class="runtime-resource-stats">
              <div v-for="item in runtimeResourceSummary.callItems" :key="item.label" class="runtime-resource-stat">
                <span>{{ item.label }}</span>
                <Transition name="runtime-resource-value" mode="out-in">
                  <strong :key="`${item.label}-${item.value}`">{{ item.value }}</strong>
                </Transition>
              </div>
            </div>
          </template>
          <div v-else class="review-empty">暂无资源统计。</div>
        </section>

        <section class="runtime-widget review-panel">
          <div class="runtime-widget-head">
            <div>
              <h3>Diff 文件</h3>
              <p v-if="reviewChanges">{{ reviewSourceLabel(reviewChanges.source) }} · {{ reviewChanges.files.length }} 个文件</p>
              <p v-else>等待会话改动</p>
            </div>
            <div class="review-actions">
              <button type="button" :disabled="reviewLoading || !activeSessionId" @click="loadReviewChanges()">刷新</button>
            </div>
          </div>
          <div v-if="reviewLoading" class="review-empty">正在读取改动...</div>
          <div v-else-if="reviewError" class="review-error">{{ reviewError }}</div>
          <div v-else-if="!reviewChanges || !reviewHasChanges" class="review-empty">
            暂无 diff 文件。
          </div>
          <template v-else>
            <div class="review-file-list">
              <div
                v-for="file in visibleReviewFiles"
                :key="file.path"
                class="review-file-row"
              >
                <button type="button" class="review-file-toggle" :title="file.path" @click="openReviewFile(file.path)">
                  <span class="review-file-name">{{ baseName(file.path) }}</span>
                </button>
              </div>
              <button
                v-if="hiddenReviewFileCount > 0"
                type="button"
                class="review-more"
                @click="reviewAllFilesVisible = !reviewAllFilesVisible"
              >
                <span>{{ reviewAllFilesVisible ? '收起文件' : '...' }}</span>
                <span>{{ reviewAllFilesVisible ? `隐藏 ${hiddenReviewFileCount} 项` : `展开其余 ${hiddenReviewFileCount} 项` }}</span>
              </button>
            </div>
          </template>
        </section>
      </div>
    </template>

    <!-- AGENTS.md modal -->
    <template #modals>
      <div v-if="showAgentsMd" class="modal-overlay" @click.self="!agentsLoading && (showAgentsMd = false)">
        <div class="modal-card wide">
          <CoreAgentsEditor
            :content="agentsContent"
            :loading="agentsLoading || agentsReadyToken !== agentsRequestToken"
            :error="agentsError"
            @save="agentsSaveHandler"
            @close="showAgentsMd = false"
          />
        </div>
      </div>
    </template>
  </WorkspaceShell>
</template>

<style scoped>
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
}

.session-title-editor {
  width: 100%;
  min-width: 0;
  display: grid;
  gap: 4px;
}

.session-title-editor h1 {
  width: 100%;
  min-width: 0;
  margin: 0;
}

.session-title-input {
  width: 100%;
  min-width: 0;
  max-width: 100%;
  height: 28px;
  border: 0;
  background: transparent;
  color: var(--theme-main-text, currentColor);
  caret-color: var(--theme-main-text, currentColor);
  padding: 2px 0;
  font: inherit;
  font-size: 17px;
  font-weight: 760;
  line-height: 1.2;
  outline: none;
  text-overflow: ellipsis;
}

.session-title-input:focus {
  background: transparent;
}

.composer-attachment-button {
  display: inline-grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: color-mix(in srgb, var(--theme-composer-text, currentColor) 74%, transparent);
  font-size: 20px;
  font-weight: 700;
  line-height: 1;
}

.composer-attachment-button:hover {
  background: color-mix(in srgb, var(--theme-composer-text, currentColor) 10%, transparent);
  color: var(--theme-composer-text, currentColor);
}

.runtime-resource-widget {
  --runtime-resource-ease: cubic-bezier(0.22, 1, 0.36, 1);
}

.runtime-resource-state {
  color: var(--green);
  font-size: 12px;
  font-weight: 850;
  line-height: 1.2;
}

.runtime-resource-main {
  display: grid;
  gap: 6px;
}

.runtime-resource-values {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
}

.runtime-resource-values strong {
  min-width: 0;
  color: var(--theme-backdrop-text);
  font-family: var(--font-mono);
  font-size: 14px;
  font-weight: 850;
  line-height: 1.25;
  transition: opacity 120ms var(--runtime-resource-ease);
  white-space: nowrap;
}

.runtime-resource-values strong:first-child {
  overflow: hidden;
  text-overflow: ellipsis;
}

.runtime-resource-bar {
  position: relative;
  height: 8px;
  overflow: hidden;
  background: color-mix(in srgb, var(--theme-backdrop-text) 10%, transparent);
  outline: none;
}

.runtime-resource-used {
  position: absolute;
  inset: 0;
  background: color-mix(in srgb, var(--green) 82%, var(--theme-backdrop-text));
  transform: scaleX(var(--runtime-resource-used, 0));
  transform-origin: left center;
  transition: transform 180ms var(--runtime-resource-ease);
}

.runtime-resource-blocked {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  left: var(--runtime-resource-blocked-left, 80%);
  background-color: color-mix(in srgb, var(--theme-backdrop-text) 14%, transparent);
  background-image: linear-gradient(
    135deg,
    transparent 0 42%,
    color-mix(in srgb, var(--theme-backdrop-text) 34%, transparent) 43% 52%,
    transparent 53% 100%
  );
  background-size: 9px 9px;
}

.runtime-resource-hint {
  min-height: 17px;
  color: color-mix(in srgb, var(--theme-backdrop-text) 52%, transparent);
  font-size: 12px;
  line-height: 1.35;
  opacity: 0;
  transform: translateY(-2px);
  transition: opacity 160ms var(--runtime-resource-ease), transform 160ms var(--runtime-resource-ease);
}

.runtime-resource-bar:hover + .runtime-resource-hint,
.runtime-resource-bar:focus-visible + .runtime-resource-hint {
  opacity: 1;
  transform: translateY(0);
}

.runtime-resource-bar:focus-visible {
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--theme-backdrop-text) 20%, transparent);
}

.runtime-resource-legend {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  margin-top: -4px;
  color: color-mix(in srgb, var(--theme-backdrop-text) 52%, transparent);
  font-size: 12px;
  line-height: 1.35;
}

.runtime-resource-stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-top: 8px;
  padding-top: 12px;
  border-top: 1px solid color-mix(in srgb, var(--theme-backdrop-text) 11%, transparent);
}

.runtime-resource-stat {
  min-width: 0;
  display: grid;
  gap: 3px;
}

.runtime-resource-stat span {
  color: color-mix(in srgb, var(--theme-backdrop-text) 52%, transparent);
  font-size: 12px;
  line-height: 1.2;
}

.runtime-resource-stat strong {
  min-width: 0;
  overflow: hidden;
  color: var(--theme-backdrop-text);
  font-family: var(--font-mono);
  font-size: 13px;
  font-weight: 850;
  line-height: 1.25;
  text-overflow: ellipsis;
  transition: opacity 120ms var(--runtime-resource-ease);
  white-space: nowrap;
}

.runtime-resource-value-enter-active,
.runtime-resource-value-leave-active {
  transition: opacity 120ms var(--runtime-resource-ease);
}

.runtime-resource-value-enter-from,
.runtime-resource-value-leave-to {
  opacity: 0.28;
}

@media (prefers-reduced-motion: reduce) {
  .runtime-resource-values strong,
  .runtime-resource-stat strong,
  .runtime-resource-used,
  .runtime-resource-hint,
  .runtime-resource-value-enter-active,
  .runtime-resource-value-leave-active {
    transition-duration: 0.01ms !important;
  }
}

@media (max-width: 760px) {
  .send {
    width: 50px;
    height: 30px;
  }
}

.agent-branch-headline {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid color-mix(in srgb, currentColor 10%, transparent);
  font-size: 12px;
}

.checkpoint-headline {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid color-mix(in srgb, currentColor 10%, transparent);
  font-size: 12px;
}

.checkpoint-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.agent-branch-headline button,
.agent-branch-actions button,
.checkpoint-actions button {
  min-height: 28px;
  padding: 0 9px;
  border-radius: 6px;
  border: 1px solid color-mix(in srgb, currentColor 16%, transparent);
  background: color-mix(in srgb, currentColor 5%, transparent);
  color: inherit;
}

.agent-branch-actions button.danger {
  color: #b42318;
}

.history-load-more {
  width: 100%;
  min-height: 30px;
  margin-top: 10px;
  border-radius: 6px;
  border: 1px solid color-mix(in srgb, currentColor 14%, transparent);
  background: color-mix(in srgb, currentColor 5%, transparent);
  color: inherit;
  font-size: 12px;
}

.agent-branch-list {
  display: grid;
  gap: 8px;
  margin-top: 8px;
}

.agent-branch-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
}

.agent-branch-row strong,
.agent-branch-row span {
  display: block;
  overflow-wrap: anywhere;
}

.agent-branch-row span {
  color: color-mix(in srgb, currentColor 64%, transparent);
  font-size: 12px;
}

.agent-branch-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.agent-branch-diff {
  max-height: 280px;
  overflow: auto;
  margin: 10px 0 0;
  padding: 10px;
  border-radius: 6px;
  background: color-mix(in srgb, currentColor 6%, transparent);
  font-size: 11px;
  white-space: pre-wrap;
}
</style>
