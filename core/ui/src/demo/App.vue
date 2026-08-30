<template>
  <TitleBar
    :left-pinned="leftPinned"
    :right-pinned="rightPinned"
    :mode-label="activeAppMode.title"
    :mode-title="nextAppModeTitle"
    :can-toggle-mode="appModes.length > 1"
    @toggle-left-pinned="toggleLeftPinned"
    @toggle-right-pinned="toggleRightPinned"
    @cycle-mode="cycleAppMode"
  />
  <div v-if="backendCrashed" class="core-update-banner" role="alert" data-backend-crashed-banner>
    <span class="core-update-banner-text">后端进程已停止响应（可能已崩溃）。请重启应用以恢复。</span>
  </div>
  <div v-if="updateBannerVisible" class="core-update-banner" data-update-banner>
    <span class="core-update-banner-text">发现新版本 v{{ updateLatestVersion }}，是否立即下载？</span>
    <button class="core-update-banner-action" type="button" data-update-banner-download @click="downloadUpdate()">下载更新</button>
    <button class="core-update-banner-close" type="button" aria-label="关闭提示" @click="dismissUpdateBanner">✕</button>
  </div>
  <CoreSettings
    v-if="showSettings"
    :models="availableModels"
    :providers="availableProviders"
    :density="density"
    :theme="theme"
    :content-width="contentWidth"
    :permission-mode="permissionMode"
    :allow-access-outside-workdir="allowAccessOutsideWorkdir"
    :request-rpc="requestConfigOperation"
    :update-state="updateState"
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
    @update-permission-mode="updatePermissionMode"
    @update-allow-outside-workdir="updateAllowAccessOutsideWorkdir"
    @create-provider="createProvider"
    @update-provider="updateProvider"
    @delete-provider="deleteProvider"
	@create-model="createModel"
	    @update-model="updateModel"
	    @delete-model="deleteModel"
	    @set-default-model="setDefaultModel"
    @reopen-onboarding="reopenOnboarding"
  />
  <PluginsShell
    v-if="showPlugins"
    :request-rpc="requestConfigOperation"
    :theme="theme"
    @close="closePlugins"
  />
  <CoreArrangeManager
    v-if="showArrange"
    :work-root="currentWorkRoot()"
    @back="showArrange = false"
  />
  <SearchShell
    v-if="showSearch"
    :request-rpc="requestConfigOperation"
    :sessions="sessions"
    :on-jump="jumpToSearchedMessage"
    :theme="theme"
    @close="showSearch = false"
  />
  <OnboardingWizard
    v-if="showOnboarding"
    :providers="availableProviders"
    :models="availableModels"
    :default-model-id="defaultModelId"
    :theme="theme"
    :loading="wizardLoading"
    :error="wizardError"
    @create-provider="onboardingCreateProvider"
    @skip="skipOnboarding"
    @finish="finishOnboarding"
  />
  <WorkspaceShell
    ref="shellRef"
    product-name="LamTools Core"
    sidebar-title="Core"
    :storage-key="settingsStorageKey"
    :density="density"
    :theme="theme"
    :content-width="contentWidth"
    :show-sidebar-header="false"
    :show-sidebar-header-action="false"
    :composer-disabled="composerInputDisabled"
    :composer-send-disabled="composerSendDisabled"
    :composer-placeholder="composerPlaceholder"
    :composer-action-mode="composerActionMode"
    :composer-active="latestStatus === 'running'"
    v-model:stage-open="stageOpen"
    @new-session="handleShellNewSession"
    @update:left-pinned="syncLeftPinned"
    @settings="openSettings"
    @plugins="openPlugins"
    @search="showSearch = true"
    @composer-submit="submitComposer"
    @composer-drop="handleComposerDrop"
  >
    <template #primary>
      <div class="core-project-primary-actions">
        <button
          v-if="sidebarPrimaryActionLabel"
          class="sidebar-create-project"
          type="button"
          data-sidebar-primary-action
          :title="sidebarPrimaryActionLabel"
          :aria-label="sidebarPrimaryActionLabel"
          @click="invokeSidebarPrimaryAction"
        >
          <span aria-hidden="true">＋</span><span>{{ sidebarPrimaryActionLabel }}</span>
        </button>
        <CoreProjectCreate
          v-if="showProjectCreate && !activePluginMode"
          :loading="projectCreateLoading"
          :error="projectCreateError"
          :api-base="apiBase"
          @submit="createProject"
          @cancel="closeProjectCreate"
        />
      </div>
    </template>

    <template #sidebar-body>
      <SessionSidebar
        :project-groups="sidebarGroups"
        :has-projects="sidebarHasProjects"
        :project-session-limit="8"
        pin-storage-key="lamtools-core.sidebar.pinned-projects"
        :active-session-id="sidebarActiveSessionId"
        :busy-project-ids="sidebarBusyProjectIds"
        :allow-project-new-session="sidebarAllowProjectNewSession"
        :allow-project-delete="sidebarAllowProjectDelete"
        :allow-project-click="sidebarAllowProjectClick"
        :allow-project-context-menu="sidebarAllowProjectContextMenu"
        :allow-session-delete="sidebarAllowSessionDelete"
        :allow-session-context-menu="sidebarAllowSessionContextMenu"
        :new-session-label="sidebarNewSessionLabel"
        @select-session="handleSidebarSession"
        @select-project="handleSidebarProject"
        @new-session="handleSidebarNewSession"
        @delete-project="deleteProject"
        @project-context-menu="openProjectActions"
        @delete-session="deleteSession"
        @rename-session="renameSessionFromSidebar"
        @export-session="exportSession"
      >
        <template #empty>
          <div class="sidebar-empty-projects" data-sidebar-empty-projects>
            <p>还没有项目</p>
            <button
              v-if="!activePluginMode"
              class="sidebar-create-project"
              type="button"
              data-sidebar-empty-create-project
              title="新建项目"
              aria-label="新建项目"
              @click="openProjectCreate"
            >
              <span aria-hidden="true">＋</span><span>新建项目</span>
            </button>
          </div>
        </template>
      </SessionSidebar>
    </template>

    <template #sidebar-footer>
      <button class="sidebar-action" type="button" @click="showArrange = true">
        <span aria-hidden="true"><CalendarClock :size="14" :stroke-width="1.8" /></span><span>长期安排</span>
      </button>
    </template>

    <template #main-header>
      <div v-if="activePluginMode" class="workspace-plugin-header" data-plugin-header></div>
      <div v-else-if="activeSessionId" class="thread-header">
        <CoreSessionTitleEditor
          :title="activeSessionTitle"
          :session-id="activeSessionId"
          :rename="renameActiveSession"
        />
        <button
          type="button"
          class="stage-toggle-btn"
          :class="{ active: stageOpen }"
          :title="stageOpen ? '关闭视窗' : '打开视窗'"
          @click="toggleStage"
        >
          <ChevronDown v-if="stageOpen" :size="14" :stroke-width="1.8" aria-hidden="true" />
          <ChevronUp v-else :size="14" :stroke-width="1.8" aria-hidden="true" />
        </button>
      </div>
    </template>

    <template #main-content>
      <PluginModeHost
        v-if="activePluginMode"
        :plugin-id="activePluginMode.pluginId"
        :mode-id="activePluginMode.id"
      />
      <section
        v-else
        ref="threadScrollEl"
        class="thread"
        @scroll.passive="threadScroll.handleScroll"
        @wheel.passive="threadScroll.handleWheel"
      >
        <button
          v-if="hasMoreHistory"
          type="button"
          class="thread-load-earlier"
          @click="loadEarlierMessages"
        >
          加载更早消息（共 {{ totalMessages }} 条）
        </button>
        <ChatThread
          :messages="messages"
          :process-expanded-ids="processExpandedIds"
          :message-actions="true"
          :api-base="apiBase"
          :project-id="activeProjectId ?? selectedProjectId"
          :work-root="activeProject?.workRoot"
          :active-turn-id="activeTurnId"
          :turn-active="activeTurnRunning"
          :checkpoint-turn-ids="checkpointTurnIds"
          @toggle-process="toggleProcess"
          @decision-select="approvalController.handleDecision"
          @fork-message="handleForkMessage"
          @rollback-message="handleRollbackMessage"
          @edit-message="handleEditMessage"
        />
        <div v-if="pendingPlaceholder" class="user-row">
          <div class="user-stack">
            <div class="user-bubble user-bubble--placeholder">{{ pendingPlaceholder.content }}</div>
          </div>
        </div>
        <Transition name="thread-jump-latest">
          <button
            v-if="!threadScroll.atBottom.value"
            type="button"
            class="thread-jump-latest"
            aria-label="回到最新消息"
            title="回到最新消息"
            @click="threadScroll.scrollToBottom(true)"
          >
            <ArrowDown :size="16" :stroke-width="1.8" aria-hidden="true" />
          </button>
        </Transition>
      </section>
    </template>

    <template #modals>
      <div v-if="activePluginMode" class="workspace-plugin-modal" data-plugin-modal></div>
      <CoreProjectSettings
        v-if="showProjectSettings && selectedProject && !activePluginMode"
        :project="{ id: selectedProject.id, name: selectedProject.name, workRoot: selectedProject.workRoot }"
        :theme="theme"
        :request-rpc="requestConfigOperation"
        :models="availableModels"
        :project-name-draft="projectNameDraft"
        :agents-content="agentsContent"
        :agents-loading="agentsLoading"
        :agents-saving="agentsSaving"
        :agents-error="agentsError"
        :project-action-loading="projectActionLoading"
        :project-action-error="projectActionError"
        @close="closeProjectSettings"
        @rename-project="renameProject"
        @save-agents="saveAgents"
        @refresh-agents="refreshAgentsContent"
      />
    </template>

    <template #runtime-overlay>
      <RuntimeChecklistCard v-if="!activePluginMode" :step-groups="stepGroups" />
    </template>

    <template #composer-preamble>
      <div v-if="activeGoal" class="core-goal-area" :data-status="activeGoal.status">
        <CoreGoalStrip :goal="activeGoal" @cancel="handleCancelGoal" />
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
      </div>
      <CoreQueuedInputTray
        v-else
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
    </template>

    <template #composer-textarea>
      <input ref="attachmentFileInput" class="sr-only" type="file" multiple @change="handleAttachmentInputChange" />
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
          :disabled="composerInputDisabled"
          :placeholder="composerPlaceholder"
          rows="1"
          @input="handleComposerInput"
          @click="updateComposerCursor"
          @keyup="handleComposerKeyup"
          @keydown="handleComposerKeydown"
          @paste="handleComposerPaste"
        />
      </div>
    </template>

    <template #composer-tools>
      <CoreExecutionControls
        :model-value="selectedModelId"
        :thinking-mode="selectedThinkingMode"
        :shallow-thinking-enabled="shallowThinkingEnabled"
        :active-mode="activeMode"
        :mode-options="modeOptions"
        :runtime-mode-label="runtimeModeLabel"
        :permission-preset="permissionPreset"
        :model-options="modelOptions"
        :thinking-mode-options="thinkingModeOptions"
        shallow-label="Shallow"
        @update:model-value="executionControls.selectModel"
        @update:thinking-mode="executionControls.selectThinkingMode"
        @update:shallow-thinking-enabled="setShallowThinking"
        @update:active-mode="executionControls.selectMode"
        @update:permission-preset="executionControls.selectPermissionPreset"
      >
        <template #leading>
          <button class="composer-attachment-button" type="button" title="添加附件" aria-label="添加附件" @click="attachmentFileInput?.click()">+</button>
        </template>
      </CoreExecutionControls>
    </template>

    <template #stage="{ open: stageIsOpen, toggle: stageToggle }">
      <StagePane
        v-if="stageIsOpen"
        ref="stagePaneRef"
        :tabs="stageTabs"
        :active-id="stageActiveId"
        @activate="stageActivate"
        @close="stageClose"
        @update-content="stageUpdateContent"
        @save="stageSave"
        @toggle-preview="stageTogglePreview"
      />
    </template>

    <template #right-panel>
      <template v-if="activePluginMode">
        <div class="workspace-plugin-right-panel" data-plugin-right-panel></div>
      </template>
      <FileTreePanel
        v-else-if="stageOpen && activeProjectId"
        :project-id="activeProjectId"
        :client="projectClient"
        @open-file="openFileInStage"
      />
      <template v-else>
        <RuntimeChecklistCard class="runtime-checklist-mobile" :step-groups="stepGroups" />
        <CoreResourceStats
          :messages="messages"
          :context-window="executionControls.activeModel.value?.context_window"
        />
        <ArtifactPanel
          v-if="activeProjectId"
          :project-id="activeProjectId"
          :api-base="apiBase"
          :request-rpc="requestConfigOperation"
        />
      </template>
    </template>
  </WorkspaceShell>

  <!-- 全窗口拖拽上传遮罩：拖入文件时亮起，松开即上传到当前会话 -->
  <div
    v-if="dragActive"
    class="attachment-drop-overlay"
    @dragover.prevent
    @drop.prevent="handleAttachmentDrop"
  >
    <div class="attachment-drop-card">
      <Upload class="attachment-drop-icon" :size="28" aria-hidden="true" />
      <p class="attachment-drop-title">松开鼠标上传附件</p>
      <p class="attachment-drop-hint">添加到当前会话</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import {
  computed,
  defineAsyncComponent,
  nextTick,
  onMounted,
  onUnmounted,
  reactive,
  ref,
  shallowRef,
  watch,
} from 'vue'
import { ArrowDown, CalendarClock, ChevronDown, ChevronUp, Upload } from 'lucide-vue-next'
import type {
  CoreAttachment,
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
  isCoreActiveTurnStatus,
  selectCoreQueuedInputs,
  selectLatestActiveTurnId,
  selectLatestTurnStatus,
  type CoreAppEvent,
  type CoreAppSnapshot,
  type CoreQueuedInput,
} from '../appServer'
import { buildCoreComposerHighlightSegments } from '../composer/inputItems'
import { buildCurrentTurnChecklistGroups } from '../runtime/checklist'
import { listArrangeJobs, updateArrangeJob } from '../durable/api'
import {
  readUpdateAutoCheck,
  useCoreApprovalController,
  useCoreAutoFollowScroll,
  useCoreExecutionControlsState,
  useCoreGoals,
  useCoreLiveComposerController,
  usePendingAttachments,
  useCoreQueuedInputController,
  useCoreUiPreferences,
  useCoreUpdateState,
  useCoreWorkbenchProjectionController,
  showToast,
} from '../composables'

import AttachmentTray from '../components/AttachmentTray.vue'
import ChatThread from '../components/ChatThread.vue'
import CommandPalette from '../components/CommandPalette.vue'
import CoreExecutionControls from '../components/CoreExecutionControls.vue'
import CoreResourceStats from '../components/CoreResourceStats.vue'
import CoreQueuedInputTray from '../components/CoreQueuedInputTray.vue'
import CoreArrangeManager from '../components/CoreArrangeManager.vue'
import CoreGoalStrip from '../components/CoreGoalStrip.vue'
import FileTreePanel from '../components/FileTreePanel.vue'
import type { StageResource, StageKind } from '../types'
import CoreProjectCreate from '../components/CoreProjectCreate.vue'
import CoreSessionTitleEditor from '../components/CoreSessionTitleEditor.vue'
import ArtifactPanel from '../components/ArtifactPanel.vue'
import OnboardingWizard from '../components/OnboardingWizard.vue'
import PluginsShell from '../components/PluginsShell.vue'
import SearchShell from '../components/SearchShell.vue'
import type {
  CoreSettingsModelPayload,
  CoreSettingsProviderPayload,
} from '../components/CoreSettings.vue'
import CoreProjectSettings from '../components/CoreProjectSettings.vue'
import RuntimeChecklistCard from '../components/RuntimeChecklistCard.vue'
import SessionSidebar, { type SessionExportFormat } from '../components/SessionSidebar.vue'
import WorkspaceShell from '../components/WorkspaceShell.vue'
import TitleBar from '../components/TitleBar.vue'
import PluginModeHost from '../components/PluginModeHost.vue'
import { refreshPluginUIModes } from '../plugins/api'
import { listModes } from '../plugins/registry'
import {
  provideCorePluginModeContext,
  readPluginSurface,
  createPluginModeRuntime,
} from '../plugins/context'
import type { PluginModeSurface } from '../plugins/context'
import type { PluginMode } from '../plugins/types'
import type { CorePermissionPreset } from '../composer/execution'

const CoreSettings = defineAsyncComponent(() => import('../components/CoreSettings.vue'))
const StagePane = defineAsyncComponent(() => import('../components/StagePane.vue'))

type StagePaneInstance = InstanceType<(typeof import('../components/StagePane.vue'))['default']>

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

type SessionExportExtension = 'md' | 'txt' | 'jsonl' | 'json' | 'zip'

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

const _rawBase = ((window as any).__LAMTOOLS_API_BASE__ as string || (import.meta as any).env?.VITE_CORE_API_BASE || '/api/core').replace(/\/$/, '')
const apiBase = /^https?:\/\//.test(_rawBase) ? _rawBase : (window.location.origin + (/^\//.test(_rawBase) ? '' : '/') + _rawBase).replace(/\/$/, '')
const projectClient = createCoreProjectClient(apiBase)
const projects = ref<CoreProject[]>([])
const sessions = ref<CoreSessionListItem[]>([])
const activeSessionId = ref<string | null>(null)
const runtime = reactive(createCoreAppServerRuntimeState<CoreAppSnapshot, CoreAppServerClient>())
const snapshot = computed(() => runtime.state)
const composerText = ref('')
const composerCursor = ref(0)
const composerTextareaEl = ref<HTMLTextAreaElement | null>(null)
const attachmentFileInput = ref<HTMLInputElement | null>(null)
const composerErrorText = ref('')

// Status/error notifications go through the global toast service (single
// queue, auto-expiry per kind, dismissible) instead of the shell's two fixed
// slots — the old path left several error sources pinned forever.
function setRuntimeStatus(text: string, duration = 3000) {
  showToast('notice', text, duration)
}

const loadError = ref<string | null>(null)

function setLoadError(text: string) {
  loadError.value = text
}
const showProjectCreate = ref(false)
const projectCreateLoading = ref(false)
const projectCreateError = ref('')
const selectedProjectId = ref<string | null>(null)
const projectNameDraft = ref('')
const projectActionLoading = ref(false)
const projectActionError = ref('')
const showProjectSettings = ref(false)
const agentsProjectId = ref<string | null>(null)
const agentsContent = ref('')
const agentsLoading = ref(false)
const agentsSaving = ref(false)
const agentsError = ref('')
const shellRef = ref<InstanceType<typeof WorkspaceShell> | null>(null)
const leftPinned = ref(true)
const rightPinned = ref(false)
const sendingDisabled = ref(false)

function toggleLeftPinned() {
  leftPinned.value = !leftPinned.value
  shellRef.value?.toggleLeftPinned()
}
function syncLeftPinned(value: boolean) {
  leftPinned.value = value
}
function toggleRightPinned() {
  rightPinned.value = !rightPinned.value
  shellRef.value?.toggleRightPinned()
}
const settingsStorageKey = 'lamtools.core.ui'
const showSettings = ref(false)
const showPlugins = ref(false)
const showSearch = ref(false)

// Ctrl+K 全局搜索：与侧边栏「搜索」按钮一样切 showSearch（同一 SearchShell 入口）。
// 打开时避免触发浏览器/输入框插件快捷键（旧 SessionSearchDialog 已并入 SearchShell）。
function handleGlobalSearchKeydown(event: KeyboardEvent): void {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    showSearch.value = !showSearch.value
  }
}
const showArrange = ref(false)
const showOnboarding = ref(false)
const wizardLoading = ref(false)
const wizardError = ref('')
// Rust 监视线程发现后端进程退出时置位，顶部横幅提示（audit 20 S3）。
const backendCrashed = ref(false)
const lastEvent = ref<CoreAppEvent | null>(null)
const pluginModeRuntime = createPluginModeRuntime()
const pluginModes = ref<PluginMode[]>([])
const coreAppMode = {
  pluginId: 'core',
  id: 'agent',
  title: 'Agent',
  entry: '',
  icon: 'agent',
  enabled: true,
  load: async () => ({}) as never,
} as PluginMode
const appModes = computed<PluginMode[]>(() => [coreAppMode, ...pluginModes.value])
const activeAppModeKey = ref('core:agent')
const activeAppMode = computed(() => (
  appModes.value.find((mode) => mode.pluginId + ':' + mode.id === activeAppModeKey.value)
    || coreAppMode
))
const activePluginMode = computed(() => (
  activeAppMode.value.pluginId === 'core' ? null : activeAppMode.value
))
const activePluginSurface = computed<PluginModeSurface | undefined>(() => {
  const mode = activePluginMode.value
  return mode ? pluginModeRuntime.get(mode.pluginId + ':' + mode.id) : undefined
})
const nextAppModeTitle = computed(() => {
  const modes = appModes.value
  if (modes.length < 2) return '没有可切换的插件模式'
  const index = modes.findIndex((mode) => mode.pluginId + ':' + mode.id === activeAppModeKey.value)
  return '切换到 ' + (modes[(index + 1) % modes.length]?.title || '下一个模式')
})

function modeKey(mode: PluginMode): string {
  return mode.pluginId + ':' + mode.id
}

function isPluginOwnedSession(session: CoreSessionListItem | undefined): boolean {
  return typeof session?.metadata?.owner_plugin === 'string'
    && Boolean(session.metadata.owner_plugin)
}

function isActivePluginSession(): boolean {
  return isPluginOwnedSession(sessions.value.find((session) => session.id === activeSessionId.value))
}

const composerPlaceholder = computed(() => (
  activePluginMode.value
    ? readPluginSurface(activePluginSurface.value?.composerPlaceholder, '输入内容…')
    : '给 Core Agent 发送任务...'
))

const composerInputDisabled = computed(() => {
  if (activePluginMode.value) {
    return readPluginSurface(activePluginSurface.value?.composerDisabled, true)
  }
  return composerActionMode.value === 'send' && (
    sendingDisabled.value
    || !activeSessionId.value
  )
})

const composerSendDisabled = computed(() => (
  composerInputDisabled.value
  || (!composerText.value.trim() && pendingAttachments.value.length === 0)
))

// --- Stage pane state ---
const stageOpen = ref(false)
const stageTabs = ref<StageResource[]>([])
const stageActiveId = ref<string | null>(null)
const stagePaneRef = ref<StagePaneInstance | null>(null)

function toggleStage() {
  stageOpen.value = !stageOpen.value
}

function stageActivate(id: string) {
  stageActiveId.value = id
}

function stageClose(id: string) {
  stageTabs.value = stageTabs.value.filter((t) => t.id !== id)
  if (stageActiveId.value === id) {
    stageActiveId.value = stageTabs.value[0]?.id ?? null
  }
  if (stageTabs.value.length === 0) {
    stageOpen.value = false
  }
}

function stageUpdateContent(payload: { id: string; content: string }) {
  const tab = stageTabs.value.find((t) => t.id === payload.id)
  if (tab) tab.content = payload.content
}

async function stageSave(payload: { id: string; content: string }) {
  const tab = stageTabs.value.find((t) => t.id === payload.id)
  if (!tab || !tab.path) return
  const projectId = activeProjectId.value
  if (!projectId) return
  try {
    await projectClient.writeFile(projectId, tab.path, payload.content)
    stagePaneRef.value?.onSaved()
  } catch {
    // 保存失败：复位 saving 让用户可重试，保持 dirty 状态提示未保存
    stagePaneRef.value?.resetSaving()
  }
}

function stageTogglePreview(id: string, mode: 'code' | 'preview') {
  const tab = stageTabs.value.find((t) => t.id === id)
  if (tab) tab.previewMode = mode
}

const EXT_TO_KIND: Record<string, StageKind> = {
  ts: 'code', tsx: 'code', js: 'code', jsx: 'code', mjs: 'code',
  vue: 'code', py: 'code', rs: 'code', go: 'code', java: 'code',
  json: 'code', css: 'code', scss: 'code', html: 'code',
  yaml: 'code', yml: 'code', toml: 'code', sh: 'code', sql: 'code',
  md: 'markdown',
  png: 'image', jpg: 'image', jpeg: 'image', gif: 'image',
  webp: 'image', svg: 'image', bmp: 'image', ico: 'image',
  mp4: 'video', webm: 'video', mov: 'video', avi: 'video',
  mp3: 'audio', wav: 'audio', ogg: 'audio', flac: 'audio',
  pdf: 'pdf',
}

function inferStageKind(ext: string): StageKind {
  return EXT_TO_KIND[ext] ?? 'code'
}

async function openFileInStage(entry: { path: string; name: string; ext: string }) {
  const projectId = activeProjectId.value
  if (!projectId) return
  const kind = inferStageKind(entry.ext)
  const tabId = `file:${entry.path}`
  const existing = stageTabs.value.find((t) => t.id === tabId)
  if (existing) {
    stageActiveId.value = tabId
    if (!stageOpen.value) stageOpen.value = true
    return
  }
  const tab: StageResource = {
    id: tabId,
    kind,
    path: entry.path,
    label: entry.name,
    language: entry.ext,
  }
  if (kind === 'code' || kind === 'markdown') {
    try {
      const result = await projectClient.readFile(projectId, entry.path)
      tab.content = result.content
    } catch {
      tab.content = '// 无法加载文件内容'
    }
  } else if (kind === 'image' || kind === 'video' || kind === 'audio' || kind === 'pdf') {
    tab.url = projectClient.fileRawUrl(projectId, entry.path)
  }
  stageTabs.value.push(tab)
  stageActiveId.value = tabId
  if (!stageOpen.value) stageOpen.value = true
}
// Split key from the shell's — useShellLayout persists stageOpen/stageHeight
// under 'lamtools.core.ui'; writing the same key from here with a different
// schema silently dropped those fields on every preference save (audit 19 S3).
const uiPreferences = useCoreUiPreferences('lamtools.core.ui.preferences')
const { density, contentWidth, theme } = uiPreferences
const availableModels = ref<RawModel[]>([])
const availableProviders = ref<RawProvider[]>([])
const defaultModelId = ref('')
const permissionMode = ref<'read_only' | 'limited_edit' | 'full_edit'>('full_edit')
const allowAccessOutsideWorkdir = ref(false)
const { pendingAttachments, attachmentInputItems, addUploaded, markFailed, removeAttachment, clearAttachments } = usePendingAttachments()
const threadScrollEl = ref<HTMLElement | null>(null)
const threadScroll = useCoreAutoFollowScroll(threadScrollEl)
const COMPOSER_MAX_ROWS = 5
let threadResizeObserver: ResizeObserver | null = null
let threadResizeObserverTarget: HTMLElement | null = null
let configClient: CoreAppServerClient | null = null

async function loadEarlierMessages(): Promise<void> {
  const el = threadScrollEl.value
  const prevScrollTop = el?.scrollTop ?? 0
  const prevHeight = el?.scrollHeight ?? 0
  loadMoreHistory()
  await nextTick()
  // Keep the viewport anchored: new history prepends above, so shift the
  // scroll position by the height delta. The ResizeObserver's follow is
  // gated by autoFollow (false while the user is not at the bottom), so it
  // cannot yank us back down.
  if (el && el.scrollHeight > prevHeight) {
    el.scrollTop = prevScrollTop + (el.scrollHeight - prevHeight)
    // Re-sync controller state with the real landed position so the
    // "回到最新" affordance and follow gate stay truthful after the anchor.
    threadScroll.handleScroll()
  }
}

const defaultModel = computed(() => (
  availableModels.value.find((model) => model.id === defaultModelId.value) || null
))
const executionControls = useCoreExecutionControlsState({
  models: availableModels,
  providers: availableProviders,
  defaultModel,
  storage: window.localStorage,
  initial: { thinkingMode: 'medium' },
  onPermissionPresetSelected: persistSessionPermissionPreset,
})
const {
  modelOptions,
  selectedModelId,
  selectedThinkingMode,
  shallowThinkingEnabled,
  thinkingModeOptions,
  activeMode,
  permissionPreset,
  selectMode,
} = executionControls

const modeOptions = computed(() =>
  activePluginMode.value ? [] : [
    { value: 'consider', label: 'consider' },
    { value: 'execute', label: 'execute' },
  ]
)
const runtimeModeLabel = computed(() => (
  activePluginMode.value?.title
    || modeOptions.value.find((option) => option.value === activeMode.value)?.label
    || activeMode.value
    || '模式'
))

const latestStatus = computed(() => snapshot.value ? selectLatestTurnStatus(snapshot.value) : 'idle')
const activeTurnId = computed(() => snapshot.value ? selectLatestActiveTurnId(snapshot.value) : '')
const activeTurnRunning = computed(() => isCoreActiveTurnStatus(latestStatus.value))
const rollbackActiveTurn = computed(() => ['running', 'waiting'].includes(latestStatus.value))

const coreSessions = computed(() => sessions.value.filter((session) => !isPluginOwnedSession(session)))
const coreProjectGroups = computed(() => buildCoreProjectGroups(projects.value, coreSessions.value))
const sidebarGroups = computed(() => {
  const sidebar = activePluginSurface.value?.sidebar
  return sidebar ? readPluginSurface(sidebar.groups, []) : coreProjectGroups.value
})
const sidebarHasProjects = computed(() => {
  const sidebar = activePluginSurface.value?.sidebar
  return sidebar
    ? readPluginSurface(sidebar.hasProjects, sidebarGroups.value.length > 0)
    : projects.value.length > 0
})
const sidebarActiveSessionId = computed(() => {
  const sidebar = activePluginSurface.value?.sidebar
  return sidebar
    ? readPluginSurface(sidebar.activeSessionId, undefined)
    : (activeSessionId.value || undefined)
})
const sidebarNewSessionLabel = computed(() => {
  const sidebar = activePluginSurface.value?.sidebar
  return sidebar ? readPluginSurface(sidebar.newSessionLabel, '新建') : '新建会话'
})
const sidebarAllowProjectNewSession = computed(() => {
  const sidebar = activePluginSurface.value?.sidebar
  return sidebar ? readPluginSurface(sidebar.allowProjectNewSession, false) : true
})
const sidebarAllowProjectDelete = computed(() => {
  const sidebar = activePluginSurface.value?.sidebar
  return sidebar ? readPluginSurface(sidebar.allowProjectDelete, false) : true
})
const sidebarAllowProjectClick = computed(() => {
  const sidebar = activePluginSurface.value?.sidebar
  return sidebar ? readPluginSurface(sidebar.allowProjectClick, false) : true
})
const sidebarAllowProjectContextMenu = computed(() => {
  const sidebar = activePluginSurface.value?.sidebar
  return sidebar ? readPluginSurface(sidebar.allowProjectContextMenu, false) : true
})
const sidebarAllowSessionDelete = computed(() => {
  const sidebar = activePluginSurface.value?.sidebar
  return sidebar ? readPluginSurface(sidebar.allowSessionDelete, false) : true
})
const sidebarAllowSessionContextMenu = computed(() => {
  const sidebar = activePluginSurface.value?.sidebar
  return sidebar ? readPluginSurface(sidebar.allowSessionContextMenu, false) : true
})
const sidebarPrimaryActionLabel = computed(() => (
  activePluginSurface.value?.sidebar
    ? readPluginSurface(activePluginSurface.value.sidebar.primaryActionLabel, '')
    : '新建项目'
))
const activeSessionTitle = computed(() => (
  sessions.value.find((session) => session.id === activeSessionId.value)?.title || 'Session'
))
const selectedProject = computed(() => (
  projects.value.find((project) => project.id === selectedProjectId.value) || null
))
const activeProjectId = computed(() => {
  const session = sessions.value.find((item) => item.id === activeSessionId.value)
  const workRoot = session?.metadata?.work_root
  if (typeof workRoot !== 'string') return null
  const project = projects.value.find((p) => p.workRoot === workRoot)
  return project?.id ?? null
})
const activeProject = computed(() => (
  projects.value.find((project) => project.id === activeProjectId.value) || null
))
const projectWorkspace = createCoreProjectWorkspaceActions({
  client: projectClient,
  projects,
  sessions,
  activeSessionId,
  selectSession,
})
const busyProjectIds = projectWorkspace.busyProjectIds
const sidebarBusyProjectIds = computed(() => (
  activePluginMode.value ? [] : busyProjectIds.value
))

const runtimeController = createCoreAppServerRuntimeController(runtime, {
    hydrateSnapshot,
    onSessionCreated: refreshSessions,
    onSessionUpdated: refreshSessions,
    createClient: ({ apiBase: frontendBase, onEvent, onSnapshot, onConnectionState }) => new CoreAppServerClient({
      url: appServerUrl(frontendBase, { path: '/api/core/app-server' }),
      clientInfo: { name: 'lamtools_core_frontend', title: 'LamTools Core Frontend', version: '0.1.0' },
      onEvent: (event) => {
        lastEvent.value = event
        onEvent(event)
      },
      onSnapshot,
      onConnectionState: (state) => {
        onConnectionState(state)
      },
    }),
  })

const liveComposerController = useCoreLiveComposerController({
  activeThreadId: activeSessionId,
  activeTurnId,
  connectedThreadId: computed(() => runtime.activeThreadId),
  connectionState: computed(() => runtime.connectionState),
  text: composerText,
  cursor: composerCursor,
  status: latestStatus,
  attachments: attachmentInputItems,
  connect: connectLive,
  startTurn: (threadId, input, workRoot, options) => runtimeController.startTurn(threadId, input, workRoot, options),
  interruptTurn: (threadId, turnId) => runtimeController.interruptTurn(threadId, turnId),
  forceResetTurn: (threadId, turnId) => runtimeController.forceResetTurn(threadId, turnId),
  steerTurn: (threadId, turnId, input) => runtimeController.steerTurn(threadId, turnId, input),
  queueInput: (threadId, input, options) => runtimeController.queueInput(threadId, input, options),
  listCommands: (workRoot) => runtimeController.listCommands(workRoot),
  getWorkRoot: currentWorkRoot,
  executeCommand: async (threadId, command, workRoot) => {
    await runtimeController.executeCommand(threadId, command, workRoot)
    return true
  },
  canExecuteCommand: () => latestStatus.value !== 'running' && latestStatus.value !== 'waiting',
  turnOptions: () => {
    const pluginOptions = activePluginSurface.value?.turnOptions?.() || {}
    // Plugin surfaces may add product-specific turn options, but the runtime
    // permission snapshot belongs to Core. Do not let a plugin mode replace
    // the Composer-selected preset or inject expanded permission fields.
    const {
      permission_preset: _permissionPreset,
      active_tier: _activeTier,
      tier_tools: _tierTools,
      approval_policy: _approvalPolicy,
      allow_access_outside_workdir: _allowOutsideWorkdir,
      ...safePluginOptions
    } = pluginOptions
    return { ...executionControls.turnOptions(), ...safePluginOptions }
  },
  clearComposer: clearComposerAfterPersisted,
  clearAttachments,
  focusComposer,
  setStatusText: (text) => {
    setRuntimeStatus(text)
  },
  onError: (text) => {
    composerErrorText.value = text
  },
  onTurnStarted: refreshSessions,
  onSubmitStart: () => {
    pendingPlaceholder.value = { id: `placeholder-${Date.now()}`, content: '…' }
  },
  messages: {
    commandCatalogLoadFailed: (error) => `命令列表加载失败：${error}`,
    noActiveThread: '请先选择会话',
    queued: '已加入待发送',
    guided: '引导已发送',
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
const { activeGoal, goalError, refreshGoal, handleCancelGoal } = useCoreGoals({ activeSessionId })
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
  onTurnFinished: () => void refreshGoal(activeSessionId.value, true),
})
const { messages, processExpandedIds, toggleProcess, hasMoreHistory, totalMessages, loadMoreHistory } = projectionController

const pendingPlaceholder = ref<{ id: string; content: string } | null>(null)
const stepGroups = computed(() => buildCurrentTurnChecklistGroups(messages.value))

const turnPrompts = computed(() => {
  const map: Record<string, string> = {}
  const state = snapshot.value
  if (!state?.turns) return map
  for (const [turnId, turn] of Object.entries(state.turns)) {
    const input = (turn as Record<string, unknown>).input
    if (Array.isArray(input)) {
      const textItem = input.find((item: Record<string, unknown>) => item.type === 'text')
      if (textItem && typeof textItem.text === 'string') map[turnId] = textItem.text
    }
  }
  return map
})

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

// ── Assistant message actions: fork / roll back at a turn's checkpoint ──
const checkpointsByTurnId = ref<Record<string, string>>({})

/** Turn ids that currently have a checkpoint — rollback/fork/edit buttons hide when absent */
const checkpointTurnIds = computed(() => new Set(Object.keys(checkpointsByTurnId.value)))

provideCorePluginModeContext({
  apiBase,
  requestRpc: requestConfigOperation,
  projectClient,
  projects,
  sessions,
  selectedProjectId,
  activeSessionId,
  selectedProject,
  activeProjectId,
  activeProject,
  currentWorkRoot,
  setSelectedProjectId: (id) => { selectedProjectId.value = id },
  selectSession,
  refreshSessions,
  setRuntimeStatus,
  availableModels,
  composerText,
  ensureRightPanelOpen,
  lastEvent,
  chat: {
    messages,
    processExpandedIds,
    toggleProcess,
    activeTurnId,
    activeTurnRunning,
    checkpointTurnIds,
    onDecisionSelect: async (payload) => {
      await approvalController.handleDecision(
        payload as Parameters<typeof approvalController.handleDecision>[0],
      )
    },
    onForkMessage: (payload) => handleForkMessage(
      payload as Parameters<typeof handleForkMessage>[0],
    ),
    onRollbackMessage: (payload) => handleRollbackMessage(
      payload as Parameters<typeof handleRollbackMessage>[0],
    ),
    onEditMessage: (payload) => handleEditMessage(
      payload as Parameters<typeof handleEditMessage>[0],
    ),
  },
}, pluginModeRuntime)
// Each error source feeds the toast service via watch; the service handles
// auto-expiry (8s for errors) and de-duplication, so nothing stays pinned.
watch(loadError, (value) => { if (value) showToast('error', value, 8000) })
watch(composerErrorText, (value) => { if (value) showToast('error', value, 8000) })
watch(() => approvalController.lastError.value, (value) => { if (value) showToast('error', value, 8000) })
watch(goalError, (value) => { if (value) showToast('error', value, 8000) })

const queuedInputs = computed<CoreQueuedInput[]>(() => {
  if (!snapshot.value || snapshot.value.thread_id !== activeSessionId.value) return []
  return selectCoreQueuedInputs(snapshot.value)
})

watch(queuedInputs, (items) => {
  const shell = document.querySelector('.workspace-shell') as HTMLElement | null
  if (!shell) return
  const count = items.length
  if (count === 0) {
    shell.style.removeProperty('--queued-tray-offset')
  } else {
    // each row: min-height 34px + padding 6px×2 = 46px, tray margin: 4px+6px = 10px
    const offset = count * 46 + 10
    shell.style.setProperty('--queued-tray-offset', `${offset}px`)
  }
}, { immediate: true })

onUnmounted(() => {
  const shell = document.querySelector('.workspace-shell') as HTMLElement | null
  shell?.style.removeProperty('--queued-tray-offset')
})
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
    await Promise.all([loadModelOptions(), loadPermissionMode(), refreshProjects(), refreshSessions()])
    await refreshPluginModes()
    if (coreSessions.value[0]) await selectSession(coreSessions.value[0].id)
  } catch (error) {
    setLoadError(error instanceof Error ? error.message : String(error))
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
  showProjectSettings.value = true
  // Load AGENTS.md content for the in-place editor inside project settings.
  void loadAgentsForProject(project.id)
}

async function loadAgentsForProject(projectId: string) {
  agentsLoading.value = true
  agentsError.value = ''
  try {
    const agents = await projectWorkspace.readAgents(projectId)
    agentsProjectId.value = projectId
    agentsContent.value = agents.content
  } catch (error) {
    agentsError.value = messageFromError(error)
  } finally {
    agentsLoading.value = false
  }
}

async function renameProject(nameFromEditor?: string) {
  const project = selectedProject.value
  if (nameFromEditor !== undefined) projectNameDraft.value = nameFromEditor
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
    if (agentsProjectId.value === project.id) { agentsProjectId.value = null; agentsContent.value = '' }
    if (showProjectSettings.value) closeProjectSettings()
    if (deleted.wasActive) {
      runtimeController.disconnect()
      liveComposerController.resetForThreadChange()
      activeSessionId.value = null
      if (sessions.value[0]) await selectSession(sessions.value[0].id)
    }
  } catch (error) {
    projectActionError.value = messageFromError(error)
  } finally {
    projectActionLoading.value = false
  }
}

function closeProjectSettings() {
  showProjectSettings.value = false
}

async function refreshAgentsContent() {
  const projectId = agentsProjectId.value || selectedProjectId.value
  if (!projectId) return
  await loadAgentsForProject(projectId)
}

async function saveAgents(content: string) {
  const projectId = agentsProjectId.value
  if (!projectId) return
  agentsSaving.value = true
  agentsError.value = ''
  try {
    const agents = await projectWorkspace.writeAgents(projectId, content)
    agentsContent.value = agents.content
    setRuntimeStatus('AGENTS.md 已保存')
  } catch (error) {
    agentsError.value = messageFromError(error)
  } finally {
    agentsSaving.value = false
  }
}

async function renameSession(sessionId: string, title: string) {
  const updated = toSession(await requestJson<RawSession>(`/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'PATCH',
    body: { title },
  }))
  sessions.value = sessions.value.map((session) => session.id === sessionId ? updated : session)
}

async function renameSessionFromSidebar(sessionId: string, title: string): Promise<void> {
  try {
    await renameSession(sessionId, title)
    setRuntimeStatus('会话已重命名')
  } catch (error) {
    composerErrorText.value = messageFromError(error)
  }
}

async function renameActiveSession(title: string) {
  if (!activeSessionId.value) return
  await renameSession(activeSessionId.value, title)
}

function sessionExportExtension(format: SessionExportFormat): SessionExportExtension {
  if (format === 'markdown') return 'md'
  if (format === 'handoff') return 'json'
  return format
}

function exportFileStem(title: string, sessionId: string): string {
  const fallback = `Session-${sessionId.slice(0, 8)}`
  const clean = title
    .trim()
    .replace(/[<>:"/\\|?*\u0000-\u001F]/g, '_')
    .replace(/[. ]+$/g, '')
    .slice(0, 80)
  return clean && clean !== '.' && clean !== '..' ? clean : fallback
}

function localDateStamp(date = new Date()): string {
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

async function exportSession(sessionId: string, format: SessionExportFormat): Promise<void> {
  const session = sessions.value.find((item) => item.id === sessionId)
  const title = session?.title || `Session ${sessionId.slice(0, 8)}`
  const mode = format === 'zip' ? 'full' : format === 'handoff' ? 'handoff' : 'transcript'
  const outputFormat = format === 'zip' ? 'zip' : format === 'handoff' ? 'json' : format

  try {
    const response = await fetch(`${apiBase}/sessions/${encodeURIComponent(sessionId)}/export`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode, format: outputFormat }),
    })
    if (!response.ok) {
      const errorText = await response.text()
      throw new Error(errorText || `${response.status} ${response.statusText}`)
    }

    const blob = await response.blob()
    const extension = sessionExportExtension(format)
    const suffix = format === 'handoff' ? '-handoff' : ''
    const filename = `${exportFileStem(title, sessionId)}-${localDateStamp()}${suffix}.${extension}`
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    link.style.display = 'none'
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 0)
    setRuntimeStatus(`已导出：${filename}`)
  } catch (error) {
    composerErrorText.value = messageFromError(error)
  }
}

async function deleteSession(sessionId: string) {
  const session = sessions.value.find((item) => item.id === sessionId)
  const title = session?.title || `Session ${sessionId.slice(0, 8)}`
  if (!window.confirm(`确定删除会话「${title}」？会话、历史、checkpoint、附件记录都会删除。此操作不可撤销。`)) return

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
  }
  await refreshSessions()
  if (deletedActiveSession && sessions.value[0]) await selectSession(sessions.value[0].id)
}

async function selectSession(id: string) {
  activeSessionId.value = id
  restoreSessionModel(id)
  restoreSessionPermissionPreset(id)
  runtimeController.disconnect()
  liveComposerController.resetForThreadChange()
  composerErrorText.value = ''
  setRuntimeStatus('', 0)
  threadScroll.reset() // invalidate in-flight scrolls from the previous session
  await connectLive(id)
  await liveComposerController.loadCommandCatalog(id)
  await refreshGoal(id, true)
  loadCheckpointGraph(id) // fire-and-forget: refresh turn→checkpoint map for rollback/fork
  await threadScroll.scrollToBottom(true)
}

// ── 全局搜索跳转（SearchShell 会话命中 → 打开会话 + 消息锚点定位）──
async function jumpToSearchedMessage(sessionId: string, messageId: string): Promise<void> {
  if (activeSessionId.value !== sessionId) {
    await selectSession(sessionId)
  }
  await locateMessage(messageId)
}

/** 定位消息：轮询目标 DOM（窗口未含则逐步加载更早历史），
 * 命中 → scrollIntoView 居中 + 高亮渐隐（2.6s）。找不到给出提示。 */
async function locateMessage(messageId: string): Promise<void> {
  const selector = `[data-message-id="${CSS.escape(messageId)}"]`
  for (let attempt = 0; attempt < 60; attempt += 1) {
    const el = document.querySelector<HTMLElement>(selector)
    if (el) {
      el.scrollIntoView({ block: 'center', behavior: 'smooth' })
      el.classList.add('rag-hit-highlight')
      window.setTimeout(() => el.classList.remove('rag-hit-highlight'), 2600)
      return
    }
    if (projectionController.hasMoreHistory.value) {
      projectionController.loadMoreHistory()
      await nextTick()
      await new Promise((resolve) => setTimeout(resolve, 150))
      continue
    }
    break
  }
  showToast('error', '未找到该消息（可能已被删除或属于子会话）', 5000)
}

// Session-scoped model memory: each session remembers its own model choice,
// so switching sessions restores that session's model instead of sharing a
// single global selection. The chosen model is persisted into the session's
// metadata by the selectedModelId watcher below.
function restoreSessionModel(id: string) {
  const session = sessions.value.find((item) => item.id === id)
  if (isPluginOwnedSession(session)) return
  const storedModelId = session?.metadata?.model_id
  if (
    typeof storedModelId === 'string'
    && storedModelId
    && availableModels.value.some((model) => model.id === storedModelId)
  ) {
    executionControls.selectModel(storedModelId)
  }
}

async function refreshAfterRollback() {
  const sessionId = activeSessionId.value
  if (!sessionId) return
  await refreshSessions()
  await selectSession(sessionId)
}

function onCheckpointGraphLoaded(nodes: Array<{
  id: string
  turn_id?: string
  actor_kind?: string
  reason?: string
}>) {
  const map: Record<string, string> = {}
  for (const node of nodes) {
    const turnId = String(node.turn_id || '').trim()
    // Only the "before user prompt" node of a main-session turn maps 1:1 to a
    // user message; sub-agent / manual / rollback-derived nodes are excluded.
    if (turnId && node.actor_kind === 'main' && node.reason === 'before_user_prompt') {
      map[turnId] = node.id
    }
  }
  checkpointsByTurnId.value = map
}

async function loadCheckpointGraph(sessionId: string) {
  try {
    const result = await requestConfigOperation('session.checkpoints.graph', { session_id: sessionId })
    onCheckpointGraphLoaded(Array.isArray(result?.nodes) ? result.nodes : [])
  } catch {
    // Graph load must never block the UI; rollback/fork handlers refresh
    // on-demand before giving up, so a failure here is non-fatal.
  }
}

async function handleForkMessage(payload: { turnId: string; content: string }) {
  const sessionId = activeSessionId.value
  if (!sessionId) {
    composerErrorText.value = '该消息没有可用的分叉节点'
    return
  }
  let checkpointId = checkpointsByTurnId.value[payload.turnId]
  if (!checkpointId) {
    // Map may be stale or not loaded yet — refresh once before giving up.
    await loadCheckpointGraph(sessionId)
    checkpointId = checkpointsByTurnId.value[payload.turnId]
  }
  if (!checkpointId) {
    composerErrorText.value = '该消息没有可用的分叉节点'
    return
  }
  if (rollbackActiveTurn.value) {
    composerErrorText.value = '任务运行中，请先停止任务再分叉'
    return
  }
  try {
    const result = await requestConfigOperation('session.fork', {
      session_id: sessionId,
      checkpoint_id: checkpointId,
    })
    const forkedSessionId = String(result?.session_id || '')
    await refreshSessions()
    if (forkedSessionId) await selectSession(forkedSessionId)
  } catch (error) {
    composerErrorText.value = error instanceof Error ? error.message : String(error)
  }
}

async function handleRollbackMessage(payload: { turnId: string; content: string }) {
  const sessionId = activeSessionId.value
  if (!sessionId) {
    composerErrorText.value = '该消息没有对应的回退节点'
    return
  }
  let checkpointId = checkpointsByTurnId.value[payload.turnId]
  if (!checkpointId) {
    // Map may be stale or not loaded yet — refresh once before giving up.
    await loadCheckpointGraph(sessionId)
    checkpointId = checkpointsByTurnId.value[payload.turnId]
  }
  if (!checkpointId) {
    composerErrorText.value = '该消息没有对应的回退节点'
    return
  }
  if (rollbackActiveTurn.value) {
    composerErrorText.value = '任务运行中，请先停止任务再回退'
    return
  }
  try {
    await requestConfigOperation('session.checkpoints.restore', {
      session_id: sessionId,
      checkpoint_id: checkpointId,
      scope: 'all',
    })
    await refreshAfterRollback()
  } catch (error) {
    composerErrorText.value = error instanceof Error ? error.message : String(error)
  }
}

async function handleEditMessage(payload: { turnId: string; content: string; attachments?: CoreAttachment[] }) {
  const sessionId = activeSessionId.value
  if (!sessionId) {
    composerErrorText.value = '该消息没有可编辑的节点'
    return
  }
  let checkpointId = checkpointsByTurnId.value[payload.turnId]
  if (!checkpointId) {
    // Map may be stale or not loaded yet — refresh once before giving up.
    await loadCheckpointGraph(sessionId)
    checkpointId = checkpointsByTurnId.value[payload.turnId]
  }
  if (!checkpointId) {
    composerErrorText.value = '该消息没有可编辑的节点'
    return
  }
  if (rollbackActiveTurn.value) {
    composerErrorText.value = '任务运行中，请先停止任务再编辑'
    return
  }
  try {
    // 回退到该用户消息发出前的检查点（同回退），再以编辑后的内容重新发送
    await requestConfigOperation('session.checkpoints.restore', {
      session_id: sessionId,
      checkpoint_id: checkpointId,
      scope: 'all',
    })
    await refreshAfterRollback()
    // 携带原消息附件（已在后端上传，直接标记 uploaded 随发送提交，无需重新上传）
    clearAttachments()
    for (const attachment of payload.attachments ?? []) {
      addUploaded({ ...attachment, status: 'uploaded' })
    }
    composerText.value = payload.content
    await submitComposer()
  } catch (error) {
    composerErrorText.value = error instanceof Error ? error.message : String(error)
  }
}

async function connectLive(threadId: string) {
  await runtimeController.connect(apiBase, threadId)
}

async function submitComposer() {
  composerErrorText.value = ''
  // 停止模式：composer 必为空，须在空文本守卫之前处理，否则 stop 请求永远发不出去
  if (composerActionMode.value === 'stop') {
    try {
      await liveComposerController.submit({ clearComposer: false })
    } catch {
      // error handled by controller
    }
    return
  }
  const text = composerText.value.trim()
  if (!text) return

  sendingDisabled.value = true

  try {
    await liveComposerController.submit({ clearComposer: true })
  } catch {
    // error handled by controller
  } finally {
    sendingDisabled.value = false
  }
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
      const projectQuery = activeProjectId.value
        ? `?project_id=${encodeURIComponent(activeProjectId.value)}`
        : ''
      const response = await fetch(`${apiBase}/sessions/${encodeURIComponent(sessionId)}/attachments${projectQuery}`, { method: 'POST', body })
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

// ── 全窗口拖拽上传：window 级 dragover 亮起遮罩，drop 统一走遮罩上传 ──
const dragActive = ref(false)

function handleWindowDragOver(event: DragEvent) {
  // 仅拦截文件拖拽；插件视图内部拖拽、文本拖选等不干预
  if (event.dataTransfer?.types.includes('Files')) {
    event.preventDefault()
    dragActive.value = true
  }
}

function handleWindowDragLeave(event: DragEvent) {
  // relatedTarget 为 null 表示已拖出窗口（子元素间移动不熄灭）
  if (!event.relatedTarget) dragActive.value = false
}

function handleWindowDrop() {
  // 兜底熄灭：drop 已由目标元素（遮罩/composer）处理上传，这里只保证遮罩收起
  dragActive.value = false
}

function handleAttachmentDrop(event: DragEvent) {
  dragActive.value = false
  if (event.dataTransfer?.files.length) void uploadFiles(event.dataTransfer.files)
}

// ── 粘贴上传：输入框聚焦时 Ctrl+V 图片/文件 → 复用上传管线；纯文本不受影响 ──
function handleComposerPaste(event: ClipboardEvent) {
  const files: File[] = []
  const items = event.clipboardData?.items
  if (items) {
    for (const item of Array.from(items)) {
      if (item.kind === 'file') {
        const file = item.getAsFile()
        if (file) files.push(file)
      }
    }
  }
  // 兜底：items 拿不到时（个别 WebView）退回 files 列表
  if (!files.length) {
    const dropped = event.clipboardData?.files
    if (dropped?.length) files.push(...Array.from(dropped))
  }
  if (files.length) void uploadFiles(files)
}

function retryPendingAttachment(id: string) {
  removeAttachment(id)
  attachmentFileInput.value?.click()
}

async function previewPendingAttachment(id: string) {
  if (id.startsWith('failed:')) return
  const response = await fetch(`${apiBase}/attachments/${encodeURIComponent(id)}/preview`)
  setRuntimeStatus(response.ok ? '附件预览已读取' : '附件预览失败')
}

async function openPendingAttachment(id: string) {
  if (id.startsWith('failed:')) return
  const response = await fetch(`${apiBase}/attachments/${encodeURIComponent(id)}/open`, { method: 'POST' })
  if (!response.ok) setRuntimeStatus('打开附件失败')
}

async function handleComposerKeydown(event: KeyboardEvent) {
  if (sendingDisabled.value) return
  updateComposerCursor()
  await liveComposerController.handleKeydown(event)
}

async function handleComposerKeyup(event: KeyboardEvent) {
  if (sendingDisabled.value) return
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

// ---- 首次启动引导 ----

async function checkOnboarding() {
  try {
    const result = await requestConfigOperation('settings.get', { namespace: 'core.onboarding' })
    const value = result.value && typeof result.value === 'object' ? result.value as Record<string, unknown> : {}
    if (value.completed === true) return
  } catch {
    return // 配置服务不可用时 fail-open，不阻塞老用户
  }
  if (availableProviders.value.some((provider) => provider.has_api_key)) return
  showOnboarding.value = true
  // 弹过一次就算“谈过”：立即标记 completed，下次不再自动弹出
  // （除非用户通过“再次显示引导”主动清除标记）。
  try {
    await requestConfigOperation('settings.update', {
      namespace: 'core.onboarding',
      value: { completed: true, version: 1, completed_at: new Date().toISOString() },
    })
  } catch {
    // 标记失败不阻塞引导展示
  }
}

async function skipOnboarding() {
  showOnboarding.value = false
  // 跳过也算谈过：与 checkOnboarding 的自动标记保持一致。
  try {
    await requestConfigOperation('settings.update', {
      namespace: 'core.onboarding',
      value: { completed: true, version: 1, completed_at: new Date().toISOString() },
    })
  } catch {
    // 标记失败不阻塞进入主界面
  }
}

async function onboardingCreateProvider(payload: CoreSettingsProviderPayload) {
  wizardError.value = ''
  wizardLoading.value = true
  try {
    loadError.value = null
    await requestConfigOperation('config.provider.create', payload as unknown as Record<string, unknown>)
    await loadModelOptions()
    setRuntimeStatus('供应商已添加')
  } catch (error) {
    wizardError.value = error instanceof Error ? error.message : String(error)
  } finally {
    wizardLoading.value = false
  }
}

async function finishOnboarding() {
  showOnboarding.value = false
  try {
    await requestConfigOperation('settings.update', {
      namespace: 'core.onboarding',
      value: { completed: true, version: 1, completed_at: new Date().toISOString() },
    })
  } catch {
    // 标记失败不阻塞进入主界面
  }
}

async function reopenOnboarding() {
  try {
    await requestConfigOperation('settings.update', {
      namespace: 'core.onboarding',
      value: { completed: false },
    })
  } catch {
    // 忽略：标记清除失败仍允许重开引导
  }
  showOnboarding.value = true
}

async function updateProvider(payload: CoreSettingsProviderPayload) {
  await mutateConfig('config.provider.update', payload, '供应商已更新')
}

async function deleteProvider(providerId: string) {
  if (!window.confirm('删除供应商会同时移除其模型配置，是否继续？')) return
  await mutateConfig('config.provider.delete', { provider_id: providerId }, '供应商已删除')
}

async function createModel(payload: CoreSettingsModelPayload) {
  await mutateConfig('config.models.upsert', { scope: 'global', ...payload }, '模型已添加')
}

async function updateModel(payload: CoreSettingsModelPayload) {
  await mutateConfig('config.models.upsert', { scope: 'global', ...payload }, '模型已更新')
}

async function deleteModel(modelRecordId: string) {
  if (!window.confirm('删除此模型配置，是否继续？')) return
  await mutateConfig('config.models.delete', { scope: 'global', model_id: modelRecordId }, '模型已删除')
}

async function setDefaultModel(modelId: string) {
  await mutateConfig('config.models.set_default', { scope: 'global', model_id: modelId }, '已设为默认模型')
}

async function loadPermissionMode() {
  try {
    const result = await requestConfigOperation('settings.get', { namespace: 'core.runtimeControls' })
    const value = result.value && typeof result.value === 'object' ? result.value as Record<string, unknown> : {}
    const mode = value.permission_mode
    if (mode === 'read_only' || mode === 'limited_edit' || mode === 'full_edit') {
      permissionMode.value = mode
    } else {
      await updatePermissionMode(permissionMode.value)
    }
    allowAccessOutsideWorkdir.value = Boolean(value.allow_access_outside_workdir)
  } catch {
    permissionMode.value = 'full_edit'
  }
}

async function updatePermissionMode(mode: 'read_only' | 'limited_edit' | 'full_edit') {
  const previous = permissionMode.value
  permissionMode.value = mode
  try {
    await requestConfigOperation('settings.update', {
      namespace: 'core.runtimeControls',
      value: { permission_mode: mode },
    })
  } catch (e) {
    // Roll back on failure — the UI must never show a security-relevant
    // mode that the backend did not persist (audit 17 S3).
    permissionMode.value = previous
    const message = e instanceof Error ? e.message : String(e)
    window.alert(`权限模式保存失败，已回滚：${message}`)
  }
}

async function updateAllowAccessOutsideWorkdir(value: boolean) {
  const previous = allowAccessOutsideWorkdir.value
  allowAccessOutsideWorkdir.value = value
  try {
    await requestConfigOperation('settings.update', {
      namespace: 'core.runtimeControls',
      value: { allow_access_outside_workdir: value },
    })
  } catch (e) {
    allowAccessOutsideWorkdir.value = previous
    const message = e instanceof Error ? e.message : String(e)
    window.alert(`工作目录外访问设置保存失败，已回滚：${message}`)
  }
}

async function mutateConfig(method: string, params: object, successText: string) {
  try {
    loadError.value = null
    await requestConfigOperation(method, params as Record<string, unknown>)
    await loadModelOptions()
    setRuntimeStatus(successText)
  } catch (error) {
    setLoadError(error instanceof Error ? error.message : String(error))
  }
}

async function requestConfigOperation(method: string, params: Record<string, unknown> = {}) {
  let lastError: Error | null = null
  const maxRetries = 5
  const baseDelay = 200
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    if (!configClient) {
      const client = new CoreAppServerClient({
        url: appServerUrl(apiBase, { path: '/api/core/app-server' }),
        clientInfo: { name: 'lamtools_core_settings', title: 'LamTools Core Settings', version: '0.1.0' },
        onConnectionState: (state) => {
          if (state === 'closed' || state === 'error') configClient = null
        },
      })
      try {
        await client.connect()
        configClient = client
      } catch (error) {
        lastError = error instanceof Error ? error : new Error(String(error))
        configClient = null
        if (attempt < maxRetries) {
          await new Promise((r) => setTimeout(r, baseDelay * 2 ** attempt))
          continue
        }
        throw lastError
      }
    }
    try {
      return await configClient.request(method, params)
    } catch (error) {
      configClient = null
      lastError = error instanceof Error ? error : new Error(String(error))
      if (attempt < maxRetries) {
        await new Promise((r) => setTimeout(r, baseDelay * 2 ** attempt))
        continue
      }
      throw lastError
    }
  }
  throw lastError ?? new Error('Core App Server 连接失败')
}

// ── 软件更新（设置 → 关于与更新；启动时静默自动检查）──
const updateState = useCoreUpdateState(requestConfigOperation)
// 解构到 setup 顶层供模板使用（嵌套 ref 在模板中不会自动解包）
const { status: updateStatus, latestVersion: updateLatestVersion, download: downloadUpdate } = updateState
const updateBannerDismissed = ref(false)
const updateBannerVisible = computed(
  () => updateStatus.value === 'update_available' && !updateBannerDismissed.value,
)
function dismissUpdateBanner() {
  updateBannerDismissed.value = true
}

function currentWorkRoot(): string {
  const session = sessions.value.find((item) => item.id === activeSessionId.value)
  const workRoot = session?.metadata?.work_root
  return typeof workRoot === 'string' ? workRoot : ''
}

function restoreSessionPermissionPreset(id: string): void {
  const session = sessions.value.find((item) => item.id === id)
  const preferences = session?.metadata?.runtime_preferences
  const preset = preferences && typeof preferences === 'object' && !Array.isArray(preferences)
    ? (preferences as Record<string, unknown>).permission_preset
    : undefined
  // A legacy session is canonicalized by the backend on listing. If an old
  // client still returns no preference block, use the safe UI default; never
  // copy the currently selected session's preset across the boundary.
  executionControls.restorePermissionPreset(preset ?? 'ask')
}

let permissionPersistence = Promise.resolve()
let permissionPersistenceGeneration = 0

function persistSessionPermissionPreset(preset: CorePermissionPreset): Promise<void> {
  const sessionId = activeSessionId.value
  const session = sessions.value.find((item) => item.id === sessionId)
  if (!sessionId || !session) return Promise.resolve()

  const metadata: Record<string, unknown> = { ...(session.metadata || {}) }
  const existing = metadata.runtime_preferences
  const preferences = existing && typeof existing === 'object' && !Array.isArray(existing)
    ? { ...(existing as Record<string, unknown>) }
    : {}
  preferences.permission_preset = preset
  metadata.runtime_preferences = preferences
  const generation = ++permissionPersistenceGeneration

  permissionPersistence = permissionPersistence.then(async () => {
    // Keep writes ordered so a quick ask → auto → full_access sequence cannot
    // leave the session with an older response that arrived last.
    try {
      const updated = await requestJson<RawSession>(`/sessions/${encodeURIComponent(sessionId)}`, {
        method: 'PATCH',
        body: { metadata },
      })
      if (generation !== permissionPersistenceGeneration) return
      sessions.value = sessions.value.map((item) => (
        item.id === sessionId ? { ...item, metadata: updated.metadata } : item
      ))
    } catch (error) {
      // Keep the chain usable for a later selection and surface the failed
      // session write without touching global runtimeControls.
      if (generation === permissionPersistenceGeneration) {
        composerErrorText.value = `权限偏好保存失败：${messageFromError(error)}`
      }
    }
  })
  return permissionPersistence
}

async function refreshPluginModes(): Promise<void> {
  try {
    await refreshPluginUIModes(requestConfigOperation)
    pluginModes.value = listModes()
    if (!appModes.value.some((mode) => modeKey(mode) === activeAppModeKey.value)) {
      activeAppModeKey.value = 'core:agent'
      if (isActivePluginSession()) {
        runtimeController.disconnect()
        liveComposerController.resetForThreadChange()
        activeSessionId.value = null
        if (coreSessions.value[0]) await selectSession(coreSessions.value[0].id)
      }
    }
  } catch (error) {
    console.error('[plugins] UI mode list failed', error)
    pluginModes.value = []
    if (activePluginMode.value) {
      activeAppModeKey.value = 'core:agent'
      if (isActivePluginSession()) {
        runtimeController.disconnect()
        liveComposerController.resetForThreadChange()
        activeSessionId.value = null
        if (coreSessions.value[0]) await selectSession(coreSessions.value[0].id)
      }
    }
  }
}

async function selectAppMode(mode: PluginMode): Promise<void> {
  if (!appModes.value.some((candidate) => modeKey(candidate) === modeKey(mode))) return
  activeAppModeKey.value = modeKey(mode)
  if (mode.pluginId === 'core' && isActivePluginSession()) {
    runtimeController.disconnect()
    liveComposerController.resetForThreadChange()
    activeSessionId.value = null
    if (coreSessions.value[0]) await selectSession(coreSessions.value[0].id)
  }
}

function cycleAppMode(): void {
  const modes = appModes.value
  if (modes.length < 2) return
  const index = modes.findIndex((mode) => modeKey(mode) === activeAppModeKey.value)
  void selectAppMode(modes[(index + 1) % modes.length])
}

function invokeSidebarPrimaryAction(): void {
  const action = activePluginSurface.value?.sidebar?.onPrimaryAction
  if (action) {
    void Promise.resolve(action()).catch((error) => {
      composerErrorText.value = messageFromError(error)
    })
    return
  }
  openProjectCreate()
}

function handleShellNewSession(): void {
  invokeSidebarPrimaryAction()
}

function handleSidebarSession(id: string): void {
  const action = activePluginSurface.value?.sidebar?.onSelectSession
  if (action) {
    void Promise.resolve(action(id)).catch((error) => {
      composerErrorText.value = messageFromError(error)
    })
    return
  }
  void selectSession(id)
}

function handleSidebarProject(id: string): void {
  const action = activePluginSurface.value?.sidebar?.onSelectProject
  if (action) {
    void Promise.resolve(action(id)).catch((error) => {
      composerErrorText.value = messageFromError(error)
    })
    return
  }
  openProjectActions(id)
}

function handleSidebarNewSession(projectGroupId: string): void {
  const action = activePluginSurface.value?.sidebar?.onNewSession
  if (action) {
    void Promise.resolve(action(projectGroupId)).catch((error) => {
      composerErrorText.value = messageFromError(error)
    })
    return
  }
  void createProjectSession(projectGroupId)
}

function openSettings(): void {
  showSettings.value = true
}

function openPlugins(): void {
  showPlugins.value = true
}

function closePlugins(): void {
  showPlugins.value = false
  void refreshPluginModes()
}

function ensureRightPanelOpen(): void {
  if (!rightPinned.value) toggleRightPinned()
}

watch(pluginModes, () => {
  if (!appModes.value.some((mode) => modeKey(mode) === activeAppModeKey.value)) {
    activeAppModeKey.value = 'core:agent'
  }
})

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
    defaultModelId.value = typeof modelsResponse.default_model_id === 'string'
      ? modelsResponse.default_model_id
      : ''
  } catch {
    availableModels.value = []
    availableProviders.value = []
    defaultModelId.value = ''
  }
}

function syncThreadResizeObserver() {
  if (typeof ResizeObserver === 'undefined') return
  const element = threadScrollEl.value
  if (!element) return
  // Rebuild only when the observed element actually changed. The .thread
  // element is replaced when switching the top-level mode (v-if/v-else) or when
  // the app re-mounts it — pointing the observer at a dead old element would
  // silently kill auto-follow. Cheap guard: compare against the current
  // observer's captured element target.
  if (threadResizeObserver && threadResizeObserverTarget === element) return
  threadResizeObserver?.disconnect()
  threadResizeObserver = null
  threadResizeObserverTarget = null
  // Single unified channel: any content/size change near the bottom follows,
  // anything else is ignored by the controller's autoFollow gate.
  threadResizeObserver = new ResizeObserver(() => {
    void threadScroll.scrollToBottom()
  })
  threadResizeObserverTarget = element
  threadResizeObserver.observe(element)
  // Observe direct children (e.g. .chat-thread) — content inside them grows
  // without necessarily resizing `element` itself if the outer is the scroller.
  for (const child of Array.from(element.children)) {
    if (child instanceof HTMLElement) {
      threadResizeObserver.observe(child)
    }
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
  if (response.status === 204) return undefined as T
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

// Persist the model chosen while a session is active into that session's
// metadata (PATCH /sessions/:id) — the per-session model memory that
// restoreSessionModel() reads back on every session switch. Best-effort: a
// failed save must not undo the local selection.
watch(selectedModelId, (modelId) => {
  const sessionId = activeSessionId.value
  const session = sessions.value.find((item) => item.id === sessionId)
  if (!sessionId || !session || isPluginOwnedSession(session)) return
  const metadata: Record<string, unknown> = { ...(session.metadata || {}) }
  if (modelId) metadata.model_id = modelId
  else delete metadata.model_id
  void requestJson(`/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'PATCH',
    body: { metadata },
  })
    .then((updated) => {
      const raw = updated as RawSession
      sessions.value = sessions.value.map((item) =>
        item.id === sessionId ? { ...item, metadata: raw.metadata } : item,
      )
    })
    .catch(() => { /* best-effort persistence */ })
})

watch(messages, (newVal, oldVal) => {
  const oldIds = new Set((oldVal || []).map(m => m.id))
  const newUserMsgs = (newVal || []).filter(m => !oldIds.has(m.id) && m.role === 'user')
  if (newUserMsgs.length > 0) pendingPlaceholder.value = null
  // 滚动跟随已统一由 ResizeObserver 单一通道驱动（见 syncThreadResizeObserver），
  // 这里不再重建 observer / 隐式滚动 —— 消除历史补丁堆叠。
}, { deep: true })

watch([activeSessionId, messages, latestStatus], ([threadId]) => {
  void refreshGoal(threadId)
})

// Sync pin state from WorkspaceShell when it mounts
watch(shellRef, (shell) => {
  if (shell) {
    leftPinned.value = shell.leftPinned
    rightPinned.value = shell.rightPinned
  }
})

onMounted(() => {
  void uiPreferences.load()
  // 全窗口拖拽上传：window 级监听亮起遮罩（Tauri 需 dragDropEnabled: false 才走 HTML5 事件）
  window.addEventListener('dragover', handleWindowDragOver)
  window.addEventListener('dragleave', handleWindowDragLeave)
  window.addEventListener('drop', handleWindowDrop)
  // Ctrl+K 全局搜索（与侧边栏「搜索」同一个 SearchShell——统一入口）
  window.addEventListener('keydown', handleGlobalSearchKeydown)
  // 滚动跟随唯一通道：容器高度变化 -> 控制器 gating（易错点 5/9/10）。
  // 线程元素在顶层模式切换时会被 Vue 销毁重建（v-if/v-else），
  // 因此这里用 watch(threadScrollEl) 跟随元素生命周期重建 observer，
  // 而不是 app 生命周期一次性建立。
  watch(threadScrollEl, () => {
    syncThreadResizeObserver()
    // 元素重建后强制回到底部一次，恢复跟随意图
    threadScroll.reset()
    void threadScroll.scrollToBottom(true)
  }, { immediate: true })
  void loadInitialData().then(() => checkOnboarding())
  // 启动时静默检查更新（仅 Tauri 桌面环境，且用户未关闭「启动时自动检查更新」）
  if ((window as any).__TAURI_INTERNALS__ && readUpdateAutoCheck()) {
    void updateState.check()
  }
  // 后端进程崩溃检测（Rust 侧监视线程发 backend-crashed）→ 显示恢复横幅
  // （audit 20 S3）。浏览器环境无 Tauri API，动态 import 静默跳过。
  if ((window as any).__TAURI_INTERNALS__) {
    void import('@tauri-apps/api/event').then(({ listen }) => {
      void listen('backend-crashed', () => {
        backendCrashed.value = true
      })
    }).catch(() => {})
  }
})

onUnmounted(() => {
  window.removeEventListener('dragover', handleWindowDragOver)
  window.removeEventListener('dragleave', handleWindowDragLeave)
  window.removeEventListener('drop', handleWindowDrop)
  window.removeEventListener('keydown', handleGlobalSearchKeydown)
  threadResizeObserver?.disconnect()
  threadResizeObserver = null
  threadResizeObserverTarget = null
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

.runtime-checklist-mobile {
  display: none;
}

@media (max-width: 640px) {
  .runtime-checklist-mobile {
    display: block;
    margin-bottom: var(--space-3);
  }
}

/* ── 新版本提示条（fixed 在标题栏下方，36px = --titlebar-offset） ── */
.core-update-banner {
  position: fixed;
  top: 36px;
  left: 0;
  right: 0;
  z-index: var(--z-modal, 80);
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 16px;
  background: var(--panel);
  border-bottom: 1px solid var(--line, rgba(128, 128, 128, 0.25));
  font-size: 13px;
}
.core-update-banner-text {
  flex: 1;
  color: var(--text);
}
.core-update-banner-action {
  border: 1px solid var(--line, rgba(128, 128, 128, 0.25));
  border-radius: 6px;
  padding: 4px 12px;
  background: var(--accent, rgba(255, 255, 255, 0.08));
  color: var(--text);
  cursor: pointer;
}
.core-update-banner-close {
  border: none;
  background: none;
  color: var(--muted);
  cursor: pointer;
  font-size: 13px;
  padding: 2px 6px;
}

/* ── 全窗口拖拽上传遮罩 ── */
.attachment-drop-overlay {
  position: fixed;
  inset: 0;
  z-index: var(--z-modal, 80);
  display: grid;
  place-items: center;
  background: color-mix(in srgb, var(--theme-main-background) 88%, transparent);
  backdrop-filter: blur(3px);
}
.attachment-drop-card {
  display: grid;
  place-items: center;
  gap: 8px;
  padding: 40px 64px;
  border: 2px dashed color-mix(in srgb, var(--green) 55%, transparent);
  border-radius: 16px;
  background: color-mix(in srgb, var(--theme-main-subtle-background) 78%, transparent);
}
.attachment-drop-icon {
  color: var(--green);
}
.attachment-drop-title {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  color: var(--theme-main-text);
}
.attachment-drop-hint {
  margin: 0;
  font-size: 12px;
  color: color-mix(in srgb, var(--theme-main-text) 60%, transparent);
}

.wf-create-backdrop {
  position: fixed;
  inset: 0;
  z-index: var(--z-modal, 80);
  display: grid;
  place-items: center;
  background: rgba(0, 0, 0, 0.34);
  backdrop-filter: blur(2px);
}
.wf-create-card {
  width: 320px;
  max-width: calc(100vw - 32px);
  padding: 16px;
  border-radius: 14px;
  background: var(--theme-main-background);
  border: 1px solid var(--theme-main-border);
  box-shadow: var(--shadow);
  display: grid;
  gap: 10px;
}
.wf-create-head {
  margin: 0;
}
.wf-create-head h2 {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  color: var(--theme-main-text);
}
.wf-create-input {
  width: 100%;
  height: 30px;
  box-sizing: border-box;
  border: 1px solid var(--theme-main-border);
  border-radius: 7px;
  background: var(--theme-main-subtle-background);
  color: var(--theme-main-text);
  padding: 0 8px;
  font: inherit;
  font-size: 13px;
  outline: 0;
}
.wf-create-input:focus {
  border-color: color-mix(in srgb, var(--blue) 60%, transparent);
}
.wf-create-error {
  margin: 0;
  font-size: 11px;
  color: var(--red);
}
.wf-create-actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
}
.wf-create-actions .text-btn,
.wf-create-actions .primary-btn {
  height: 28px;
  padding: 0 12px;
  border-radius: 7px;
  border: 0;
  font-size: 12px;
  cursor: pointer;
}
.wf-create-actions .text-btn {
  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text) 65%, transparent);
}
.wf-create-actions .primary-btn {
  background: color-mix(in srgb, var(--blue) 80%, transparent);
  color: color-mix(in srgb, var(--theme-backdrop-text) 90%, transparent);
  font-weight: 600;
}
.wf-create-actions .primary-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.stage-toggle-btn {
  flex: 0 0 auto;
  width: 30px;
  height: 30px;
  border: 1px solid color-mix(in srgb, var(--theme-main-text) 12%, transparent);
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text) 65%, transparent);
  cursor: pointer;
  font-size: 14px;
  display: grid;
  place-items: center;
  transition: background 0.15s, color 0.15s;
}
.stage-toggle-btn:hover {
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), transparent);
  color: var(--text, #f2efeb);
}
.stage-toggle-btn.active {
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-active), transparent);
  color: var(--text, #f2efeb);
}

/* ── "回到最新" floating affordance ──
   Anchored to the bottom of the .thread scroll container via sticky
   positioning (the .workspace-main ancestor is itself position:fixed,
   so a fixed-positioned button would escape the content column). Stays
   below the composer (z-edge-trigger < z-composer) and follows the
   control-area surface recipe per the design spec. */
.thread-load-earlier {
  --text: var(--theme-control-text);
  width: fit-content;
  margin: var(--space-3, 12px) auto var(--space-2, 8px);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 6px 14px;
  border: 1px solid color-mix(in srgb, var(--text) 12%, transparent);
  border-radius: var(--radius-sm);
  background: var(--theme-control-background);
  color: var(--text);
  font-size: 12px;
  font-weight: 560;
  line-height: 1;
  box-shadow: var(--shadow-sm);
  cursor: pointer;
  transition: background .18s ease, transform .18s ease;
}
.thread-load-earlier:hover {
  background: color-mix(in srgb, var(--text) var(--alpha-hover, 8%), var(--theme-control-background));
}
.thread-load-earlier:active {
  background: color-mix(in srgb, var(--text) var(--alpha-active, 12%), var(--theme-control-background));
  transform: translateY(1px);
}
.thread-jump-latest {
  --text: var(--theme-control-text);
  position: sticky;
  bottom: var(--space-2, 8px);
  justify-self: center;
  z-index: var(--z-edge-trigger, 35);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: var(--space-6, 32px);
  height: var(--space-6, 32px);
  padding: 0;
  border: 1px solid color-mix(in srgb, var(--text) 12%, transparent);
  border-radius: 50%;
  background: var(--theme-control-background);
  color: var(--text);
  box-shadow: var(--shadow-sm);
  cursor: pointer;
  transition: background .18s ease, transform .18s ease;
}
.thread-jump-latest:hover {
  background: color-mix(in srgb, var(--text) var(--alpha-hover, 8%), var(--theme-control-background));
}
.thread-jump-latest:active {
  background: color-mix(in srgb, var(--text) var(--alpha-active, 12%), var(--theme-control-background));
  transform: translateY(1px);
}
/* enter from just below; leave by fading. Reduced-motion drops the slide. */
.thread-jump-latest-enter-active,
.thread-jump-latest-leave-active {
  transition: opacity .18s ease, transform .18s ease;
}
.thread-jump-latest-enter-from,
.thread-jump-latest-leave-to {
  opacity: 0;
  transform: translateY(8px);
}
@media (prefers-reduced-motion: reduce) {
  .thread-jump-latest,
  .thread-jump-latest:hover,
  .thread-jump-latest:active,
  .thread-jump-latest-enter-active,
  .thread-jump-latest-leave-active {
    transition: opacity .18s ease;
    transform: none;
  }
  .thread-jump-latest-enter-from,
  .thread-jump-latest-leave-to {
    transform: none;
  }
}

</style>
