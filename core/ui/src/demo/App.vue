<template>
  <CoreSettings
    v-if="showSettings"
    :models="availableModels"
    :providers="availableProviders"
    :density="density"
    :theme="theme"
    :content-width="contentWidth"
    :allow-environment-import="true"
    :command-policies="commandPolicies"
    @close="showSettings = false"
    @update:density="uiPreferences.setDensity"
    @update:content-width="uiPreferences.setContentWidth"
    @reset-theme="uiPreferences.resetTheme"
    @apply-preset="uiPreferences.applyThemePreset"
    @update-stops="uiPreferences.updateThemeStops"
    @update-angle="uiPreferences.updateThemeAngle"
    @update-opacity="uiPreferences.updateThemeOpacity"
    @update-text-color="uiPreferences.updateThemeText"
    @add-stop="uiPreferences.addStop"
    @remove-stop="uiPreferences.removeStop"
    @sort-stops="uiPreferences.sortStops"
    @import-environment="importEnvironmentConfig"
    @update-command-policy="updateCommandPolicy"
    @create-provider="createProvider"
    @update-provider="updateProvider"
    @delete-provider="deleteProvider"
    @create-model="createModel"
    @update-model="updateModel"
    @delete-model="deleteModel"
  />
  <WorkspaceShell
    v-else
    product-name="LamTools Core"
    sidebar-title="Core"
    :storage-key="settingsStorageKey"
    :density="density"
    :theme="theme"
    :content-width="contentWidth"
    :composer-disabled="composerActionMode === 'send' && (!activeSessionId || (!composerText.trim() && pendingAttachments.length === 0))"
    :composer-action-mode="composerActionMode"
    :error-text="workbenchErrorText"
    :notice-text="runtimeStatusText"
    @new-session="openProjectCreate"
    @settings="showSettings = true"
    @composer-submit="submitComposer"
    @composer-drop="handleComposerDrop"
  >
    <template #sidebar-header-action>
      <div class="core-project-header-action">
        <button class="icon-btn" type="button" title="新建项目" aria-label="新建项目" @click="openProjectCreate">+</button>
        <CoreProjectCreate
          v-if="showProjectCreate"
          :loading="projectCreateLoading"
          :error="projectCreateError"
          :select-work-root="pickProjectDirectory"
          @submit="createProject"
          @cancel="closeProjectCreate"
        />
      </div>
    </template>

    <template #sidebar-body>
      <SessionSidebar
        :project-groups="projectGroups"
        :project-session-limit="8"
        pin-storage-key="lamtools-core.sidebar.pinned-projects"
        :active-session-id="activeSessionId || undefined"
        :busy-project-ids="busyProjectIds"
        :allow-project-delete="true"
        :allow-project-click="true"
        :allow-project-context-menu="true"
        :allow-session-delete="true"
        @select-session="selectSession"
        @select-project="openProjectActions"
        @new-session="createProjectSession"
        @delete-project="deleteProject"
        @project-context-menu="openProjectActions"
        @rename-session="renameSession"
        @delete-session="deleteSession"
      />
      <section v-if="selectedProject" class="core-project-management" :aria-busy="projectActionLoading">
        <form @submit.prevent="renameProject">
          <label>
            <span>项目名称</span>
            <input v-model="projectNameDraft" class="field-input" :disabled="projectActionLoading" />
          </label>
          <div class="core-project-management-actions">
            <button type="button" class="btn-cancel" :disabled="projectActionLoading || agentsLoading" @click="openAgentsEditor">AGENTS.md</button>
            <button type="submit" class="btn-primary-sm" :disabled="projectActionLoading || !projectNameDraft.trim()">
              {{ projectActionLoading ? '保存中' : '重命名' }}
            </button>
          </div>
        </form>
        <p v-if="projectActionError" class="core-project-management-error" role="alert">{{ projectActionError }}</p>
      </section>
      <CoreAgentsEditor
        v-if="agentsProjectId"
        :content="agentsContent"
        :loading="agentsLoading"
        :error="agentsError"
        @save="saveAgents"
        @close="closeAgentsEditor"
      />
    </template>

    <template #main-content>
      <section
        ref="threadScrollEl"
        class="thread"
        @scroll.passive="threadScroll.handleScroll"
        @wheel.passive="threadScroll.handleWheel"
      >
        <ChatThread
          :messages="messages"
          :process-expanded-ids="processExpandedIds"
          @toggle-process="toggleProcess"
          @decision-select="approvalController.handleDecision"
        />
      </section>
    </template>

    <template #composer-textarea>
      <input ref="attachmentFileInput" class="sr-only" type="file" multiple @change="handleAttachmentInputChange" />
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
      <div class="composer-input-wrap" :class="{ 'has-command-tokens': hasComposerCommandTokens }">
        <CommandPalette
          v-if="commandPaletteVisible"
          :commands="commandPalette.filteredCommands.value"
          :active-index="commandPalette.activeIndex.value"
          @select="liveComposerController.selectCommand"
        />
        <div v-if="hasComposerCommandTokens" class="composer-syntax-overlay" aria-hidden="true">
          <span
            v-for="(segment, index) in composerHighlightSegments"
            :key="index"
            :class="{ 'composer-skill-token': segment.command }"
          >{{ segment.text }}</span>
        </div>
        <textarea
          ref="composerTextareaEl"
          v-model="composerText"
          :disabled="!activeSessionId"
          placeholder="给 Core Agent 发送任务..."
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
        shallow-label="Shallow"
        @update:model-value="executionControls.selectModel"
        @update:thinking-mode="executionControls.selectThinkingMode"
        @update:shallow-thinking-enabled="setShallowThinking"
      >
        <template #leading>
          <button class="composer-attachment-button" type="button" title="添加附件" aria-label="添加附件" @click="attachmentFileInput?.click()">+</button>
        </template>
      </CoreExecutionControls>
    </template>

    <template #right-panel>
      <RuntimePanel :events="events" :step-groups="stepGroups" />
    </template>
  </WorkspaceShell>
</template>

<script setup lang="ts">
import {
  computed,
  nextTick,
  onMounted,
  onUnmounted,
  reactive,
  ref,
  shallowRef,
  watch,
} from 'vue'
import type {
  CoreAttachment,
  CoreRuntimeEvent,
  CoreRuntimeStepGroup,
  CoreSessionListItem,
} from '../types'
import {
  buildCoreProjectGroups,
  type CoreProject,
  type CoreProjectCreatePayload,
} from '../projects/types'
import { createCoreProjectClient } from '../projects/client'
import { createCoreProjectWorkspaceActions } from '../projects/workspace'
import {
  appServerUrl,
  CoreAppServerClient,
  createCoreAppServerRuntimeController,
  createCoreAppServerRuntimeState,
  hydrateSnapshot,
  selectCoreQueuedInputs,
  selectLatestActiveTurnId,
  selectLatestTurnStatus,
  type CoreAppEvent,
  type CoreAppSnapshot,
  type CoreQueuedInput,
} from '../appServer'
import { buildCoreComposerHighlightSegments } from '../composer/inputItems'
import {
  useCoreApprovalController,
  useCoreAutoFollowScroll,
  useCoreExecutionControlsState,
  useCoreLiveComposerController,
  usePendingAttachments,
  useCoreQueuedInputController,
  useCoreUiPreferences,
  useCoreWorkbenchProjectionController,
} from '../composables'

import AttachmentTray from '../components/AttachmentTray.vue'
import ChatThread from '../components/ChatThread.vue'
import CommandPalette from '../components/CommandPalette.vue'
import CoreExecutionControls from '../components/CoreExecutionControls.vue'
import CoreQueuedInputTray from '../components/CoreQueuedInputTray.vue'
import CoreAgentsEditor from '../components/CoreAgentsEditor.vue'
import CoreProjectCreate from '../components/CoreProjectCreate.vue'
import CoreSettings, {
  type CoreSettingsModelPayload,
  type CoreSettingsProviderPayload,
} from '../components/CoreSettings.vue'
import RuntimePanel from '../components/RuntimePanel.vue'
import SessionSidebar from '../components/SessionSidebar.vue'
import WorkspaceShell from '../components/WorkspaceShell.vue'

type RawSession = {
  id: string
  title: string
  status?: string
  created_at?: string
  createdAt?: string
  updated_at?: string
  updatedAt?: string
  metadata?: Record<string, unknown>
}

type RawModel = {
  id: string
  provider_id?: string
  model_id?: string
  display_name?: string
  context_window?: number
  max_output_tokens?: number
  thinking_supported?: boolean
  thinking_budget?: number
  temperature?: number
}

type RawProvider = {
  id: string
  name: string
  api_type?: string
  base_url?: string
  has_api_key?: boolean
}

const apiBase = (import.meta.env.VITE_CORE_API_BASE || '/api/core').replace(/\/$/, '')
const projectClient = createCoreProjectClient(apiBase)
const projects = ref<CoreProject[]>([])
const sessions = ref<CoreSessionListItem[]>([])
const activeSessionId = ref<string | null>(null)
const runtime = reactive(createCoreAppServerRuntimeState<CoreAppSnapshot, CoreAppServerClient>())
const snapshot = computed(() => runtime.state)
const events = ref<CoreRuntimeEvent[]>([])
const composerText = ref('')
const composerCursor = ref(0)
const composerTextareaEl = ref<HTMLTextAreaElement | null>(null)
const attachmentFileInput = ref<HTMLInputElement | null>(null)
const composerErrorText = ref('')
const runtimeStatusText = ref('')
const loadError = ref<string | null>(null)
const showProjectCreate = ref(false)
const projectCreateLoading = ref(false)
const projectCreateError = ref('')
const selectedProjectId = ref<string | null>(null)
const projectNameDraft = ref('')
const projectActionLoading = ref(false)
const projectActionError = ref('')
const agentsProjectId = ref<string | null>(null)
const agentsContent = ref('')
const agentsLoading = ref(false)
const agentsError = ref('')
const settingsStorageKey = 'lamtools.core.ui'
const showSettings = ref(false)
const uiPreferences = useCoreUiPreferences(settingsStorageKey)
const { density, contentWidth, theme } = uiPreferences
const availableModels = ref<RawModel[]>([])
const availableProviders = ref<RawProvider[]>([])
const commandPolicies = ref<Record<'regular' | 'dangerous', 'auto_allow' | 'ask_user'>>({
  regular: 'auto_allow',
  dangerous: 'ask_user',
})
const { pendingAttachments, attachmentInputItems, addUploaded, markFailed, removeAttachment, clearAttachments } = usePendingAttachments()
const threadScrollEl = ref<HTMLElement | null>(null)
const threadScroll = useCoreAutoFollowScroll(threadScrollEl)
const COMPOSER_MAX_ROWS = 5
let threadResizeObserver: ResizeObserver | null = null
let configClient: CoreAppServerClient | null = null

const defaultModel = computed(() => availableModels.value[0] || null)
const executionControls = useCoreExecutionControlsState({
  models: availableModels,
  providers: availableProviders,
  defaultModel,
  storage: window.localStorage,
  initial: { thinkingMode: 'medium' },
})
const {
  modelOptions,
  selectedModelId,
  selectedThinkingMode,
  shallowThinkingEnabled,
  thinkingModeOptions,
} = executionControls

const latestStatus = computed(() => snapshot.value ? selectLatestTurnStatus(snapshot.value) : 'idle')

const stepGroups = computed<CoreRuntimeStepGroup[]>(() => {
  if (!snapshot.value || latestStatus.value === 'idle') return []
  const active = latestStatus.value === 'running' || latestStatus.value === 'waiting'
  return [{
    id: 'core-live',
    label: 'Core',
    status: active ? 'running' : latestStatus.value === 'failed' ? 'failed' : 'completed',
    steps: events.value.slice(-20).map((event) => ({
      id: event.id,
      title: event.type,
      status: event.type.includes('interrupted') ? 'failed' : active ? 'running' : 'completed',
      timestamp: event.timestamp,
      metadata: { event },
    })),
  }]
})

const projectGroups = computed(() => buildCoreProjectGroups(projects.value, sessions.value))
const selectedProject = computed(() => (
  projects.value.find((project) => project.id === selectedProjectId.value) || null
))
const projectWorkspace = createCoreProjectWorkspaceActions({
  client: projectClient,
  projects,
  sessions,
  activeSessionId,
  selectSession,
})
const busyProjectIds = projectWorkspace.busyProjectIds

const runtimeController = createCoreAppServerRuntimeController(runtime, {
  hydrateSnapshot,
  createClient: ({ apiBase: frontendBase, onSnapshot, onConnectionState }) => new CoreAppServerClient({
    url: appServerUrl(frontendBase, { path: '/api/core/app-server' }),
    clientInfo: { name: 'lamtools_core_frontend', title: 'LamTools Core Frontend', version: '0.1.0' },
    onSnapshot,
    onEvent: appendLiveEvent,
    onConnectionState: (state) => {
      onConnectionState(state)
      if (state === 'error') {
        loadError.value = 'Core App Server 连接失败'
      } else if (state === 'open' && loadError.value === 'Core App Server 连接失败') {
        loadError.value = null
      }
    },
  }),
})

const liveComposerController = useCoreLiveComposerController({
  activeThreadId: activeSessionId,
  connectedThreadId: computed(() => runtime.activeThreadId),
  connectionState: computed(() => runtime.connectionState),
  text: composerText,
  cursor: composerCursor,
  status: latestStatus,
  attachments: attachmentInputItems,
  connect: connectLive,
  startTurn: (threadId, input, workRoot, options) => runtimeController.startTurn(threadId, input, workRoot, options),
  interruptTurn: (threadId) => runtimeController.interruptTurn(threadId),
  queueInput: (threadId, input) => runtimeController.queueInput(threadId, input),
  listCommands: (workRoot) => runtimeController.listCommands(workRoot),
  getWorkRoot: currentWorkRoot,
  executeCommand: async (threadId, command, workRoot) => {
    await runtimeController.executeCommand(threadId, command, workRoot)
    return true
  },
  canExecuteCommand: () => latestStatus.value !== 'running' && latestStatus.value !== 'waiting',
  turnOptions: () => ({
    ...(selectedModelId.value ? { model_id: selectedModelId.value } : {}),
    ...executionControls.turnOptions(),
  }),
  clearComposer: clearComposerAfterPersisted,
  clearAttachments,
  focusComposer,
  setStatusText: (text) => {
    runtimeStatusText.value = text
  },
  onError: (text) => {
    composerErrorText.value = text
  },
  onTurnStarted: refreshSessions,
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
  commandPalette,
  paletteVisible: commandPaletteVisible,
} = liveComposerController
const composerHighlightSegments = computed(() => (
  buildCoreComposerHighlightSegments(composerText.value, commandCatalog.value)
))
const hasComposerCommandTokens = computed(() => (
  composerHighlightSegments.value.some((segment) => segment.command)
))

const approvalControllerRef = shallowRef<ReturnType<typeof useCoreApprovalController>>()
const projectionController = useCoreWorkbenchProjectionController({
  snapshot,
  activeThreadId: activeSessionId,
  status: latestStatus,
  submittingApprovalRequestIds: computed(() => (
    approvalControllerRef.value?.submittingRequestIds.value ?? new Set<string>()
  )),
  shallowThinkingPending: shallowThinkingEnabled,
  source: 'core_app_server',
  onStatusChange: ({ status }) => syncActiveSessionStatus(status),
})
const { messages, processExpandedIds, toggleProcess } = projectionController

const approvalController = useCoreApprovalController({
  messages,
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
  deferText: (text) => {
    composerText.value = text
  },
})
approvalControllerRef.value = approvalController
const workbenchErrorText = computed(() => (
  loadError.value || composerErrorText.value || approvalController.lastError.value
))

const queuedInputs = computed<CoreQueuedInput[]>(() => {
  if (!snapshot.value || snapshot.value.thread_id !== activeSessionId.value) return []
  return selectCoreQueuedInputs(snapshot.value)
})
const activeTurnId = computed(() => snapshot.value ? selectLatestActiveTurnId(snapshot.value) : '')
const queueController = useCoreQueuedInputController({
  activeTurnId,
  ensureConnected: async (threadId) => {
    if (!await liveComposerController.ensureConnected(threadId)) {
      throw new Error(liveComposerController.lastError.value)
    }
  },
  updateQueueInput: (threadId, itemId, text) => runtimeController.updateQueueInput(threadId, itemId, text),
  deleteQueueInput: (threadId, itemId) => runtimeController.deleteQueueInput(threadId, itemId),
  guideQueueInput: (threadId, turnId, itemId, text) => (
    runtimeController.guideQueueInput(threadId, turnId, itemId, text)
  ),
  onError: (error) => {
    composerErrorText.value = error instanceof Error ? error.message : String(error)
  },
})
const editingQueuedInputId = queueController.editingId
const queuedInputDraft = queueController.draft
const canGuideQueuedInput = queueController.canGuide

async function loadInitialData() {
  try {
    loadError.value = null
    await Promise.all([loadModelOptions(), loadCommandPolicies(), refreshProjects(), refreshSessions()])
    if (sessions.value[0]) await selectSession(sessions.value[0].id)
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : String(error)
  }
}

async function refreshProjects() {
  projects.value = await projectClient.list()
}

async function refreshSessions() {
  const loaded = (await requestJson<RawSession[]>('/sessions')).map(toSession)
  const currentId = activeSessionId.value
  sessions.value = loaded.map((session) => (
    session.id === currentId ? { ...session, status: latestStatus.value } : session
  ))
}

function openProjectCreate() {
  projectCreateError.value = ''
  showProjectCreate.value = true
}

function closeProjectCreate() {
  if (projectCreateLoading.value) return
  projectCreateError.value = ''
  showProjectCreate.value = false
}

async function createProject(payload: CoreProjectCreatePayload) {
  projectCreateLoading.value = true
  projectCreateError.value = ''
  try {
    const created = await projectWorkspace.createProject(payload)
    selectedProjectId.value = created.project.id
    showProjectCreate.value = false
  } catch (error) {
    projectCreateError.value = messageFromError(error)
  } finally {
    projectCreateLoading.value = false
  }
}

async function pickProjectDirectory() {
  projectCreateError.value = ''
  try {
    const result = await requestConfigOperation('project.directory.pick')
    return typeof result.path === 'string' ? result.path : ''
  } catch (error) {
    projectCreateError.value = messageFromError(error)
    return ''
  }
}

async function createProjectSession(projectId: string) {
  try {
    await projectWorkspace.createProjectSession(projectId)
  } catch (error) {
    composerErrorText.value = messageFromError(error)
  }
}

function openProjectActions(projectId: string) {
  const project = projects.value.find((item) => item.id === projectId)
  if (!project) return
  selectedProjectId.value = project.id
  projectNameDraft.value = project.name
  projectActionError.value = ''
}

async function renameProject() {
  const project = selectedProject.value
  const name = projectNameDraft.value.trim()
  if (!project || !name) return
  projectActionLoading.value = true
  projectActionError.value = ''
  try {
    const updated = await projectWorkspace.renameProject(project.id, name)
    projectNameDraft.value = updated.name
  } catch (error) {
    projectActionError.value = messageFromError(error)
  } finally {
    projectActionLoading.value = false
  }
}

async function deleteProject(projectId: string) {
  const project = projects.value.find((item) => item.id === projectId)
  if (!project || !window.confirm(`确定删除项目「${project.name}」及其会话记录？此操作不可撤销。`)) return
  projectActionLoading.value = true
  projectActionError.value = ''
  try {
    const deleted = await projectWorkspace.deleteProject(project.id)
    if (!deleted) return
    if (selectedProjectId.value === project.id) selectedProjectId.value = null
    if (agentsProjectId.value === project.id) closeAgentsEditor()
    if (deleted.wasActive) {
      runtimeController.disconnect()
      liveComposerController.resetForThreadChange()
      activeSessionId.value = null
      events.value = []
      if (sessions.value[0]) await selectSession(sessions.value[0].id)
    }
  } catch (error) {
    projectActionError.value = messageFromError(error)
  } finally {
    projectActionLoading.value = false
  }
}

async function openAgentsEditor() {
  const project = selectedProject.value
  if (!project) return
  projectActionLoading.value = true
  agentsLoading.value = true
  agentsError.value = ''
  try {
    const agents = await projectWorkspace.readAgents(project.id)
    agentsProjectId.value = project.id
    agentsContent.value = agents.content
  } catch (error) {
    projectActionError.value = messageFromError(error)
  } finally {
    agentsLoading.value = false
    projectActionLoading.value = false
  }
}

function closeAgentsEditor() {
  if (agentsLoading.value) return
  agentsProjectId.value = null
  agentsContent.value = ''
  agentsError.value = ''
}

async function saveAgents(content: string) {
  const projectId = agentsProjectId.value
  if (!projectId) return
  agentsLoading.value = true
  agentsError.value = ''
  try {
    const agents = await projectWorkspace.writeAgents(projectId, content)
    agentsContent.value = agents.content
    runtimeStatusText.value = 'AGENTS.md 已保存'
    agentsProjectId.value = null
    agentsContent.value = ''
  } catch (error) {
    agentsError.value = messageFromError(error)
  } finally {
    agentsLoading.value = false
  }
}

async function renameSession(sessionId: string, title: string) {
  const updated = toSession(await requestJson<RawSession>(`/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'PATCH',
    body: { title },
  }))
  sessions.value = sessions.value.map((session) => session.id === sessionId ? updated : session)
}

async function deleteSession(sessionId: string) {
  try {
    await requestJson(`/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE' })
  } catch (error) {
    composerErrorText.value = error instanceof Error ? error.message : String(error)
    return
  }
  const deletedActiveSession = activeSessionId.value === sessionId
  if (deletedActiveSession) {
    runtimeController.disconnect()
    liveComposerController.resetForThreadChange()
    activeSessionId.value = null
    events.value = []
  }
  await refreshSessions()
  if (deletedActiveSession && sessions.value[0]) await selectSession(sessions.value[0].id)
}

async function selectSession(id: string) {
  activeSessionId.value = id
  runtimeController.disconnect()
  liveComposerController.resetForThreadChange()
  events.value = []
  composerErrorText.value = ''
  runtimeStatusText.value = ''
  await connectLive(id)
  await liveComposerController.loadCommandCatalog(id)
  await threadScroll.scrollToBottom(true)
}

async function connectLive(threadId: string) {
  await runtimeController.connect(window.location.origin, threadId)
}

async function submitComposer() {
  composerErrorText.value = ''
  await liveComposerController.submit({ clearComposer: true })
}

async function uploadFiles(files: FileList | File[]) {
  const sessionId = activeSessionId.value
  if (!sessionId) {
    composerErrorText.value = '请先选择会话'
    return
  }
  for (const file of Array.from(files)) {
    const failedId = `failed:${file.name}:${Date.now()}`
    try {
      const body = new FormData()
      body.append('file', file)
      const response = await fetch(`${apiBase}/sessions/${encodeURIComponent(sessionId)}/attachments`, { method: 'POST', body })
      if (!response.ok) throw new Error(await response.text() || '上传失败')
      addUploaded(await response.json() as CoreAttachment)
    } catch (error) {
      markFailed(failedId, file.name, messageFromError(error))
      composerErrorText.value = `附件上传失败：${file.name}`
    }
  }
}

function handleAttachmentInputChange(event: Event) {
  const input = event.target as HTMLInputElement
  if (input.files?.length) void uploadFiles(input.files)
  input.value = ''
}

function handleComposerDrop(event: DragEvent) {
  if (event.dataTransfer?.files.length) void uploadFiles(event.dataTransfer.files)
}

function retryPendingAttachment(id: string) {
  removeAttachment(id)
  attachmentFileInput.value?.click()
}

async function previewPendingAttachment(id: string) {
  if (id.startsWith('failed:')) return
  const response = await fetch(`${apiBase}/attachments/${encodeURIComponent(id)}/preview`)
  runtimeStatusText.value = response.ok ? '附件预览已读取' : '附件预览失败'
}

async function openPendingAttachment(id: string) {
  if (id.startsWith('failed:')) return
  const response = await fetch(`${apiBase}/attachments/${encodeURIComponent(id)}/open`, { method: 'POST' })
  if (!response.ok) runtimeStatusText.value = '打开附件失败'
}

async function handleComposerKeydown(event: KeyboardEvent) {
  updateComposerCursor()
  await liveComposerController.handleKeydown(event)
}

async function handleComposerKeyup(event: KeyboardEvent) {
  updateComposerCursor()
  await liveComposerController.handleKeyup(event)
}

function handleComposerInput() {
  composerErrorText.value = ''
  resizeComposerTextarea()
  updateComposerCursor()
}

function updateComposerCursor() {
  composerCursor.value = composerTextareaEl.value?.selectionStart ?? composerText.value.length
}

function focusComposer(cursor: number) {
  void nextTick(() => {
    const textarea = composerTextareaEl.value
    if (!textarea) return
    textarea.focus()
    textarea.setSelectionRange(cursor, cursor)
  })
}

function clearComposerAfterPersisted(expectedText: string) {
  if (composerText.value.trim() !== expectedText) return
  composerText.value = ''
  void nextTick(resizeComposerTextarea)
}

function resizeComposerTextarea() {
  const element = composerTextareaEl.value
  if (!element) return
  element.style.height = 'auto'
  const style = window.getComputedStyle(element)
  const lineHeight = Number.parseFloat(style.lineHeight) || 22
  const paddingTop = Number.parseFloat(style.paddingTop) || 0
  const paddingBottom = Number.parseFloat(style.paddingBottom) || 0
  const maxHeight = lineHeight * COMPOSER_MAX_ROWS + paddingTop + paddingBottom
  element.style.height = `${Math.min(element.scrollHeight, maxHeight)}px`
  element.style.overflowY = element.scrollHeight > maxHeight ? 'auto' : 'hidden'
}

function setShallowThinking(enabled: boolean) {
  shallowThinkingEnabled.value = enabled
}

async function createProvider(payload: CoreSettingsProviderPayload) {
  await mutateConfig('config.provider.create', payload, '供应商已添加')
}

async function updateProvider(payload: CoreSettingsProviderPayload) {
  await mutateConfig('config.provider.update', payload, '供应商已更新')
}

async function deleteProvider(providerId: string) {
  if (!window.confirm('删除供应商会同时移除其模型配置，是否继续？')) return
  await mutateConfig('config.provider.delete', { provider_id: providerId }, '供应商已删除')
}

async function createModel(payload: CoreSettingsModelPayload) {
  await mutateConfig('config.model.create', payload, '模型已添加')
}

async function updateModel(payload: CoreSettingsModelPayload) {
  await mutateConfig('config.model.update', payload, '模型已更新')
}

async function deleteModel(modelRecordId: string) {
  if (!window.confirm('删除此模型配置，是否继续？')) return
  await mutateConfig('config.model.delete', { model_record_id: modelRecordId }, '模型已删除')
}

async function importEnvironmentConfig() {
  await mutateConfig('config.import_env', {}, '已从当前环境导入')
}

async function loadCommandPolicies() {
  try {
    const result = await requestConfigOperation('settings.get', { namespace: 'core.runtimeControls' })
    const value = result.value && typeof result.value === 'object' ? result.value as Record<string, unknown> : {}
    const policies = value.command_policies && typeof value.command_policies === 'object'
      ? value.command_policies as Record<string, unknown>
      : {}
    commandPolicies.value = {
      regular: policies.regular === 'ask_user' ? 'ask_user' : 'auto_allow',
      dangerous: policies.dangerous === 'auto_allow' ? 'auto_allow' : 'ask_user',
    }
  } catch {
    commandPolicies.value = { regular: 'auto_allow', dangerous: 'ask_user' }
  }
}

async function updateCommandPolicy(group: 'regular' | 'dangerous', policy: 'auto_allow' | 'ask_user') {
  const next = { ...commandPolicies.value, [group]: policy }
  await requestConfigOperation('settings.update', {
    namespace: 'core.runtimeControls',
    value: { command_policies: next },
  })
  commandPolicies.value = next
}

async function mutateConfig(method: string, params: object, successText: string) {
  try {
    loadError.value = null
    await requestConfigOperation(method, params as Record<string, unknown>)
    await loadModelOptions()
    runtimeStatusText.value = successText
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : String(error)
  }
}

async function requestConfigOperation(method: string, params: Record<string, unknown> = {}) {
  if (!configClient) {
    const client = new CoreAppServerClient({
      url: appServerUrl(window.location.origin, { path: '/api/core/app-server' }),
      clientInfo: { name: 'lamtools_core_settings', title: 'LamTools Core Settings', version: '0.1.0' },
      onConnectionState: (state) => {
        if (state === 'closed' || state === 'error') configClient = null
      },
    })
    await client.connect()
    configClient = client
  }
  return await configClient.request(method, params)
}

function currentWorkRoot(): string {
  const session = sessions.value.find((item) => item.id === activeSessionId.value)
  const workRoot = session?.metadata?.work_root
  return typeof workRoot === 'string' ? workRoot : ''
}

function syncActiveSessionStatus(status: string) {
  const sessionId = activeSessionId.value
  if (!sessionId) return
  const index = sessions.value.findIndex((item) => item.id === sessionId)
  if (index < 0) return
  const next = [...sessions.value]
  next[index] = { ...next[index], status, updatedAt: new Date().toISOString() }
  sessions.value = next
}

async function loadModelOptions() {
  try {
    const providersResponse = await requestConfigOperation('config.providers.list')
    const modelsResponse = await requestConfigOperation('config.models.list')
    availableProviders.value = Array.isArray(providersResponse.providers)
      ? providersResponse.providers as RawProvider[]
      : []
    availableModels.value = Array.isArray(modelsResponse.models)
      ? modelsResponse.models as RawModel[]
      : []
  } catch {
    availableModels.value = []
    availableProviders.value = []
  }
}

function appendLiveEvent(event: CoreAppEvent) {
  const runtimeEvent: CoreRuntimeEvent = {
    id: event.event_id,
    type: event.method,
    timestamp: event.created_at,
    data: event.payload,
  }
  if (events.value.some((item) => item.id === runtimeEvent.id)) return
  events.value = [...events.value, runtimeEvent].sort((a, b) => a.timestamp.localeCompare(b.timestamp))
}

function syncThreadResizeObserver() {
  if (typeof ResizeObserver === 'undefined') return
  threadResizeObserver?.disconnect()
  threadResizeObserver = new ResizeObserver(() => {
    void threadScroll.scrollToBottom()
  })
  const element = threadScrollEl.value
  if (!element) return
  threadResizeObserver.observe(element)
  for (const child of Array.from(element.children)) {
    if (child instanceof HTMLElement) threadResizeObserver.observe(child)
  }
}

async function requestJson<T = unknown>(
  path: string,
  options: { method?: string; body?: unknown } = {},
): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    method: options.method || 'GET',
    headers: options.body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  })
  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `${response.status} ${response.statusText}`)
  }
  return await response.json() as T
}

function toSession(raw: RawSession): CoreSessionListItem {
  return {
    id: raw.id,
    title: raw.title || raw.id,
    createdAt: raw.created_at || raw.createdAt || '',
    updatedAt: raw.updated_at || raw.updatedAt,
    status: raw.status,
    metadata: raw.metadata,
  }
}

function messageFromError(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

watch(composerText, () => {
  void nextTick(resizeComposerTextarea)
})

watch(messages, async () => {
  await nextTick()
  syncThreadResizeObserver()
  await threadScroll.scrollToBottom()
}, { deep: true })

onMounted(() => {
  void uiPreferences.load()
  void loadInitialData()
})

onUnmounted(() => {
  threadResizeObserver?.disconnect()
  runtimeController.disconnect()
  configClient?.close()
  configClient = null
})
</script>

<style>
@import '../styles/variables.css';
@import '../styles/base.css';
@import '../styles/layout.css';
@import '../styles/theme-editor.css';

.core-project-header-action {
  position: relative;
}

.core-project-management {
  margin-top: 10px;
  padding: 10px;
  border-top: 1px solid color-mix(in srgb, var(--theme-backdrop-text) 14%, transparent);
}

.core-project-management form,
.core-project-management label {
  display: grid;
  gap: 6px;
}

.core-project-management label {
  color: color-mix(in srgb, var(--theme-backdrop-text) 72%, transparent);
  font-size: 12px;
}

.core-project-management-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 8px;
}

.core-project-management-error {
  margin: 8px 0 0;
  color: var(--red);
  font-size: 12px;
  line-height: 1.35;
}

</style>
