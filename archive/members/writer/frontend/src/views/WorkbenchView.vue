<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useProjectStore } from '@/stores/project'
import { useSessionStore } from '@/stores/session'
import { useStepStore } from '@/stores/step'
import { useSseStore } from '@/stores/sse'
import { useConfigStore } from '@/stores/config'
import * as api from '@/api'
import type { Attachment, ChatRequest, GitVersionGraph, Message, Project, ReplyAttachment, Session, SessionChanges, Step } from '@/types'
import type { RuntimeActivity } from '@/stores/sse'
import { defaultTheme, normalizeColor, clampNumber, normalizeGradientStops, gradientFromStops, rgbaFromHex, hexToRgb } from '@/lib/theme'
import type { ThemeStop } from '@/lib/theme'
import { statusLabel, phaseLabel, stepKindLabel, runtimeTextLabel, formatTime, shortSha, stringValue, normalizeMessageText, numberValue, businessText, isTechnicalNoise, technicalReasonLabel, workflowPhaseLabel, localizeStatusWords, formatDurationMs, activityGroupMeta, activityGroupOrder } from '@/lib/labels'
import type { RuntimeActivityGroup } from '@/lib/labels'
import type { RuntimeBlock, AgentSummary, AgentProgressLine, AgentLogView, ProjectGroup, ProjectSessionMode, ReviewMode, DecisionView, DecisionPlanStepView, DecisionPlanView, ActivityGroupView, LifecycleView, PlanProgressView, ReplyAttachmentPreview, RuntimeGroup, TranscriptItem, DiffRow, DiffBlock, DiffFileView } from '@/lib/runtime-types'
import { runtimeBlockClass, isCompletedRuntime, isAgentRuntimeBlock, formatRuntimeGroupDuration, processedGroupTitle, summarizeDetails, escapeHtml, renderMarkdown, renderReply, parseUnifiedDiff } from '@/lib/runtime-helpers'

const router = useRouter()
const projectStore = useProjectStore()
const sessionStore = useSessionStore()
const stepStore = useStepStore()
const sseStore = useSseStore()
const configStore = useConfigStore()

const messageInput = ref('')
const selectedMode = ref('EXECUTE')
const qualityMode = ref('auto')
const selectedModel = ref('')
const showModelMenu = ref(false)
const showQualityMenu = ref(false)
const showNewProject = ref(false)
const showNewSession = ref(false)
const showAgentsMd = ref(false)
const newProjectRoot = ref('')
const newSessionTitle = ref('')
const expandedSteps = ref<Set<string>>(new Set())
const previousAgentStatuses = ref<Record<string, string>>({})
const runtimeProcessedExpanded = ref(false)
const activityProcessedExpanded = ref(false)
const showChangeReview = ref(false)
const showUndoConfirm = ref(false)
const replyAttachmentPreview = ref<ReplyAttachmentPreview | null>(null)
const diffWrap = ref(true)
const selectedDiffPath = ref('')
const messagesArea = ref<HTMLElement | null>(null)
const mainArea = ref<HTMLElement | null>(null)
const composerEl = ref<HTMLElement | null>(null)
const messageBox = ref<HTMLTextAreaElement | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const errorText = ref('')
const noticeText = ref('')
const gitGraph = ref<GitVersionGraph | null>(null)
const sessionAttachments = ref<Attachment[]>([])
const pendingAttachments = ref<Attachment[]>([])
const uploadingAttachment = ref(false)
const gitError = ref('')
const sessionChanges = ref<SessionChanges | null>(null)
const changesError = ref('')
const undoingChanges = ref(false)
const leftOpen = ref(true)
const rightOpen = ref(false)
const leftPinned = ref(true)
const rightPinned = ref(false)
const dragOver = ref(false)
const runStartedAt = ref<number | null>(null)
const lastElapsedMs = ref(0)
const elapsedNow = ref(Date.now())
const uiSettings = ref({
  density: 'standard',
  contentWidth: 780,
  showGitGraph: true,
  showRuntime: true,
  theme: { ...defaultTheme },
})
const projectSessionModes = reactive<Record<string, ProjectSessionMode>>({})
let elapsedTimer: number | undefined

const modelOptions = computed(() => {
  if (configStore.models.length === 0) return [{ value: 'glm5.1', label: 'glm5.1', providerId: 'local' }]
  return configStore.models.map((model) => ({
    value: model.id,
    label: model.display_name || model.model_id,
    providerId: model.provider_id,
  }))
})

const modelGroups = computed(() => {
  if (configStore.models.length === 0) {
    return [{ providerId: 'local', providerName: 'Local', models: [{ value: 'glm5.1', label: 'glm5.1' }] }]
  }
  return configStore.providers.map((provider) => ({
    providerId: provider.id,
    providerName: provider.name,
    models: modelOptions.value.filter((model) => model.providerId === provider.id),
  })).filter((group) => group.models.length > 0)
})

const selectedModelLabel = computed(() => {
  const option = modelOptions.value.find((item) => item.value === selectedModel.value)
  return option?.label || modelOptions.value[0]?.label || 'glm5.1'
})

const qualityOptions = [
  { value: 'auto', note: '默认' },
  { value: 'toy', note: '玩具级' },
  { value: 'low', note: '轻量' },
  { value: 'medium', note: '平衡' },
  { value: 'high', note: '高质量' },
  { value: 'crazy', note: '不推荐' },
]

const canSend = computed(() => Boolean(
  (messageInput.value.trim() || pendingAttachments.value.length > 0)
  && sessionStore.activeSession
  && (!sseStore.running || sseStore.awaitingUser),
))

const shellClass = computed(() => ({
  'left-open': leftOpen.value,
  'right-open': rightOpen.value,
  [`density-${uiSettings.value.density}`]: true,
}))

const shellStyle = computed(() => {
  const theme = normalizeTheme(uiSettings.value.theme)
  return {
    '--content-width': `${Math.min(1120, Math.max(560, Number(uiSettings.value.contentWidth) || 780))}px`,
    '--theme-backdrop-background': gradientFromStops(theme.backdropAngle, theme.backdropStops, 1),
    '--theme-backdrop-text': theme.backdropText,
    '--theme-main-background': gradientFromStops(theme.mainAngle, theme.mainStops, theme.mainOpacity),
    '--theme-main-text': theme.mainText,
    '--theme-composer-background': gradientFromStops(theme.composerAngle, theme.composerStops, theme.composerOpacity),
    '--theme-composer-text': theme.composerText,
    '--theme-control-background': gradientFromStops(theme.controlAngle, theme.controlStops, theme.controlOpacity),
    '--theme-control-text': theme.controlText,
  }
})

const projectGroups = computed<ProjectGroup[]>(() => {
  const groups = new Map<string, ProjectGroup>()
  for (const project of projectStore.projects) {
    const key = projectGroupKey(project)
    const existing = groups.get(key)
    if (existing) {
      existing.projects.push(project)
    } else {
      groups.set(key, { key, primary: project, projects: [project], sessions: [] })
    }
  }
  for (const group of groups.values()) {
    group.projects.sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at))
    group.primary = group.projects[0]
    group.sessions = group.projects
      .flatMap((project) => sessionStore.sessionsByProject.get(project.id) || [])
      .sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at))
  }
  return Array.from(groups.values()).sort((a, b) => (
    Date.parse(b.primary.updated_at) - Date.parse(a.primary.updated_at)
  ))
})

const elapsedText = computed(() => {
  if (!runStartedAt.value && !lastElapsedMs.value) return '暂无任务'
  const start = runStartedAt.value
  const ms = start ? elapsedNow.value - start : lastElapsedMs.value
  const seconds = Math.max(0, Math.floor(ms / 1000))
  const minutes = Math.floor(seconds / 60)
  const remain = seconds % 60
  return minutes > 0 ? `${minutes}m ${remain}s` : `${remain}s`
})

const runtimeBlocks = computed<RuntimeBlock[]>(() => {
  const blocks: RuntimeBlock[] = []
  let readonlyGroup: Step[] = []
  let agentGroup: Step[] = []

  const flushReadonly = () => {
    if (!readonlyGroup.length) return
    blocks.push(makeReadonlyBlock(readonlyGroup))
    readonlyGroup = []
  }
  const flushAgent = () => {
    if (!agentGroup.length) return
    blocks.push(makeAgentBlock(agentGroup))
    agentGroup = []
  }

  for (const step of stepStore.steps) {
    if (isReadonlyStep(step)) {
      flushAgent()
      readonlyGroup.push(step)
      continue
    }
    if (isAgentStep(step)) {
      flushReadonly()
      agentGroup.push(step)
      continue
    }
    flushReadonly()
    flushAgent()
    blocks.push(makeRuntimeBlock(step))
  }
  flushReadonly()
  flushAgent()
  return blocks
})

const transcriptItems = computed<TranscriptItem[]>(() => {
  const messageItems: TranscriptItem[] = visibleTranscriptMessages().map((message) => ({
    kind: 'message',
    id: message.id,
    createdAt: message.created_at,
    message,
  }))
  return [...messageItems, ...runtimeBlocks.value].sort((a, b) => {
    const at = new Date(a.createdAt).getTime()
    const bt = new Date(b.createdAt).getTime()
    if (Number.isNaN(at) || Number.isNaN(bt)) return 0
    return at - bt
  })
})

function visibleTranscriptMessages(): Message[] {
  const persistedReplyTexts = new Set(
    sessionStore.messages
      .filter((message) => isReplyMessage(message) && !message.id.startsWith('local-reply'))
      .map((message) => normalizeMessageText(message.content)),
  )
  const seenReplies = new Set<string>()
  return sessionStore.messages.filter((message) => {
    if (!isReplyMessage(message)) return true
    const text = normalizeMessageText(message.content)
    if (!text) return true
    if (message.id.startsWith('local-reply') && persistedReplyTexts.has(text)) return false
    if (seenReplies.has(text)) return false
    seenReplies.add(text)
    return true
  })
}

const replyTimes = computed(() => sessionStore.messages
  .filter((message) => isReplyMessage(message))
  .map((message) => new Date(message.created_at).getTime())
  .filter((time) => !Number.isNaN(time)))

const hasVisibleReply = computed(() => Boolean(sseStore.assistantDraft) || replyTimes.value.length > 0)

const displayTranscriptItems = computed<TranscriptItem[]>(() => {
  const out: TranscriptItem[] = []
  let runtimeRun: RuntimeBlock[] = []

  const flushRun = () => {
    if (!runtimeRun.length) return
    const group: RuntimeGroup = {
      kind: 'runtime-group',
      id: `processed-${runtimeRun[0]?.id}-${runtimeRun[runtimeRun.length - 1]?.id}`,
      createdAt: runtimeRun[0]?.createdAt || new Date().toISOString(),
      title: processedGroupTitle(runtimeRun),
      blocks: runtimeRun,
    }
    out.push(group)
    if (runtimeProcessedExpanded.value) out.push(...runtimeRun)
    runtimeRun = []
  }

  for (const item of transcriptItems.value) {
    if (item.kind === 'runtime' && shouldFoldRuntimeBlock(item)) {
      runtimeRun.push(item)
      continue
    }
    flushRun()
    out.push(item)
  }
  flushRun()
  return out
})

const showProcessingPlaceholder = computed(() => {
  if (!sseStore.running || sseStore.assistantDraft) return false
  return !runtimeBlocks.value.some((block) => block.status === 'running' || block.status === 'in_progress')
})

const activeSessionStale = computed(() => {
  const session = sessionStore.activeSession
  if (!session || session.status !== 'active' || sseStore.running || sseStore.awaitingUser) return false
  if (!stepStore.steps.length) return false
  return !stepStore.steps.some((step) => step.status === 'running' || step.status === 'in_progress')
})

const planProgressView = computed<PlanProgressView | null>(() => {
  const progress = sseStore.latestProgress?.plan_progress
  if (!progress) return null
  const total = numberValue(progress.total ?? progress.total_steps, 0)
  const completed = numberValue(progress.completed, 0)
  const failed = numberValue(progress.failed, 0)
  const pctSource = progress.pct ?? progress.progress_pct
  const pct = clampNumber(
    numberValue(pctSource, total > 0 ? (completed / total) * 100 : 0),
    0,
    100,
    0,
  )
  const currentStep = businessText(String(progress.current_step || ''))
  const nextStep = businessText(String(progress.next_step || ''))
  if (total <= 0 && completed <= 0 && failed <= 0 && !currentStep && !nextStep) return null
  return { total, completed, failed, pct, currentStep, nextStep }
})

const workflowLabel = computed(() => {
  const workflow = sseStore.latestProgress?.workflow
  const record = workflow && typeof workflow === 'object' ? workflow as Record<string, unknown> : {}
  const phase = String(record.phase || '')
  return phase ? workflowPhaseLabel(phase) : ''
})

const activeSessionActivities = computed(() => {
  const sessionId = sessionStore.activeSession?.id
  if (!sessionId) return []
  return sseStore.activityFeed.filter((item) => item.session_id === sessionId)
})

const activityGroupViews = computed<ActivityGroupView[]>(() => {
  const grouped = new Map<RuntimeActivity['group'], RuntimeActivity[]>()
  for (const item of activeSessionActivities.value) {
    const list = grouped.get(item.group) || []
    list.push(item)
    grouped.set(item.group, list)
  }
  return activityGroupOrder
    .map((group) => {
      const items = grouped.get(group) || []
      if (!items.length) return null
      const latest = items[items.length - 1]
      const visibleItems = activityProcessedExpanded.value ? items : items.slice(-5)
      return {
        group,
        label: activityGroupMeta[group],
        status: latest.status,
        count: items.length,
        items: visibleItems,
        hiddenCount: Math.max(0, items.length - visibleItems.length),
      }
    })
    .filter((item): item is ActivityGroupView => Boolean(item))
})

const showActivityFlow = computed(() => activeSessionActivities.value.length > 0 && !hasVisibleReply.value)
const hasFoldedRuntimeProcess = computed(() => displayTranscriptItems.value.some((item) => item.kind === 'runtime-group'))
const showActivityProcessedRow = computed(() => activeSessionActivities.value.length > 0 && hasVisibleReply.value && !hasFoldedRuntimeProcess.value)
const showActivityProcessedDetails = computed(() => (
  activeSessionActivities.value.length > 0
  && hasVisibleReply.value
  && activityProcessedExpanded.value
))

const editedFiles = computed(() => {
  if (sessionChanges.value?.files.length) {
    return sessionChanges.value.files.map((file) => ({
      path: file.path,
      count: 0,
      additions: file.additions,
      deletions: file.deletions,
      binary: file.binary,
      source: 'git',
    }))
  }
  const files = new Map<string, { path: string; count: number }>()
  for (const block of runtimeBlocks.value) {
    if (block.blockType !== 'write') continue
    for (const step of block.steps) {
      const path = stepTarget(step)
      if (!path) continue
      const existing = files.get(path)
      files.set(path, { path, count: (existing?.count || 0) + 1 })
    }
  }
  return Array.from(files.values()).map((file) => ({
    ...file,
    additions: null,
    deletions: null,
    binary: false,
    source: 'step',
  }))
})

const reviewMode = computed<ReviewMode>(() => {
  if (sessionChanges.value?.files.length) return 'diff'
  return 'record'
})

const changeReviewTitle = computed(() => {
  if (reviewMode.value === 'diff') return '审核改动'
  return '写入记录'
})

const changeReviewActionLabel = computed(() => {
  if (reviewMode.value === 'diff') return '查看 diff'
  return '查看记录'
})

const changeReviewSubtitle = computed(() => {
  if (sessionChanges.value?.files.length) {
    const source = sessionChanges.value.source === 'checkpoint'
      ? `来自 checkpoint ${sessionChanges.value.ref?.slice(0, 8) || ''}`.trim()
      : '来自当前 Git diff'
    return `${source} · +${sessionChanges.value.total_additions} -${sessionChanges.value.total_deletions}`
  }
  if (editedFiles.value.length) return '没有真实 Git diff，仅显示 Writer 写入过的路径'
  return ''
})

const parsedDiffFiles = computed<DiffFileView[]>(() => parseUnifiedDiff(sessionChanges.value?.diff || ''))

const visibleDiffFiles = computed<DiffFileView[]>(() => {
  if (!selectedDiffPath.value) return parsedDiffFiles.value
  const selected = parsedDiffFiles.value.find((file) => file.path === selectedDiffPath.value)
  return selected ? [selected] : parsedDiffFiles.value
})

const gitWorkingTreeSummary = computed(() => {
  const changes = sessionChanges.value
  if (!changes || changes.source === 'none' || changes.source === 'not_git' || changes.files.length === 0) return null
  return {
    label: changes.source === 'checkpoint' ? 'Checkpoint 改动' : '当前工作区改动',
    stat: `+${changes.total_additions} -${changes.total_deletions}`,
    files: changes.files,
  }
})

const gitTimeline = computed(() => {
  const graph = gitGraph.value
  if (!graph) return []
  const branchHeads = new Map<string, string[]>()
  for (const lane of graph.lanes) {
    const head = lane.commits[0]?.sha
    if (!head) continue
    const labels = branchHeads.get(head) || []
    labels.push(lane.branch)
    branchHeads.set(head, labels)
  }

  const ordered = []
  const seen = new Set<string>()
  const currentLane = graph.lanes.find((lane) => lane.is_current) || graph.lanes[0]
  for (const commit of currentLane?.commits || []) {
    if (seen.has(commit.sha)) continue
    seen.add(commit.sha)
    ordered.push(commit)
  }
  for (const lane of graph.lanes) {
    for (const commit of lane.commits) {
      if (seen.has(commit.sha)) continue
      seen.add(commit.sha)
      ordered.push(commit)
    }
  }

  return ordered.slice(0, 12).map((commit, index) => ({
    ...commit,
    index,
    labels: branchHeads.get(commit.sha) || [],
    isHead: commit.sha === graph.head,
  }))
})

const statusTextCn = computed(() => {
  if (sseStore.awaitingUser) return '等待用户决策'
  if (sseStore.running) return sseStore.statusText ? runtimeTextLabel(sseStore.statusText) : '运行中'
  if (activeSessionStale.value) return '已停止，等待继续'
  const phase = sessionStore.activeSession?.phase || ''
  const phaseText = phaseLabel(phase)
  if (phaseText && phaseText !== '暂无任务' && phaseText !== '空闲') return phaseText
  return sseStore.statusText ? runtimeTextLabel(sseStore.statusText) : '空闲'
})

const slowModelWaitText = computed(() => {
  if (!sseStore.running || !sseStore.lastEventAt) return ''
  const last = new Date(sseStore.lastEventAt).getTime()
  if (Number.isNaN(last)) return ''
  const seconds = Math.max(0, Math.floor((elapsedNow.value - last) / 1000))
  if (seconds < 90) return ''
  const minutes = Math.floor(seconds / 60)
  const remain = seconds % 60
  return `${minutes}m ${remain}s，进程仍活跃`
})

const gitDisplayError = computed(() => {
  if (!gitError.value) return ''
  if (gitError.value.includes('Not a git repository')) return '当前 Work root 不是 Git 仓库'
  if (gitError.value.includes('work_root')) return '当前会话没有有效 Work root'
  return gitError.value
})

onMounted(async () => {
  loadWorkbenchSettings()
  elapsedTimer = window.setInterval(() => {
    elapsedNow.value = Date.now()
  }, 1000)
  document.addEventListener('keydown', onGlobalKeydown)
  document.addEventListener('pointerdown', onGlobalPointerDown)
  await Promise.all([
    projectStore.fetchProjects(),
    sessionStore.fetchSessions(),
    configStore.fetchProviders(),
    configStore.fetchModels(),
  ])
  selectedModel.value = configStore.models[0]?.id || 'glm5.1'
  if (projectStore.projects.length > 0) {
    projectStore.selectProject(projectStore.projects[0])
    await selectFirstProjectSession(projectStore.projects[0].id)
  }
})

onUnmounted(() => {
  if (elapsedTimer) window.clearInterval(elapsedTimer)
  sseStore.stopSessionEvents()
  document.removeEventListener('keydown', onGlobalKeydown)
  document.removeEventListener('pointerdown', onGlobalPointerDown)
})

async function loadProjectSessions(projectId: string) {
  await sessionStore.fetchSessions()
  await selectFirstProjectSession(projectId)
}

async function selectFirstProjectSession(projectId: string) {
  const projectSessions = sessionStore.sessionsByProject.get(projectId) || []
  if (projectSessions.length > 0) {
    sessionStore.selectSession(projectSessions[0])
    await loadSessionData(projectSessions[0].id)
  } else {
    sessionStore.selectSession(null)
    sessionStore.clearMessages()
    stepStore.clearSteps()
    gitGraph.value = null
  }
}

async function loadSessionData(sessionId: string) {
  await sessionStore.fetchMessages(sessionId)
  await loadAttachments(sessionId)
  sseStore.replayLifecycleAlert(sessionId)
  await stepStore.fetchSteps(sessionId)
  await stepStore.fetchSummary(sessionId)
  await loadGitGraph(sessionId)
  await loadSessionChanges(sessionId)
  void sseStore.watchSessionEvents(sessionId)
}

async function loadAttachments(sessionId: string) {
  try {
    sessionAttachments.value = await api.listAttachments(sessionId)
  } catch {
    sessionAttachments.value = []
  }
}

async function loadGitGraph(sessionId: string, clear = true) {
  if (clear) gitGraph.value = null
  gitError.value = ''
  try {
    gitGraph.value = await api.getGitGraph(sessionId)
  } catch (err) {
    gitError.value = err instanceof Error ? err.message : String(err)
  }
}

function showError(err: unknown, fallback: string) {
  errorText.value = err instanceof Error ? err.message : String(err || fallback)
  window.setTimeout(() => {
    errorText.value = ''
  }, 5200)
}

function showNotice(message: string) {
  noticeText.value = message
  window.setTimeout(() => {
    noticeText.value = ''
  }, 2600)
}

function onGlobalKeydown(event: KeyboardEvent) {
  if (!event.ctrlKey) return
  const key = event.key.toLowerCase()
  if (key === 'tab') {
    event.preventDefault()
    if (leftPinned.value) {
      leftPinned.value = false
      leftOpen.value = false
    } else {
      leftOpen.value = !leftOpen.value
    }
  }
  if (key === 'e') {
    event.preventDefault()
    rightOpen.value = !rightOpen.value
  }
}

function onGlobalPointerDown(event: PointerEvent) {
  const target = event.target as HTMLElement | null
  if (!target) return
  if (!target.closest('.composer-menu') && !target.closest('.composer-pill')) {
    showModelMenu.value = false
    showQualityMenu.value = false
  }
  if (!leftPinned.value && leftOpen.value && !target.closest('.drawer-left') && !target.closest('.edge-left')) {
    leftOpen.value = false
  }
  if (!rightPinned.value && rightOpen.value && !target.closest('.drawer-right') && !target.closest('.edge-right')) {
    rightOpen.value = false
  }
}

function toggleLeftPinned() {
  leftPinned.value = !leftPinned.value
  if (leftPinned.value) leftOpen.value = true
}

function toggleRightPinned() {
  rightPinned.value = !rightPinned.value
  if (rightPinned.value) rightOpen.value = true
}

function onLeftDrawerLeave() {
  if (!leftPinned.value) leftOpen.value = false
}

function onRightDrawerLeave() {
  if (!rightPinned.value) rightOpen.value = false
}

function loadWorkbenchSettings() {
  loadRemoteWorkbenchSettings().catch(() => {
    const savedUi = readLocalSetting<Partial<typeof uiSettings.value>>('lamwriter.settings.uiSystem')
    if (savedUi) applyUiSettings(savedUi)
    const savedWriter = readLocalSetting<{ qualityMode?: string }>('lamwriter.settings.writerDefaults')
    if (savedWriter?.qualityMode) qualityMode.value = savedWriter.qualityMode
  })
}

async function loadRemoteWorkbenchSettings() {
  const [ui, writer] = await Promise.all([
    configStore.fetchAppSetting('lamwriter.settings.uiSystem'),
    configStore.fetchAppSetting('lamwriter.settings.writerDefaults'),
  ])
  applyUiSettings(ui.value)
  if (typeof writer.value.qualityMode === 'string') qualityMode.value = writer.value.qualityMode
}

function applyUiSettings(value: Partial<typeof uiSettings.value>) {
  uiSettings.value = {
    ...uiSettings.value,
    ...value,
    theme: {
      ...defaultTheme,
      ...uiSettings.value.theme,
      ...(value.theme || {}),
    },
  }
}

function readLocalSetting<T>(key: string): T | null {
  try {
    const raw = window.localStorage.getItem(key)
    return raw ? JSON.parse(raw) as T : null
  } catch {
    return null
  }
}

function normalizeTheme(value: Partial<typeof uiSettings.value.theme> | undefined) {
  return {
    backdropStart: normalizeColor(value?.backdropStart, defaultTheme.backdropStart),
    backdropEnd: normalizeColor(value?.backdropEnd, defaultTheme.backdropEnd),
    backdropStops: normalizeGradientStops(value?.backdropStops, normalizeColor(value?.backdropStart, defaultTheme.backdropStart), normalizeColor(value?.backdropEnd, defaultTheme.backdropEnd)),
    backdropAngle: clampNumber(value?.backdropAngle, 0, 360, defaultTheme.backdropAngle),
    backdropText: normalizeColor(value?.backdropText, defaultTheme.backdropText),
    mainSurface: normalizeColor(value?.mainSurface, defaultTheme.mainSurface),
    mainSurfaceEnd: normalizeColor(value?.mainSurfaceEnd, defaultTheme.mainSurfaceEnd),
    mainStops: normalizeGradientStops(value?.mainStops, normalizeColor(value?.mainSurface, defaultTheme.mainSurface), normalizeColor(value?.mainSurfaceEnd, defaultTheme.mainSurfaceEnd)),
    mainAngle: clampNumber(value?.mainAngle, 0, 360, defaultTheme.mainAngle),
    mainText: normalizeColor(value?.mainText, defaultTheme.mainText),
    mainOpacity: clampNumber(value?.mainOpacity, 0.1, 1, defaultTheme.mainOpacity),
    composerSurface: normalizeColor(value?.composerSurface, defaultTheme.composerSurface),
    composerSurfaceEnd: normalizeColor(value?.composerSurfaceEnd, defaultTheme.composerSurfaceEnd),
    composerStops: normalizeGradientStops(value?.composerStops, normalizeColor(value?.composerSurface, defaultTheme.composerSurface), normalizeColor(value?.composerSurfaceEnd, defaultTheme.composerSurfaceEnd)),
    composerAngle: clampNumber(value?.composerAngle, 0, 360, defaultTheme.composerAngle),
    composerText: normalizeColor(value?.composerText, defaultTheme.composerText),
    composerOpacity: clampNumber(value?.composerOpacity, 0.1, 1, defaultTheme.composerOpacity),
    controlSurface: normalizeColor(value?.controlSurface, normalizeColor(value?.composerSurface, defaultTheme.controlSurface)),
    controlSurfaceEnd: normalizeColor(value?.controlSurfaceEnd, normalizeColor(value?.composerSurfaceEnd, defaultTheme.controlSurfaceEnd)),
    controlStops: normalizeGradientStops(value?.controlStops, normalizeColor(value?.controlSurface, normalizeColor(value?.composerSurface, defaultTheme.controlSurface)), normalizeColor(value?.controlSurfaceEnd, normalizeColor(value?.composerSurfaceEnd, defaultTheme.controlSurfaceEnd))),
    controlAngle: clampNumber(value?.controlAngle, 0, 360, clampNumber(value?.composerAngle, 0, 360, defaultTheme.controlAngle)),
    controlText: normalizeColor(value?.controlText, normalizeColor(value?.composerText, defaultTheme.controlText)),
    controlOpacity: clampNumber(value?.controlOpacity, 0.1, 1, clampNumber(value?.composerOpacity, 0.1, 1, defaultTheme.controlOpacity)),
  }
}

async function loadSessionChanges(sessionId: string, clear = true) {
  if (clear) sessionChanges.value = null
  changesError.value = ''
  try {
    sessionChanges.value = await api.getSessionChanges(sessionId)
  } catch (err) {
    changesError.value = err instanceof Error ? err.message : String(err)
  }
}

function toggleModelMenu() {
  showModelMenu.value = !showModelMenu.value
  showQualityMenu.value = false
}

function toggleQualityMenu() {
  showQualityMenu.value = !showQualityMenu.value
  showModelMenu.value = false
}

function openNewProjectModal() {
  configStore.fetchAppSetting('lamwriter.settings.projectDefaults')
    .then((setting) => {
      newProjectRoot.value = typeof setting.value.workRoot === 'string' ? setting.value.workRoot : ''
    })
    .catch(() => {
      const defaults = readLocalSetting<{ workRoot?: string }>('lamwriter.settings.projectDefaults')
      newProjectRoot.value = defaults?.workRoot || ''
    })
    .finally(() => {
      showNewProject.value = true
    })
}

function selectModel(value: string) {
  selectedModel.value = value
  showModelMenu.value = false
}

function selectQuality(value: string) {
  qualityMode.value = value
  showQualityMenu.value = false
}

function openChangeReview() {
  if (editedFiles.value.length === 0) return
  showChangeReview.value = true
  selectedDiffPath.value = parsedDiffFiles.value[0]?.path || editedFiles.value[0]?.path || ''
}

function safeDiffId(path: string): string {
  let hash = 0
  for (let i = 0; i < path.length; i += 1) {
    hash = ((hash << 5) - hash + path.charCodeAt(i)) | 0
  }
  return `diff-${Math.abs(hash)}`
}

async function scrollDiffFile(path: string) {
  selectedDiffPath.value = path
}

function onUndoChanges() {
  if (!sessionStore.activeSession || undoingChanges.value) return
  showUndoConfirm.value = true
}

async function confirmUndoChanges() {
  if (!sessionStore.activeSession || undoingChanges.value) return
  showUndoConfirm.value = false
  undoingChanges.value = true
  try {
    await api.undoSessionChanges(sessionStore.activeSession.id)
    await loadSessionChanges(sessionStore.activeSession.id)
    await loadGitGraph(sessionStore.activeSession.id)
    await stepStore.fetchSteps(sessionStore.activeSession.id)
    await stepStore.fetchSummary(sessionStore.activeSession.id)
    if (editedFiles.value.length === 0) showChangeReview.value = false
  } catch (err) {
    showError(err, 'Undo changes failed')
  } finally {
    undoingChanges.value = false
  }
}

function onSelectProject(projectId: string) {
  const project = projectStore.projects.find((x) => x.id === projectId)
  if (!project) return
  projectStore.selectProject(project)
  selectFirstProjectSession(project.id).catch((err) => showError(err, 'Load project failed'))
}

async function onSelectProjectGroup(group: ProjectGroup) {
  projectStore.selectProject(group.primary)
  const firstSession = group.sessions[0]
  if (firstSession) {
    sessionStore.selectSession(firstSession)
    await loadSessionData(firstSession.id)
  } else {
    await selectFirstProjectSession(group.primary.id)
  }
}

function onOpenNewSession(projectId: string) {
  const project = projectStore.projects.find((x) => x.id === projectId)
  if (project) projectStore.selectProject(project)
  showNewSession.value = true
}

function cycleProjectSessionMode(key: string) {
  const current = projectSessionMode(key)
  projectSessionModes[key] = current === 'normal'
    ? 'collapsed'
    : current === 'collapsed'
      ? 'expanded'
      : 'normal'
}

function projectSessionMode(key: string): ProjectSessionMode {
  return projectSessionModes[key] || 'normal'
}

function projectSessionToggleLabel(key: string): string {
  const mode = projectSessionMode(key)
  if (mode === 'collapsed') return '▸'
  if (mode === 'expanded') return '▾'
  return '−'
}

function projectSessionToggleTitle(key: string): string {
  const mode = projectSessionMode(key)
  if (mode === 'collapsed') return '展开全部会话'
  if (mode === 'expanded') return '恢复显示最近 3 个会话'
  return '折叠会话'
}

function visibleProjectSessions(group: ProjectGroup): Session[] {
  const mode = projectSessionMode(group.key)
  if (mode === 'collapsed') return []
  if (mode === 'expanded') return group.sessions
  return group.sessions.slice(0, 3)
}

function hiddenProjectSessionCount(group: ProjectGroup): number {
  if (projectSessionMode(group.key) !== 'normal') return 0
  return Math.max(0, group.sessions.length - 3)
}

async function onCreateProject() {
  const root = newProjectRoot.value.trim()
  if (!root) {
    showError('请选择或填写 Work root。一个 Work root 就是一个项目。', 'Invalid work root')
    return
  }
  if (!isAbsolutePath(root)) {
    showError('Work root 必须填写绝对路径，例如 E:\\MyProject。浏览器无法提供真实本机路径，请手动输入。', 'Invalid work root')
    return
  }
  try {
    const project = await projectStore.createProject({
      work_root: root,
    })
    projectStore.selectProject(project)
    await sessionStore.fetchSessions()
    await selectFirstProjectSession(project.id)
    showNewProject.value = false
    newProjectRoot.value = ''
  } catch (err) {
    showError(err, 'Create project failed')
  }
}

async function onDeleteProject(projectId: string) {
  try {
    await projectStore.deleteProject(projectId)
    if (projectStore.projects.length > 0) {
      projectStore.selectProject(projectStore.projects[0])
      await sessionStore.fetchSessions()
      await selectFirstProjectSession(projectStore.projects[0].id)
    } else {
      projectStore.selectProject(null)
      sessionStore.selectSession(null)
      sessionStore.clearMessages()
      stepStore.clearSteps()
      gitGraph.value = null
    }
  } catch (err) {
    showError(err, 'Delete project failed')
  }
}

async function onSelectSession(sessionId: string) {
  const session = sessionStore.sessions.find((x) => x.id === sessionId)
  if (!session) return
  sessionStore.selectSession(session)
  await loadSessionData(session.id)
}

async function onCreateSession() {
  if (!newSessionTitle.value.trim()) return
  try {
    const session = await sessionStore.createSession({
      title: newSessionTitle.value.trim(),
      mode: selectedMode.value,
      project_id: projectStore.activeProject?.id,
      work_root: projectStore.activeProject?.work_root || undefined,
    })
    sessionStore.selectSession(session)
    await loadSessionData(session.id)
    showNewSession.value = false
    newSessionTitle.value = ''
  } catch (err) {
    showError(err, 'Create session failed')
  }
}

async function onDeleteSession(sessionId: string) {
  try {
    await sessionStore.deleteSession(sessionId)
    if (sessionStore.sessions.length > 0) {
      sessionStore.selectSession(sessionStore.sessions[0])
      await loadSessionData(sessionStore.sessions[0].id)
    } else {
      stepStore.clearSteps()
      gitGraph.value = null
    }
  } catch (err) {
    showError(err, 'Delete session failed')
  }
}

async function onSendMessage() {
  const text = messageInput.value.trim()
  if ((!text && pendingAttachments.value.length === 0) || !sessionStore.activeSession) return
  if (sseStore.running && !sseStore.awaitingUser) return

  const attachmentsToSend = [...pendingAttachments.value]
  messageInput.value = ''
  pendingAttachments.value = []
  resizeComposer()
  runStartedAt.value = Date.now()
  lastElapsedMs.value = 0
  const localMessage = {
    id: `local-user-${Date.now()}`,
    session_id: sessionStore.activeSession.id,
    role: 'user',
    content: text,
    parts: attachmentsToSend.length ? { attachments: attachmentsToSend } : null,
    created_at: new Date().toISOString(),
  }
  sessionStore.appendMessage(localMessage)
  await scrollThreadToBottom()

  const chatReq: ChatRequest = {
    message: text,
    mode: selectedMode.value,
    quality_mode: qualityMode.value as ChatRequest['quality_mode'],
    work_root: sessionStore.activeSession.work_root || undefined,
    attachment_ids: attachmentsToSend.map((item) => item.id),
  }

  try {
    sseStore.stopSessionEvents()
    await sseStore.startStream(sessionStore.activeSession.id, chatReq)
    if (sessionStore.activeSession) {
      await sessionStore.fetchMessages(sessionStore.activeSession.id)
      await loadAttachments(sessionStore.activeSession.id)
      sseStore.replayLifecycleAlert(sessionStore.activeSession.id)
      const lastMessage = sessionStore.messages[sessionStore.messages.length - 1]
      if (!lastMessage || lastMessage.role !== 'assistant' || lastMessage.id.startsWith('local-reply')) {
        upsertReplyDraft(sseStore.assistantDraft)
      }
      await stepStore.fetchSteps(sessionStore.activeSession.id)
      await stepStore.fetchSummary(sessionStore.activeSession.id)
      await loadGitGraph(sessionStore.activeSession.id)
      await loadSessionChanges(sessionStore.activeSession.id)
      await sessionStore.fetchSessions()
      void sseStore.watchSessionEvents(sessionStore.activeSession.id)
    }
  } catch (err) {
    showError(err, 'Send message failed')
  } finally {
    if (runStartedAt.value) lastElapsedMs.value = Date.now() - runStartedAt.value
    runStartedAt.value = null
    if (sessionStore.activeSession) void sseStore.watchSessionEvents(sessionStore.activeSession.id)
  }

  await scrollThreadToBottom()
}

function triggerAttachmentUpload() {
  fileInput.value?.click()
}

async function onAttachmentSelected(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = ''
  if (!files.length || !sessionStore.activeSession) return
  uploadingAttachment.value = true
  try {
    for (const file of files) {
      const attachment = await api.uploadAttachment(sessionStore.activeSession.id, file)
      pendingAttachments.value.push(attachment)
      sessionAttachments.value.push(attachment)
    }
  } catch (err) {
    showError(err, 'Upload attachment failed')
  } finally {
    uploadingAttachment.value = false
  }
}

function removePendingAttachment(id: string) {
  pendingAttachments.value = pendingAttachments.value.filter((item) => item.id !== id)
}

async function onDeleteProjectGroup(projectIds: string[]) {
  try {
    for (const projectId of projectIds) {
      await projectStore.deleteProject(projectId)
    }
    if (projectStore.projects.length > 0) {
      projectStore.selectProject(projectStore.projects[0])
      await sessionStore.fetchSessions()
      await selectFirstProjectSession(projectStore.projects[0].id)
    } else {
      projectStore.selectProject(null)
      sessionStore.selectSession(null)
      sessionStore.clearMessages()
      stepStore.clearSteps()
      gitGraph.value = null
    }
  } catch (err) {
    showError(err, 'Delete project failed')
  }
}

function decisionFromMessage(message: Message): { title?: string; decision_type?: string; options?: Array<Record<string, unknown>>; context?: Record<string, unknown> } | null {
  const parts = message.parts as { decision?: { title?: string; decision_type?: string; options?: Array<Record<string, unknown>>; context?: Record<string, unknown> } } | null
  return parts?.decision || null
}

function lifecycleFromMessage(message: Message): { lifecycle_type?: string; reason?: string; details?: Record<string, unknown> } | null {
  const parts = message.parts as { lifecycle?: { lifecycle_type?: string; reason?: string; details?: Record<string, unknown> } } | null
  return parts?.lifecycle || null
}

function isReplyMessage(message: Message): boolean {
  if (message.role !== 'assistant') return false
  const parts = message.parts as { reply?: boolean; decision?: unknown; lifecycle?: unknown; output_meta?: { final?: boolean } } | null
  if (parts?.decision || parts?.lifecycle) return false
  return parts?.reply === true || parts?.output_meta?.final === true || message.id.startsWith('local-reply')
}

function replyAttachments(message: Message): ReplyAttachment[] {
  const parts = message.parts as {
    attachments?: unknown
    output_meta?: { attachments?: unknown }
  } | null
  return normalizeReplyAttachments(parts?.attachments || parts?.output_meta?.attachments)
}

function normalizeReplyAttachments(raw: unknown): ReplyAttachment[] {
  if (!Array.isArray(raw)) return []
  const attachments: ReplyAttachment[] = []
  for (const item of raw) {
    if (typeof item === 'string') {
      const known = sessionAttachments.value.find((attachment) => attachment.id === item)
      attachments.push(known || { id: item, label: '附件' })
      continue
    }
    if (!item || typeof item !== 'object') continue
    const record = item as Record<string, unknown>
    const id = String(record.id || record.runtime_event_id || record.label || record.filename || '')
    if (!id) continue
    const known = sessionAttachments.value.find((attachment) => attachment.id === id)
    const metadata = (
      record.metadata && typeof record.metadata === 'object'
        ? record.metadata
        : known?.metadata && typeof known.metadata === 'object'
          ? known.metadata
          : {}
    ) as Record<string, unknown>
    const title = stringValue(record.title || metadata.title || record.label || known?.title || known?.metadata?.title || '')
    attachments.push({
      ...known,
      id,
      title,
      label: title || stringValue(record.label || known?.label || record.filename || known?.filename || '附件'),
      filename: typeof record.filename === 'string' ? record.filename : known?.filename,
      kind: typeof record.kind === 'string' ? record.kind : stringValue(metadata.attachment_kind || known?.metadata?.attachment_kind || ''),
      source: typeof record.source === 'string' ? record.source : known?.source,
      agent_name: typeof record.agent_name === 'string' ? record.agent_name : known?.agent_name,
      preview: typeof record.preview === 'string' ? record.preview : known?.preview,
      preview_type: typeof record.preview_type === 'string' ? record.preview_type : known?.preview_type,
      mime_type: typeof record.mime_type === 'string' ? record.mime_type : known?.mime_type,
      size: typeof record.size === 'number' ? record.size : known?.size,
      runtime_event_id: typeof record.runtime_event_id === 'string' ? record.runtime_event_id : null,
      content: typeof record.content === 'string' ? record.content : undefined,
      metadata,
      created_at: typeof record.created_at === 'string' ? record.created_at : known?.created_at,
    })
  }
  return attachments
}

function attachmentSourceLabel(attachment: ReplyAttachment): string {
  const sourceMap: Record<string, string> = {
    design_agent: '架构设计师',
    agent_generated: attachment.agent_name === 'architecture' || attachment.agent_name === 'design' ? '架构设计师' : attachment.agent_name ? `${attachment.agent_name} Agent` : 'Agent',
    writer_generated: 'Writer',
    user_upload: '用户上传',
  }
  const source = sourceMap[attachment.source || ''] || attachment.source || 'Writer'
  const parts = [source]
  if (attachment.kind) parts.push(attachmentKindLabel(attachment.kind))
  const runLabel = stringValue(attachment.metadata?.agent_run_id || '')
  if (runLabel) parts.push(runLabel.replace(/^run-/, ''))
  return parts.join(' · ')
}

function attachmentTitle(attachment: ReplyAttachment): string {
  return attachment.title || attachment.label || attachmentKindLabel(attachment.kind || '') || attachment.filename || '附件'
}

function attachmentKindLabel(kind: string): string {
  const map: Record<string, string> = {
    architecture_doc: '架构方案',
    execution_handoff: '执行交接',
    design_report: '设计书',
    design_handoff: '设计方案',
  }
  return map[kind] || businessText(kind)
}

async function openReplyAttachment(attachment: ReplyAttachment) {
  const previewType = attachment.preview_type || ''
  if (previewType && previewType !== 'text') {
    try {
      await api.openAttachment(attachment.id)
      showNotice('已请求使用系统默认方式打开。')
    } catch (err) {
      showError(err, 'Open attachment failed')
    }
    return
  }
  replyAttachmentPreview.value = {
    attachment,
    title: attachmentTitle(attachment),
    body: attachment.content || attachment.preview || '正在读取附件内容。',
    loading: true,
  }
  try {
    if (attachment.runtime_event_id && sessionStore.activeSession) {
      const event = await stepStore.fetchRuntimeEvent(sessionStore.activeSession.id, attachment.runtime_event_id)
      replyAttachmentPreview.value = {
        attachment,
        title: attachmentTitle(attachment) || event.summary || '附件',
        body: event.full_text || event.preview || event.summary || '附件没有可预览内容。',
        loading: false,
      }
      return
    }
    const preview = await api.previewAttachment(attachment.id)
    replyAttachmentPreview.value = {
      attachment,
      title: attachmentTitle(attachment) || preview.filename,
      body: preview.text || attachment.content || attachment.preview || '附件没有可预览内容。',
      loading: false,
    }
  } catch (err) {
    replyAttachmentPreview.value = {
      attachment,
      title: attachmentTitle(attachment),
      body: `读取失败：${err instanceof Error ? err.message : String(err)}`,
      loading: false,
    }
  }
}

function closeReplyAttachmentPreview() {
  replyAttachmentPreview.value = null
}

function lifecycleView(message: Message): LifecycleView | null {
  const lifecycle = lifecycleFromMessage(message)
  if (!lifecycle) return null
  const type = lifecycle.lifecycle_type === 'error' ? 'error' : lifecycle.lifecycle_type === 'failed' ? 'failed' : ''
  if (!type) return null
  const reason = technicalReasonLabel(lifecycle.reason || '')
  return {
    title: type === 'error' ? 'Writer 运行出错' : 'Writer 执行失败',
    severity: type,
    reason,
    detail: summarizeDetails(lifecycle.details || {}),
    statusLabel: type === 'error' ? '异常' : '失败',
  }
}

function decisionView(message: Message): DecisionView | null {
  const decision = decisionFromMessage(message)
  if (!decision) return null
  const context = decision.context || {}
  const plan = planViewFromDecision(decision)
  const details = decisionDetailSections(decision)
  const reason = businessText(stringValue(
    context.reason
    || context.why
    || context.description
    || context.question
    || context.waiting_title
    || '',
  ))
  const type = stringValue(context.kind || context.type || decision.title || '').toLowerCase()
  const blocking = decision.decision_type === 'decision_point'
    || Boolean(context.blocking)
    || type.includes('blocking')
    || type.includes('阻塞')
  const riskText = [
    decision.title,
    context.reason,
    context.description,
    context.kind,
    context.type,
  ].map((item) => stringValue(item).toLowerCase()).join('\n')
  const kind: DecisionView['kind'] = /delete|remove|overwrite|undo|revert|permission|danger|删除|覆盖|撤销|权限|风险/.test(riskText)
    ? 'risk'
    : plan
      ? 'plan'
      : 'light'
  const title = businessText(stringValue(decision.title || message.content || '')) || decisionKindTitle(kind)
  const prompt = decisionPrompt(kind, title, reason, plan, context)
  return {
    title,
    kind,
    kindLabel: decisionKindLabel(kind),
    reason: reason || decisionDefaultReason(kind, plan),
    prompt,
    options: decision.options || [],
    blocking,
    statusLabel: blocking ? '暂停中' : '可继续',
    plan,
    details,
  }
}

function decisionKindTitle(kind: DecisionView['kind']): string {
  if (kind === 'risk') return '需要确认风险操作'
  if (kind === 'plan') return '需要确认方案'
  return '需要你的决定'
}

function decisionKindLabel(kind: DecisionView['kind']): string {
  if (kind === 'risk') return '风险决策'
  if (kind === 'plan') return '方案决策'
  return '轻决策'
}

function decisionDefaultReason(kind: DecisionView['kind'], plan: DecisionPlanView | null): string {
  if (kind === 'risk') return '继续前需要确认影响范围，避免误操作。'
  if (kind === 'plan') return plan ? 'Writer 已整理执行方案，确认后开始实施。' : '继续前需要确认方向。'
  return 'Writer 需要你选择下一步。'
}

function decisionPrompt(kind: DecisionView['kind'], title: string, reason: string, plan: DecisionPlanView | null, context: Record<string, unknown>): string {
  const question = stringList(context.question || context.waiting_title)[0]
  const normalizedQuestion = normalizeMessageText(question)
  const isUsableQuestion = question
    && normalizedQuestion !== normalizeMessageText(title)
    && normalizedQuestion !== normalizeMessageText(reason)
    && !/plan ready|review and confirm|计划已生成|确认后继续/i.test(question)
  if (isUsableQuestion) return question
  if (kind === 'risk') return '请确认是否执行这个有影响的操作。'
  if (kind === 'plan') return plan?.summary ? `是否按当前方案继续？${plan.summary}` : '是否按当前方案继续？'
  return title
}

function decisionDetailSections(decision: { context?: Record<string, unknown>; options?: Array<Record<string, unknown>> }): Array<{ label: string; lines: string[] }> {
  const context = decision.context || {}
  const sections: Array<{ label: string; lines: string[] }> = []
  const question = stringList(context.question || context.waiting_title)
  if (question.length) sections.push({ label: '需要决策', lines: question })
  const blocking = stringList(context.blocking_decision_points || context.blocking_points || context.items)
  if (blocking.length) sections.push({ label: '阻塞点', lines: blocking })
  const potential = stringList(context.potential_user_decisions || context.potential_decisions)
  if (potential.length) sections.push({ label: '可能影响', lines: potential })
  const token = tokenEstimateLines(context.estimated_token_total)
  if (token.length) sections.push({ label: '规模估计', lines: token })
  const defaultOption = businessText(stringValue(context.default_option || ''))
  if (defaultOption) sections.push({ label: '默认选择', lines: [defaultOption] })
  return sections
}

function tokenEstimateLines(value: unknown): string[] {
  if (!value || typeof value !== 'object') return []
  const record = value as Record<string, unknown>
  const display = businessText(stringValue(record.display || ''))
  if (display) return [display]
  return Object.entries(record)
    .map(([key, item]) => `${key}: ${businessText(stringValue(item))}`)
    .filter(Boolean)
    .slice(0, 5)
}

function planViewFromDecision(decision: { context?: Record<string, unknown> }): DecisionPlanView | null {
  const plan = decision.context?.plan
  if (!plan || typeof plan !== 'object') return null
  const record = plan as Record<string, unknown>
  const rawSteps = Array.isArray(record.steps) ? record.steps : []
  const steps = rawSteps
    .map((raw, index) => {
      if (!raw || typeof raw !== 'object') return null
      const step = raw as Record<string, unknown>
      const description = businessText(stringValue(step.description || step.title || step.name || ''))
      const deliverables = stringList(step.deliverables)
      const acceptance = stringList(step.acceptance_criteria || step.acceptance || step.criteria)
      if (!description && !deliverables.length && !acceptance.length) return null
      return {
        index: index + 1,
        description: description || `步骤 ${index + 1}`,
        deliverables,
        acceptance,
      }
    })
    .filter((item): item is DecisionPlanStepView => Boolean(item))
  const constraints = stringList(record.constraints)
  const goal = businessText(stringValue(record.goal || record.intent || record.summary || ''))
  if (!goal && !steps.length && !constraints.length) return null
  const summaryParts = []
  if (steps.length) summaryParts.push(`${steps.length} 步`)
  if (constraints.length) summaryParts.push(`${constraints.length} 条约束`)
  const deliverableCount = steps.reduce((count, step) => count + step.deliverables.length, 0)
  if (deliverableCount) summaryParts.push(`${deliverableCount} 个产出`)
  const shortGoal = goal.length > 120 ? '目标已识别，完整计划可展开查看。' : goal
  return { goal, shortGoal, constraints, steps, summary: summaryParts.join(' · ') || '计划待确认' }
}

function stringList(value: unknown): string[] {
  const source = Array.isArray(value)
    ? value
    : typeof value === 'string'
      ? value.split(/\r?\n|,|，/)
      : value && typeof value === 'object'
        ? Object.entries(value as Record<string, unknown>).map(([key, item]) => `${key}: ${stringValue(item)}`)
        : []
  return source
    .map((item) => businessText(stringValue(item)))
    .filter(Boolean)
    .slice(0, 8)
}

function decisionOptionLabel(option: Record<string, unknown>): string {
  const raw = String(option.label || option.name || option.id || option.value || '继续')
  const key = raw.trim().toLowerCase()
  const map: Record<string, string> = {
    confirm: '按当前方案继续',
    continue: '继续执行',
    proceed: '继续执行',
    approve: '确认并继续',
    accept: '确认并继续',
    revise: '调整方案',
    change: '调整方案',
    edit: '调整方案',
    cancel: '取消本轮任务',
    abort: '取消本轮任务',
  }
  return map[key] || businessText(raw) || '继续'
}

function decisionOptionDescription(option: Record<string, unknown>): string {
  const label = decisionOptionLabel(option)
  const rawId = String(option.id || option.value || option.name || option.label || '').toLowerCase()
  const description = businessText(String(option.description || option.detail || option.summary || ''))
    || defaultDecisionOptionDescription(rawId, label)
  const consequences = stringList(option.consequences)
  return [description, consequences.length ? `影响：${consequences.join('；')}` : ''].filter(Boolean).join(' · ')
}

function defaultDecisionOptionDescription(id: string, label: string): string {
  const key = `${id} ${label}`.toLowerCase()
  if (/confirm|continue|proceed|approve|accept|继续|确认/.test(key)) return '开始执行，后续改动会进入审核。'
  if (/revise|change|edit|调整|修改/.test(key)) return '回到设计阶段，等待补充修改意见。'
  if (/cancel|abort|取消/.test(key)) return '停止本轮任务，不继续新增改动。'
  return ''
}

async function sendDecisionOption(option: Record<string, unknown>) {
  const id = String(option.id || option.value || option.name || decisionOptionLabel(option))
  const label = decisionOptionLabel(option)
  messageInput.value = `${id}: ${label}`
  await onSendMessage()
}

async function onCancelRun() {
  sseStore.stopStream()
  if (!sessionStore.activeSession) return
  try {
    await api.cancelSession(sessionStore.activeSession.id)
  } catch (err) {
    showError(err, 'Cancel failed')
  }
}

async function onRetryStep(stepId: string) {
  if (!sessionStore.activeSession) return
  try {
    await stepStore.retryStep(sessionStore.activeSession.id, stepId)
  } catch (err) {
    showError(err, 'Retry step failed')
  }
}

async function toggleStep(stepId: string) {
  const next = new Set(expandedSteps.value)
  const opening = !next.has(stepId)
  if (opening) next.add(stepId)
  else next.delete(stepId)
  expandedSteps.value = next
  if (!opening || !sessionStore.activeSession) return
  const block = runtimeBlocks.value.find((item) => item.id === stepId)
  if (!block) return
  await Promise.all([
    stepStore.fetchStepDetails(sessionStore.activeSession.id, block.steps.map((step) => step.id)),
    stepStore.fetchRuntimeEvents(sessionStore.activeSession.id, agentRuntimeLogIds(block)),
  ])
}

function openAgentsMd(projectId: string) {
  projectStore.selectProject(projectStore.projects.find((p) => p.id === projectId) || projectStore.activeProject)
  projectStore.fetchAgentsMd(projectId).catch((err) => showError(err, 'Load AGENTS.md failed'))
  showAgentsMd.value = true
}

async function saveAgentsMd() {
  if (!projectStore.activeProject) return
  try {
    await projectStore.saveAgentsMd(projectStore.activeProject.id, projectStore.agentsMdContent)
    showAgentsMd.value = false
  } catch (err) {
    showError(err, 'Save AGENTS.md failed')
  }
}

async function chooseWorkRoot() {
  if (window.lamwriterDesktop?.selectDirectory) {
    try {
      const selected = await window.lamwriterDesktop.selectDirectory()
      if (selected) newProjectRoot.value = selected
      return
    } catch (err) {
      showError(err, 'Folder picker failed')
      return
    }
  }
  showError('浏览器目录选择拿不到真实绝对路径。当前版本请手动输入 E:\\... 形式的 Work root。', 'Folder picker unavailable')
}

function isAbsolutePath(path: string): boolean {
  return /^[a-zA-Z]:[\\/]/.test(path) || /^\\\\[^\\]+\\[^\\]+/.test(path) || path.startsWith('/')
}

function projectDisplayName(project: Project): string {
  return folderNameFromPath(project.work_root) || project.name
}

function projectGroupKey(project: Project): string {
  return normalizeProjectPath(project.work_root) || project.id
}

function isProjectGroupActive(group: ProjectGroup): boolean {
  const activeId = projectStore.activeProject?.id
  return Boolean(activeId && group.projects.some((project) => project.id === activeId))
}

function folderNameFromPath(path: string): string {
  const normalized = path.trim().replace(/[\\/]+$/, '')
  const parts = normalized.split(/[\\/]/).filter(Boolean)
  return parts[parts.length - 1] || normalized
}

function normalizeProjectPath(path: string): string {
  return path.trim().replace(/[\\/]+$/, '').replace(/\//g, '\\').toLowerCase()
}

async function scrollThreadToBottom() {
  await nextTick()
  const target = messagesArea.value || mainArea.value
  if (target) target.scrollTop = target.scrollHeight
}

function resizeComposer() {
  nextTick(() => {
    const el = messageBox.value
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 190)}px`
  })
}

function goToSettings() {
  router.push('/settings')
}

function statusClass(status: string): string {
  if (status === 'running') return 'status-running'
  if (status === 'completed' || status === 'done') return 'status-done'
  if (status === 'failed' || status === 'error') return 'status-failed'
  if (status === 'waiting') return 'status-waiting'
  return ''
}

function isReadonlyStep(step: Step): boolean {
  const name = (step.tool_name || step.step_type || '').toLowerCase()
  return [
    'read_file',
    'read',
    'list_dir',
    'glob',
    'grep',
    'search',
    'inspect_project',
    'web_search',
    'webfetch',
  ].some((key) => name.includes(key))
}

function isAgentStep(step: Step): boolean {
  const name = (step.tool_name || step.step_type || '').toLowerCase()
  return step.step_type === 'agent_call' || step.step_type === 'agent_progress' || name === 'architecture' || name === 'design' || name.includes('agent')
}

function makeReadonlyBlock(steps: Step[]): RuntimeBlock {
  const counts = {
    read: steps.filter((s) => (s.tool_name || s.step_type || '').toLowerCase().includes('read')).length,
    search: steps.filter((s) => /(grep|glob|search|web)/i.test(s.tool_name || s.step_type || '')).length,
    list: steps.filter((s) => /(list|inspect)/i.test(s.tool_name || s.step_type || '')).length,
  }
  const parts = []
  if (counts.read) parts.push(`读取 ${counts.read} 个文件`)
  if (counts.search) parts.push(`搜索 ${counts.search} 次`)
  if (counts.list) parts.push(`查看 ${counts.list} 个目录/项目`)
  const running = steps.some((s) => s.status === 'running' || s.status === 'in_progress')
  const failed = steps.find((s) => s.status === 'failed' || s.status === 'error')
  const last = steps[steps.length - 1]
  return {
    id: `runtime-readonly-${steps.map((s) => s.id).join('-')}`,
    kind: 'runtime',
    blockType: counts.search ? 'search' : counts.list ? 'read' : 'read',
    status: failed ? failed.status : running ? 'running' : last?.status || 'completed',
    title: parts.join('，') || `查看上下文 ${steps.length} 次`,
    subtitle: `${steps.length} 个上下文动作`,
    detail: steps.map(stepDetailLine).filter(Boolean).join('\n'),
    createdAt: steps[0]?.created_at || new Date().toISOString(),
    completedAt: last?.completed_at || null,
    steps,
  }
}

function makeAgentBlock(steps: Step[]): RuntimeBlock {
  const last = steps[steps.length - 1]
  const failed = steps.find((s) => s.status === 'failed' || s.status === 'error')
  const running = steps.some((s) => s.status === 'running' || s.status === 'in_progress')
  const summary = designAgentSummary(steps)
  return {
    id: `runtime-agent-${steps.map((s) => s.id).join('-')}`,
    kind: 'runtime',
    blockType: 'design-agent',
    status: failed ? failed.status : running ? 'running' : last?.status || 'completed',
    title: summary.title,
    subtitle: runtimeBlockSubtitle(last),
    detail: steps.map(stepDetailLine).filter(Boolean).join('\n') || '暂无详细输出。',
    createdAt: steps[0]?.created_at || new Date().toISOString(),
    completedAt: last?.completed_at || null,
    steps,
    agentSummary: summary,
  }
}

function makeRuntimeBlock(step: Step): RuntimeBlock {
  const name = step.tool_name || step.step_type || 'tool'
  const lower = name.toLowerCase()
  let blockType: RuntimeBlock['blockType'] = 'tool'
  if (lower.includes('write') || lower.includes('edit') || lower.includes('patch')) blockType = 'write'
  else if (lower.includes('command') || lower.includes('shell') || lower.includes('test') || lower.includes('run')) blockType = lower.includes('test') ? 'verify' : 'command'
  else if (lower.includes('agent')) blockType = 'agent'
  else if (lower.includes('git')) blockType = 'git'
  else if (lower.includes('checklist') || lower.includes('plan')) blockType = 'plan'
  else if (lower.includes('decision')) blockType = 'decision'

  return {
    id: `runtime-${step.id}`,
    kind: 'runtime',
    blockType,
    status: step.status,
    title: runtimeBlockTitle(step, blockType),
    subtitle: runtimeBlockSubtitle(step),
    detail: stepDetailLine(step) || '暂无详细输出。',
    createdAt: step.created_at || new Date().toISOString(),
    completedAt: step.completed_at,
    steps: [step],
  }
}

function runtimeBlockTitle(step: Step, blockType: RuntimeBlock['blockType']): string {
  const target = safeStepTarget(step)
  if (blockType === 'write') return target ? `修改 ${target}` : '修改文件'
  if (blockType === 'command') return target ? `运行 ${target}` : '运行命令'
  if (blockType === 'verify') return target ? `验证 ${target}` : '执行验证'
  if (blockType === 'agent') return target ? `调用 ${target}` : '调用 Agent'
  if (blockType === 'design-agent') return '设计中'
  if (blockType === 'git') return target ? `Git：${target}` : 'Git 操作'
  if (blockType === 'plan') return '更新计划'
  if (blockType === 'decision') return '等待决策'
  return stepKindLabel(step.step_type, step.tool_name)
}

function runtimeBlockSubtitle(step: Step): string {
  const bits = [statusLabel(step.status)]
  if (step.duration_ms !== null && step.duration_ms !== undefined) bits.push(formatDurationMs(step.duration_ms))
  if (step.retry_count > 0) bits.push(`第 ${step.retry_count + 1} 次尝试`)
  return bits.join(' · ')
}

function stepTarget(step: Step): string {
  const args = step.tool_args || {}
  const raw = args.path || args.file || args.command || args.name || args.agent || args.task || args.description || step.content || ''
  return String(raw).split('\n')[0].slice(0, 96)
}

function safeStepTarget(step: Step): string {
  const raw = stepTarget(step)
  return businessText(raw)
}

function stepDetailLine(step: Step): string {
  const rows = []
  const target = safeStepTarget(step)
  if (target) rows.push(`目标：${target}`)
  if (step.content) rows.push(businessText(step.content))
  if (step.tool_result_summary) rows.push(`结果：${businessText(step.tool_result_summary)}`)
  if (step.error) rows.push(`错误：${businessText(step.error)}`)
  return rows.join('\n')
}

function detailedStep(step: Step): Step {
  return stepStore.stepDetails[step.id] || step
}

function stepMetadata(step: Step): Record<string, unknown> {
  const detail = detailedStep(step) as Step & { metadata_?: Record<string, unknown> | null }
  return detail.metadata_ || step.metadata_ || {}
}

function runtimeBlockDetail(block: RuntimeBlock): string {
  return block.steps.map((step) => fullStepDetailLine(detailedStep(step))).filter(Boolean).join('\n\n') || block.detail
}

function fullStepDetailLine(step: Step): string {
  const detail = step as Step & { tool_result?: string | null; metadata_?: Record<string, unknown> | null }
  const rows = []
  rows.push(`#${step.step_number} ${stepKindLabel(step.step_type, step.tool_name)} · ${statusLabel(step.status)}`)
  const target = safeStepTarget(step)
  if (target) rows.push(`目标：${target}`)
  if (step.content) rows.push(`内容：${businessText(step.content)}`)
  if (detail.tool_result) rows.push(`返回：${detail.tool_result}`)
  else if (step.tool_result_summary) rows.push(`返回：${businessText(step.tool_result_summary)}`)
  if (step.error) rows.push(`错误：${businessText(step.error)}`)
  if (detail.metadata_) rows.push(`元数据：${JSON.stringify(detail.metadata_, null, 2)}`)
  return rows.filter(Boolean).join('\n')
}

function agentRuntimeLogIds(block: RuntimeBlock): string[] {
  return block.steps
    .map((step) => stringValue(stepMetadata(step).log_id))
    .filter(Boolean)
}

function runtimeIcon(block: RuntimeBlock): string {
  if (block.status === 'running' || block.status === 'in_progress') return '•'
  if (block.status === 'failed' || block.status === 'error') return '!'
  if (block.blockType === 'decision') return '?'
  return '✓'
}

function designAgentSummary(steps: Step[]): AgentSummary {
  const completed = [...steps].reverse().find((step) => step.status === 'completed' && (detailedStep(step).tool_result_summary || (detailedStep(step) as Step & { tool_result?: string | null }).tool_result))
  const resultText = agentResultText(completed)
  const result = parseLooseObject(resultText)
  const selected = stringValue(result?.winner_name || result?.architecture || result?.selected || result?.winner) || extractAgentField(resultText, 'Winner')
  const running = steps.some((s) => s.status === 'running' || s.status === 'in_progress')
  const failed = steps.some((s) => s.status === 'failed' || s.status === 'error')
  const title = selected ? '设计完成' : running ? '正在设计方案' : failed ? '设计遇到问题' : '设计处理'
  const phaseText = steps.map((step) => stringValue(step.content || step.tool_name || step.step_type).toLowerCase()).join('\n')
  const hasPhase = (pattern: RegExp) => pattern.test(phaseText)
  const progress = agentProgressLines(steps)
  const resultSummary = agentPayloadSummary(result, resultText)
  const updates = [
    ...progress.slice(-3).map((line) => `${line.phase}：${line.detail}`),
    resultSummary,
  ]
    .filter(Boolean)
    .filter((value, index, source) => source.indexOf(value) === index)
    .slice(0, 5)
  const candidates = extractDesignCandidates(result).slice(0, 4)
  const sections = agentSummarySections(result, resultText, candidates, selected, hasPhase, running)
  return {
    title,
    task: agentTaskText(steps),
    result: resultSummary.slice(0, 1200),
    progressLabel: progress.length
      ? `第 ${progress.length} 步 · ${progress[progress.length - 1].phase}`
      : running
        ? '准备启动'
        : '暂无流式步骤',
    currentLine: progress[progress.length - 1] || null,
    selected,
    sections,
    updates,
    candidates,
    progress,
  }
}

function agentSummarySections(
  result: Record<string, unknown> | null,
  raw: string,
  candidates: string[],
  selected: string,
  hasPhase: (pattern: RegExp) => boolean,
  running: boolean,
): Array<{ label: string; value: string }> {
  const rows: Array<{ label: string; value: string }> = []
  const add = (label: string, value: string) => {
    const cleaned = businessText(value)
    if (cleaned) rows.push({ label, value: cleaned })
  }

  const intent = stringValue(result?.intent || result?.intent_summary || result?.task_intent)
  if (intent) add('意图分析', intent)
  else if (running && hasPhase(/intent|意图|目标|约束/)) add('意图分析', '正在识别目标和约束。')

  if (candidates.length) add('候选方案', candidates.join(' / '))
  else {
    const count = Number(result?.candidate_count || result?.candidates_count || 0)
    if (count > 0) add('候选方案', `已生成 ${count} 个候选方案。`)
    else if (running && hasPhase(/candidate|候选|方案/)) add('候选方案', '正在生成候选方案。')
  }

  const revision = stringValue(result?.revision_summary || result?.revision_notes)
  if (revision) add('修订', revision)
  else if (hasPhase(/revise|revision|修订|评分|score|evaluation/)) add('修订', running ? '正在评分和修订。' : '已完成评分和修订。')

  if (selected) add('决策', `选中方案：${selected}`)
  else if (running && hasPhase(/decision|最终|winner/)) add('决策', '正在形成最终选择。')

  const review = result?.architecture_review
  if (review && typeof review === 'object') {
    const record = review as Record<string, unknown>
    const verdict = stringValue(record.review_verdict || record.verdict || record.summary)
    if (verdict) add('审稿', verdict)
  }

  if (!rows.length && raw) add('摘要', agentPayloadSummary(result, raw))
  return rows
}

function agentTaskText(steps: Step[]): string {
  const taskStep = steps.find((step) => step.step_type === 'agent_call' && step.content)
    || steps.find((step) => step.content)
  return businessText(taskStep?.content || '') || '未收到任务描述'
}

function agentResultText(step?: Step): string {
  if (!step) return ''
  const detail = detailedStep(step) as Step & { tool_result?: string | null }
  return stringValue(detail.tool_result || detail.tool_result_summary || step.tool_result_summary || '')
}

function agentProgressLines(steps: Step[]): AgentProgressLine[] {
  return steps
    .filter((step) => step.step_type === 'agent_progress' || step.tool_name === 'architecture' || step.tool_name === 'design')
    .map((step, index) => {
      const raw = stringValue(detailedStep(step).content || step.content || step.tool_result_summary || step.error || '')
      const match = raw.match(/^([^:\n]{1,60}):\s*([\s\S]*)$/)
      const phase = agentPhaseLabel(match?.[1] || step.tool_name || step.step_type)
      const detail = agentProgressDetail(match?.[2] || raw || step.tool_result_summary || step.error || statusLabel(step.status))
      return {
        index: index + 1,
        phase,
        status: statusLabel(step.status),
        detail: detail || statusLabel(step.status),
      }
    })
    .filter((line) => line.detail && !isTechnicalNoise(line.detail))
}

function agentProgressDetail(value: string): string {
  const text = businessText(value)
  if (!text) return ''
  if (/要求[:：]|work root|目录|实现|完成后/i.test(text)) {
    return '正在梳理任务范围、交付物和验收条件。'
  }
  return text.length > 220 ? `${text.slice(0, 180)}...` : text
}

function agentPhaseLabel(value: string): string {
  const key = value.trim().toLowerCase()
  const map: Record<string, string> = {
    architecture: '架构管线',
    design: '架构管线',
    intent: '意图分析',
    comparable: '对标调研',
    candidates: '候选方案',
    walkthrough: '流程走查',
    revision: '修订方案',
    evaluation: '评分评估',
    adversarial: '反向检查',
    decision: '最终决策',
  }
  return map[key] || businessText(value) || 'Agent 步骤'
}

function agentLogViews(block: RuntimeBlock): AgentLogView[] {
  const views: AgentLogView[] = []
  const append = (title: string, text: string) => {
    const cleaned = text.trim()
    if (!cleaned) return
    const parsed = parseLooseValue(cleaned)
    if (parsed && typeof parsed === 'object') {
      views.push({
        title,
        kind: 'json',
        text: '',
        rows: objectRows(parsed as Record<string, unknown>),
      })
      return
    }
    views.push({
      title,
      kind: 'text',
      text: cleaned,
      rows: [],
    })
  }

  for (const step of block.steps) {
    const detail = fullStepDetailLine(detailedStep(step))
    append(`#${step.step_number} ${stepKindLabel(step.step_type, step.tool_name)}`, detail)
  }
  for (const id of agentRuntimeLogIds(block)) {
    const event = stepStore.runtimeEvents[id]
    if (!event) continue
    const title = [event.source, event.phase, event.status].filter(Boolean).join(' · ') || event.id
    append(title, event.full_text || event.preview || event.summary || '')
  }
  if (!views.length) {
    views.push({ title: '过程明细', kind: 'text', text: '暂无可展开的过程明细。', rows: [] })
  }
  return views
}

function objectRows(value: Record<string, unknown>): Array<{ key: string; value: string }> {
  return Object.entries(value)
    .filter(([, raw]) => raw !== null && raw !== undefined && raw !== '')
    .slice(0, 80)
    .map(([key, raw]) => ({ key: fieldLabel(key), value: displayJsonValue(raw) }))
}

function displayJsonValue(value: unknown): string {
  if (Array.isArray(value)) {
    return value
      .map((item) => typeof item === 'object' && item !== null ? compactObject(item as Record<string, unknown>) : stringValue(item))
      .filter(Boolean)
      .join('；')
  }
  if (value && typeof value === 'object') return compactObject(value as Record<string, unknown>)
  return businessText(stringValue(value)) || stringValue(value)
}

function compactObject(value: Record<string, unknown>): string {
  const preferred = ['name', 'title', 'summary', 'architecture', 'status', 'phase', 'detail', 'reason', 'winner_name', 'valid_design']
  const pairs = Object.entries(value)
  const selected = [
    ...preferred.filter((key) => key in value).map((key) => [key, value[key]] as [string, unknown]),
    ...pairs.filter(([key]) => !preferred.includes(key)),
  ].slice(0, 6)
  return selected
    .map(([key, raw]) => `${fieldLabel(key)}：${Array.isArray(raw) ? raw.map(stringValue).join('、') : stringValue(raw)}`)
    .filter((item) => item.length > 0)
    .join('，')
}

function fieldLabel(key: string): string {
  const labels: Record<string, string> = {
    task: '任务',
    selected_mode: '请求档位',
    result_mode: '结果档位',
    valid_design: '设计有效',
    winner_name: '选定方案',
    architecture: '架构',
    rounds: '步骤',
    degraded_rounds: '降级步骤',
    execution_estimate: '执行估计',
    handoff: '交付说明',
    design_report: '设计报告',
    trace: '过程追踪',
    status: '状态',
    phase: '阶段',
    summary: '摘要',
    detail: '详情',
    metadata: '元数据',
  }
  return labels[key] || key.replace(/_/g, ' ')
}

function agentPayloadSummary(result: Record<string, unknown> | null, raw: string): string {
  if (!result) {
    const winner = extractAgentField(raw, 'Winner')
    const architecture = extractAgentField(raw, 'Architecture')
    const mode = raw.match(/mode=([a-z]+)/i)?.[1] || ''
    const rounds = raw.match(/rounds=(\d+)/i)?.[1] || ''
    const parts = []
    if (winner) parts.push(`选定方案：${winner}`)
    if (architecture) parts.push(`架构：${architecture}`)
    if (mode) parts.push(`档位：${mode}`)
    if (rounds) parts.push(`完成 ${rounds} 个步骤`)
    return parts.join('；') || businessText(raw).slice(0, 260)
  }
  const parts = []
  const winner = stringValue(result.winner_name || result.winner || result.selected)
  const architecture = stringValue(result.architecture)
  const valid = result.valid_design
  const mode = stringValue(result.result_mode || result.selected_mode || result.mode)
  const rounds = Array.isArray(result.rounds) ? result.rounds.length : 0
  if (winner) parts.push(`选定方案：${winner}`)
  if (architecture) parts.push(`架构：${architecture}`)
  if (mode) parts.push(`档位：${mode}`)
  if (typeof valid === 'boolean') parts.push(valid ? '设计有效' : '设计未通过')
  if (rounds) parts.push(`完成 ${rounds} 个步骤`)
  return parts.join('；') || businessText(raw).slice(0, 1200)
}

function extractAgentField(text: string, label: string): string {
  const match = text.match(new RegExp(`^${label}:\\s*(.+)$`, 'im'))
  return businessText(match?.[1] || '').slice(0, 180)
}

function extractDesignCandidates(result: Record<string, unknown> | null): string[] {
  if (!result) return []
  const raw = result.candidates || result.options || result.designs
  if (!Array.isArray(raw)) return []
  return raw
    .map((item) => {
      if (!item || typeof item !== 'object') return stringValue(item)
      const record = item as Record<string, unknown>
      return stringValue(record.name || record.title || record.architecture || record.description)
    })
    .map((item) => businessText(item))
    .filter(Boolean)
}

function parseLooseObject(text: string): Record<string, unknown> | null {
  if (!text) return null
  try {
    const parsed = parseLooseValue(text)
    return parsed && typeof parsed === 'object' ? parsed as Record<string, unknown> : null
  } catch {
    return null
  }
}

function parseLooseValue(text: string): unknown | null {
  if (!text) return null
  const trimmed = text.trim()
  const fenced = trimmed.match(/```(?:json)?\s*([\s\S]*?)```/i)
  const candidate = fenced?.[1]?.trim() || extractJsonSlice(trimmed)
  if (!candidate) return null
  try {
    return JSON.parse(candidate)
  } catch {
    try {
      return JSON.parse(candidate.replace(/'/g, '"'))
    } catch {
      return null
    }
  }
}

function extractJsonSlice(text: string): string {
  const startObj = text.indexOf('{')
  const startArr = text.indexOf('[')
  const starts = [startObj, startArr].filter((index) => index >= 0)
  if (!starts.length) return ''
  const start = Math.min(...starts)
  const opener = text[start]
  const closer = opener === '{' ? '}' : ']'
  const end = text.lastIndexOf(closer)
  if (end <= start) return ''
  return text.slice(start, end + 1)
}

function shouldFoldRuntimeBlock(block: RuntimeBlock): boolean {
  if (!hasVisibleReply.value) return false
  if (!isCompletedRuntime(block)) return false
  if (isAgentRuntimeBlock(block)) return false
  return hasReplyAfter(block.createdAt)
}

function hasReplyAfter(createdAt: string): boolean {
  if (sseStore.assistantDraft) return true
  const created = new Date(createdAt).getTime()
  if (Number.isNaN(created)) return replyTimes.value.length > 0
  return replyTimes.value.some((time) => time >= created)
}

function sessionStatusLabel(session: Session): string {
  if (sessionStore.activeSession?.id === session.id && activeSessionStale.value) {
    return '已停止'
  }
  return statusLabel(session.status)
}

watch(() => messageInput.value, () => {
  resizeComposer()
})

watch(() => sseStore.assistantDraft, async (draft) => {
  upsertReplyDraft(draft)
  await scrollThreadToBottom()
})

watch(() => sseStore.assistantDraftAttachments, () => {
  upsertReplyDraft(sseStore.assistantDraft)
}, { deep: true })

function upsertReplyDraft(draft: string) {
  if (!draft || !sessionStore.activeSession) return
  const lastMsg = sessionStore.messages[sessionStore.messages.length - 1]
  if (lastMsg && lastMsg.role === 'assistant' && lastMsg.id.startsWith('local-reply')) {
    sessionStore.messages[sessionStore.messages.length - 1] = {
      ...lastMsg,
      content: draft,
      parts: {
        ...(lastMsg.parts || {}),
        reply: true,
        attachments: sseStore.assistantDraftAttachments,
      },
    }
  } else {
    sessionStore.appendMessage({
      id: `local-reply-${Date.now()}`,
      session_id: sessionStore.activeSession.id,
      role: 'assistant',
      content: draft,
      parts: { reply: true, attachments: sseStore.assistantDraftAttachments },
      created_at: new Date().toISOString(),
    })
  }
}

watch(() => stepStore.steps.length, () => {
  if (sseStore.running) scrollThreadToBottom()
})

watch(runtimeBlocks, (blocks) => {
  const previous = previousAgentStatuses.value
  const current: Record<string, string> = {}
  const nextExpanded = new Set(expandedSteps.value)
  for (const block of blocks) {
    if (!isAgentRuntimeBlock(block)) continue
    current[block.id] = block.status
    const wasRunning = previous[block.id] === 'running' || previous[block.id] === 'in_progress'
    const isRunning = block.status === 'running' || block.status === 'in_progress'
    if (wasRunning && !isRunning) nextExpanded.delete(block.id)
  }
  previousAgentStatuses.value = current
  expandedSteps.value = nextExpanded
})

watch(() => sseStore.gitRefreshTick, async (tick, previous) => {
  if (!tick || tick === previous) return
  const sessionId = sessionStore.activeSession?.id
  if (!sessionId || sseStore.lastGitSessionId !== sessionId) return
  await Promise.all([
    loadGitGraph(sessionId, false),
    loadSessionChanges(sessionId, false),
  ])
})
</script>

<template>
  <div class="writer-shell" :class="shellClass" :style="shellStyle">
    <div v-if="errorText" class="error-toast">{{ errorText }}</div>
    <div v-if="noticeText" class="notice-toast">{{ noticeText }}</div>
    <div class="edge edge-left" @mouseenter="!leftPinned && (leftOpen = true)"></div>
    <div class="edge edge-right" @mouseenter="rightOpen = true"></div>

    <aside class="writer-drawer drawer-left" :class="{ open: leftOpen, pinned: leftPinned }" @mouseleave="onLeftDrawerLeave">
      <header class="drawer-head">
        <button class="pin-plain" :class="{ active: leftPinned }" title="固定侧栏" @click="toggleLeftPinned">
          {{ leftPinned ? '◆' : '◇' }}
        </button>
        <strong>LamWriter</strong>
        <button class="icon-btn" title="新建项目" @click="openNewProjectModal">+</button>
      </header>

      <div class="drawer-body">
        <div v-if="projectStore.loading && projectStore.projects.length === 0" class="empty">Loading...</div>
        <div v-if="!projectStore.loading && projectStore.projects.length === 0" class="empty">No projects. Create one.</div>

        <section
          v-for="group in projectGroups"
          :key="group.key"
          class="project-block"
          :class="{ active: isProjectGroupActive(group) }"
          @click="onSelectProjectGroup(group)"
          @contextmenu.prevent="openAgentsMd(group.primary.id)"
        >
          <div class="project-top">
            <div class="project-btns">
              <button class="project-action add" title="新建会话" @click.stop="onOpenNewSession(group.primary.id)">+</button>
              <button
                class="project-action fold"
                :title="projectSessionToggleTitle(group.key)"
                @click.stop="cycleProjectSessionMode(group.key)"
              >
                {{ projectSessionToggleLabel(group.key) }}
              </button>
              <button class="project-action remove" title="删除项目" @click.stop="onDeleteProjectGroup(group.projects.map((project) => project.id))">×</button>
            </div>
            <div class="project-name">
              <strong>{{ projectDisplayName(group.primary) }}</strong>
              <span class="work-root">{{ group.primary.work_root }}</span>
            </div>
          </div>

          <div class="conversation-list">
            <button
              v-for="s in visibleProjectSessions(group)"
              :key="s.id"
              class="conversation"
              :class="{ active: sessionStore.activeSession?.id === s.id }"
              @click.stop="onSelectSession(s.id)"
            >
              <span class="conversation-dot"></span>
              <span>
                <strong>{{ s.title || `Session ${s.id.slice(0, 8)}` }}</strong>
                <span>#{{ s.id.slice(0, 8) }} · {{ phaseLabel(s.phase) }} / {{ s.mode }}</span>
              </span>
              <span class="status" :class="statusClass(s.status)">{{ sessionStatusLabel(s) }}</span>
            </button>
            <button
              v-if="hiddenProjectSessionCount(group) > 0"
              type="button"
              class="conversation-more"
              @click.stop="cycleProjectSessionMode(group.key)"
            >
              还有 {{ hiddenProjectSessionCount(group) }} 个会话
            </button>
          </div>
        </section>
      </div>

      <footer class="drawer-footer">
        <button class="settings-entry" @click="goToSettings">
          <span>⌘</span>
          <span>Settings</span>
        </button>
      </footer>
    </aside>

    <main class="writer-main" ref="mainArea">
      <header class="thread-header">
        <div>
          <h1>{{ sessionStore.activeSession?.title || 'No session selected' }}</h1>
          <span v-if="sessionStore.activeSession">#{{ sessionStore.activeSession.id.slice(0, 8) }}</span>
          <span class="run-status" :class="{ running: sseStore.running }">{{ statusTextCn }}</span>
          <div v-if="planProgressView" class="runtime-progress-strip">
            <span>计划 {{ planProgressView.completed }}/{{ planProgressView.total || '?' }}</span>
            <div class="runtime-progress-track"><i :style="{ width: `${planProgressView.pct}%` }"></i></div>
            <span v-if="planProgressView.currentStep">{{ planProgressView.currentStep }}</span>
          </div>
        </div>
        <div class="header-controls">
          <button v-if="sseStore.running" class="small-btn danger" @click="onCancelRun">停止</button>
        </div>
      </header>
      <section class="thread" ref="messagesArea">
        <div v-if="displayTranscriptItems.length === 0" class="empty">
          {{ sessionStore.activeSession ? '暂无消息，发送一个任务。' : '选择一个会话开始。' }}
        </div>

        <template v-for="item in displayTranscriptItems" :key="item.id">
          <div v-if="item.kind === 'message' && item.message.role === 'user'" class="user-row">
            <div class="user-bubble">
              <div v-if="item.message.content">{{ item.message.content }}</div>
              <div v-if="replyAttachments(item.message).length" class="reply-attachments user-attachments">
                <button
                  v-for="attachment in replyAttachments(item.message)"
                  :key="attachment.id"
                  class="reply-attachment"
                  type="button"
                  @click="openReplyAttachment(attachment)"
                >
                  <span>
                    <strong>{{ attachmentTitle(attachment) }}</strong>
                    <small>{{ attachmentSourceLabel(attachment) }}</small>
                  </span>
                  <em>{{ attachment.preview_type === 'text' ? '预览' : '打开' }}</em>
                </button>
              </div>
            </div>
          </div>
          <div v-else-if="item.kind === 'message' && isReplyMessage(item.message)" class="writer-reply-row">
            <div class="writer-reply-bubble">
              <div class="reply-label">Writer</div>
              <div v-html="renderReply(item.message.content)"></div>
              <div v-if="replyAttachments(item.message).length" class="reply-attachments">
                <button
                  v-for="attachment in replyAttachments(item.message)"
                  :key="attachment.id"
                  class="reply-attachment"
                  type="button"
                  @click="openReplyAttachment(attachment)"
                >
                  <span>
                    <strong>{{ attachmentTitle(attachment) }}</strong>
                    <small>{{ attachmentSourceLabel(attachment) }}</small>
                  </span>
                  <em>{{ attachment.preview_type && attachment.preview_type !== 'text' ? '打开' : '预览' }}</em>
                </button>
              </div>
            </div>
          </div>
          <article
            v-else-if="item.kind === 'message' && lifecycleView(item.message)"
            class="lifecycle-card"
            :class="lifecycleView(item.message)?.severity"
          >
            <div class="lifecycle-top">
              <div>
                <strong>{{ lifecycleView(item.message)?.title }}</strong>
                <div v-if="lifecycleView(item.message)?.reason" class="lifecycle-reason">
                  原因：{{ lifecycleView(item.message)?.reason }}
                </div>
              </div>
              <span class="lifecycle-badge">{{ lifecycleView(item.message)?.statusLabel }}</span>
            </div>
            <pre v-if="lifecycleView(item.message)?.detail" class="lifecycle-detail">{{ lifecycleView(item.message)?.detail }}</pre>
          </article>
          <article
            v-else-if="item.kind === 'message' && decisionView(item.message)"
            class="decision-card"
            :class="[`decision-kind-${decisionView(item.message)?.kind}`, { blocking: decisionView(item.message)?.blocking }]"
          >
            <div class="decision-top">
              <div>
                <div class="decision-kind">{{ decisionView(item.message)?.kindLabel }}</div>
                <strong>{{ decisionView(item.message)?.title }}</strong>
                <div v-if="decisionView(item.message)?.reason" class="decision-reason">
                  {{ decisionView(item.message)?.reason }}
                </div>
              </div>
              <span class="decision-badge" :class="{ blocking: decisionView(item.message)?.blocking }">
                {{ decisionView(item.message)?.statusLabel }}
              </span>
            </div>
            <div v-if="decisionView(item.message)?.prompt" class="decision-prompt">
              {{ decisionView(item.message)?.prompt }}
            </div>
            <div class="decision-options">
              <button
                v-for="option in decisionView(item.message)?.options || []"
                :key="String(option.id || option.value || option.name || decisionOptionLabel(option))"
                type="button"
                class="decision-option"
                @click="sendDecisionOption(option)"
              >
                <span>{{ decisionOptionLabel(option) }}</span>
                <small v-if="decisionOptionDescription(option)">{{ decisionOptionDescription(option) }}</small>
              </button>
            </div>
            <div
              v-if="decisionView(item.message)?.plan || decisionView(item.message)?.details.length"
              class="decision-disclosures"
            >
              <details v-if="decisionView(item.message)?.plan" class="decision-plan">
                <summary>查看完整计划</summary>
                <p v-if="decisionView(item.message)?.plan?.goal" class="decision-plan-goal">
                  {{ decisionView(item.message)?.plan?.goal }}
                </p>
                <ol v-if="decisionView(item.message)?.plan?.steps.length" class="decision-plan-steps">
                  <li v-for="step in decisionView(item.message)?.plan?.steps || []" :key="step.index">
                    <div>
                      <strong>{{ step.index }}. {{ step.description }}</strong>
                      <small v-if="step.deliverables.length">产出：{{ step.deliverables.join('、') }}</small>
                      <small v-if="step.acceptance.length">验收：{{ step.acceptance.join('；') }}</small>
                    </div>
                  </li>
                </ol>
                <div v-if="decisionView(item.message)?.plan?.constraints.length" class="decision-plan-constraints">
                  <span v-for="constraint in decisionView(item.message)?.plan?.constraints" :key="constraint">
                    {{ constraint }}
                  </span>
                </div>
              </details>
              <details v-if="decisionView(item.message)?.details.length" class="decision-more">
                <summary>查看决策背景</summary>
                <div class="decision-detail-grid">
                  <section v-for="section in decisionView(item.message)?.details || []" :key="section.label">
                    <strong>{{ section.label }}</strong>
                    <p v-for="line in section.lines" :key="line">{{ line }}</p>
                  </section>
                </div>
              </details>
            </div>
          </article>
          <div
            v-else-if="item.kind === 'message'"
            class="writer-output"
            v-html="renderMarkdown(item.message.content)"
          ></div>
          <button
            v-else-if="item.kind === 'runtime-group'"
            class="processed-row"
            type="button"
            @click="runtimeProcessedExpanded = !runtimeProcessedExpanded"
          >
            <span>{{ item.title }}</span>
            <span class="chevron" :class="{ open: runtimeProcessedExpanded }">›</span>
          </button>
          <article v-else class="writer-card process-card" :class="runtimeBlockClass(item)">
            <template v-if="item.blockType === 'design-agent' && item.agentSummary">
              <div class="agent-card-inner">
                <header class="agent-head">
                  <div>
                    <strong>{{ item.agentSummary.title }}</strong>
                    <span>{{ item.agentSummary.progressLabel }}</span>
                  </div>
                  <button class="agent-expand" type="button" @click="toggleStep(item.id)">
                    {{ expandedSteps.has(item.id) ? '收起已收到过程' : '展开已收到过程' }}
                  </button>
                </header>
                <div
                  v-if="item.agentSummary.currentLine && !expandedSteps.has(item.id) && (item.status === 'running' || item.status === 'in_progress')"
                  class="agent-current"
                >
                  <span>正在处理</span>
                  <p>第 {{ item.agentSummary.currentLine.index }} 步 · {{ item.agentSummary.currentLine.phase }}：{{ item.agentSummary.currentLine.detail }}</p>
                </div>
                <div
                  v-else-if="!expandedSteps.has(item.id)"
                  class="agent-current agent-current-muted"
                >
                  <span>{{ statusLabel(item.status) }}</span>
                  <p>{{ item.agentSummary.result || item.agentSummary.updates[0] || 'Agent 过程已折叠。' }}</p>
                </div>
                <div v-if="expandedSteps.has(item.id)" class="agent-task">
                  <strong>任务</strong>
                  <p>{{ item.agentSummary.task }}</p>
                </div>
                <div v-if="expandedSteps.has(item.id)" class="agent-grid">
                  <template v-for="section in item.agentSummary.sections" :key="section.label">
                    <div>{{ section.label }}</div>
                    <div>{{ section.value }}</div>
                  </template>
                </div>
                <div
                  v-if="item.agentSummary.progress.length && expandedSteps.has(item.id)"
                  class="agent-stream"
                >
                  <strong>流式过程</strong>
                  <div v-for="line in item.agentSummary.progress" :key="`${item.id}-${line.index}`" class="agent-stream-line">
                    <span>第 {{ line.index }} 步 · {{ line.phase }}</span>
                    <small>{{ line.status }}</small>
                    <p>{{ line.detail }}</p>
                  </div>
                </div>
                <div v-if="expandedSteps.has(item.id) && item.agentSummary.updates.length" class="agent-updates">
                  <strong>最新进展</strong>
                  <p v-for="update in item.agentSummary.updates" :key="update">{{ update }}</p>
                </div>
                <div v-if="expandedSteps.has(item.id) && item.agentSummary.result" class="agent-result">
                  <strong>返回信息</strong>
                  <p>{{ item.agentSummary.result }}</p>
                </div>
                <div v-if="expandedSteps.has(item.id)" class="agent-full-log">
                  <section
                    v-for="log in agentLogViews(item)"
                    :key="`${item.id}-${log.title}`"
                    class="agent-log-section"
                  >
                    <h4>{{ log.title }}</h4>
                    <dl v-if="log.kind === 'json'" class="agent-json-view">
                      <template v-for="row in log.rows" :key="row.key">
                        <dt>{{ row.key }}</dt>
                        <dd>{{ row.value }}</dd>
                      </template>
                    </dl>
                    <pre v-else>{{ log.text }}</pre>
                  </section>
                </div>
              </div>
            </template>
            <template v-else>
            <div class="step-head">
              <span class="done-mark" :class="{ 'running-dot': item.status === 'running' || item.status === 'in_progress' }">
                {{ runtimeIcon(item) }}
              </span>
              <button class="step-toggle" type="button" @click="toggleStep(item.id)">
                <span class="step-title">{{ item.title }}</span>
                <span class="step-sub">{{ item.subtitle }} · {{ formatTime(item.createdAt) }}</span>
              </button>
              <span class="chevron" :class="{ open: expandedSteps.has(item.id) }">›</span>
            </div>
            <div v-if="expandedSteps.has(item.id)" class="step-body runtime-detail">
              <pre>{{ runtimeBlockDetail(item) }}</pre>
              <div v-if="item.steps.length > 1" class="runtime-substeps">
                <div v-for="step in item.steps" :key="step.id" class="runtime-substep">
                  <span>{{ step.step_number }}. {{ stepKindLabel(step.step_type, step.tool_name) }}</span>
                  <span :class="statusClass(step.status)">{{ statusLabel(step.status) }}</span>
                </div>
              </div>
              <button
                v-if="item.steps.some((step) => step.status === 'failed')"
                class="btn-retry"
                @click.stop="onRetryStep(item.steps.find((step) => step.status === 'failed')!.id)"
              >
                重试失败步骤
              </button>
            </div>
            </template>
          </article>
        </template>

        <button
          v-if="showActivityProcessedRow"
          class="processed-row"
          type="button"
          @click="activityProcessedExpanded = !activityProcessedExpanded"
        >
          <span>已处理 {{ activeSessionActivities.length }} 条过程</span>
          <span class="chevron" :class="{ open: activityProcessedExpanded }">›</span>
        </button>

        <article v-if="showActivityFlow || showActivityProcessedDetails" class="activity-flow-card" :class="{ compact: showActivityProcessedDetails }">
          <header class="activity-flow-head">
            <div>
              <strong>{{ showActivityProcessedDetails ? '过程明细' : 'Writer 过程' }}</strong>
              <span>{{ statusTextCn }}</span>
            </div>
            <em>{{ activeSessionActivities.length }} 条事件</em>
          </header>
          <div class="activity-groups">
            <section
              v-for="group in activityGroupViews"
              :key="group.group"
              class="activity-group"
              :class="[group.status, { active: sseStore.activeActivityGroup === group.group }]"
            >
              <header>
                <span class="activity-dot"></span>
                <strong>{{ group.label }}</strong>
                <em>{{ group.count }}</em>
              </header>
              <div class="activity-lines">
                <small v-if="group.hiddenCount" class="activity-hidden">
                  还有 {{ group.hiddenCount }} 条较早过程，展开后查看。
                </small>
                <div v-for="activity in group.items" :key="activity.id" class="activity-line">
                  <span>{{ activity.label }}</span>
                  <small v-if="activity.detail">{{ activity.detail }}</small>
                  <pre
                    v-if="activityProcessedExpanded && activity.raw_detail && activity.raw_detail !== activity.detail"
                    class="activity-raw"
                  >{{ activity.raw_detail }}</pre>
                </div>
              </div>
            </section>
          </div>
        </article>

        <article
          v-if="editedFiles.length > 0"
          class="change-review-card"
          role="button"
          tabindex="0"
          @click="openChangeReview"
          @keydown.enter.prevent="openChangeReview"
          @keydown.space.prevent="openChangeReview"
        >
          <div class="change-review-head">
            <div class="change-icon">{{ reviewMode === 'diff' ? '⊞' : '≡' }}</div>
            <div>
              <strong>{{ changeReviewTitle }}</strong>
              <span>{{ changeReviewSubtitle || '点击审核查看对应改动' }}</span>
            </div>
            <button type="button" class="review-undo" :disabled="undoingChanges" @click.stop="onUndoChanges">
              {{ undoingChanges ? '撤销中' : '撤销 ↶' }}
            </button>
            <button type="button" class="review-btn" @click.stop.prevent="openChangeReview">{{ changeReviewActionLabel }}</button>
          </div>
        </article>

        <article v-if="showProcessingPlaceholder" class="writer-card process-card">
          <div class="step-head">
            <span class="done-mark running-dot">•</span>
            <button class="step-toggle" type="button">
              <span class="step-title">Writer 正在处理</span>
              <span class="step-sub">{{ workflowLabel || statusTextCn }}</span>
            </button>
            <span class="chevron">›</span>
          </div>
          <div class="step-body processing-body">
            <div v-if="planProgressView" class="runtime-progress-card">
              <div>
                <strong>计划进度</strong>
                <span>{{ planProgressView.completed }}/{{ planProgressView.total || '?' }}</span>
              </div>
              <div class="runtime-progress-track"><i :style="{ width: `${planProgressView.pct}%` }"></i></div>
              <small v-if="planProgressView.nextStep">下一步：{{ planProgressView.nextStep }}</small>
            </div>
            <div class="typing-indicator"><span></span><span></span><span></span></div>
          </div>
        </article>
      </section>
    </main>

    <form
      ref="composerEl"
      class="floating-composer"
      :class="{ dragover: dragOver }"
      @submit.prevent="onSendMessage"
      @dragover.prevent="dragOver = true"
      @dragleave="dragOver = false"
      @drop.prevent="dragOver = false"
    >
      <input
        ref="fileInput"
        type="file"
        multiple
        class="hidden-file-input"
        @change="onAttachmentSelected"
      />
      <div v-if="pendingAttachments.length" class="pending-attachments">
        <button
          v-for="attachment in pendingAttachments"
          :key="attachment.id"
          class="pending-attachment"
          type="button"
          @click="removePendingAttachment(attachment.id)"
        >
          <span>{{ attachment.filename }}</span>
          <em>移除</em>
        </button>
      </div>
      <textarea
        ref="messageBox"
        v-model="messageInput"
        :disabled="sseStore.running && !sseStore.awaitingUser"
        rows="1"
        placeholder="要求后续变更"
        @keydown.enter.exact.prevent="onSendMessage"
        @keydown.ctrl.enter.prevent="onSendMessage"
      ></textarea>
      <div class="composer-bottom">
        <div class="tool-row">
          <button
            class="attach"
            type="button"
            title="上传附件"
            :disabled="uploadingAttachment || !sessionStore.activeSession"
            @click="triggerAttachmentUpload"
          >
            {{ uploadingAttachment ? '…' : '＋' }}
          </button>
          <div class="composer-menu-wrap">
            <button
              class="composer-pill"
              :class="{ open: showModelMenu }"
              type="button"
              aria-label="模型选择"
              @click="toggleModelMenu"
            >
              <strong>{{ selectedModelLabel }}</strong>
            </button>
            <div v-if="showModelMenu" class="composer-menu model-menu">
              <div v-for="group in modelGroups" :key="group.providerId" class="composer-menu-group">
                <div class="composer-menu-heading">{{ group.providerName }}</div>
                <button
                  v-for="option in group.models"
                  :key="option.value"
                  class="composer-menu-item model-option"
                  :class="{ active: selectedModel === option.value }"
                  type="button"
                  @click="selectModel(option.value)"
                >
                  <strong>{{ option.label }}</strong>
                </button>
              </div>
            </div>
          </div>
          <div class="composer-menu-wrap">
            <button
              class="composer-pill"
              :class="{ open: showQualityMenu }"
              type="button"
              aria-label="质量档位"
              @click="toggleQualityMenu"
            >
              <span class="quality-label">quality</span>
              <strong>{{ qualityMode }}</strong>
            </button>
            <div v-if="showQualityMenu" class="composer-menu quality-menu">
              <button
                v-for="option in qualityOptions"
                :key="option.value"
                class="composer-menu-item"
                :class="{ active: qualityMode === option.value }"
                type="button"
                @click="selectQuality(option.value)"
              >
                <strong>{{ option.value }}</strong>
                <span>{{ option.note }}</span>
              </button>
            </div>
          </div>
        </div>
        <button class="send" type="submit" title="发送" :disabled="!canSend">↑</button>
      </div>
      <div class="drop-hint">拖拽图片到这里上传</div>
    </form>

    <aside class="writer-drawer drawer-right" :class="{ open: rightOpen, pinned: rightPinned }" @mouseleave="onRightDrawerLeave">
      <header class="drawer-head">
        <strong>运行状态</strong>
        <button class="pin-plain" :class="{ active: rightPinned }" title="固定侧栏" @click="toggleRightPinned">
          {{ rightPinned ? '◆' : '◇' }}
        </button>
      </header>
      <div class="drawer-body right-body">
        <section v-if="uiSettings.showGitGraph" class="side-section">
          <h3>Git</h3>
          <div v-if="gitError" class="git-empty">{{ gitDisplayError }}</div>
          <div v-else-if="!gitGraph" class="git-empty">暂无 Git 数据</div>
          <div v-else-if="gitGraph.lanes.length === 0" class="git-empty">当前 Work root 不是 Git 仓库</div>
          <div v-else class="git-log">
            <button
              v-if="gitWorkingTreeSummary"
              class="git-working-tree"
              type="button"
              @click="openChangeReview"
            >
              <span>
                <strong>{{ gitWorkingTreeSummary.label }}</strong>
                <small>{{ gitWorkingTreeSummary.files.length }} 个文件 · {{ gitWorkingTreeSummary.stat }}</small>
              </span>
              <em>查看</em>
            </button>
            <div v-if="gitWorkingTreeSummary" class="git-dirty-files">
              <div v-for="file in gitWorkingTreeSummary.files.slice(0, 5)" :key="file.path" class="git-dirty-file">
                <span>{{ file.path }}</span>
                <strong v-if="file.binary">二进制</strong>
                <strong v-else>+{{ file.additions ?? 0 }} -{{ file.deletions ?? 0 }}</strong>
              </div>
              <div v-if="gitWorkingTreeSummary.files.length > 5" class="git-dirty-more">
                还有 {{ gitWorkingTreeSummary.files.length - 5 }} 个文件
              </div>
            </div>
            <div class="git-tree-line">
              <div
                v-for="commit in gitTimeline"
                :key="commit.sha"
                class="git-tree-row"
                :class="{ current: commit.isHead, first: commit.index === 0, last: commit.index === gitTimeline.length - 1 }"
              >
                <span class="git-graph-cell"><span class="rail"></span><span class="commit-node"></span></span>
                <span class="git-tree-main">
                  <span class="git-message">{{ shortSha(commit.sha) }} · {{ commit.message || 'commit' }}</span>
                  <span v-if="commit.labels.length" class="git-labels">
                    <span v-for="label in commit.labels" :key="label" class="git-label" :class="{ current: label === gitGraph.current_branch }">
                      {{ label }}
                    </span>
                  </span>
                </span>
              </div>
            </div>
          </div>
        </section>

        <section v-if="uiSettings.showRuntime" class="side-section">
          <h3>Status</h3>
          <div class="activity-item"><span class="activity-kind">流状态</span><span class="activity-text">{{ sseStore.running ? '运行中' : '空闲' }}</span></div>
          <div class="activity-item"><span class="activity-kind">运行时长</span><span class="activity-text">{{ elapsedText }}</span></div>
          <div class="activity-item"><span class="activity-kind">LLM 调用</span><span class="activity-text">{{ sseStore.llmCallCount }}</span></div>
          <div class="activity-item"><span class="activity-kind">事件数</span><span class="activity-text">{{ sseStore.eventCount }}</span></div>
          <div class="activity-item" v-if="sseStore.lastEventAt"><span class="activity-kind">最近事件</span><span class="activity-text">{{ formatTime(sseStore.lastEventAt) }}</span></div>
          <div class="activity-item" v-if="workflowLabel"><span class="activity-kind">工作流</span><span class="activity-text">{{ workflowLabel }}</span></div>
          <div class="side-progress" v-if="planProgressView">
            <div class="activity-item"><span class="activity-kind">计划进度</span><span class="activity-text">{{ planProgressView.completed }}/{{ planProgressView.total || '?' }}</span></div>
            <div class="runtime-progress-track"><i :style="{ width: `${planProgressView.pct}%` }"></i></div>
          </div>
          <div class="activity-item" v-if="slowModelWaitText"><span class="activity-kind">模型等待</span><span class="activity-text warn">{{ slowModelWaitText }}</span></div>
        </section>
      </div>
    </aside>

    <div v-if="showNewProject" class="modal-overlay" @click.self="showNewProject = false">
      <div class="modal-card">
        <h2>新建项目</h2>
        <div class="form-grid">
          <label>Work root
            <div class="path-row">
              <input v-model="newProjectRoot" placeholder="E:\MyProject" />
              <button class="small-btn" type="button" @click="chooseWorkRoot">路径说明</button>
            </div>
          </label>
          <p class="hint">项目名会自动使用 Work root 最后一级文件夹名；同一个 Work root 只对应一个项目。</p>
        </div>
        <div class="modal-actions">
          <button @click="showNewProject = false">取消</button>
          <button class="btn-primary" @click="onCreateProject">创建项目</button>
        </div>
      </div>
    </div>

    <div v-if="showNewSession" class="modal-overlay" @click.self="showNewSession = false">
      <div class="modal-card">
        <h2>新建会话</h2>
        <div class="form-grid">
          <label>命名 <input v-model="newSessionTitle" /></label>
        </div>
        <p class="hint">Work root 会继承当前项目。</p>
        <div class="modal-actions">
          <button @click="showNewSession = false">取消</button>
          <button class="btn-primary" @click="onCreateSession">创建会话</button>
        </div>
      </div>
    </div>

    <div v-if="showAgentsMd" class="modal-overlay" @click.self="showAgentsMd = false">
      <div class="modal-card wide">
        <h2>AGENTS.md</h2>
        <textarea v-model="projectStore.agentsMdContent" class="agents-editor"></textarea>
        <div class="modal-actions">
          <button @click="showAgentsMd = false">取消</button>
          <button class="btn-primary" @click="saveAgentsMd">保存配置</button>
        </div>
      </div>
    </div>

    <div v-if="replyAttachmentPreview" class="modal-overlay" @click.self="closeReplyAttachmentPreview">
      <div class="modal-card wide reply-attachment-modal">
        <header class="reply-attachment-head">
          <div>
            <h2>{{ replyAttachmentPreview.title }}</h2>
            <span>{{ attachmentSourceLabel(replyAttachmentPreview.attachment) }}</span>
          </div>
          <button class="small-btn" type="button" @click="closeReplyAttachmentPreview">关闭</button>
        </header>
        <div v-if="replyAttachmentPreview.loading" class="attachment-loading">正在读取附件内容。</div>
        <pre v-else class="reply-attachment-body">{{ replyAttachmentPreview.body }}</pre>
      </div>
    </div>

    <div v-if="showChangeReview" class="modal-overlay review-overlay" @click.self="showChangeReview = false">
      <div class="modal-card diff-modal" :class="{ wrap: diffWrap }">
        <header class="diff-modal-head">
          <div>
            <h2>改动审核</h2>
            <p>{{ changeReviewSubtitle || '暂无 Git diff，当前仅显示 Writer 步骤统计。' }}</p>
          </div>
          <div class="diff-modal-actions">
            <button class="small-btn" type="button" @click="diffWrap = !diffWrap">
              {{ diffWrap ? '取消换行' : '自动换行' }}
            </button>
            <button class="small-btn" type="button" :disabled="undoingChanges" @click="onUndoChanges">
              {{ undoingChanges ? '撤销中' : '撤销 ↶' }}
            </button>
            <button class="small-btn" type="button" @click="showChangeReview = false">关闭</button>
          </div>
        </header>
        <div class="diff-modal-body">
          <aside class="diff-file-pane">
            <button
              v-for="file in editedFiles"
              :key="file.path"
              class="diff-file-item"
              :class="{ active: selectedDiffPath === file.path }"
              type="button"
              @click="scrollDiffFile(file.path)"
            >
              <span>{{ file.path }}</span>
              <strong v-if="file.binary">二进制</strong>
              <strong v-else-if="file.source === 'git'">+{{ file.additions ?? 0 }} -{{ file.deletions ?? 0 }}</strong>
              <strong v-else>{{ file.count }} 次</strong>
            </button>
          </aside>
          <section class="diff-content-pane">
            <p v-if="changesError" class="change-note">{{ changesError }}</p>
            <pre v-if="sessionChanges?.diff_stat && !parsedDiffFiles.length" class="change-diff-stat">{{ sessionChanges.diff_stat }}</pre>
            <div v-if="parsedDiffFiles.length" class="code-diff-view">
              <section
                v-for="file in visibleDiffFiles"
                :id="safeDiffId(file.path)"
                :key="file.path"
                class="code-diff-file"
              >
                <header class="code-diff-file-head">{{ file.path }}</header>
                <template v-for="block in file.blocks" :key="block.id">
                  <button v-if="block.kind === 'fold'" class="diff-fold" type="button">
                    <span>⌃</span>
                    <strong>{{ block.count }} unmodified lines</strong>
                  </button>
                  <div v-else class="diff-row-group">
                    <div
                      v-for="(row, index) in block.rows"
                      :key="`${block.id}-${index}`"
                      class="diff-code-row"
                      :class="`is-${row.type}`"
                    >
                      <span class="diff-line old">{{ row.oldLine ?? '' }}</span>
                      <span class="diff-line new">{{ row.newLine ?? '' }}</span>
                      <code>{{ row.text || ' ' }}</code>
                    </div>
                  </div>
                </template>
              </section>
            </div>
            <pre v-else-if="sessionChanges?.diff" class="change-diff">{{ sessionChanges.diff }}</pre>
            <div v-if="!sessionChanges?.diff && !changesError" class="empty compact-empty">
              当前没有可展示的 Git patch。
            </div>
          </section>
        </div>
      </div>
    </div>

    <div v-if="showUndoConfirm" class="modal-overlay undo-overlay" @click.self="showUndoConfirm = false">
      <div class="modal-card">
        <h2>撤销改动</h2>
        <p class="hint">将撤销当前审核面板中显示的改动；新增文件会被删除，已跟踪文件会恢复到 Git 当前版本。</p>
        <div class="modal-actions">
          <button type="button" @click="showUndoConfirm = false">取消</button>
          <button class="btn-primary" type="button" @click="confirmUndoChanges">确认撤销</button>
        </div>
      </div>
    </div>
  </div>
</template>
