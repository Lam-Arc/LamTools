<template>
  <TitleBar
    :left-pinned="leftPinned"
    :right-pinned="rightPinned"
    :workflow-mode="workflowMode"
    @toggle-left-pinned="toggleLeftPinned"
    @toggle-right-pinned="toggleRightPinned"
    @toggle-workflow-mode="toggleWorkflowMode"
  />
  <CoreSettings
    v-if="showSettings"
    :models="availableModels"
    :providers="availableProviders"
    :density="density"
    :theme="theme"
    :content-width="contentWidth"
    :allow-environment-import="true"
    :permission-mode="permissionMode"
    :request-rpc="requestConfigOperation"
    :workflows="settingsWorkflowList"
    :workflow-list-loading="settingsWorkflowLoading"
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
    @update-permission-mode="updatePermissionMode"
    @create-provider="createProvider"
    @update-provider="updateProvider"
    @delete-provider="deleteProvider"
@create-model="createModel"
	    @update-model="updateModel"
	    @delete-model="deleteModel"
	    @set-default-model="setDefaultModel"
    @refresh-workflows="loadSettingsWorkflows"
    @toggle-workflow-exposed="onToggleWorkflowExposed"
  />
  <CoreArrangeManager
    v-if="showArrange"
    :work-root="currentWorkRoot()"
    @back="showArrange = false"
  />
  <WorkspaceShell
    ref="shellRef"
    product-name="LamTools Core"
    sidebar-title="Core"
    :storage-key="settingsStorageKey"
    :density="density"
    :theme="theme"
    :content-width="contentWidth"
    :composer-disabled="composerDisabled"
    :composer-action-mode="composerActionMode"
    :error-text="workbenchErrorText"
    :notice-text="runtimeStatusText"
    v-model:stage-open="stageOpen"
    @new-session="openProjectCreate"
    @settings="openSettings"
    @composer-submit="submitComposer"
    @composer-drop="handleComposerDrop"
  >
    <template #sidebar-header-action>
      <div class="core-project-header-action">
        <button v-if="!workflowMode" class="icon-btn" type="button" title="新建项目" aria-label="新建项目" @click="openProjectCreate">+</button>
        <button v-else class="icon-btn" type="button" title="新建工作流" aria-label="新建工作流" @click="openWorkflowCreate">+</button>
        <CoreProjectCreate
          v-if="showProjectCreate"
          :loading="projectCreateLoading"
          :error="projectCreateError"
          :api-base="apiBase"
          @submit="createProject"
          @cancel="closeProjectCreate"
        />
        <Teleport v-if="showWorkflowCreate" defer to=".workspace-shell">
          <div class="wf-create-backdrop" @mousedown.self="closeWorkflowCreate">
            <div class="wf-create-card" role="dialog" aria-modal="true" aria-label="新建工作流">
              <header class="wf-create-head"><h2>新建工作流</h2></header>
              <input
                v-model="workflowNameDraft"
                class="wf-create-input"
                type="text"
                placeholder="工作流名称"
                autocomplete="off"
                :disabled="workflowCreateLoading"
                @keydown.enter.prevent="createWorkflowFromCard"
                @keydown.esc.prevent="closeWorkflowCreate"
              />
              <p v-if="workflowCreateError" class="wf-create-error">{{ workflowCreateError }}</p>
              <div class="wf-create-actions">
                <button type="button" class="text-btn" :disabled="workflowCreateLoading" @click="closeWorkflowCreate">取消</button>
                <button type="button" class="primary-btn" :disabled="workflowCreateLoading || !workflowNameDraft.trim()" @click="createWorkflowFromCard">
                  {{ workflowCreateLoading ? '创建中' : '创建' }}
                </button>
              </div>
            </div>
          </div>
        </Teleport>
      </div>
    </template>

    <template #sidebar-body>
      <SessionSidebar
        :project-groups="projectGroups"
        :project-session-limit="8"
        pin-storage-key="lamtools-core.sidebar.pinned-projects"
        :active-session-id="workflowMode ? (activeWorkflowName || undefined) : (activeSessionId || undefined)"
        :busy-project-ids="busyProjectIds"
        :allow-project-delete="!workflowMode"
        :allow-project-click="true"
        :allow-project-context-menu="!workflowMode"
        :allow-session-delete="!workflowMode"
        :new-session-label="workflowMode ? '新建工作流' : '新建会话'"
        @select-session="workflowMode ? selectWorkflow($event) : selectSession($event)"
        @select-project="workflowMode ? selectWorkflowProject($event) : openProjectActions($event)"
        @new-session="workflowMode ? openWorkflowCreate() : createProjectSession($event)"
        @delete-project="deleteProject"
        @project-context-menu="openProjectActions"
        @delete-session="deleteSession"
      />
    </template>

    <template #sidebar-footer>
      <button class="sidebar-action" type="button" @click="showArrange = true">
        <span aria-hidden="true">&#x25F7;</span><span>长期安排</span>
      </button>
    </template>

    <template #main-header>
      <div v-if="workflowMode" class="thread-header wf-floating-header">
        <CoreSessionTitleEditor
          :title="workflowDefinition?.name || ''"
          :session-id="workflowDefinition?.name || ''"
          :rename="renameWorkflow"
        />
        <button
          type="button"
          class="stage-toggle-btn"
          :class="{ active: canvasLocked }"
          :title="canvasLocked ? '解锁画布' : '锁定画布'"
          @click="canvasLocked = !canvasLocked"
        >
          <svg v-if="canvasLocked" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>
          <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 7.5-2"/></svg>
        </button>
      </div>
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
        >{{ stageOpen ? '▾' : '▴' }}</button>
      </div>
    </template>

    <template #main-content>
      <WorkflowCanvas
        v-if="workflowMode"
        :definition="workflowDefinition || emptyWorkflow"
        :node-states="workflowNodeStates"
        :selected-node-id="selectedNodeId || undefined"
        :available-tools="availableTools"
        :available-models="availableModels"
        :locked="canvasLocked"
        @update:definition="onWorkflowUpdate"
        @select-node="onSelectNode"
        @run-from="runFromNode"
        @run-node="runSingleNode"
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
          :typing-message-ids="typingMessageIds"
          :message-actions="true"
          @toggle-process="toggleProcess"
          @decision-select="approvalController.handleDecision"
          @fork-message="handleForkMessage"
          @rollback-message="handleRollbackMessage"
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
            @click="threadScroll.scrollToBottom(true)"
          >
            <span class="thread-jump-latest__arrow" aria-hidden="true">↓</span>
            回到最新
          </button>
        </Transition>
      </section>
    </template>

    <template #modals>
      <CoreProjectSettings
        v-if="showProjectSettings && selectedProject && !workflowMode"
        :project="{ id: selectedProject.id, name: selectedProject.name, workRoot: selectedProject.workRoot }"
        :theme="theme"
        :request-rpc="requestConfigOperation"
        :models="availableModels"
        :workflows="settingsWorkflowList"
        :workflow-list-loading="settingsWorkflowLoading"
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
        @refresh-workflows="reloadProjectSettingsWorkflows"
        @toggle-workflow-exposed="(name, exposed) => onToggleWorkflowExposed(name, exposed, selectedProject?.workRoot)"
      />
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
          :disabled="workflowMode ? false : !activeSessionId"
          :placeholder="workflowMode ? '用自然语言编辑工作流图…' : '给 Core Agent 发送任务...'"
          rows="1"
          @input="handleComposerInput"
          @click="updateComposerCursor"
          @keyup="handleComposerKeyup"
          @keydown="handleComposerKeydown"
        />
      </div>
    </template>

    <template #composer-status>
      <CoreResourceStats
        :messages="messages"
        :context-window="executionControls.activeModel.value?.context_window"
        variant="composer"
      />
    </template>

    <template #composer-tools>
      <CoreExecutionControls
        :model-value="selectedModelId"
        :thinking-mode="selectedThinkingMode"
        :shallow-thinking-enabled="shallowThinkingEnabled"
        :active-mode="activeMode"
        :mode-options="modeOptions"
        :model-options="modelOptions"
        :thinking-mode-options="thinkingModeOptions"
        shallow-label="Shallow"
        @update:model-value="executionControls.selectModel"
        @update:thinking-mode="executionControls.selectThinkingMode"
        @update:shallow-thinking-enabled="setShallowThinking"
        @update:active-mode="executionControls.selectMode"
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
      <template v-if="workflowMode">
        <div class="wf-right-panel">
          <!-- Upper half: node list -->
          <section class="wf-right-nodes">
            <h3>节点</h3>
            <ul v-if="workflowDefinition?.nodes.length" class="wf-node-list">
              <li
                v-for="n in workflowDefinition.nodes"
                :key="n.id"
                class="wf-node-list-item"
                :class="{ active: n.id === selectedNodeId }"
                @click="onSelectNode(n.id)"
              >
                <span class="wf-node-list-kind" aria-hidden="true">{{ nodeKindIcon(n.kind) }}</span>
                <span class="wf-node-list-title" :title="n.title || n.id">{{ n.title || n.id }}</span>
              </li>
            </ul>
            <p v-else class="wf-right-empty">暂无节点</p>
          </section>
          <!-- Lower half: global NL edit conversation or selected-node info -->
          <section class="wf-right-info">
            <template v-if="selectedNodeId">
              <div class="wf-right-info-head">
                <h3>{{ selectedNode?.title || selectedNodeId }}</h3>
                <button type="button" class="text-btn" title="返回对话" @click="onSelectNode(null)">✕</button>
              </div>
              <div v-if="selectedNode" class="wf-node-info-body">
                <p class="wf-node-info-row"><span>类型</span><strong>{{ selectedNode.kind }}</strong></p>
                <div v-if="selectedNode.config.instruction" class="wf-node-info-block">
                  <span>指令</span><pre>{{ String(selectedNode.config.instruction) }}</pre>
                </div>
                <div v-if="selectedNode.config.command" class="wf-node-info-block">
                  <span>命令</span><code>{{ String(selectedNode.config.command) }}</code>
                </div>
                <p v-if="selectedNode.config.model_id" class="wf-node-info-row"><span>模型</span><strong>{{ String(selectedNode.config.model_id) }}</strong></p>
                <p v-if="selectedNode.config.mode" class="wf-node-info-row"><span>模式</span><strong>{{ String(selectedNode.config.mode) }}</strong></p>
                <p class="wf-node-info-row"><span>端口</span><strong>{{ selectedNode.ports.map((p) => p.name).join(', ') || '—' }}</strong></p>
              </div>
            </template>
            <template v-else>
              <div class="wf-convo-card">
                <header class="wf-convo-head">
                  <h3>对话</h3>
                  <button type="button" class="text-btn" title="放大" @click="conversationExpanded = true">⤢</button>
                </header>
                <div class="wf-convo-body">
                  <ChatThread
                    :messages="messages"
                    :process-expanded-ids="processExpandedIds"
                    :typing-message-ids="typingMessageIds"
                    :message-actions="true"
                    @toggle-process="toggleProcess"
                    @decision-select="approvalController.handleDecision"
                    @fork-message="handleForkMessage"
                    @rollback-message="handleRollbackMessage"
                  />
                </div>
              </div>
            </template>
          </section>
        </div>
      </template>
      <Teleport v-if="workflowMode && conversationExpanded" defer to=".workspace-shell">
        <section class="wf-convo-float" role="dialog" aria-modal="false" aria-label="工作流对话">
          <header class="wf-convo-float-head">
            <h3>{{ activeWorkflowName || '工作流' }} · 对话</h3>
            <button type="button" class="text-btn" title="收起" @click="conversationExpanded = false">✕</button>
          </header>
          <div class="wf-convo-float-body">
            <ChatThread
              :messages="messages"
              :process-expanded-ids="processExpandedIds"
              :typing-message-ids="typingMessageIds"
              :message-actions="true"
              @toggle-process="toggleProcess"
              @decision-select="approvalController.handleDecision"
              @fork-message="handleForkMessage"
              @rollback-message="handleRollbackMessage"
            />
          </div>
        </section>
      </Teleport>
      <FileTreePanel
        v-else-if="stageOpen && activeProjectId"
        :project-id="activeProjectId"
        :client="projectClient"
        @open-file="openFileInStage"
      />
      <template v-else>
        <CoreResourceStats
          :messages="messages"
          :context-window="executionControls.activeModel.value?.context_window"
        />
        <RuntimePanel :step-groups="stepGroups" />
        <CoreSessionRollback
          v-if="activeSessionId"
          :key="activeSessionId"
          :session-id="activeSessionId"
          :request="requestConfigOperation"
          :active-turn="rollbackActiveTurn"
          :turn-prompts="turnPrompts"
          @restored="refreshAfterRollback"
          @graph-loaded="onCheckpointGraphLoaded"
        />
      </template>
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
  type CoreAppSnapshot,
  type CoreQueuedInput,
} from '../appServer'
import { buildCoreComposerHighlightSegments } from '../composer/inputItems'
import { buildCurrentTurnChecklistGroups } from '../runtime/checklist'
import { listArrangeJobs, updateArrangeJob } from '../durable/api'
import {
  listWorkflows,
  listGroupedWorkflows,
  getWorkflow,
  createWorkflow,
  updateWorkflow,
  deleteWorkflow,
  runWorkflow as runWorkflowApi,
  setWorkflowExposed,
  listToolNames,
} from '../workflow/api'
import type { WorkflowDef, WorkflowNodeData, NodeStateStatus } from '../workflow/types'
import {
  useCoreApprovalController,
  useCoreAutoFollowScroll,
  useCoreExecutionControlsState,
  useCoreGoals,
  useCoreLiveComposerController,
  usePendingAttachments,
  useCoreQueuedInputController,
  useCoreUiPreferences,
  useCoreWorkbenchProjectionController,
} from '../composables'

import AttachmentTray from '../components/AttachmentTray.vue'
import ChatThread from '../components/ChatThread.vue'
import WorkflowCanvas from '../components/WorkflowCanvas.vue'
import UiSelect from '../components/UiSelect.vue'
import CommandPalette from '../components/CommandPalette.vue'
import CoreExecutionControls from '../components/CoreExecutionControls.vue'
import CoreResourceStats from '../components/CoreResourceStats.vue'
import CoreQueuedInputTray from '../components/CoreQueuedInputTray.vue'
import CoreArrangeManager from '../components/CoreArrangeManager.vue'
import CoreGoalStrip from '../components/CoreGoalStrip.vue'
import StagePane from '../components/StagePane.vue'
import FileTreePanel from '../components/FileTreePanel.vue'
import type { StageResource, StageKind } from '../types'
import CoreProjectCreate from '../components/CoreProjectCreate.vue'
import CoreSessionTitleEditor from '../components/CoreSessionTitleEditor.vue'
import CoreSessionRollback from '../components/CoreSessionRollback.vue'
import CoreSettings, {
  type CoreSettingsModelPayload,
  type CoreSettingsProviderPayload,
  type WorkflowListItem,
} from '../components/CoreSettings.vue'
import CoreProjectSettings from '../components/CoreProjectSettings.vue'
import RuntimePanel from '../components/RuntimePanel.vue'
import SessionSidebar from '../components/SessionSidebar.vue'
import WorkspaceShell from '../components/WorkspaceShell.vue'
import TitleBar from '../components/TitleBar.vue'

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
const runtimeStatusText = ref('')
let runtimeStatusTimer: ReturnType<typeof setTimeout> | null = null

function setRuntimeStatus(text: string, duration = 3000) {
  if (runtimeStatusTimer) { clearTimeout(runtimeStatusTimer); runtimeStatusTimer = null }
  runtimeStatusText.value = text
  if (text) { runtimeStatusTimer = window.setTimeout(() => { runtimeStatusText.value = '' }, duration) }
}

const loadError = ref<string | null>(null)
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
const composerDisabled = computed(() => {
  if (workflowMode.value) {
    return workflowRunning.value || (!composerText.value.trim())
  }
  return composerActionMode.value === 'send' && (sendingDisabled.value || !activeSessionId.value || (!composerText.value.trim() && pendingAttachments.value.length === 0))
})

function toggleLeftPinned() {
  leftPinned.value = !leftPinned.value
  shellRef.value?.toggleLeftPinned()
}
function toggleRightPinned() {
  rightPinned.value = !rightPinned.value
  shellRef.value?.toggleRightPinned()
}
const settingsStorageKey = 'lamtools.core.ui'
const showSettings = ref(false)
const showArrange = ref(false)
const workflowMode = ref(false)
const canvasLocked = ref(false)
const workflows = ref<WorkflowDef[]>([])
const workflowGroups = ref<Record<string, WorkflowDef[]>>({})
const activeWorkflowName = ref<string>('')
const workflowDefinition = ref<WorkflowDef | null>(null)
const workflowNodeStates = ref<Record<string, NodeStateStatus>>({})
const workflowRunning = ref(false)
const workflowStatusText = ref('')
const selectedNodeId = ref<string | null>(null)
const settingsWorkflowList = ref<WorkflowDef[]>([])
const settingsWorkflowLoading = ref(false)
const showWorkflowCreate = ref(false)
const workflowCreateLoading = ref(false)
const workflowCreateError = ref('')
const workflowNameDraft = ref('')
// Available tool specs for node tool-set selection (checkbox list).
const availableTools = ref<Array<{ name: string; description: string }>>([])
// Conversation card expanded into a right-half floating window.
const conversationExpanded = ref(false)
let autosaveTimer: ReturnType<typeof setTimeout> | null = null
// Timestamp of the last save we initiated — used to suppress the file-watcher
// "workflow/changed" refetch that our own save triggers (avoids a feedback
// loop that resets dragged node positions during interaction).
let lastSelfSaveAt = 0

const emptyWorkflow: WorkflowDef = {
  name: '',
  description: '',
  nodes: [],
  edges: [],
  input_params: [],
  output_port: '',
  exposed: false,
  tool_name: '',
  work_root: '',
  map: '',
  created_at: '',
  updated_at: '',
}

const workflowSelectOptions = computed(() =>
  workflows.value.map((w) => ({ value: w.name, label: w.name + (w.exposed ? ' ◇' : '') })),
)

// --- Stage pane state ---
const stageOpen = ref(false)
const stageTabs = ref<StageResource[]>([])
const stageActiveId = ref<string | null>(null)
const stagePaneRef = ref<InstanceType<typeof StagePane> | null>(null)

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
const uiPreferences = useCoreUiPreferences(settingsStorageKey)
const { density, contentWidth, theme } = uiPreferences
const availableModels = ref<RawModel[]>([])
const availableProviders = ref<RawProvider[]>([])
const defaultModelId = ref('')
const permissionMode = ref<'read_only' | 'limited_edit' | 'full_edit'>('full_edit')
const { pendingAttachments, attachmentInputItems, addUploaded, markFailed, removeAttachment, clearAttachments } = usePendingAttachments()
const threadScrollEl = ref<HTMLElement | null>(null)
const threadScroll = useCoreAutoFollowScroll(threadScrollEl)
const COMPOSER_MAX_ROWS = 5
let threadResizeObserver: ResizeObserver | null = null
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
})
const {
  modelOptions,
  selectedModelId,
  selectedThinkingMode,
  shallowThinkingEnabled,
  thinkingModeOptions,
  activeMode,
  selectMode,
} = executionControls

const modeOptions = computed(() =>
  workflowMode.value ? [] : [
    { value: 'consider', label: 'consider' },
    { value: 'execute', label: 'execute' },
  ]
)

const latestStatus = computed(() => snapshot.value ? selectLatestTurnStatus(snapshot.value) : 'idle')
const activeTurnId = computed(() => snapshot.value ? selectLatestActiveTurnId(snapshot.value) : '')
const rollbackActiveTurn = computed(() => ['running', 'waiting'].includes(latestStatus.value))

const projectGroups = computed(() =>
  workflowMode.value ? workflowProjectGroups.value : buildCoreProjectGroups(projects.value, sessions.value),
)
// In workflow mode the sidebar shows Project → Workflows (no sessions).
const workflowProjectGroups = computed(() => {
  type WfSessionItem = {
    id: string
    title: string
    status?: string
    meta?: string
    createdAt?: string
    updatedAt?: string
  }
  type WfGroup = {
    id: string
    name: string
    workRoot?: string
    sessions: WfSessionItem[]
    canManage?: boolean
  }
  const groups: WfGroup[] = []
  for (const project of projects.value) {
    const defs = workflowGroups.value[project.workRoot] || []
    groups.push({
      id: project.id,
      name: project.name,
      workRoot: project.workRoot,
      canManage: true,
      sessions: defs.map((w) => ({
        id: w.name,
        title: w.name,
        status: w.exposed ? 'completed' : 'idle',
        meta: w.exposed ? '已暴露' : '',
        updatedAt: w.updated_at || undefined,
        createdAt: w.created_at || undefined,
      })),
    })
  }
  // Personal/global workflows land in a synthetic "个人" group.
  const globalDefs = workflowGroups.value['global'] || []
  if (globalDefs.length) {
    groups.push({
      id: 'global',
      name: '个人',
      canManage: false,
      sessions: globalDefs.map((w) => ({
        id: w.name,
        title: w.name,
        status: w.exposed ? 'completed' : 'idle',
        meta: w.exposed ? '已暴露' : '',
        updatedAt: w.updated_at || undefined,
        createdAt: w.created_at || undefined,
      })),
    })
  }
  return groups
})
const activeSessionTitle = computed(() => (
  sessions.value.find((session) => session.id === activeSessionId.value)?.title || 'Session'
))
const selectedNode = computed(() => (
  workflowDefinition.value?.nodes.find((n) => n.id === selectedNodeId.value) || null
))
// System-instruction override for workflow-mode turns: tells the agent it is
// operating on a LamTools workflow graph (not GitHub Actions etc.) and which
// tools it has for editing the graph.
const workflowModeInstructions = computed(() => {
  const name = activeWorkflowName.value || ''
  return [
    '你是 LamTools 工作流模式的助手。用户说的"workflow/工作流/建工作流"一律指画布上的工作流节点图（WorkflowDef），不是 GitHub Actions、CI 或其它外部工作流。',
    '节点类型有五种：ai、command、script、content、subgraph。',
    '- ai：AI 处理。config.mode 区分 single（单次生成）/ loop（自判断反复迭代）/ agent（多轮自主+工具）。有命名输出端口→强制 JSON 输出，端口名=字段名。指令支持 {{端口名}} 插值。',
    '- command：跑 shell 命令调用 CLI 工具（curl/git/ffmpeg 等）。config.command 是 shell 命令，用与 run_command 相同的 shell（Windows 下 Git Bash）。stdin 收 {\"inputs\":{端口名:值}} JSON，同时设 INPUT_<端口名> 环境变量。stdout 是 JSON 对象则按 key 拆到同名输出端口，否则整段放默认端口。command 图灵完备，http/file-data 一律用 command（curl/cat/jq）。',
    '- script：写 Python 代码。config.script 是纯 Python，输入端口名直接当变量用（节点 IN a、IN b → 代码里用 a、b），给输出端口名赋值即输出（OUT y → 代码里 y=...）。不要 print、不要解析 stdin（运行时把输入绑成局部变量、从局部变量读输出）。新建 script 节点会自动生成带端口变量注释的脚手架。',
    '- content：仅有输出端口，每个配常量值，不执行任何操作。用来注入常量。',
    '- subgraph：引用外部工作流。config.iterate 区分 none（调用一次）/ loop（循环到 condition 满足）/ map（遍历数组）。config.workflow_name 指定目标工作流。',
    '修饰符：condition（边级 Python 表达式，不满足该边传哨兵→下游跳过）/ transform（边上 $.field 提取子值）/ on_error（节点级 abort/fallback/skip）。',
    '每个节点有输入/输出端口，节点间通过 out→in 端口连线。一个输入端口可接多条边→聚合成数组。端口类型校验：同类型/any 通配/number→string 兼容。',
    '你可用以下工具操作当前工作流图：',
    '- workflow_graph：查看当前图的完整 JSON（含节点 id、端口、连线）。',
    '- workflow_add_node：加节点（kind/title/config/ports/position）。',
    '- workflow_connect：连线（source/source_port/target/target_port）。',
    '- workflow_delete_node：按 node_id 删节点（连带删相关连线）。',
    '- workflow_update_node：按 node_id 改节点的 title/config/ports/position。',
    '改图前先 workflow_graph 看现状，确认节点 id 和端口名后再加/连/删，避免引用不存在的 id。当前工作流名：' + (name || '（未选中）'),
  ].join('\n')
})
function nodeKindIcon(kind: string): string {
  if (kind === 'ai') return '◇'
  if (kind === 'command') return '◆'
  if (kind === 'script') return '◳'
  if (kind === 'content') return '□'
  if (kind === 'subgraph') return '⬡'
  return '◆'
}
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
    onSessionCreated: refreshSessions,
    onSessionUpdated: refreshSessions,
    createClient: ({ apiBase: frontendBase, onEvent, onSnapshot, onConnectionState }) => new CoreAppServerClient({
      url: appServerUrl(frontendBase, { path: '/api/core/app-server' }),
      clientInfo: { name: 'lamtools_core_frontend', title: 'LamTools Core Frontend', version: '0.1.0' },
      onEvent: (event) => {
        // Intercept workflow/changed broadcasts from the file watcher —
        // refetch the active workflow definition so the canvas auto-updates.
        // Skip the refetch for ~3s after our own save to avoid a feedback
        // loop that resets dragged node positions during interaction.
        if (event.method === 'workflow/changed') {
          if (Date.now() - lastSelfSaveAt < 3000) return
          if (workflowMode.value && activeWorkflowName.value) {
            const wr = (event.payload as Record<string, unknown> | undefined)?.work_root
            if (!wr || wr === (currentWorkRoot() || '')) {
              getWorkflow(activeWorkflowName.value, currentWorkRoot() || undefined)
                .then((fresh) => { workflowDefinition.value = fresh })
                .catch(() => {})
            }
          }
          return
        }
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
  queueInput: (threadId, input) => runtimeController.queueInput(threadId, input),
  listCommands: (workRoot) => runtimeController.listCommands(workRoot),
  getWorkRoot: currentWorkRoot,
  executeCommand: async (threadId, command, workRoot) => {
    await runtimeController.executeCommand(threadId, command, workRoot)
    return true
  },
  canExecuteCommand: () => latestStatus.value !== 'running' && latestStatus.value !== 'waiting',
  turnOptions: () => ({
    ...executionControls.turnOptions(),
    ...(workflowMode.value ? {
      active_mode: 'workflow',
      instructions: workflowModeInstructions.value,
    } : {}),
  }),
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

const typingMessageIds = ref(new Set<string>())
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
const workbenchErrorText = computed(() => (
  loadError.value || composerErrorText.value || approvalController.lastError.value || goalError.value
))

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
  // Workflow mode reuses Core sessions (thread id = wf_<name>) for its
  // conversation, but those shouldn't clutter the normal agent session list.
  // Filter them out unless we're actively in workflow mode.
  const visible = workflowMode.value ? loaded : loaded.filter((s) => !s.id.startsWith('wf_'))
  sessions.value = visible.map((session) => (
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
  // Load project-scoped workflows for the 工作流 section.
  void loadProjectSettingsWorkflows(project.workRoot)
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

async function loadProjectSettingsWorkflows(workRoot?: string) {
  settingsWorkflowLoading.value = true
  try {
    settingsWorkflowList.value = await listWorkflows(workRoot)
  } catch (err) {
    console.error('[project-settings] list workflows failed', err)
    settingsWorkflowList.value = []
  } finally {
    settingsWorkflowLoading.value = false
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

async function reloadProjectSettingsWorkflows() {
  const workRoot = selectedProject.value?.workRoot
  await loadProjectSettingsWorkflows(workRoot)
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

async function renameActiveSession(title: string) {
  if (!activeSessionId.value) return
  await renameSession(activeSessionId.value, title)
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
  }
  await refreshSessions()
  if (deletedActiveSession && sessions.value[0]) await selectSession(sessions.value[0].id)
}

async function selectSession(id: string) {
  activeSessionId.value = id
  restoreSessionModel(id)
  runtimeController.disconnect()
  liveComposerController.resetForThreadChange()
  composerErrorText.value = ''
  setRuntimeStatus('', 0)
  await connectLive(id)
  await liveComposerController.loadCommandCatalog(id)
  await refreshGoal(id, true)
  await threadScroll.scrollToBottom(true)
}

// Session-scoped model memory: each session remembers its own model choice,
// so switching sessions restores that session's model instead of sharing a
// single global selection. The chosen model is persisted into the session's
// metadata by the selectedModelId watcher below.
function restoreSessionModel(id: string) {
  if (id.startsWith('wf_')) return
  const session = sessions.value.find((item) => item.id === id)
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

// ── Assistant message actions: fork / roll back at a turn's checkpoint ──
const checkpointsByTurnId = ref<Record<string, string>>({})

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

async function handleForkMessage(payload: { turnId: string; content: string }) {
  const sessionId = activeSessionId.value
  const checkpointId = checkpointsByTurnId.value[payload.turnId]
  if (!sessionId || !checkpointId) {
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
  const checkpointId = checkpointsByTurnId.value[payload.turnId]
  if (!sessionId || !checkpointId) {
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

async function importEnvironmentConfig() {
  await mutateConfig('config.import_env', {}, '已从当前环境导入')
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
  } catch {
    permissionMode.value = 'full_edit'
  }
}

async function updatePermissionMode(mode: 'read_only' | 'limited_edit' | 'full_edit') {
  permissionMode.value = mode
  await requestConfigOperation('settings.update', {
    namespace: 'core.runtimeControls',
    value: { permission_mode: mode },
  })
}

async function mutateConfig(method: string, params: object, successText: string) {
  try {
    loadError.value = null
    await requestConfigOperation(method, params as Record<string, unknown>)
    await loadModelOptions()
    setRuntimeStatus(successText)
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : String(error)
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

function currentWorkRoot(): string {
  if (workflowMode.value) {
    // Workflow mode has no sessions — derive work_root from the selected project.
    const project = selectedProject.value
    if (project?.workRoot) return project.workRoot
    return ''
  }
  const session = sessions.value.find((item) => item.id === activeSessionId.value)
  const workRoot = session?.metadata?.work_root
  return typeof workRoot === 'string' ? workRoot : ''
}

// ---------------------------------------------------------------------------
// Workflow mode
// ---------------------------------------------------------------------------

async function refreshWorkflows() {
  try {
    const projectRoots = projects.value.map((p) => p.workRoot).filter(Boolean) as string[]
    workflowGroups.value = await listGroupedWorkflows(projectRoots)
    // Flattened list (global + selected project) for backward-compat selectors.
    const flat: WorkflowDef[] = []
    for (const defs of Object.values(workflowGroups.value)) flat.push(...defs)
    workflows.value = flat
  } catch (err) {
    console.error('[workflow] list failed', err)
    workflowGroups.value = {}
    workflows.value = []
  }
}

function toggleWorkflowMode() {
  workflowMode.value = !workflowMode.value
  if (workflowMode.value) {
    void refreshWorkflows()
    void loadAvailableTools()
    // Open the right panel so the node list + NL conversation are visible.
    if (!rightPinned.value) toggleRightPinned()
  } else {
    // Leaving workflow mode: drop the bound wf_* session so the agent-mode
    // sidebar (which filters wf_* out) isn't left pointing at a hidden thread.
    activeWorkflowName.value = ''
    workflowDefinition.value = null
    if (activeSessionId.value && activeSessionId.value.startsWith('wf_')) {
      activeSessionId.value = null
    }
  }
}

async function loadAvailableTools() {
  if (availableTools.value.length) return
  try {
    availableTools.value = await listToolNames()
  } catch (err) {
    console.error('[workflow] list tools failed', err)
    availableTools.value = []
  }
}

function openSettings() {
  showSettings.value = true
  void loadSettingsWorkflows()
}

async function selectWorkflow(name: string) {
  if (!name) {
    workflowDefinition.value = null
    activeWorkflowName.value = ''
    return
  }
  activeWorkflowName.value = name
  try {
    workflowDefinition.value = await getWorkflow(name, currentWorkRoot() || undefined)
    workflowNodeStates.value = {}
  } catch (err) {
    console.error('[workflow] get failed', err)
    workflowDefinition.value = null
  }
  // Reuse the normal conversation: connect a Core session thread bound to this
  // workflow so the composer + ChatThread (rendered in the right panel) show
  // the workflow's own conversation. Thread id is stable per workflow.
  await selectSession(workflowThreadId(name))
}

function workflowThreadId(name: string): string {
  const safe = name.replace(/[^a-zA-Z0-9_-]/g, '_')
  return `wf_${safe}`
}

function newWorkflow() {
  // 5C: the sidebar header "+" opens a create card instead of a random name.
  openWorkflowCreate()
}

function openWorkflowCreate() {
  workflowNameDraft.value = ''
  workflowCreateError.value = ''
  showWorkflowCreate.value = true
}

function selectWorkflowProject(projectId: string) {
  // In workflow mode, selecting a project just sets the active work_root
  // (no session-style action overlay). Workflows for that project are already
  // in workflowGroups; the sidebar re-renders from the computed.
  const project = projects.value.find((p) => p.id === projectId)
  if (!project) return
  selectedProjectId.value = project.id
}

function closeWorkflowCreate() {
  showWorkflowCreate.value = false
  workflowCreateError.value = ''
}

async function createWorkflowFromCard() {
  const name = workflowNameDraft.value.trim()
  if (!name) return
  const workRoot = currentWorkRoot() || ''
  if (!workRoot && workflowGroups.value['global'] === undefined) {
    // No project selected and no global bucket — fall back to empty work_root.
  }
  const draft: WorkflowDef = {
    ...emptyWorkflow,
    name,
    work_root: workRoot,
    nodes: [],
    edges: [],
  }
  workflowCreateLoading.value = true
  workflowCreateError.value = ''
  try {
    const saved = await createWorkflow({ ...draft, work_root: workRoot })
    workflowDefinition.value = saved
    activeWorkflowName.value = saved.name
    selectedNodeId.value = null
    workflowNodeStates.value = {}
    await refreshWorkflows()
    closeWorkflowCreate()
    setRuntimeStatus(`已创建：${saved.name}`, 2500)
  } catch (err) {
    workflowCreateError.value = `创建失败：${(err as Error).message}`
  } finally {
    workflowCreateLoading.value = false
  }
}

function onWorkflowUpdate(def: WorkflowDef) {
  workflowDefinition.value = def
  scheduleAutosave()
}

function scheduleAutosave() {
  if (autosaveTimer) clearTimeout(autosaveTimer)
  autosaveTimer = setTimeout(() => { lastSelfSaveAt = Date.now(); void saveWorkflow(true) }, 800)
}

async function renameWorkflow(title: string): Promise<void> {
  const def = workflowDefinition.value
  if (!def) return
  const oldName = def.name
  const newName = title.trim()
  if (!newName || newName === oldName) return
  const renamed = { ...def, name: newName }
  // Workflow key == file name; update_fields cannot rename. Delete the old
  // file then create the renamed one to avoid leaving a stale duplicate.
  const existed = workflows.value.some((w) => w.name === oldName)
  const workRoot = currentWorkRoot() || undefined
  try {
    if (existed && oldName) await deleteWorkflow(oldName, workRoot)
    const saved = await createWorkflow({ ...renamed, work_root: workRoot || '' })
    workflowDefinition.value = saved
    activeWorkflowName.value = saved.name
    await refreshWorkflows()
    setRuntimeStatus(`已重命名：${saved.name}`, 2500)
  } catch (err) {
    console.error('[workflow] rename failed', err)
    setRuntimeStatus(`重命名失败：${(err as Error).message}`, 4000)
    throw err
  }
}

function onSelectNode(id: string | null) {
  selectedNodeId.value = id
}

async function runFromNode(nodeId: string) {
  await executeWorkflowRun(undefined, { startNode: nodeId })
}

async function runSingleNode(nodeId: string) {
  await executeWorkflowRun(undefined, { singleNode: nodeId })
}

async function saveWorkflow(silent = false) {
  const def = workflowDefinition.value
  if (!def) return
  const workRoot = currentWorkRoot() || undefined
  try {
    const saved = await (def.name && workflows.value.some((w) => w.name === def.name)
      ? updateWorkflow(def.name, {
          description: def.description,
          nodes: def.nodes as unknown as Record<string, unknown>[],
          edges: def.edges as unknown as Record<string, unknown>[],
          input_params: def.input_params as unknown as Record<string, unknown>[],
          output_port: def.output_port,
          exposed: def.exposed,
          tool_name: def.tool_name,
        }, workRoot)
      : createWorkflow({
          ...def,
          work_root: workRoot || '',
        }))
    workflowDefinition.value = saved
    activeWorkflowName.value = saved.name
    await refreshWorkflows()
    if (!silent) setRuntimeStatus(`已保存：${saved.name}`, 2500)
  } catch (err) {
    console.error('[workflow] save failed', err)
    if (!silent) setRuntimeStatus(`保存失败：${(err as Error).message}`, 4000)
  }
}

async function runWorkflow() {
  await executeWorkflowRun(undefined)
}

async function stepWorkflow() {
  await executeWorkflowRun(1)
}

async function executeWorkflowRun(maxSteps: number | undefined, options: { startNode?: string; singleNode?: string } = {}) {
  const def = workflowDefinition.value
  if (!def || !def.name) {
    setRuntimeStatus('先保存工作流再运行', 3000)
    return
  }
  workflowRunning.value = true
  workflowStatusText.value = options.singleNode ? '运行节点…' : options.startNode ? '从此节点运行…' : '运行中…'
  // Mark all nodes idle before running.
  workflowNodeStates.value = def.nodes.reduce(
    (acc, n) => ({ ...acc, [n.id]: 'idle' as NodeStateStatus }),
    {},
  )
  try {
    const result = await runWorkflowApi(def.name, {
      workRoot: currentWorkRoot() || undefined,
      maxSteps,
      startNode: options.startNode,
      singleNode: options.singleNode,
    })
    const states = result.run.node_states || {}
    const mapped: Record<string, NodeStateStatus> = {}
    for (const [nid, s] of Object.entries(states)) {
      const status = (s as { status?: NodeStateStatus } | undefined)?.status
      mapped[nid] = status ?? 'idle'
    }
    workflowNodeStates.value = mapped
    if (result.run.status === 'paused') {
      workflowStatusText.value = '已暂停（单步）'
    } else if (result.run.status === 'completed') {
      workflowStatusText.value = '完成'
    } else {
      workflowStatusText.value = result.run.status
    }
  } catch (err) {
    console.error('[workflow] run failed', err)
    workflowStatusText.value = `运行失败：${(err as Error).message}`
  } finally {
    workflowRunning.value = false
  }
}

async function toggleExpose() {
  const def = workflowDefinition.value
  if (!def) return
  try {
    const updated = await setWorkflowExposed(
      def.name,
      !def.exposed,
      currentWorkRoot() || undefined,
    )
    workflowDefinition.value = updated
    await refreshWorkflows()
    setRuntimeStatus(updated.exposed ? `已暴露：${updated.tool_name || 'workflow_' + updated.name}` : '已取消暴露', 2500)
  } catch (err) {
    console.error('[workflow] expose failed', err)
    setRuntimeStatus(`操作失败：${(err as Error).message}`, 4000)
  }
}

async function loadSettingsWorkflows() {
  settingsWorkflowLoading.value = true
  try {
    settingsWorkflowList.value = await listWorkflows(currentWorkRoot() || undefined)
  } catch (err) {
    console.error('[workflow] settings list failed', err)
    settingsWorkflowList.value = []
  } finally {
    settingsWorkflowLoading.value = false
  }
}

async function onToggleWorkflowExposed(name: string, exposed: boolean, workRootOverride?: string) {
  try {
    const workRoot = workRootOverride ?? (currentWorkRoot() || undefined)
    await setWorkflowExposed(name, exposed, workRoot)
    if (workRootOverride !== undefined) {
      await loadProjectSettingsWorkflows(workRootOverride)
    } else {
      await loadSettingsWorkflows()
    }
  } catch (err) {
    console.error('[workflow] settings toggle expose failed', err)
  }
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
  // One-shot setup: the observer callback already scrolls to bottom on every
  // content height change, so per-message watchers no longer need to scroll.
  // Per-frame re-observation is pointless — the observer instance and its
  // targets persist for the lifetime of the app.
  if (threadResizeObserver) return
  threadResizeObserver = new ResizeObserver(() => {
    void threadScroll.scrollToBottom()
  })
  const element = threadScrollEl.value
  if (!element) return
  threadResizeObserver.observe(element)
  // Ensure direct children of .thread are observed (e.g. .chat-thread).
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
  if (!sessionId || sessionId.startsWith('wf_')) return
  const session = sessions.value.find((item) => item.id === sessionId)
  if (!session) return
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

watch(messages, async (newVal, oldVal) => {
  const oldIds = new Set((oldVal || []).map(m => m.id))
  const newUserMsgs = (newVal || []).filter(m => !oldIds.has(m.id) && m.role === 'user')
  for (const msg of newUserMsgs) {
    typingMessageIds.value.add(msg.id)
    pendingPlaceholder.value = null
  }
  syncThreadResizeObserver()
}, { deep: true })

watch([activeSessionId, messages, latestStatus], ([threadId]) => {
  void refreshGoal(threadId)
})

// Workflow mode: the agent edits the graph via build tools (workflow_add_node
// etc.) during a turn. Each tool result lands in the message stream, so when
// messages change we debounce-reload the workflow definition — the canvas
// updates in near-realtime as the agent edits. We also reload when the turn
// finishes (status leaves running/waiting): the agent's last batch of edits
// often lands right as the turn ends, and without this final reload the canvas
// would stay frozen on the pre-turn graph ("暂无节点" after a build turn).
let graphReloadTimer: ReturnType<typeof setTimeout> | null = null
let prevStatus = ''
function reloadWorkflowGraph() {
  if (!workflowMode.value || !activeWorkflowName.value) return
  if (graphReloadTimer) clearTimeout(graphReloadTimer)
  graphReloadTimer = setTimeout(() => {
    void (async () => {
      try {
        const fresh = await getWorkflow(activeWorkflowName.value, currentWorkRoot() || undefined)
        workflowDefinition.value = fresh
      } catch (err) {
        console.error('[workflow] live graph reload failed', err)
      }
    })()
  }, 400)
}
watch(() => messages.value.length, () => {
  // Reload on each new message while a turn is active (live edit streaming).
  if (latestStatus.value === 'running' || latestStatus.value === 'waiting') {
    reloadWorkflowGraph()
  }
})
// Final reload when the turn transitions out of running/waiting — catches the
// last edits that arrived as the turn ended (the message-stream watcher above
// would have skipped them because status already flipped to done/idle).
watch(latestStatus, (status, prev) => {
  if (!workflowMode.value || !activeWorkflowName.value) return
  if (prev && (prev === 'running' || prev === 'waiting') && prev !== status) {
    reloadWorkflowGraph()
  }
  prevStatus = status
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
  color: var(--muted);
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
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 8px;
  background: transparent;
  color: var(--muted, #888);
  cursor: pointer;
  font-size: 14px;
  display: grid;
  place-items: center;
  transition: background 0.15s, color 0.15s;
}
.stage-toggle-btn:hover {
  background: rgba(255,255,255,0.06);
  color: var(--text, #f2efeb);
}
.stage-toggle-btn.active {
  background: rgba(255,255,255,0.08);
  color: var(--text, #f2efeb);
}

/* Workflow mode */
.thread-header .wf-mode-label {
  font-size: 13px;
  font-weight: 650;
  color: var(--text);
  opacity: 0.85;
  letter-spacing: -0.02em;
  margin-right: 4px;
}
.thread-header:has(.wf-mode-label) {
  gap: 8px;
}

/* Workflow mode: the whole main area is the canvas; the thin title floats
   over it transparently (no card chrome) instead of taking vertical space. */
.wf-floating-header {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  z-index: var(--z-popover, 60);
  pointer-events: auto;
  background: transparent;
  border: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 16px;
}

/* ---- Workflow right panel (Phase 5E) ---- */
.wf-right-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
.wf-right-panel > section {
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.wf-right-panel > section > h3 {
  margin: 0 0 8px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: color-mix(in srgb, var(--theme-main-text, #f2efeb) 50%, transparent);
}
.wf-right-nodes {
  flex: 0 0 auto;
  max-height: 45%;
  padding: 12px;
  border-bottom: 1px solid var(--theme-main-border);
  overflow: auto;
}
.wf-node-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 2px;
}
.wf-node-list-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 8px;
  border-radius: 7px;
  cursor: pointer;
  font-size: 13px;
  color: var(--theme-main-text);
  transition: background 0.12s;
}
.wf-node-list-item:hover {
  background: var(--theme-main-soft-background);
}
.wf-node-list-item.active {
  background: color-mix(in srgb, var(--blue) 22%, transparent);
}
.wf-node-list-kind {
  opacity: 0.7;
  font-size: 12px;
}
.wf-node-list-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.wf-right-info {
  flex: 1 1 auto;
  padding: 12px;
  overflow: auto;
}

/* Conversation card in the right panel */
.wf-convo-card {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  border-radius: 12px;
  background: var(--theme-main-background);
  border: 1px solid var(--theme-main-border);
  overflow: hidden;
}
.wf-convo-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 10px;
  border-bottom: 1px solid var(--theme-main-border);
}
.wf-convo-head h3 {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
}
.wf-convo-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding: 8px;
}

/* Right-half floating window */
/* Centered floating conversation card (no full-screen overlay; the canvas
   and composer remain interactive). 0.8 opacity so the graph stays visible. */
.wf-convo-float {
  position: fixed;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  z-index: var(--z-modal, 80);
  width: min(640px, 70vw);
  height: min(560px, 76vh);
  display: flex;
  flex-direction: column;
  background: var(--theme-main-background);
  border: 1px solid var(--theme-main-border);
  border-radius: 16px;
  box-shadow: var(--shadow);
  pointer-events: auto;
}
.wf-convo-float-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--theme-main-border);
}
.wf-convo-float-head h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
}
.wf-convo-float-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding: 16px;
}
.wf-right-info-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.wf-right-info-head h3 {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
}
.wf-right-empty {
  margin: 0;
  font-size: 12px;
  color: color-mix(in srgb, var(--theme-main-text) 40%, transparent);
}
.wf-node-info-body {
  display: grid;
  gap: 8px;
  font-size: 12px;
}
.wf-node-info-row {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  margin: 0;
}
.wf-node-info-row > span {
  color: color-mix(in srgb, var(--theme-main-text) 50%, transparent);
}
.wf-node-info-block {
  margin: 0;
  display: grid;
  gap: 4px;
}
.wf-node-info-block > span {
  color: color-mix(in srgb, var(--theme-main-text) 50%, transparent);
}
.wf-node-info-block pre {
  margin: 0;
  padding: 8px;
  border-radius: 7px;
  background: var(--theme-main-subtle-background);
  font-size: 11px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 160px;
  overflow: auto;
}
.wf-node-info-block code {
  font-size: 11px;
  word-break: break-all;
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
.thread-jump-latest:hover {
  background: color-mix(in srgb, var(--text) var(--alpha-hover, 8%), var(--theme-control-background));
}
.thread-jump-latest:active {
  background: color-mix(in srgb, var(--text) var(--alpha-active, 12%), var(--theme-control-background));
  transform: translateY(1px);
}
.thread-jump-latest__arrow {
  font-size: 13px;
  line-height: 1;
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
