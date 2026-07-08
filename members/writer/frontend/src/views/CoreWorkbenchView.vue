<script setup lang="ts">
/**
 * CoreWorkbenchView — LamWriter powered by @lamtools/ui WorkspaceShell
 *
 * Uses the real project store + session store for project→session grouping.
 * Project-level actions (new session, delete, AGENTS.md) wired through sidebar.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  WorkspaceShell,
  SessionSidebar,
  ChatThread,
  AttachmentTray,
  CommandPalette,
  parseComposerSyntax,
  useComposerCommandPalette,
  useCoreWorkbenchController,
  usePendingAttachments,
  type CoreAttachment,
  type CoreCommandCatalogItem,
  type CoreInputItem,
  type CoreMessage,
  type MessagePart,
  type CoreWorkbenchApi,
  type CoreSessionListItem,
  type ProjectGroup,
  type SessionItem,
} from '@lamtools/ui'
import { useProjectStore } from '@/stores/project'
import { useSessionStore } from '@/stores/session'
import { useConfigStore } from '@/stores/config'
import { useWriterAppServerStore } from '@/appServer/store'
import { selectChatMessages, selectLatestTurnStatus, selectQueueTray } from '@/appServer/selectors'
import { workbenchSessionRouteQuery, type WorkbenchRouteQuery } from '@/utils/workbenchRoute'
import { pickProjectDirectory, projectNameFromPath } from '@/lib/project-directory-picker'
import type { WriterAppItem, WriterAppQueueItem, WriterAppRequestState } from '@/appServer/protocol'
import UiSelect from '@/components/UiSelect.vue'
import MarkdownRenderer from '@/components/MarkdownRenderer.vue'
import {
  listCoreSessions,
  createCoreSession,
  listCoreProviders,
} from '@/api/core'
import * as api from '@/api'
import { removeSessionsByIds } from '@/lib/session-list'
import type { Provider, Project, Session, Model, SessionChanges, SessionCheckpoint, CommitReview, AgentBranch, WriterQueuedInput } from '@/types'

const router = useRouter()
const requestedSessionIdFromUrl = new URLSearchParams(window.location.search).get('session')
const projectStore = useProjectStore()
const sessionStore = useSessionStore()
const configStore = useConfigStore()
const appServerStore = useWriterAppServerStore()
const runtimeStatusText = ref('')
const composerErrorText = ref('')

// --- Execution model selection ---
const selectedModelId = ref<string>('')
type ThinkingMode = 'none' | 'low' | 'medium' | 'high' | 'max'
const THINKING_MODE_KEY = 'lamwriter.composer.thinkingMode'
const SHALLOW_THINKING_KEY = 'lamwriter.composer.shallowThinking'
const selectedThinkingMode = ref<ThinkingMode>(readThinkingMode())
const shallowThinkingEnabled = ref(readShallowThinkingEnabled())
const thinkingBudgets: Record<Exclude<ThinkingMode, 'none'>, number> = {
  low: 2000,
  medium: 6000,
  high: 10000,
  max: 20000,
}
const thinkingLabels: Record<ThinkingMode, string> = {
  none: '无思考',
  low: '低思考',
  medium: '中思考',
  high: '高思考',
  max: 'Max 思考',
}

const defaultModel = computed(() => {
  const resolvedId = configStore.resolvedConfig?.model?.id
  if (resolvedId) {
    const resolved = configStore.models.find((model) => model.id === resolvedId)
    if (resolved) return resolved
  }
  return configStore.models[0] || null
})

const activeExecutionModel = computed(() => {
  if (selectedModelId.value) {
    const selected = configStore.models.find((model) => model.id === selectedModelId.value)
    if (selected) return selected
  }
  return defaultModel.value
})

const activeExecutionProvider = computed(() => {
  const model = activeExecutionModel.value
  if (!model) return null
  return configStore.providers.find((provider) => provider.id === model.provider_id) || null
})

const isXfyunCodingProvider = computed(() => {
  const provider = activeExecutionProvider.value
  if (!provider) return false
  const text = `${provider.name} ${provider.base_url}`.toLowerCase()
  return text.includes('xf-yun') || text.includes('xfyun') || text.includes('maas-coding')
})

const thinkingModeOptions = computed(() => {
  const model = activeExecutionModel.value
  if (!model) {
    return [
      { value: 'max', label: 'Max 思考' },
      { value: 'high', label: '高思考' },
      { value: 'medium', label: '中思考' },
      { value: 'low', label: '低思考' },
      { value: 'none', label: '无思考' },
    ]
  }
  const supportsThinking = Boolean(model?.thinking_supported)
  if (!supportsThinking) return [{ value: 'none', label: '无思考' }]
  if (isXfyunCodingProvider.value) {
    return [
      { value: 'max', label: 'Max 思考' },
      { value: 'none', label: '无思考' },
    ]
  }
  return [
    { value: 'max', label: 'Max 思考' },
    { value: 'high', label: '高思考' },
    { value: 'medium', label: '中思考' },
    { value: 'low', label: '低思考' },
    { value: 'none', label: '无思考' },
  ]
})

const selectedThinkingLabel = computed(() => (
  thinkingLabels[normalizeThinkingMode(selectedThinkingMode.value)]
))

const modelOptions = computed(() => {
  const modelsByProvider = new Map<string, Model[]>()
  for (const model of configStore.models) {
    const list = modelsByProvider.get(model.provider_id) || []
    list.push(model)
    modelsByProvider.set(model.provider_id, list)
  }

  const options: Array<{ value: string; label: string; selectedLabel: string; group: string }> = []
  if (defaultModel.value) {
    const label = defaultModel.value.display_name || defaultModel.value.model_id
    options.push({
      value: '',
      label: `当前：${label}`,
      selectedLabel: label,
      group: '',
    })
  }

  const pushProviderModels = (provider: Provider | null, models: Model[]) => {
    for (const model of models) {
      options.push({
        value: model.id,
        label: model.display_name || model.model_id,
        selectedLabel: model.display_name || model.model_id,
        group: provider?.name || model.provider_id || 'Provider',
      })
    }
  }

  for (const provider of configStore.providers) {
    pushProviderModels(provider, modelsByProvider.get(provider.id) || [])
    modelsByProvider.delete(provider.id)
  }
  for (const models of modelsByProvider.values()) {
    pushProviderModels(null, models)
  }
  return options
})

async function selectModel(modelId: string) {
  selectedModelId.value = ''
  if (!modelId) return
  const model = configStore.models.find((item) => item.id === modelId)
  if (!model) return
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
}

function syncSelectedModel() {
  selectedModelId.value = ''
}

watch(() => configStore.models.map((model) => model.id).join('|'), syncSelectedModel)

watch(thinkingModeOptions, (options) => {
  if (options.some((option) => option.value === selectedThinkingMode.value)) return
  selectedThinkingMode.value = String(options[0]?.value || 'none') as ThinkingMode
}, { immediate: true })

watch(selectedThinkingMode, (mode) => {
  try {
    window.localStorage?.setItem(THINKING_MODE_KEY, normalizeThinkingMode(mode))
  } catch {
    // Local storage can be unavailable in hardened desktop/browser contexts.
  }
})

watch(shallowThinkingEnabled, (enabled) => {
  try {
    window.localStorage?.setItem(SHALLOW_THINKING_KEY, enabled ? '1' : '0')
  } catch {
    // Local storage can be unavailable in hardened desktop/browser contexts.
  }
})

function normalizeThinkingMode(value: unknown): ThinkingMode {
  return value === 'low' || value === 'medium' || value === 'high' || value === 'max' ? value : 'none'
}

function readThinkingMode(): ThinkingMode {
  try {
    const saved = window.localStorage?.getItem(THINKING_MODE_KEY)
    return saved ? normalizeThinkingMode(saved) : 'max'
  } catch {
    return 'max'
  }
}

function readShallowThinkingEnabled(): boolean {
  try {
    return window.localStorage?.getItem(SHALLOW_THINKING_KEY) === '1'
  } catch {
    return false
  }
}

function selectThinkingMode(value: string) {
  selectedThinkingMode.value = normalizeThinkingMode(value)
}

function toggleShallowThinking() {
  shallowThinkingEnabled.value = !shallowThinkingEnabled.value
}

function currentThinkingOptions(): { thinking_enabled: boolean; thinking_budget?: number; shallow_thinking_enabled?: boolean } {
  const mode = normalizeThinkingMode(selectedThinkingMode.value)
  const shallow = shallowThinkingEnabled.value
  if (mode === 'none' || !activeExecutionModel.value?.thinking_supported) {
    return { thinking_enabled: false, shallow_thinking_enabled: shallow }
  }
  const modelBudget = Number(activeExecutionModel.value.thinking_budget || 0)
  const budget = isXfyunCodingProvider.value
    ? modelBudget || 10000
    : Math.max(modelBudget || 0, thinkingBudgets[mode])
  return { thinking_enabled: true, thinking_budget: budget, shallow_thinking_enabled: shallow }
}

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

const messages = ref<CoreMessage[]>([])
const queuedInputs = computed<WriterQueuedInput[]>(() => appServerQueuedInputs())
const editingQueuedInputId = ref<string | null>(null)
const queuedInputDraft = ref('')
const editingActiveSessionTitle = ref(false)
const activeSessionTitleDraft = ref('')
const composerTextareaEl = ref<HTMLTextAreaElement | null>(null)
const composerCursor = ref(0)
const commandCatalog = ref<CoreCommandCatalogItem[]>([])
const commandError = ref('')
const commandPaletteDismissedText = ref('')
const attachmentFileInput = ref<HTMLInputElement | null>(null)
const threadScrollEl = ref<HTMLElement | null>(null)
const threadAutoFollow = ref(true)
const submittingApprovalRequestIds = ref<Set<string>>(new Set())
let threadResizeObserver: ResizeObserver | null = null
let lastComposerEnterHandledAt = 0
const THREAD_BOTTOM_THRESHOLD_PX = 80
const COMPOSER_MAX_ROWS = 5
const COMPOSER_ENTER_FALLBACK_MS = 750
const isAppServerActive = computed(() =>
  Boolean(activeSessionId.value && appServerStore.state?.thread_id === activeSessionId.value),
)
const {
  pendingAttachments,
  hasBlockingFailure,
  attachmentInputItems,
  addUploaded,
  markFailed,
  removeAttachment,
  clearAttachments,
} = usePendingAttachments()
const commandPalette = useComposerCommandPalette({
  text: composerText,
  cursor: composerCursor,
  commands: commandCatalog,
})
const commandPaletteVisible = computed(() =>
  commandPalette.open.value && commandPaletteDismissedText.value !== composerText.value,
)
const composerHighlightSegments = computed(() => buildComposerHighlightSegments(composerText.value))
const hasComposerCommandTokens = computed(() => composerHighlightSegments.value.some(segment => segment.command))

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

interface ComposerHighlightSegment {
  text: string
  command: boolean
}

function buildComposerHighlightSegments(text: string): ComposerHighlightSegment[] {
  const spans = parseComposerSyntax(text)
    .filter(span => span.kind === 'slash')
    .filter(span => Boolean(insertTokenCommand(span.value)))
  if (!spans.length) return [{ text, command: false }]

  const segments: ComposerHighlightSegment[] = []
  let cursor = 0
  for (const span of spans) {
    if (span.start > cursor) segments.push({ text: text.slice(cursor, span.start), command: false })
    segments.push({ text: text.slice(span.start, span.end), command: true })
    cursor = span.end
  }
  if (cursor < text.length) segments.push({ text: text.slice(cursor), command: false })
  return segments
}

function insertTokenCommand(value: string): CoreCommandCatalogItem | undefined {
  const normalized = value.toLowerCase()
  return commandCatalog.value.find(command =>
    command.action === 'insert_token' && command.name.toLowerCase() === normalized,
  )
}

function actionCommand(value: string): CoreCommandCatalogItem | undefined {
  const normalized = value.toLowerCase()
  return commandCatalog.value.find(command =>
    command.action === 'run_action' && command.name.toLowerCase() === normalized,
  )
}

function toCoreCommandCatalogItem(item: unknown): CoreCommandCatalogItem | null {
  if (!isRecord(item)) return null
  const name = String(item.name || '').trim().replace(/^\/+/, '')
  if (!name) return null
  const rawAction = String(item.action || 'run_action')
  const action: CoreCommandCatalogItem['action'] =
    rawAction === 'insert_token' || rawAction === 'expand_on_send' ? rawAction : 'run_action'
  const source: CoreCommandCatalogItem['source'] = item.source === 'member' ? 'member' : 'core'
  return {
    name,
    title: String(item.title || name),
    description: String(item.description || ''),
    icon: String(item.icon || '/'),
    source,
    action,
    accepts_args: Boolean(item.accepts_args),
  }
}

async function loadCommandCatalog(sessionId = activeSessionId.value || '') {
  commandCatalog.value = []
  commandError.value = ''
  if (!sessionId) return
  try {
    await ensureAppServerConnected(sessionId)
    const commands = await appServerStore.listCommands(currentSessionWorkRoot())
    commandCatalog.value = commands
      .map(item => toCoreCommandCatalogItem(item))
      .filter((item): item is CoreCommandCatalogItem => Boolean(item))
  } catch (err) {
    commandError.value = err instanceof Error ? err.message : String(err)
    runtimeStatusText.value = `命令列表加载失败：${commandError.value}`
    console.error('Failed to load composer commands:', err)
  }
}

watch(composerText, () => {
  if (commandPaletteDismissedText.value && commandPaletteDismissedText.value !== composerText.value) {
    commandPaletteDismissedText.value = ''
  }
  void nextTick(resizeComposerTextarea)
})

const activeSessionStatus = computed(() => {
  if (isAppServerActive.value && appServerStore.state) {
    return selectLatestTurnStatus(appServerStore.state)
  }
  if (appServerStore.connectionState === 'error') return 'failed'
  const active = sessions.value.find(session => session.id === activeSessionId.value)
  return normalizeSessionStatus(active?.status || 'idle')
})

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

const canGuideQueuedInput = computed(() =>
  activeSessionStatus.value === 'running' || activeSessionStatus.value === 'waiting',
)
const composerIsRunning = computed(() =>
  activeSessionStatus.value === 'running' || activeSessionStatus.value === 'waiting',
)
const composerActionMode = computed<'send' | 'stop'>(() =>
  composerIsRunning.value && !composerText.value.trim() && pendingAttachments.value.length === 0 ? 'stop' : 'send',
)

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

// Process collapse state (per-message; process = tool calls, thinking, etc.)
const processExpandedIds = ref<Set<string>>(new Set())

function toggleProcess(id: string) {
  const next = new Set(processExpandedIds.value)
  if (next.has(id)) {
    next.delete(id)
  } else {
    next.add(id)
  }
  processExpandedIds.value = next
}

function rebuildMessages() {
  messages.value = appServerMessages()
}

function hasProcessParts(message: CoreMessage): boolean {
  return (message.parts || []).some(part => part.partType !== 'text' && part.partType !== 'model_text')
}

function syncLiveProcessExpansion(status = activeSessionStatus.value) {
  const isActive = isActiveTurnStatus(status)
  if (!isActive) return
  const next = new Set(processExpandedIds.value)
  for (const message of messages.value) {
    if (message.role === 'assistant' && hasProcessParts(message)) {
      next.add(message.id)
    }
  }
  processExpandedIds.value = next
}

function syncActiveSessionListStatus(status = activeSessionStatus.value) {
  const sessionId = activeSessionId.value
  if (!sessionId) return
  const nextStatus = normalizeSessionStatus(status)
  const now = new Date().toISOString()
  const index = sessions.value.findIndex(item => item.id === sessionId)
  if (index >= 0 && sessions.value[index].status !== nextStatus) {
    const updated = [...sessions.value]
    updated[index] = {
      ...updated[index],
      status: nextStatus,
      updatedAt: now,
    } as CoreSessionListItem
    sessions.value = updated
  }
  const storeIndex = sessionStore.sessions.findIndex(item => item.id === sessionId)
  if (storeIndex >= 0 && sessionStore.sessions[storeIndex].status !== nextStatus) {
    sessionStore.sessions[storeIndex] = {
      ...sessionStore.sessions[storeIndex],
      status: nextStatus,
      updated_at: now,
    }
  }
}

function normalizeSessionStatus(status: string): string {
  const value = String(status || '').toLowerCase()
  if (value === 'active') return 'idle'
  if (value === 'running' || value === 'waiting' || value === 'completed' || value === 'failed') return value
  return 'idle'
}

function appServerMessages(): CoreMessage[] {
  if (!appServerStore.state) return buildSystemMessages()
  const sourceMessages = selectChatMessages(appServerStore.state)
  const lastAssistantIndex = sourceMessages.findLastIndex(message => message.role === 'assistant')
  const rendered = sourceMessages.map((message, index) => {
    const isActiveAssistant = index === lastAssistantIndex
      && message.role === 'assistant'
      && isActiveTurnStatus(activeSessionStatus.value)
    return {
    id: message.id,
    role: message.role,
    content: message.content,
    timestamp: '',
    parts: [
      ...message.parts.map(appServerItemToPart),
      ...(message.attachments || []).map((attachment) => ({
        id: `${message.id}:attachment:${attachment.id}`,
        partType: 'attachment' as const,
        status: 'completed' as const,
        content: '',
        label: attachment.label || attachment.filename,
        metadata: { attachment },
      })),
    ],
    metadata: {
      source: 'writer_app_server',
      ...(message.metadata || {}),
      live: message.metadata?.live,
      shallowThinkingPending: isActiveAssistant && shallowThinkingEnabled.value ? true : undefined,
    },
  } satisfies CoreMessage
  })
  return [...buildSystemMessages(), ...rendered]
}

function appServerItemToPart(item: WriterAppItem): MessagePart {
  const type = String(item.type || '')
  const requestId = typeof item.request_id === 'string' ? item.request_id : ''
  const requestState = requestStateForId(requestId)
  const partType: MessagePart['partType'] = type === 'dynamicToolCall'
    ? 'tool_call'
    : type === 'serverRequest'
      ? 'decision'
      : type === 'agentMessage'
        ? 'model_text'
        : appServerPartType(type)
  const isResolvedRequest = requestState?.status === 'resolved' || item.status === 'resolved'
  const isSubmittingRequest = requestId ? submittingApprovalRequestIds.value.has(requestId) : false
  const status = appServerPartStatus(String(item.status || ''), isResolvedRequest, isSubmittingRequest)
  const waitingResponse = requestState?.status === 'resolved'
    ? appServerDecisionToWaitingResponse(String(requestState.decision || ''), String(requestState.guidance || ''))
    : undefined
  return {
    id: item.item_id,
    partType,
    status,
    content: String(item.content || item.message || item.summary || ''),
    label: appServerPartLabel(item, partType),
    detail: String(item.message || item.summary || ''),
    toolName: typeof item.tool_name === 'string' ? item.tool_name : undefined,
    toolArgs: {
      ...(isRecord(item.arguments) ? item.arguments : {}),
      ...(Array.isArray(item.options) ? { options: item.options } : {}),
    },
    toolResult: typeof item.content === 'string' ? item.content : undefined,
    inputPreview: normalizeInputPreview(item.input_preview || item.inputPreview),
    metadata: {
      ...(isRecord(item.metadata) ? item.metadata : {}),
      request_id: requestId || undefined,
      title: item.title,
      question: item.question,
      description: item.description || item.message,
      options: item.options,
      waitingResponse,
      waitingRequest: requestId ? {
        kind: item.kind || 'approval',
        request_id: requestId,
        options: item.options,
        response: waitingResponse,
      } : undefined,
    },
  }
}

function normalizeInputPreview(value: unknown): MessagePart['inputPreview'] | undefined {
  if (!isRecord(value)) return undefined
  const content = typeof value.content === 'string' ? value.content : ''
  const field = typeof value.field === 'string' ? value.field : ''
  const chars = typeof value.chars === 'number' ? value.chars : content.length
  if (!content || !field) return undefined
  return {
    field,
    content,
    chars,
    truncated: value.truncated === true,
  }
}

function appServerPartLabel(item: WriterAppItem, partType: MessagePart['partType']): string {
  if (partType === 'model_text') return '正文'
  return String(item.tool_name || item.kind || partType)
}

function requestStateForId(requestId: string): WriterAppRequestState | null {
  if (!requestId) return null
  return appServerStore.state?.core?.requests?.[requestId] || appServerStore.state?.requests?.[requestId] || null
}

function appServerDecisionToWaitingResponse(decision: string, guidance: string): Record<string, unknown> {
  if (decision === 'deny') return { action: 'deny', response: guidance || 'deny' }
  if (decision === 'other_guidance') return { action: 'guide', response: guidance || 'guide' }
  if (decision === 'approve_once' || decision === 'approve_for_session') {
    return { action: 'approve', response: decision }
  }
  return { action: decision || 'handled', response: guidance || decision }
}

function appServerPartStatus(rawStatus: string, isResolvedRequest: boolean, isSubmittingRequest: boolean): MessagePart['status'] {
  if (isResolvedRequest) return 'completed'
  if (isSubmittingRequest) return 'running'
  if (rawStatus === 'waiting') return 'pending'
  if (rawStatus === 'failed') return 'error'
  if (rawStatus === 'completed' || rawStatus === 'error' || rawStatus === 'pending' || rawStatus === 'running') {
    return rawStatus
  }
  return 'running'
}

function appServerPartType(type: string): MessagePart['partType'] {
  if (type === 'reasoning') return 'reasoning'
  if (type === 'error') return 'error'
  if (type === 'fileChange') return 'file_diff'
  if (type === 'commandExecution') return 'command_output'
  if (type === 'dynamicToolCall' || type === 'mcpToolCall' || type === 'collabToolCall' || type === 'webSearch') return 'tool_call'
  if (type === 'agent_summary' || type === 'sub_line') return type
  if (type === 'toolResult') return 'tool_result'
  if (type === 'plan') return 'plan'
  if (type === 'contextCompaction' || type === 'compaction') return 'compaction'
  if (type === 'status') return 'status'
  if (type === 'imageView') return 'tool_result'
  return 'error'
}

function appServerQueuedInputs(): WriterQueuedInput[] {
  if (!appServerStore.state) return []
  if (!activeSessionId.value || appServerStore.state.thread_id !== activeSessionId.value) return []
  return selectQueueTray(appServerStore.state).map((item, index) => appServerQueueItemToWriterInput(item, index))
}

function appServerQueueItemToWriterInput(item: WriterAppQueueItem, index: number): WriterQueuedInput {
  return {
    id: item.queue_item_id,
    session_id: appServerStore.state?.thread_id || activeSessionId.value || '',
    text: inputToText(item.input),
    mode: String(item.mode || 'next_turn'),
    status: String(item.status || 'queued'),
    position: index + 1,
    target_turn_id: null,
    created_at: null,
    updated_at: null,
    dispatching_at: null,
    dispatched_at: null,
    consumed_at: null,
    error: null,
    metadata: { source: 'writer_app_server' },
  }
}

function inputToText(input: unknown): string {
  if (typeof input === 'string') return input
  if (!Array.isArray(input)) return ''
  return input.map((item) => {
    if (!isRecord(item)) return ''
    if (item.type === 'skill') return String(item.source_text || `/${item.name || ''}`)
    return String(item.text || '')
  }).join('')
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}

watch(
  [
    activeSessionStatus,
    () => appServerStore.state?.snapshot_seq,
  ],
  () => {
    rebuildMessages()
    syncActiveSessionListStatus()
    syncLiveProcessExpansion()
  },
  { immediate: true },
)

function isThreadNearBottom(): boolean {
  const el = threadScrollEl.value
  if (!el) return true
  return el.scrollHeight - el.scrollTop - el.clientHeight <= THREAD_BOTTOM_THRESHOLD_PX
}

function handleThreadWheel(event: WheelEvent) {
  if (event.deltaY < 0) {
    threadAutoFollow.value = false
  }
}

function handleThreadScroll() {
  if (isThreadNearBottom()) {
    threadAutoFollow.value = true
  }
}

function afterFrame(): Promise<void> {
  if (typeof requestAnimationFrame !== 'function') return Promise.resolve()
  return new Promise(resolve => requestAnimationFrame(() => resolve()))
}

function shouldReduceMotion(): boolean {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

async function scrollThreadToBottom(force = false, behavior: ScrollBehavior = 'auto') {
  await nextTick()
  const el = threadScrollEl.value
  if (!el) return
  if (!force && !threadAutoFollow.value) return
  if (behavior === 'smooth' && !shouldReduceMotion()) {
    el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    threadAutoFollow.value = true
    return
  }
  el.scrollTop = el.scrollHeight
  await afterFrame()
  el.scrollTop = el.scrollHeight
  threadAutoFollow.value = true
}

function syncThreadResizeObserver() {
  if (typeof ResizeObserver === 'undefined') return
  threadResizeObserver?.disconnect()
  threadResizeObserver = new ResizeObserver(() => {
    void scrollThreadToBottom()
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
    void scrollThreadToBottom()
  },
  { flush: 'post' },
)

watch(
  latestUserMessageId,
  (newId, oldId) => {
    if (!newId || oldId === undefined || newId === oldId) return
    threadAutoFollow.value = true
    void scrollThreadToBottom(true, 'smooth')
  },
  { flush: 'post' },
)

onMounted(() => {
  void refreshThreadResizeObserver()
  void scrollThreadToBottom(true)
})

onBeforeUnmount(() => {
  threadResizeObserver?.disconnect()
  threadResizeObserver = null
})

function buildSystemMessages(): CoreMessage[] {
  return []
}

// --- Project groups (real grouping from projectStore + sessionStore) ---
function projectGroupKey(p: { work_root: string; id: string }): string {
  return p.work_root || p.id
}

function projectGroupIdFromKey(key: string): string {
  return `project:${key}`
}

function orphanGroupIdFromKey(key: string): string {
  return `orphan:${key}`
}

function rawProjectGroupKeyFromId(projectGroupId: string): string {
  return projectGroupId.startsWith('project:') ? projectGroupId.slice('project:'.length) : projectGroupId
}

interface RawProjectGroup {
  key: string
  primary: { id: string; name: string; work_root: string; updated_at: string }
  projects: { id: string; name: string; work_root: string; updated_at: string }[]
  sessions: Session[]
}

interface SortableProjectGroup {
  group: ProjectGroup
  sortAt: string
}

const projectGroups = computed<ProjectGroup[]>(() => {
  const coreById = coreSessionById.value
  const groupedSessionIds = new Set<string>()
  // If no projects yet, show empty state — user must create a project first
  const rawGroups = new Map<string, RawProjectGroup>()
  for (const project of projectStore.projects) {
    const key = projectGroupKey(project as unknown as { work_root: string; id: string })
    const existing = rawGroups.get(key)
    if (existing) {
      existing.projects.push({
        id: project.id,
        name: project.name,
        work_root: project.work_root,
        updated_at: project.updated_at,
      })
    } else {
      rawGroups.set(key, {
        key,
        primary: {
          id: project.id,
          name: project.name,
          work_root: project.work_root,
          updated_at: project.updated_at,
        },
        projects: [
          {
            id: project.id,
            name: project.name,
            work_root: project.work_root,
            updated_at: project.updated_at,
          },
        ],
        sessions: [],
      })
    }
  }

  for (const group of rawGroups.values()) {
    group.projects.sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at))
    group.primary = group.projects[0]
    group.sessions = group.projects
      .flatMap((p) => sessionStore.sessionsByProject.get(p.id) || [])
      .sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at))
    for (const session of group.sessions) groupedSessionIds.add(session.id)
  }

  const groupedProjects: SortableProjectGroup[] = Array.from(rawGroups.values())
    .sort((a, b) => Date.parse(b.primary.updated_at) - Date.parse(a.primary.updated_at))
    .map((g) => {
      const latestSessionAt = g.sessions[0]?.updated_at || ''
      return {
        group: {
          id: projectGroupIdFromKey(g.key),
          name: projectDisplayName(g.primary),
          workRoot: g.primary.work_root,
          sessions: g.sessions.map(toSessionItem),
        },
        sortAt: latestTimestamp(g.primary.updated_at, latestSessionAt),
      }
    })

  const orphanGroups = sessions.value
    .filter((session) => !groupedSessionIds.has(session.id))
    .reduce((groups, session) => {
      const workRoot = coreSessionWorkRoot(session)
      const key = workRoot || `session:${session.id}`
      const group = groups.get(key) || {
        id: orphanGroupIdFromKey(key),
        name: workRoot ? projectDisplayName({ name: '', work_root: workRoot }) : '未归档会话',
        workRoot,
        sessions: [] as SessionItem[],
      }
      group.sessions.push(toCoreSessionItem(coreById.get(session.id) || session))
      groups.set(key, group)
      return groups
    }, new Map<string, ProjectGroup>())

  return [
    ...Array.from(orphanGroups.values()).map((group) => ({
      group,
      sortAt: latestTimestamp(...group.sessions.map((session) => session.updatedAt || session.createdAt || '')),
    })),
    ...groupedProjects,
  ]
    .sort((a, b) => timestampSortValue(b.sortAt) - timestampSortValue(a.sortAt))
    .map((item) => item.group)
})

const coreSessionById = computed(() => {
  const map = new Map<string, CoreSessionListItem>()
  for (const session of sessions.value) map.set(session.id, session)
  return map
})

function projectDisplayName(p: { name: string; work_root: string }): string {
  return p.name || p.work_root.split(/[/\\]/).filter(Boolean).pop() || '未命名项目'
}

function latestTimestamp(...values: string[]): string {
  let latest = ''
  let latestTime = Number.NEGATIVE_INFINITY
  for (const value of values) {
    const time = Date.parse(value)
    if (Number.isFinite(time) && time > latestTime) {
      latest = value
      latestTime = time
    }
  }
  return latest
}

function timestampSortValue(value: string): number {
  const time = Date.parse(value)
  return Number.isFinite(time) ? time : 0
}

function toSessionItem(s: Session): SessionItem {
  const core = coreSessionById.value.get(s.id)
  return {
    id: s.id,
    title: s.title || `Session ${s.id.slice(0, 8)}`,
    status: normalizeSessionStatus(core?.status || s.status || 'idle'),
    createdAt: s.created_at,
    updatedAt: core?.updatedAt || s.updated_at,
    metadata: { meta: `${s.phase || '?'} / ${s.mode || '?'}` },
  }
}

function toCoreSessionItem(s: CoreSessionListItem): SessionItem {
  return {
    id: s.id,
    title: s.title || `Session ${s.id.slice(0, 8)}`,
    status: normalizeSessionStatus(s.status || 'idle'),
    createdAt: s.createdAt,
    updatedAt: s.updatedAt,
    metadata: s.metadata,
  }
}

// --- Actions ---
async function handleStop() {
  if (!activeSessionId.value) return
  runtimeStatusText.value = '正在停止'
  try {
    if (!isAppServerActive.value) {
      await appServerStore.connect(api.API_BASE, activeSessionId.value)
    }
    await appServerStore.interruptTurn(activeSessionId.value)
  } catch (err) {
    console.error('Failed to cancel session:', err)
    runtimeStatusText.value = '停止失败'
  }
}

async function handleNewSession(projectGroupId: string) {
  const group = projectGroups.value.find((g) => g.id === projectGroupId)
  if (!group) {
    await newSession()
    return
  }

  const rawProjectGroupKey = rawProjectGroupKeyFromId(projectGroupId)
  const rawProject = projectStore.projects.find(
    (p) => projectGroupKey(p as unknown as { work_root: string; id: string }) === rawProjectGroupKey,
  )

  try {
    const session = await createCoreSession(
      'New Session',
      group.workRoot || '',
      rawProject?.id || null,
    )
    sessions.value.unshift(session)

    // Also push to sessionStore so the sidebar updates immediately
    const now = new Date().toISOString()
    sessionStore.sessions.unshift({
      id: session.id,
      title: session.title,
      work_root: group.workRoot || '',
      branch: null,
      phase: 'idle',
      mode: 'EXECUTE',
      status: normalizeSessionStatus(session.status || 'idle'),
      project_id: rawProject?.id || null,
      created_at: now,
      updated_at: now,
    })

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
      sessionStore.clearMessages()
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
  if (!text && pendingAttachments.value.length === 0 && composerActionMode.value === 'stop') {
    await handleStop()
    return
  }
  await submitWriterText(text, { clearComposer: true, attachments: attachmentInputItems.value })
}

function replaceActiveSlash(command: CoreCommandCatalogItem, replacement?: string): void {
  const span = commandPalette.activeSlash.value
  if (!span) return
  const nextText = replacement ?? (command.action === 'insert_token' ? `/${command.name}` : '')
  const updatedText = `${composerText.value.slice(0, span.start)}${nextText}${composerText.value.slice(span.end)}`
  composerText.value = updatedText
  if (command.action === 'insert_token') commandPaletteDismissedText.value = updatedText
  void nextTick(() => {
    const el = composerTextareaEl.value
    const cursor = span.start + nextText.length
    el?.focus()
    el?.setSelectionRange(cursor, cursor)
    updateComposerCursor()
    resizeComposerTextarea()
  })
}

async function selectComposerCommand(command: CoreCommandCatalogItem) {
  commandPalette.reset()
  if (command.action === 'insert_token') {
    replaceActiveSlash(command)
    return
  }
  replaceActiveSlash(command, `/${command.name}`)
  const ok = await executeComposerAction(command.name)
  if (ok) replaceActiveSlash(command, '')
  else commandPaletteDismissedText.value = composerText.value
}

async function executeComposerAction(command: string): Promise<boolean> {
  if (!activeSessionId.value) {
    setComposerError('请先选择会话')
    return false
  }
  if (composerIsRunning.value) {
    setComposerError('当前正在运行，请等本轮结束后再执行命令')
    return false
  }
  clearComposerError()
  try {
    await ensureAppServerConnected(activeSessionId.value)
    const result = await appServerStore.executeCommand(activeSessionId.value, command, currentSessionWorkRoot())
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

function buildComposerInputItems(text: string, attachments: CoreInputItem[]): CoreInputItem[] {
  const spans = parseComposerSyntax(text)
    .filter(span => span.kind === 'slash')
    .filter(span => Boolean(insertTokenCommand(span.value)))

  if (!spans.length) return [{ type: 'text', text }, ...attachments]

  const items: CoreInputItem[] = []
  let cursor = 0
  for (const span of spans) {
    if (span.start > cursor) items.push({ type: 'text', text: text.slice(cursor, span.start) })
    const command = insertTokenCommand(span.value)
    if (command) items.push({ type: 'skill', name: command.name, source_text: span.raw })
    cursor = span.end
  }
  if (cursor < text.length) items.push({ type: 'text', text: text.slice(cursor) })
  return [...items, ...attachments]
}

function standaloneActionCommand(text: string): string {
  const spans = parseComposerSyntax(text)
  if (spans.length !== 1) return ''
  const span = spans[0]
  if (span.kind !== 'slash') return ''
  if (text.slice(0, span.start).trim() || text.slice(span.end).trim()) return ''
  return actionCommand(span.value)?.name ?? ''
}

async function handleComposerKeydown(event: KeyboardEvent) {
  updateComposerCursor()
  if (commandPaletteVisible.value) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      commandPalette.move(1)
      return
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      commandPalette.move(-1)
      return
    }
    if (event.key === 'Escape') {
      event.preventDefault()
      commandPalette.reset()
      commandPaletteDismissedText.value = composerText.value
      return
    }
  }
  if (event.key === 'Enter' && (!event.shiftKey || commandPaletteVisible.value)) {
    await handleComposerEnter(event)
  }
}

async function handleComposerKeyup(event: KeyboardEvent) {
  updateComposerCursor()
  if (event.key !== 'Enter' || event.shiftKey) return
  if (Date.now() - lastComposerEnterHandledAt < COMPOSER_ENTER_FALLBACK_MS) return
  await handleComposerEnter(event)
}

async function handleComposerEnter(event: KeyboardEvent) {
  event.preventDefault()
  lastComposerEnterHandledAt = Date.now()
  if (commandPaletteVisible.value) {
    const selected = commandPalette.selected()
    if (selected) {
      await selectComposerCommand(selected)
      return
    }
  }
  await sendWriterTask()
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
  const attachments = options.attachments || []
  if (!cleaned && attachments.length === 0) return
  clearComposerError()

  const sessionId = await ensureActiveSession(cleaned.slice(0, 48))
  if (!sessionId) {
    setComposerError('请先新建项目并选择一个会话')
    composerText.value = cleaned
    return
  }

  const status = activeSessionStatus.value
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
  if ((status === 'running' || status === 'waiting') && attachments.length > 0) {
    setComposerError('当前正在运行，带附件的消息请等本轮结束后再发送')
    composerText.value = cleaned
    return
  }

  const standaloneCommand = attachments.length === 0 ? standaloneActionCommand(cleaned) : ''
  if (standaloneCommand) {
    const ok = await executeComposerAction(standaloneCommand)
    if (ok && options.clearComposer) clearComposerAfterPersisted(cleaned)
    if (!ok) composerText.value = cleaned
    return
  }

  if (status === 'running' || status === 'waiting') {
    const inputItems = buildComposerInputItems(cleaned, [])
    try {
      await appServerStore.queueInput(sessionId, inputItems)
      if (options.clearComposer) clearComposerAfterPersisted(cleaned)
      runtimeStatusText.value = '已加入待发送'
    } catch (err) {
      console.error('Failed to queue Writer task:', err)
      setComposerError(err instanceof Error ? err.message : '加入待发送失败')
      composerText.value = cleaned
    }
    return
  }

  const inputItems = buildComposerInputItems(cleaned, attachments)
  const runOk = await runWriterTask(sessionId, inputItems)
  if (runOk) {
    if (options.clearComposer) clearComposerAfterPersisted(cleaned)
    clearAttachments()
  } else if (options.clearComposer) {
    composerText.value = cleaned
  }
}

async function handleDecisionSelect(payload: DecisionSelectPayload) {
  const part = findMessagePart(payload.partId)
  const waitingRequest = part?.metadata?.waitingRequest
  if (activeSessionId.value && isAppServerActive.value && waitingRequest && typeof waitingRequest === 'object') {
    const requestId = String((waitingRequest as Record<string, unknown>).request_id || '')
    if (requestId) {
      try {
        submittingApprovalRequestIds.value = new Set([...submittingApprovalRequestIds.value, requestId])
        rebuildMessages()
        await appServerStore.respondApproval(requestId, appServerDecision(payload.option.id || payload.response), payload.response)
      } catch (err) {
        const next = new Set(submittingApprovalRequestIds.value)
        next.delete(requestId)
        submittingApprovalRequestIds.value = next
        rebuildMessages()
        console.error('Failed to respond approval:', err)
        runtimeStatusText.value = '授权处理失败'
      }
      return
    }
  }
  const text = payload.response.trim()
  if (!text) return
  if (!activeSessionId.value) {
    composerText.value = text
    return
  }
  await submitWriterText(text)
}

function appServerDecision(value: string): string {
  const normalized = value.trim().toLowerCase()
  if (normalized === 'approve' || normalized === 'accept' || normalized === 'approve_once') return 'approve_once'
  if (normalized === 'approve_for_session' || normalized === 'acceptforsession') return 'approve_for_session'
  if (normalized === 'deny' || normalized === 'decline' || normalized === 'cancel') return 'deny'
  return 'other_guidance'
}

function findMessagePart(partId: string) {
  for (const message of messages.value) {
    const part = message.parts?.find(item => item.id === partId)
    if (part) return part
  }
  return null
}

async function runWriterTask(sessionId: string, inputItems: CoreInputItem[]) {
  try {
    if (!isAppServerActive.value) {
      await appServerStore.connect(api.API_BASE, sessionId)
    }
    await appServerStore.startTurn(sessionId, inputItems, currentSessionWorkRoot(), currentThinkingOptions())
    runtimeStatusText.value = '已发送'
    clearComposerError()
    void listCoreSessions().then((refreshed) => {
      sessions.value = refreshed
    })
    return true
  } catch (err) {
    console.error('Failed to run Writer task:', err)
    setComposerError(err instanceof Error ? err.message : '发送失败')
    return false
  }
}

function currentSessionWorkRoot(): string {
  const active = sessions.value.find(session => session.id === activeSessionId.value)
  return active ? coreSessionWorkRoot(active) : ''
}

async function handleDeleteProject(projectGroupId: string) {
  const group = projectGroups.value.find((item) => item.id === projectGroupId)
  const rawProjectGroupKey = rawProjectGroupKeyFromId(projectGroupId)
  const rawGroup = projectStore.projects.find(
    (p) => projectGroupKey(p as unknown as { work_root: string; id: string }) === rawProjectGroupKey,
  )
  if (!rawGroup) {
    await handleDeleteOrphanProjectGroup(projectGroupId)
    return
  }
  const confirmed = window.confirm(`确定删除项目「${rawGroup.name || rawGroup.work_root}」？此操作不可撤销。`)
  if (!confirmed) return
  try {
    const deletedSessionIds = new Set((group?.sessions || []).map((session) => session.id))
    await projectStore.deleteProject(rawGroup.id)
    sessions.value = removeSessionsByIds(sessions.value, deletedSessionIds)
    sessionStore.removeSessions(deletedSessionIds)
    if (activeSessionId.value && deletedSessionIds.has(activeSessionId.value)) {
      appServerStore.disconnect()
      sessionStore.clearMessages()
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

async function handleDeleteOrphanProjectGroup(projectGroupId: string) {
  const group = projectGroups.value.find((item) => item.id === projectGroupId)
  if (!group) return
  const sessionIds = group.sessions.map((session) => session.id)
  if (sessionIds.length === 0) return
  const label = group.workRoot || group.name || '未归档会话'
  const confirmed = window.confirm(`确定删除工作区「${label}」下的 ${sessionIds.length} 个会话？此操作不可撤销。`)
  if (!confirmed) return
  try {
    for (const sessionId of sessionIds) {
      await sessionStore.deleteSession(sessionId)
    }
    const deleted = new Set(sessionIds)
    sessions.value = removeSessionsByIds(sessions.value, deleted)
    if (activeSessionId.value && deleted.has(activeSessionId.value)) {
      appServerStore.disconnect()
      sessionStore.clearMessages()
      const nextSession = sessions.value[0]
      if (nextSession) {
        await selectSession(nextSession.id)
      } else {
        await loadInitialData()
      }
    }
  } catch (err) {
    console.error('Failed to delete orphan project group:', err)
  }
}

function handleProjectContextMenu(projectGroupId: string) {
  const rawProjectGroupKey = rawProjectGroupKeyFromId(projectGroupId)
  const rawGroup = projectStore.projects.find(
    (p) => projectGroupKey(p as unknown as { work_root: string; id: string }) === rawProjectGroupKey,
  )
  if (!rawGroup) return
  // Open AGENTS.md for this project
  projectStore.fetchAgentsMd(rawGroup.id)
  showAgentsMd.value = true
  agentsMdProjectId.value = rawGroup.id
}

const showAgentsMd = ref(false)
const agentsMdProjectId = ref('')

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

async function removeQueuedInput(item: WriterQueuedInput) {
  try {
    await ensureAppServerConnected(item.session_id)
    if (editingQueuedInputId.value === item.id) {
      editingQueuedInputId.value = null
      queuedInputDraft.value = ''
    }
    await appServerStore.deleteQueueInput(item.session_id, item.id)
  } catch (err) {
    console.error('Failed to remove queued input:', err)
  }
}

async function beginEditQueuedInput(item: WriterQueuedInput) {
  if (item.status !== 'queued') return
  editingQueuedInputId.value = item.id
  queuedInputDraft.value = item.text
  await nextTick()
  document.querySelector<HTMLInputElement>(`[data-queued-input-edit="${item.id}"]`)?.focus()
}

function cancelEditQueuedInput() {
  editingQueuedInputId.value = null
  queuedInputDraft.value = ''
}

async function saveQueuedInput(item: WriterQueuedInput) {
  if (editingQueuedInputId.value !== item.id) return
  const text = queuedInputDraft.value.trim()
  if (!text) {
    cancelEditQueuedInput()
    return
  }
  try {
    await ensureAppServerConnected(item.session_id)
    if (text !== item.text) {
      await appServerStore.updateQueueInput(item.session_id, item.id, text)
    }
  } catch (err) {
    console.error('Failed to update queued input:', err)
  } finally {
    cancelEditQueuedInput()
  }
}

async function guideWithQueuedInput(item: WriterQueuedInput) {
  try {
    await ensureAppServerConnected(item.session_id)
    if (editingQueuedInputId.value === item.id) {
      await saveQueuedInput(item)
    }
    const activeTurnId = latestActiveAppServerTurnId()
    if (activeTurnId) {
      await appServerStore.steerTurn(item.session_id, activeTurnId, item.text)
      await appServerStore.deleteQueueInput(item.session_id, item.id)
    }
  } catch (err) {
    console.error('Failed to send queued input as guidance:', err)
  }
}

async function ensureAppServerConnected(sessionId: string) {
  if (!sessionId) throw new Error('No active Writer session')
  if (!isAppServerActive.value || appServerStore.connectionState !== 'open') {
    await appServerStore.connect(api.API_BASE, sessionId)
  }
}

function latestActiveAppServerTurnId(): string {
  const state = appServerStore.state
  const turns = state?.turns || {}
  const coreTurns = state?.core?.turns || {}
  const active = Object.values(turns)
    .filter((turn) => {
      const coreStatus = coreTurns[turn.turn_id]?.status
      const status = coreStatus || turn.status
      return status === 'running' || status === 'waiting'
    })
    .sort((a, b) => Number(b.seq || 0) - Number(a.seq || 0))
  return active[0]?.turn_id || ''
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
      status: normalizeSessionStatus(session.status || 'idle'),
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

// ── Reset process expansion on session change ──
watch(activeSessionId, (newId) => {
  void syncSessionUrl(newId ?? null)
  processExpandedIds.value = new Set()
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
  commandCatalog.value = []
  commandError.value = ''
  commandPaletteDismissedText.value = ''
  if (newId) {
    appServerStore.disconnect()
    // Reset session store messages
    sessionStore.clearMessages()
    // Reset step store
    void appServerStore.connect(api.API_BASE, newId)
      .then(() => loadCommandCatalog(newId))
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
  const index = sessions.value.findIndex(item => item.id === session.id)
  if (index < 0) return
  const updated = [...sessions.value]
  updated[index] = {
    ...updated[index],
    status: normalizeSessionStatus(session.status || 'idle'),
    updatedAt: session.updated_at || updated[index].updatedAt,
  } as CoreSessionListItem
  sessions.value = updated
  const storeIndex = sessionStore.sessions.findIndex(item => item.id === session.id)
  if (storeIndex >= 0) {
    sessionStore.sessions[storeIndex] = {
      ...sessionStore.sessions[storeIndex],
      status: normalizeSessionStatus(session.status || 'idle'),
      updated_at: session.updated_at || sessionStore.sessions[storeIndex].updated_at,
    }
  }
}

function upsertCreatedProjectSession(project: Project, session: CoreSessionListItem) {
  const createdAt = session.createdAt || new Date().toISOString()
  const updatedAt = session.updatedAt || createdAt

  const coreIndex = sessions.value.findIndex(item => item.id === session.id)
  if (coreIndex >= 0) {
    const updated = [...sessions.value]
    updated[coreIndex] = { ...updated[coreIndex], ...session }
    sessions.value = updated
  } else {
    sessions.value = [session, ...sessions.value]
  }

  const storeSession: Session = {
    id: session.id,
    title: session.title || 'New Session',
    work_root: project.work_root,
    branch: null,
    phase: 'idle',
    mode: 'EXECUTE',
    status: normalizeSessionStatus(session.status || 'idle'),
    project_id: project.id,
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

function isActiveTurnStatus(status: string) {
  return status === 'running' || status === 'waiting'
}

// ── Auto-collapse process when run finishes ──
watch(
  () => activeSessionStatus.value,
  (nowStatus, wasStatus) => {
    const nowRunning = isActiveTurnStatus(nowStatus)
    const wasRunning = isActiveTurnStatus(String(wasStatus))
    syncActiveSessionListStatus(nowStatus)
    if (nowRunning) {
      syncLiveProcessExpansion(nowStatus)
    }
    if (!nowRunning && wasRunning) {
      processExpandedIds.value = new Set()
      void loadReviewChanges()
    }
  },
)

async function saveAgentsMd() {
  await projectStore.saveAgentsMd(agentsMdProjectId.value, projectStore.agentsMdContent)
  showAgentsMd.value = false
}

const showNewProject = ref(false)
const newProjectWorkRoot = ref('')
const newProjectName = ref('')
const selectingProjectDirectory = ref(false)

function resetNewProjectForm() {
  showNewProject.value = false
  newProjectWorkRoot.value = ''
  newProjectName.value = ''
}

async function browseProjectDirectory() {
  selectingProjectDirectory.value = true
  try {
    const selected = await pickProjectDirectory({
      desktop: window.lamwriterDesktop,
      appServerPickDirectory: api.pickProjectDirectory,
    })
    if (!selected.path) {
      if (selected.message) window.alert(selected.message)
      return
    }
    newProjectWorkRoot.value = selected.path
    if (!newProjectName.value.trim()) {
      newProjectName.value = projectNameFromPath(selected.path)
    }
  } finally {
    selectingProjectDirectory.value = false
  }
}

async function handleNewProject() {
  const workRoot = newProjectWorkRoot.value.trim()
  if (!workRoot) return
  try {
    const project = await projectStore.createProject({
      name: newProjectName.value.trim() || workRoot.split(/[/\\]/).filter(Boolean).pop() || '未命名',
      work_root: workRoot,
    })
    const session = await createCoreSession('New Session', project.work_root, project.id)
    upsertCreatedProjectSession(project, session)
    resetNewProjectForm()
    await router.push({ name: 'workbench' }).catch(() => undefined)
    await selectSession(session.id)
    await Promise.all([
      sessionStore.fetchSessions(),
      projectStore.fetchProjects(),
    ])
    upsertCreatedProjectSession(project, session)
    await selectSession(session.id)
  } catch (err) {
    console.error('Failed to create project:', err)
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
  syncSelectedModel()
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
    @new-session="newSession"
    @settings="router.push('/settings')"
    @composer-submit="sendWriterTask"
    @composer-drop="handleComposerDrop"
  >
    <!-- Header action: replace default "+" with project-aware menu -->
    <template #sidebar-header-action>
      <div class="header-new-menu">
        <button class="icon-btn" title="新建项目" @click="showNewProject = !showNewProject">+</button>
        <div v-if="showNewProject" class="new-project-popover" @keydown.esc="resetNewProjectForm">
          <div class="new-project-head">
            <strong>新建项目</strong>
          </div>
          <label class="new-project-field">
            <span>项目名称</span>
            <input v-model="newProjectName" placeholder="可选" class="field-input" @keydown.enter="handleNewProject" />
          </label>
          <label class="new-project-field">
            <span>工作目录</span>
            <div class="path-picker-row">
              <input v-model="newProjectWorkRoot" placeholder="选择或输入绝对路径" class="field-input" @keydown.enter="handleNewProject" />
              <button
                type="button"
                class="btn-secondary-sm"
                :disabled="selectingProjectDirectory"
                @click="browseProjectDirectory"
              >
                {{ selectingProjectDirectory ? '选择中' : '浏览' }}
              </button>
            </div>
          </label>
          <div class="popover-actions">
            <button class="btn-cancel" @click="resetNewProjectForm">取消</button>
            <button class="btn-primary-sm" :disabled="!newProjectWorkRoot.trim()" @click="handleNewProject">新建项目</button>
          </div>
        </div>
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
        @scroll.passive="handleThreadScroll"
        @wheel.passive="handleThreadWheel"
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
          >
            <template #assistant-content="slotProps">
              <MarkdownRenderer
                v-if="slotProps.content"
                :content="slotProps.content"
                :streaming="Boolean((slotProps as { live?: boolean }).live)"
              />
            </template>
            <template #reasoning-content="slotProps">
              <MarkdownRenderer
                v-if="slotProps.content"
                :content="slotProps.content"
                :streaming="Boolean((slotProps as { live?: boolean }).live)"
              />
            </template>
          </ChatThread>
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
      <div v-if="queuedInputs.length" class="queued-input-tray" aria-label="待发送输入">
        <div v-for="(item, index) in queuedInputs" :key="item.id" class="queued-input-row">
          <div class="queued-input-copy">
            <span class="queued-input-status">{{ index + 1 }}.</span>
            <input
              v-if="editingQueuedInputId === item.id"
              v-model="queuedInputDraft"
              class="queued-input-edit"
              :data-queued-input-edit="item.id"
              @blur="saveQueuedInput(item)"
              @keydown.enter.prevent="saveQueuedInput(item)"
              @keydown.esc.prevent="cancelEditQueuedInput"
            />
            <span v-else class="queued-input-text">{{ item.text }}</span>
          </div>
          <div class="queued-input-actions">
            <button
              class="queued-input-icon-action"
              type="button"
              :disabled="item.status !== 'queued'"
              title="编辑"
              aria-label="编辑待发送内容"
              @click="beginEditQueuedInput(item)"
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M12 20h9" />
                <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4 11.5-11.5Z" />
              </svg>
            </button>
            <button
              type="button"
              :disabled="!canGuideQueuedInput || item.status !== 'queued'"
              @click="guideWithQueuedInput(item)"
            >
              引导
            </button>
            <button
              class="queued-input-icon-action"
              type="button"
              :disabled="item.status === 'dispatching'"
              title="删除"
              aria-label="删除待发送内容"
              @click="removeQueuedInput(item)"
            >
              ×
            </button>
          </div>
        </div>
      </div>
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
          @select="selectComposerCommand"
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
      <div class="composer-model-row">
        <button
          class="composer-attachment-button"
          type="button"
          title="添加附件"
          aria-label="添加附件"
          @click="attachmentFileInput?.click()"
        >
          +
        </button>
        <UiSelect
          v-if="modelOptions.length > 0"
          class="composer-model-select"
          :model-value="selectedModelId"
          :options="modelOptions"
          placeholder="选择模型..."
          direction="up"
          @update:model-value="selectModel"
        />
        <UiSelect
          class="composer-thinking-select"
          :model-value="selectedThinkingMode"
          :options="thinkingModeOptions"
          :placeholder="selectedThinkingLabel"
          direction="up"
          @update:model-value="selectThinkingMode"
        />
        <button
          class="composer-shallow-toggle"
          :class="{ active: shallowThinkingEnabled }"
          type="button"
          title="Shallow thinking"
          aria-label="Shallow thinking"
          :aria-pressed="shallowThinkingEnabled"
          @click="toggleShallowThinking"
        >
          Shallow
        </button>
      </div>
    </template>

    <template #composer-action>
      <button
        class="send"
        :class="{ 'send--stop': composerActionMode === 'stop' }"
        type="submit"
        :disabled="composerActionMode === 'send' && !composerText.trim() && pendingAttachments.length === 0"
        :title="composerActionMode === 'stop' ? '停止运行' : '发送'"
        :aria-label="composerActionMode === 'stop' ? '停止运行' : '发送'"
        @click.prevent="sendWriterTask"
      >{{ composerActionMode === 'stop' ? 'stop' : 'send' }}</button>
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
      <div v-if="showAgentsMd" class="modal-overlay" @click.self="showAgentsMd = false">
        <div class="modal-card wide">
          <h2>AGENTS.md</h2>
          <textarea
            :value="projectStore.agentsMdContent"
            class="agents-editor"
            @input="projectStore.agentsMdContent = ($event.target as HTMLTextAreaElement).value"
          />
          <div class="modal-actions">
            <button @click="showAgentsMd = false">取消</button>
            <button class="btn-primary" @click="saveAgentsMd">保存配置</button>
          </div>
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

:deep(.composer-model-select) {
  width: auto;
  min-width: 0;
}

:deep(.composer-thinking-select),
:deep(.composer-model-select) {
  width: auto;
  min-width: 0;
}

:deep(.composer-thinking-select .ui-select-trigger),
:deep(.composer-model-select .ui-select-trigger) {
  width: auto;
  min-width: 0;
  min-height: 28px;
  height: 28px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  padding: 0 26px 0 8px;
  color: color-mix(in srgb, var(--theme-composer-text, currentColor) 76%, transparent);
  font-size: 12px;
  font-weight: 600;
}

:deep(.composer-thinking-select .ui-select-trigger:hover),
:deep(.composer-thinking-select.open .ui-select-trigger),
:deep(.composer-model-select .ui-select-trigger:hover),
:deep(.composer-model-select.open .ui-select-trigger) {
  background: color-mix(in srgb, var(--theme-composer-text, currentColor) 8%, transparent);
  color: var(--theme-composer-text, currentColor);
}

:deep(.composer-thinking-select .ui-select-trigger:focus-visible),
:deep(.composer-model-select .ui-select-trigger:focus-visible) {
  outline: 2px solid color-mix(in srgb, var(--theme-composer-text, currentColor) 26%, transparent);
  outline-offset: 2px;
}

:deep(.composer-thinking-select .ui-select-arrow),
:deep(.composer-model-select .ui-select-arrow) {
  right: 10px;
}

.composer-shallow-toggle {
  height: 28px;
  padding: 0 10px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: color-mix(in srgb, var(--theme-composer-text, currentColor) 70%, transparent);
  box-shadow: none;
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  line-height: 28px;
  cursor: pointer;
}

.composer-shallow-toggle:hover {
  background: color-mix(in srgb, var(--theme-composer-text, currentColor) 8%, transparent);
  color: var(--theme-composer-text, currentColor);
}

.composer-shallow-toggle.active {
  background: transparent;
  color: var(--green);
  box-shadow: none;
}

.composer-shallow-toggle:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--theme-composer-text, currentColor) 26%, transparent);
  outline-offset: 2px;
}

:global(.floating-composer:has(.composer-thinking-select.open)),
:global(.floating-composer:has(.composer-model-select.open)),
:global(.floating-composer:has(.command-palette)),
:global(.floating-composer:has(.queued-input-tray)) {
  overflow: visible;
}

:deep(.composer-thinking-select .ui-select-menu),
:deep(.composer-model-select .ui-select-menu) {
  z-index: var(--z-popover, 60);
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

.composer-input-wrap {
  position: relative;
  min-width: 0;
}

.composer-feedback {
  margin: 0 0 8px;
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 13px;
  line-height: 1.35;
}

.composer-feedback--error {
  border: 1px solid color-mix(in srgb, #ef4444 34%, transparent);
  background: color-mix(in srgb, #ef4444 10%, transparent);
  color: color-mix(in srgb, #fecaca 72%, var(--theme-composer-text, currentColor));
}

.composer-input-wrap textarea {
  position: relative;
  z-index: 1;
}

.composer-input-wrap.has-command-tokens textarea {
  color: transparent;
  caret-color: var(--theme-composer-text, currentColor);
}

.composer-input-wrap.has-command-tokens textarea::placeholder {
  color: color-mix(in srgb, var(--theme-composer-text, currentColor) 52%, transparent);
}

.composer-syntax-overlay {
  position: absolute;
  inset: 0;
  z-index: 0;
  min-height: 42px;
  max-height: 190px;
  overflow: hidden;
  padding: 13px 16px 7px;
  color: var(--theme-composer-text, currentColor);
  font-size: 15px;
  line-height: 1.45;
  pointer-events: none;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.composer-skill-token {
  border-radius: 4px;
  background: color-mix(in srgb, #8ecbff 16%, transparent);
  color: #8ecbff;
}

.queued-input-tray {
  display: grid;
  position: absolute;
  z-index: 4;
  left: var(--queued-input-left-inset, 20px);
  bottom: 100%;
  width: calc(100% - var(--composer-side-width, 58px) - var(--queued-input-left-inset, 20px) - var(--queued-input-right-inset, 0px));
  margin: 0;
}

.queued-input-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  min-height: 42px;
  padding: 0 12px 0 16px;
  border: 1px solid color-mix(in srgb, var(--theme-composer-text, currentColor) 12%, transparent);
  border-bottom-width: 0;
  background: var(--theme-composer-background);
}

.queued-input-row:first-child {
  border-radius: 10px 10px 0 0;
}

.queued-input-row + .queued-input-row {
  border-top-color: color-mix(in srgb, var(--theme-composer-text, currentColor) 8%, transparent);
}

.queued-input-copy {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 9px;
  min-height: 28px;
  font-size: 13px;
}

.queued-input-status {
  flex: 0 0 auto;
  color: color-mix(in srgb, var(--theme-composer-text, currentColor) 64%, transparent);
  font-weight: 700;
}

.queued-input-text {
  min-width: 0;
  overflow: hidden;
  color: var(--theme-composer-text, currentColor);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.queued-input-edit {
  min-width: 0;
  width: 100%;
  height: 28px;
  border: 1px solid color-mix(in srgb, var(--theme-composer-text, currentColor) 18%, transparent);
  border-radius: 6px;
  background: color-mix(in srgb, var(--theme-composer-background, transparent) 82%, transparent);
  color: var(--theme-composer-text, currentColor);
  padding: 0 8px;
  font: inherit;
  outline: none;
}

.queued-input-edit:focus {
  border-color: color-mix(in srgb, var(--theme-composer-text, currentColor) 34%, transparent);
}

.queued-input-actions {
  display: flex;
  flex: 0 0 auto;
  gap: 4px;
  justify-content: flex-end;
  white-space: nowrap;
}

.queued-input-actions button {
  min-width: 32px;
  height: 28px;
  padding: 0 8px;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  color: var(--theme-composer-text, currentColor);
  font-size: 12px;
  font-weight: 800;
  line-height: 1;
}

.queued-input-actions button:hover:not(:disabled) {
  border-color: color-mix(in srgb, var(--theme-composer-text, currentColor) 16%, transparent);
  background: color-mix(in srgb, var(--theme-composer-text, currentColor) 12%, transparent);
}

.queued-input-actions button:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.queued-input-icon-action {
  display: inline-grid;
  place-items: center;
  width: 28px;
  padding: 0;
  font-size: 18px;
}

.queued-input-icon-action svg {
  width: 15px;
  height: 15px;
  fill: none;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 2;
}

.send {
  width: 54px;
  height: 30px;
  border: 1px solid color-mix(in srgb, var(--theme-control-text) 12%, transparent);
  border-radius: 9px;
  background: color-mix(in srgb, var(--theme-control-background) 70%, transparent);
  color: color-mix(in srgb, var(--theme-control-text) 72%, transparent);
  display: grid;
  place-items: center;
  font-size: 12px;
  font-weight: 850;
  line-height: 1;
}

.send--stop {
  border-color: color-mix(in srgb, var(--red) 28%, transparent);
  background: color-mix(in srgb, var(--red) 12%, var(--theme-control-background));
  color: var(--red);
}

.send--stop:hover {
  background: color-mix(in srgb, var(--red) 18%, var(--theme-control-background));
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
  .queued-input-row {
    min-height: 42px;
    padding: 0 10px 0 12px;
  }

  .queued-input-copy {
    gap: 7px;
  }

  .queued-input-actions {
    gap: 2px;
  }

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
