<template>
  <div
    class="workflow-view"
    data-plugin-mode="workflow"
    :data-workflow-running="workflowRunning ? 'true' : 'false'"
  >
    <WorkflowCanvas
      :definition="workflowDefinition || emptyWorkflow"
      :node-states="workflowNodeStates"
      :node-state-details="workflowRun?.node_states || {}"
      :timeline="workflowTimeline"
      :human-tasks="humanTasks"
      :selected-human-task="selectedHumanTask"
      :human-task-loading="humanTaskLoading"
      :human-task-busy="humanTaskBusy"
      :human-task-error="humanTaskError"
      :on-refresh-human-tasks="refreshHumanTasks"
      :on-select-human-task="selectHumanTask"
      :on-complete-human-task="completeHumanTask"
      :selected-node-id="selectedNodeId || undefined"
      :available-tools="availableTools"
      :available-models="availableModels"
      :node-schemas="nodeSchemas"
      :locked="chat.activeTurnRunning.value"
      @update:definition="onWorkflowUpdate"
      @select-node="onSelectNode"
      @run-from="runFromNode"
      @run-node="runSingleNode"
    >
      <template #controls>
        <WorkflowControlBar
          :running="workflowRunning"
          :status-text="workflowStatusText"
          :dirty="workflowDirty"
          :save-error="workflowSaveErrorMessage"
          :conflict="workflowConflictMessage"
          :can-undo="workflowDocumentState?.canUndo"
          :can-redo="workflowDocumentState?.canRedo"
          @run="runWorkflow"
          @step="stepWorkflow"
          @save="saveWorkflow"
          @undo="undoWorkflow"
          @redo="redoWorkflow"
          @cancel="cancelWorkflowRun"
          @accept-remote="acceptRemoteWorkflow"
          @keep-local="keepLocalAndRetryWorkflow"
        />
      </template>
    </WorkflowCanvas>
    <div v-if="workflowSwitchGuard" class="wf-switch-guard" role="dialog" aria-modal="true" aria-labelledby="wf-switch-guard-title">
      <div class="wf-switch-guard-card">
        <h2 id="wf-switch-guard-title">工作流有未保存修改</h2>
        <p>切换前要如何处理当前草稿？</p>
        <div class="wf-switch-guard-actions">
          <button type="button" class="text-btn" @click="resolveWorkflowSwitch('cancel')">取消</button>
          <button type="button" class="text-btn" @click="resolveWorkflowSwitch('discard')">放弃修改</button>
          <button type="button" class="primary-btn" @click="resolveWorkflowSwitch('save')">保存并切换</button>
        </div>
      </div>
    </div>
  </div>

  <Teleport v-if="workflowDefinition" defer to=".workspace-plugin-header">
    <div class="thread-header wf-floating-header" data-workflow-header>
      <div class="wf-header-title">
        <CoreSessionTitleEditor
          :title="workflowDefinition.name"
          :session-id="workflowSessionId(workflowDefinition)"
          :rename="renameWorkflow"
        />
      </div>
    </div>
  </Teleport>

  <Teleport v-if="workflowTabs.length > 1" defer to="[data-titlebar-workflow-tabs]">
    <nav class="wf-workflow-tabs" role="tablist" aria-label="打开的工作流">
      <button
        v-for="tab in workflowTabs"
        :key="tab.id"
        type="button"
        class="wf-workflow-tab"
        :class="{ active: tab.id === activeWorkflowId }"
        role="tab"
        :aria-selected="tab.id === activeWorkflowId ? 'true' : 'false'"
        :tabindex="tab.id === activeWorkflowId ? 0 : -1"
        @click="selectWorkflow(tab.id)"
      >
        <span class="wf-workflow-tab-title">{{ tab.name || '未命名工作流' }}</span>
        <span v-if="tab.dirty" class="wf-workflow-tab-dirty" aria-label="有未保存修改">
          <CircleDotDashed :size="9" :stroke-width="2" aria-hidden="true" />
        </span>
        <span
          class="wf-workflow-tab-close"
          role="button"
          tabindex="0"
          aria-label="关闭工作流标签"
          @click.stop="closeWorkflowTab(tab.id)"
          @keydown.enter.stop.prevent="closeWorkflowTab(tab.id)"
          @keydown.space.stop.prevent="closeWorkflowTab(tab.id)"
        >
          <X :size="13" :stroke-width="1.8" aria-hidden="true" />
        </span>
      </button>
    </nav>
  </Teleport>

  <Teleport v-if="workflowDefinition" defer to=".workspace-plugin-modal">
    <section
      class="wf-convo-float"
      :class="{ 'is-pinned': conversationExpanded }"
      data-workflow-conversation
      role="region"
      aria-label="工作流对话"
    >
      <header class="wf-convo-float-head">
        <h3>{{ workflowDefinition?.name || '工作流' }} · 对话</h3>
        <button type="button" class="text-btn" title="收起" @click="conversationExpanded = false">
          <X :size="14" :stroke-width="1.8" aria-hidden="true" />
        </button>
      </header>
      <div class="wf-convo-float-body thread">
        <ChatThread
          :messages="chat.messages.value"
          :process-expanded-ids="chat.processExpandedIds.value"
          :message-actions="true"
          :transport="transport"
          :project-id="activeProjectId ?? selectedProjectId"
          :work-root="activeProject?.workRoot"
          :active-turn-id="chat.activeTurnId.value"
          :turn-active="chat.activeTurnRunning.value"
          :locked-message-ids="chat.lockedMessageIds.value"
          @toggle-process="chat.toggleProcess"
          @decision-select="chat.onDecisionSelect"
          @fork-message="chat.onForkMessage"
          @rollback-message="chat.onRollbackMessage"
          @edit-message="chat.onEditMessage"
        />
      </div>
    </section>
  </Teleport>

  <Teleport v-if="showWorkflowCreate" defer to=".workspace-plugin-modal">
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
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { CircleDotDashed, X } from 'lucide-vue-next'
import type { CoreAppEvent } from '../../../../../../ui/src/appServer'
import type { ProjectGroup, SessionItem } from '../../../../../../ui/src/components/SessionSidebar.vue'
import type { PluginModeSurface } from '../../../../../../ui/src/plugins/context'
import type { RightSidebarPluginContribution } from '../../../../../../ui/src/right-sidebar/types'
import { useCorePluginModeContext, usePluginModeRuntime } from '../../../../../../ui/src/plugins/context'
import {
  normalizeNodeStateStatus,
  normalizeWorkflowRunStatus,
  type NodeStateStatus,
  type WorkflowDef,
  type WorkflowNode,
  type WorkflowNodeSchema,
  type WorkflowNodeState,
  type WorkflowQueueItem,
  type WorkflowActivation,
  type WorkflowRunResult,
  type WorkflowRunTimelineItem,
  type WorkflowHumanTask,
} from './types'
import {
  createWorkflowApi,
  isWorkflowRevisionConflict,
  normalizeWorkflowNodeState,
  normalizeWorkflowRunResponse,
  normalizeWorkflowRunResult,
  type WorkflowApi,
  type WorkflowContinuationState,
} from './api'
import {
  createWorkflowDocument,
  type WorkflowDocumentController,
  type WorkflowDocumentSnapshot,
} from './document'
import { createWorkflowNodeFromSchema } from './catalog'
import {
  downloadJson,
  downloadWorkflowJson,
  normalizeImportedWorkflow,
  WORKFLOW_TEMPLATES,
  type WorkflowExportFormat,
  type WorkflowImportSource,
  type WorkflowTemplate,
} from './resources'
import {
  mergeWorkflowCanvasSidecar,
  writeWorkflowCanvasSidecar,
} from './canvas'
import WorkflowCanvas from './WorkflowCanvas.vue'
import WorkflowControlBar from './WorkflowControlBar.vue'
import WorkflowInspector from './WorkflowInspector.vue'
import ChatThread from '../../../../../../ui/src/components/ChatThread.vue'
import CoreSessionTitleEditor from '../../../../../../ui/src/components/CoreSessionTitleEditor.vue'

const props = withDefaults(defineProps<{
  pluginId?: string
  modeId?: string
}>(), {
  pluginId: 'workflow',
  modeId: 'workflow',
})

const context = useCorePluginModeContext()
const modeRuntime = usePluginModeRuntime()
const workflowApi: WorkflowApi = createWorkflowApi(context.requestRpc)

const {
  transport,
  projects,
  selectedProjectId,
  selectedProject,
  activeProjectId,
  activeProject,
  setSelectedProjectId,
  selectSession,
  refreshSessions,
  setRuntimeStatus,
  availableModels,
  selectedModelId,
  permissionPreset,
  composerText,
  ensureRightPanelOpen,
  lastEvent,
  chat,
} = context

const workflows = ref<WorkflowDef[]>([])
const workflowGroups = ref<Record<string, WorkflowDef[]>>({})
const activeWorkflowId = ref('')
const workflowDefinition = ref<WorkflowDef | null>(null)
const openWorkflowIds = ref<string[]>([])
const workflowNodeStates = ref<Record<string, NodeStateStatus>>({})
const workflowRun = ref<WorkflowRunResult | null>(null)
const workflowContinuation = ref<WorkflowContinuationState | undefined>(undefined)
const workflowTimeline = ref<WorkflowRunTimelineItem[]>([])
const workflowDocumentState = ref<WorkflowDocumentSnapshot | null>(null)
const selectedNodeId = ref<string | null>(null)
const selectedNode = computed<WorkflowNode | null>(() => (
  workflowDefinition.value?.nodes.find((node) => node.id === selectedNodeId.value) || null
))
const availableTools = ref<Array<{ name: string; description: string }>>([])
const nodeSchemas = ref<Record<string, WorkflowNodeSchema>>({})
const queueItems = ref<WorkflowQueueItem[]>([])
const historyItems = ref<WorkflowQueueItem[]>([])
const selectedQueueItem = ref<WorkflowQueueItem | null>(null)
const humanTasks = ref<WorkflowHumanTask[]>([])
const selectedHumanTask = ref<WorkflowHumanTask | null>(null)
const humanTaskLoading = ref(false)
const humanTaskBusy = ref(false)
const humanTaskError = ref('')
const activations = ref<WorkflowActivation[]>([])
const activationsLoading = ref(false)
const activationBusy = ref(false)
const queueLoading = ref(false)
const workflowRunning = ref(false)
const workflowStatusText = ref('')
const activeRunId = ref('')
const conversationExpanded = ref(false)
const showWorkflowCreate = ref(false)
const workflowCreateLoading = ref(false)
const workflowCreateError = ref('')
const workflowNameDraft = ref('')
let workflowDocument: WorkflowDocumentController | null = null
let unsubscribeWorkflowDocument: (() => void) | null = null
const workflowDocuments = new Map<string, WorkflowDocumentController>()
let workflowDocumentKey = ''
const workflowSwitchGuard = ref<{ targetId: string } | null>(null)
let workflowSwitchResolver: ((choice: 'save' | 'discard' | 'cancel') => void) | null = null
let autosaveTimer: ReturnType<typeof setTimeout> | null = null
let graphReloadTimer: ReturnType<typeof setTimeout> | null = null
let queueRefreshTimer: ReturnType<typeof setInterval> | null = null
let lastSelfSaveAt = 0

const workflowDirty = computed(() => workflowDocumentState.value?.dirty === true)
const workflowSaveErrorMessage = computed(() => workflowDocumentState.value?.saveError?.message || '')
const workflowConflictMessage = computed(() => workflowDocumentState.value?.conflict?.message || '')
const workflowNodeStateEntries = computed<WorkflowNodeState[]>(() => Object.values(workflowRun.value?.node_states || {}))
const workflowTabs = computed(() => openWorkflowIds.value.flatMap((id) => {
  const definition = workflows.value.find((item) => item.id === id)
    || (id === activeWorkflowId.value ? workflowDefinition.value : null)
  if (!definition) return []
  const document = workflowDocuments.get(id)
  return [{ id, name: document?.snapshot().definition.name || definition.name, dirty: document?.snapshot().dirty === true }]
}))

const emptyWorkflow: WorkflowDef = {
  id: '',
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

const workflowModeInstructions = computed(() => {
  const name = workflowDefinition.value?.name || ''
  return [
    '你是 LamTools 工作流模式的助手。用户说的"workflow/工作流/建工作流"一律指画布上的工作流节点图（WorkflowDef），不是 GitHub Actions、CI 或其它外部工作流。',
    '节点类型由后端 object_info 注册表动态提供，目录按 category 分组并支持搜索；常用类型包括 model、agent、command、python、constant、input、output、template、condition、merge、join、subgraph。',
    '- model：独立的模型推理节点，config.instruction 是指令，config.model_id 选择模型；不再用旧 ai 的 mode 复用 Agent。',
    '- agent：独立的 Agent 执行节点，config.instruction 是目标，config.model_id 选择模型，config.tools/allowed_tools 选择工具。',
    '创建 model 或 agent 节点时必须填写 config.model_id；用户未指定时使用当前会话模型，后端也会以当前会话模型兜底。',
    '- command：跑 shell 命令调用 CLI 工具（curl/git/ffmpeg 等）。config.command 是 shell 命令，用与 run_command 相同的 shell（Windows 下 Git Bash）。stdin 收 {"inputs":{端口名:值}} JSON，同时设 INPUT_<端口名> 环境变量。stdout 是 JSON 对象则按 key 拆到同名输出端口，否则整段放默认端口。',
    '- python：写 Python 代码。config.script 是纯 Python，输入端口名直接当变量用，给输出端口名赋值即输出；旧 script 节点继续兼容。',
    '- constant：仅有输出端口，每个端口保存常量值；旧 content 节点继续兼容。',
    '- subgraph：引用外部工作流；config.workflow_name 指定目标工作流，iterate 可为 none/loop/map。',
    '- ai：仅作为旧工作流兼容类型保留，不作为新建节点的默认选择；旧节点仍可渲染、编辑和运行。',
    '其它节点由注册表 schema 定义输入/输出与配置。边级 condition/transform 和节点级 on_error 是可选执行修饰符。',
    '每个节点有输入/输出端口，节点间通过 out→in 端口连线。一个输入端口可接多条边→聚合成数组。端口类型校验：同类型/any 通配/number→string 兼容。',
    '你可用以下工具操作当前工作流图：',
    '- workflow_graph：查看当前图的语义化 JSON（含节点参数、位置、稳定端口 id 和连线修饰符）。',
    '- workflow_add_node：加节点（kind/title/config/ports/position）。',
    '- workflow_connect：连线（优先 source_port_id/target_port_id，端口名仅作兼容回退）。',
    '- workflow_delete_node：按 node_id 删节点（连带删相关连线）。',
    '- workflow_update_node：按 node_id 改节点的 title/config/ports/position。',
    '改图前先 workflow_graph 看现状，确认节点与稳定端口 id 后再加/连/删，避免引用不存在的 id。当前工作流名：' + (name || '（未选中）'),
  ].join('\n')
})

const workflowRightSidebar = computed<RightSidebarPluginContribution[]>(() => {
  const definition = workflowDefinition.value
  if (!definition) return []
  return [{
    id: 'workflow-inspector',
    title: '工作流检查器',
    order: 5,
    defaultVisible: true,
    defaultCollapsed: false,
    component: WorkflowInspector,
    componentProps: {
      workflowDefinition: definition,
      selectedNodeId: selectedNodeId.value,
      selectedNode: selectedNode.value,
      workflowRun: workflowRun.value,
      workflowNodeStateEntries: workflowNodeStateEntries.value,
      nodeSchemas: nodeSchemas.value,
      workflowRunning: workflowRunning.value,
      queueItems: queueItems.value,
      historyItems: historyItems.value,
      selectedQueueItem: selectedQueueItem.value,
      queueLoading: queueLoading.value,
      activations: activations.value,
      activationsLoading: activationsLoading.value,
      activationBusy: activationBusy.value,
      templates: WORKFLOW_TEMPLATES,
      chat,
      transport,
      projectId: activeProjectId.value ?? selectedProjectId.value,
      workRoot: activeProject.value?.workRoot || workflowRoot(definition) || null,
      onSelectNode,
      onExpandConversation: () => { conversationExpanded.value = true },
      onAddNode: addNodeFromCatalog,
      onRunWithInputs: runWorkflowWithInputs,
      onRefreshQueue: refreshQueue,
      onEnqueueWorkflow: enqueueWorkflow,
      onCancelQueuedRun: cancelQueuedRun,
      onInspectQueuedRun: inspectQueuedRun,
      onClearQueue: clearWorkflowQueue,
      onImportWorkflow: importWorkflowDefinition,
      onExportWorkflow: exportWorkflowDefinition,
      onUseTemplate: useWorkflowTemplate,
      onToggleExpose: toggleExpose,
      onUpdateDefinition: onWorkflowUpdate,
      onRefreshActivations: refreshWorkflowActivations,
      onActivateTrigger: activateWorkflowTrigger,
      onDeactivateTrigger: deactivateWorkflowTrigger,
      humanTasks: humanTasks.value,
      selectedHumanTask: selectedHumanTask.value,
      humanTaskLoading: humanTaskLoading.value,
      humanTaskBusy: humanTaskBusy.value,
      humanTaskError: humanTaskError.value,
      onRefreshHumanTasks: refreshHumanTasks,
      onSelectHumanTask: selectHumanTask,
      onCompleteHumanTask: completeHumanTask,
    },
  }]
})

const workflowProjectGroups = computed<ProjectGroup[]>(() => {
  const groups: ProjectGroup[] = projects.value.map((project) => ({
    id: project.id,
    name: project.name,
    workRoot: project.workRoot,
    canManage: true,
    sessions: (workflowGroups.value[project.workRoot] || []).map(workflowSessionItem),
  }))
  const globalDefinitions = workflowGroups.value.global || []
  if (globalDefinitions.length) {
    groups.push({
      id: 'global',
      name: '个人',
      canManage: false,
      sessions: globalDefinitions.map(workflowSessionItem),
    })
  }
  return groups
})

const activeWorkflow = computed(() => (
  workflows.value.find((item) => item.id === activeWorkflowId.value)
    || workflowDefinition.value
    || null
))

const workflowSurface: PluginModeSurface = {
  composerPlaceholder: '用自然语言编辑工作流图…',
  // Empty input disables only submission; the composer itself remains
  // editable so the Workflow pill can expand on focus and accept a prompt.
  composerDisabled: computed(() => workflowRunning.value || !activeWorkflowId.value),
  turnOptions: () => ({
    active_mode: 'workflow:workflow',
    instructions: workflowModeInstructions.value,
    // Bind the turn to the selected workflow's actual repository scope. The
    // session may predate plugin metadata repair and otherwise inherit the
    // currently selected project (or a stale default) instead.
    work_root: workflowRoot(activeWorkflow.value) || '',
  }),
  rightSidebar: workflowRightSidebar,
  sidebar: {
    groups: workflowProjectGroups,
    hasProjects: computed(() => workflowProjectGroups.value.length > 0),
    activeSessionId: computed(() => activeWorkflowId.value || undefined),
    primaryActionLabel: '新建工作流',
    onPrimaryAction: openWorkflowCreate,
    allowProjectNewSession: true,
    allowProjectDelete: false,
    allowSessionDelete: false,
    allowSessionContextMenu: false,
    allowProjectClick: true,
    allowProjectContextMenu: false,
    newSessionLabel: '新建工作流',
    onSelectSession: selectWorkflow,
    onSelectProject: selectWorkflowProject,
    onNewSession: (projectGroupId) => {
      if (projectGroupId && projectGroupId !== 'global') setSelectedProjectId(projectGroupId)
      openWorkflowCreate()
    },
  },
}

const unregisterSurface = modeRuntime.register(`${props.pluginId}:${props.modeId}`, workflowSurface)

function workflowSessionItem(definition: WorkflowDef): SessionItem {
  return {
    id: definition.id,
    title: definition.name,
    status: definition.exposed ? 'completed' : 'idle',
    meta: definition.exposed ? '已暴露' : '',
    createdAt: definition.created_at || undefined,
    updatedAt: definition.updated_at || undefined,
    metadata: {
      owner_plugin: 'workflow',
      resource_type: 'workflow',
      resource_id: definition.id,
      ...(definition.work_root ? { work_root: definition.work_root } : {}),
    },
  }
}

function workflowRoot(definition?: WorkflowDef | null): string | undefined {
  const root = definition ? definition.work_root : (selectedProject.value?.workRoot || '')
  return root || undefined
}

function workflowSessionId(definition: WorkflowDef): string {
  return `workflow:${definition.id}`
}

function attachWorkflowDocument(definition: WorkflowDef): void {
  unsubscribeWorkflowDocument?.()
  const hydrated = hydrateWorkflowDefinition(definition)
  const key = hydrated.id || definition.id
  workflowDocument = (key && workflowDocuments.get(key)) || createWorkflowDocument(hydrated)
  if (key) workflowDocuments.set(key, workflowDocument)
  workflowDocumentKey = key
  unsubscribeWorkflowDocument = workflowDocument.subscribe((snapshot) => {
    if (workflowDocumentKey !== key || activeWorkflowId.value !== key) return
    workflowDocumentState.value = snapshot
    workflowDefinition.value = snapshot.definition
    if (snapshot.definition.id) writeWorkflowCanvasSidecar(snapshot.definition.id, snapshot.definition.canvas_elements ?? [])
  })
}

function hydrateWorkflowDefinition(definition: WorkflowDef): WorkflowDef {
  // Canonical V2 already contains canvas data. The local sidecar exists only
  // for legacy hosts and must not override an intentionally empty V2 canvas.
  return definition.document ? definition : mergeWorkflowCanvasSidecar(definition)
}

function rememberOpenWorkflow(workflowId: string): void {
  if (!workflowId || openWorkflowIds.value.includes(workflowId)) return
  openWorkflowIds.value = [...openWorkflowIds.value, workflowId]
}

function requestWorkflowSwitch(targetId: string): Promise<'save' | 'discard' | 'cancel'> {
  if (!workflowDirty.value || !activeWorkflowId.value || activeWorkflowId.value === targetId) return Promise.resolve('save')
  workflowSwitchGuard.value = { targetId }
  return new Promise((resolve) => { workflowSwitchResolver = resolve })
}

function resolveWorkflowSwitch(choice: 'save' | 'discard' | 'cancel'): void {
  const resolver = workflowSwitchResolver
  workflowSwitchResolver = null
  workflowSwitchGuard.value = null
  resolver?.(choice)
}

function discardActiveWorkflowDraft(): void {
  if (!activeWorkflowId.value) return
  workflowDocuments.delete(activeWorkflowId.value)
}

async function closeWorkflowTab(workflowId: string): Promise<void> {
  if (!workflowId) return
  if (workflowId === activeWorkflowId.value && workflowDirty.value) {
    const choice = await requestWorkflowSwitch('')
    if (choice === 'cancel') return
    cancelAutosave()
    if (choice === 'save') {
      await saveWorkflow(true)
      if (workflowDirty.value) return
    } else discardActiveWorkflowDraft()
  }
  openWorkflowIds.value = openWorkflowIds.value.filter((id) => id !== workflowId)
  if (workflowId === activeWorkflowId.value) {
    const nextId = openWorkflowIds.value.at(-1) || ''
    await selectWorkflow(nextId)
  }
}

function applyWorkflowDocumentUpdate(definition: WorkflowDef, label = '编辑工作流'): void {
  if (!workflowDocument) {
    attachWorkflowDocument(definition)
    return
  }
  workflowDocument.update(definition, { label, origin: 'user' })
}

function workflowNodeTitle(nodeId: string): string {
  const node = workflowDefinition.value?.nodes.find((item) => item.id === nodeId)
  return node?.title || nodeId
}

function nodeStateLabel(status: NodeStateStatus): string {
  if (status === 'running') return '运行中'
  if (status === 'waiting') return '等待中'
  if (status === 'done') return '已完成'
  if (status === 'error') return '失败'
  if (status === 'skipped') return '已跳过'
  if (status === 'cancelled') return '已取消'
  return '未运行'
}

function workflowRunStatusLabel(status: WorkflowRunResult['status']): string {
  if (status === 'running') return '运行中'
  if (status === 'completed') return '完成'
  if (status === 'failed') return '失败'
  if (status === 'paused') return '已暂停'
  if (status === 'cancelled') return '已取消'
  return String(status)
}

function formatRuntimeValue(value: unknown): string {
  if (value === undefined) return '—'
  if (typeof value === 'string') return value || '—'
  try { return JSON.stringify(value, null, 2) || '—' } catch { return String(value) }
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return '—'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString()
}

function applyWorkflowRunResult(raw: unknown, continuation?: WorkflowContinuationState): WorkflowRunResult | null {
  if (!isRecord(raw)) return null
  const normalized = normalizeWorkflowRunResult(raw as any)
  if (!normalized.run_id && activeRunId.value) normalized.run_id = activeRunId.value
  activeRunId.value = normalized.run_id || activeRunId.value
  workflowRun.value = normalized
  workflowContinuation.value = continuation || continuationFromRun(raw)
  workflowNodeStates.value = Object.fromEntries(
    Object.entries(normalized.node_states || {}).map(([nodeId, state]) => [nodeId, normalizeNodeStateStatus(state.status)]),
  ) as Record<string, NodeStateStatus>
  mergeWorkflowRunTimeline(normalized)
  workflowRunning.value = normalized.status === 'running'
  workflowStatusText.value = workflowRunStatusLabel(normalized.status)
  return normalized
}

function continuationFromRun(raw: Record<string, unknown>): WorkflowContinuationState | undefined {
  const value = isRecord(raw.continuation) ? raw.continuation : raw
  const token = String(value.token ?? value.continuation_token ?? '').trim()
  const state = value.state ?? value.continuation_state
  const runId = String(value.run_id ?? value.runId ?? '').trim()
  if (!token && state === undefined && !runId) return undefined
  return {
    ...(token ? { token } : {}),
    ...(state !== undefined ? { state } : {}),
    ...(runId ? { runId } : {}),
  }
}

function mergeWorkflowRunTimeline(run: WorkflowRunResult): void {
  for (const state of Object.values(run.node_states || {})) {
    const id = `state:${state.node_id}`
    if (workflowTimeline.value.some((item) => item.id === id)) continue
    workflowTimeline.value.push({
      id,
      node_id: state.node_id,
      title: workflowNodeTitle(state.node_id),
      status: state.status,
      input: state.input,
      output: state.output,
      error: state.error,
      attempts: state.attempts,
      attempt_id: state.attempt_id,
      duration_ms: state.duration_ms,
      cache_status: state.cache_status,
      cache_key: state.cache_key,
      tool_calls: state.tool_calls,
      logs: state.logs,
      audit: state.audit,
      started_at: state.started_at,
      finished_at: state.finished_at,
    })
  }
}

function appendWorkflowTimeline(item: WorkflowRunTimelineItem): void {
  const existingIndex = workflowTimeline.value.findIndex((entry) => entry.id === item.id)
  if (existingIndex >= 0) {
    workflowTimeline.value = workflowTimeline.value.map((entry, index) => index === existingIndex ? { ...entry, ...item } : entry)
    return
  }
  workflowTimeline.value = [...workflowTimeline.value.slice(-199), item]
}

async function refreshWorkflows(): Promise<void> {
  try {
    const roots = projects.value.map((project) => project.workRoot).filter(Boolean)
    const grouped = await workflowApi.listGrouped(roots)
    workflowGroups.value = Object.fromEntries(Object.entries(grouped).map(([root, definitions]) => [
      root,
      definitions.map((definition) => hydrateWorkflowDefinition(definition)),
    ]))
    workflows.value = Object.values(workflowGroups.value).flat()
    if (activeWorkflowId.value) {
      const current = workflows.value.find((item) => item.id === activeWorkflowId.value)
      if (current && workflowDefinition.value?.updated_at !== current.updated_at) {
        const remote = await workflowApi.getDocumentById(current.id, workflowRoot(current))
        if (workflowDocumentState.value?.dirty) {
          workflowDocument?.markConflict(remote)
          workflowStatusText.value = '远端工作流有更新，请处理冲突'
        } else {
          workflowDocument?.acceptRemote(remote)
        }
      }
    }
    if (!activeWorkflowId.value && workflows.value.length) {
      await selectWorkflow(workflows.value[0].id)
    }
  } catch (error) {
    console.error('[workflow] list failed', error)
    workflowGroups.value = {}
    workflows.value = []
  }
}

async function loadAvailableTools(): Promise<void> {
  try {
    availableTools.value = await workflowApi.listTools()
  } catch (error) {
    console.error('[workflow] list tools failed', error)
    availableTools.value = []
  }
}

async function loadNodeSchemas(): Promise<void> {
  try {
    nodeSchemas.value = await workflowApi.objectInfo()
  } catch (error) {
    // Catalog failure is non-fatal; the canvas remains usable for editing and
    // running existing nodes, while the registry picker reports no choices.
    console.error('[workflow] object info failed', error)
    nodeSchemas.value = {}
  }
}

async function refreshQueue(): Promise<void> {
  const definition = workflowDefinition.value
  if (!definition) {
    queueItems.value = []
    historyItems.value = []
    selectedQueueItem.value = null
    activations.value = []
    return
  }
  queueLoading.value = true
  try {
    const scope = { workRoot: workflowRoot(definition), workflowId: definition.id, name: definition.name, limit: 50 }
    const [active, history] = await Promise.all([
      workflowApi.listQueue({ ...scope, includeHistory: false }),
      workflowApi.historyQueue({ ...scope, includeActive: false }),
    ])
    queueItems.value = active
    historyItems.value = history
    if (selectedQueueItem.value) {
      const current = [...active, ...history].find((item) => item.queue_id === selectedQueueItem.value?.queue_id)
      if (current) selectedQueueItem.value = current
    }
  } catch (error) {
    console.error('[workflow] queue refresh failed', error)
    workflowStatusText.value = `队列刷新失败：${messageFromError(error)}`
  } finally {
    queueLoading.value = false
  }
}

async function refreshHumanTasks(): Promise<void> {
  const definition = workflowDefinition.value
  if (!definition) {
    humanTasks.value = []
    selectedHumanTask.value = null
    humanTaskError.value = ''
    return
  }
  humanTaskLoading.value = true
  humanTaskError.value = ''
  try {
    const tasks = await workflowApi.listHumanTasks({
      workRoot: workflowRoot(definition) || activeProject.value?.workRoot || undefined,
      workflowId: definition.id,
      status: 'pending',
      limit: 50,
    })
    humanTasks.value = tasks
    if (selectedHumanTask.value) {
      const current = tasks.find((task) => task.task_id === selectedHumanTask.value?.task_id)
      selectedHumanTask.value = current || tasks[0] || null
    } else selectedHumanTask.value = tasks[0] || null
  } catch (error) {
    humanTaskError.value = messageFromError(error)
  } finally {
    humanTaskLoading.value = false
  }
}

async function selectHumanTask(taskId: string): Promise<void> {
  if (!taskId) {
    selectedHumanTask.value = null
    return
  }
  const definition = workflowDefinition.value
  try {
    selectedHumanTask.value = await workflowApi.getHumanTask(taskId, {
      workRoot: definition ? workflowRoot(definition) || activeProject.value?.workRoot || undefined : undefined,
    })
    humanTaskError.value = ''
  } catch (error) {
    humanTaskError.value = messageFromError(error)
  }
}

async function completeHumanTask(
  task: WorkflowHumanTask,
  decision: string,
  payload: Record<string, unknown>,
): Promise<void> {
  if (humanTaskBusy.value) return
  const definition = workflowDefinition.value
  humanTaskBusy.value = true
  humanTaskError.value = ''
  try {
    const completed = await workflowApi.completeHumanTask(task.task_id, decision, payload, {
      workRoot: definition ? workflowRoot(definition) || activeProject.value?.workRoot || undefined : undefined,
    })
    if (completed.run) {
      // A signal may finish the waiting run synchronously.  Treat the returned
      // snapshot as the active run so node states, continuation, output, and
      // the canvas-side result panel all move together.
      if (!activeRunId.value && task.run_id) activeRunId.value = task.run_id
      const response = normalizeWorkflowRunResponse({ run: completed.run as any })
      const applied = applyWorkflowRunResult(response.run, response.continuation)
      if (applied && task.node_id && workflowDefinition.value?.nodes.some((node) => node.id === task.node_id)) {
        selectedNodeId.value = task.node_id
      }
    }
    await refreshHumanTasks()
    selectedHumanTask.value = completed.task
    setRuntimeStatus(completed.idempotent ? '任务已处理' : '人工任务已提交', 2500)
  } catch (error) {
    humanTaskError.value = messageFromError(error)
  } finally {
    humanTaskBusy.value = false
  }
}

async function refreshWorkflowActivations(): Promise<void> {
  const definition = workflowDefinition.value
  if (!definition || !definition.name) {
    activations.value = []
    return
  }
  activationsLoading.value = true
  try {
    activations.value = await workflowApi.listActivations(definition.name, workflowRoot(definition))
  } catch (error) {
    // Activation inspection is best effort: a host without Arrange support
    // must not make the workflow editor unusable. Keep the last known list so
    // an intermittent read failure does not hide a still-running activation.
    console.error('[workflow] activation refresh failed', error)
    workflowStatusText.value = `激活状态刷新失败：${messageFromError(error)}`
  } finally {
    activationsLoading.value = false
  }
}

async function activateWorkflowTrigger(triggerId: string, replace = false): Promise<void> {
  const definition = workflowDefinition.value
  if (!definition || !definition.name || !triggerId || activationBusy.value) return
  activationBusy.value = true
  try {
    // Trigger edits live in the same canonical document as the graph. Save a
    // dirty draft before activation so Arrange never receives an older
    // trigger list/revision when the user clicks activate immediately.
    if (workflowDirty.value) {
      await saveWorkflow(true)
      if (workflowDirty.value) throw new Error('请先保存工作流并解决冲突，再激活触发器')
    }
    const current = workflowDefinition.value
    if (!current || !current.name) throw new Error('工作流不存在')
    await workflowApi.activate(current.name, {
      workRoot: workflowRoot(current),
      triggerId,
      // Keep replacement an explicit user choice. The normal activation path
      // sends the false intent as well, while the separate UI action passes
      // true only after the user clicks “替换并激活”.
      replace,
    })
    await refreshWorkflowActivations()
    setRuntimeStatus(replace ? '已替换并激活触发器' : '已激活触发器', 2500)
  } catch (error) {
    setRuntimeStatus(`激活失败：${messageFromError(error)}`, 4000)
    throw error
  } finally {
    activationBusy.value = false
  }
}

async function deactivateWorkflowTrigger(triggerId: string): Promise<void> {
  const definition = workflowDefinition.value
  if (!definition || !definition.name || !triggerId || activationBusy.value) return
  activationBusy.value = true
  try {
    await workflowApi.deactivate(definition.name, {
      workRoot: workflowRoot(definition),
      triggerId,
    })
    await refreshWorkflowActivations()
    setRuntimeStatus('已停用触发器', 2500)
  } catch (error) {
    setRuntimeStatus(`停用失败：${messageFromError(error)}`, 4000)
    throw error
  } finally {
    activationBusy.value = false
  }
}

function addNodeFromCatalog(schema: WorkflowNodeSchema): void {
  const definition = workflowDefinition.value
  if (!definition) return
  const base = String(schema.type_id ?? schema.name ?? 'node').replace(/[^a-zA-Z0-9_-]/g, '-').toLowerCase() || 'node'
  let id = `${base}-${definition.nodes.length + 1}`
  let serial = definition.nodes.length + 1
  while (definition.nodes.some((node) => node.id === id)) id = `${base}-${++serial}`
  const lastX = definition.nodes.reduce((max, node) => Math.max(max, Number(node.position?.x) || 0), 0)
  const node = createWorkflowNodeFromSchema(schema, id, { x: lastX + 260, y: 120 + (definition.nodes.length % 4) * 110 })
  if (['ai', 'model', 'agent'].includes(node.kind) && !String(node.config.model_id || '').trim()) {
    node.config.model_id = selectedModelId.value
  }
  applyWorkflowDocumentUpdate({ ...definition, nodes: [...definition.nodes, node] }, `添加节点：${node.title}`)
  selectedNodeId.value = node.id
  scheduleAutosave()
}

async function enqueueWorkflow(): Promise<void> {
  const definition = workflowDefinition.value
  if (!definition || !definition.name) {
    setRuntimeStatus('先保存工作流再排队', 3000)
    return
  }
  try {
    const item = await workflowApi.enqueue(definition.name, {
      workRoot: workflowRoot(definition),
      modelId: selectedModelId.value,
      permissions: workflowRunPermissions(),
      threadId: workflowSessionId(definition),
      inputs: {},
    })
    selectedQueueItem.value = item
    setRuntimeStatus(`已加入队列：${item.queue_id || item.run_id}`, 2500)
    await refreshQueue()
  } catch (error) {
    setRuntimeStatus(`排队失败：${messageFromError(error)}`, 4000)
  }
}

async function cancelQueuedRun(item: WorkflowQueueItem): Promise<void> {
  try {
    const cancelled = await workflowApi.cancelQueue(item.queue_id, item.run_id)
    selectedQueueItem.value = cancelled
    setRuntimeStatus('已取消队列运行', 2500)
    await refreshQueue()
  } catch (error) {
    setRuntimeStatus(`取消失败：${messageFromError(error)}`, 4000)
  }
}

async function inspectQueuedRun(item: WorkflowQueueItem): Promise<void> {
  try {
    selectedQueueItem.value = await workflowApi.getQueue(item.queue_id, item.run_id)
  } catch (error) {
    selectedQueueItem.value = item
    setRuntimeStatus(`读取运行详情失败：${messageFromError(error)}`, 3500)
  }
}

async function clearWorkflowQueue(all: boolean): Promise<void> {
  const definition = workflowDefinition.value
  if (!definition) return
  try {
    const count = await workflowApi.clearQueue({
      confirm: true,
      all,
      workRoot: workflowRoot(definition),
      workflowId: definition.id,
      name: definition.name,
    })
    selectedQueueItem.value = null
    setRuntimeStatus(`已清理 ${count} 个队列/历史项`, 2500)
    await refreshQueue()
  } catch (error) {
    setRuntimeStatus(`清理失败：${messageFromError(error)}`, 4000)
  }
}

async function importWorkflowDefinition(imported: WorkflowImportSource): Promise<void> {
  const current = workflowDefinition.value
  // Imported JSON is untrusted input.  Bind the new resource to the active
  // project (or the current scoped document), never to a path supplied by the
  // file itself.
  const scopedRoot = workflowRoot(current) || selectedProject.value?.workRoot || ''
  let saved: WorkflowDef
  if (imported.kind === 'native-v2') {
    const document = {
      ...imported.document,
      resource: { ...imported.document.resource, work_root: scopedRoot, revision: 0 },
    }
    saved = await workflowApi.saveDocument(document, scopedRoot || undefined, 0)
  } else if (imported.kind === 'comfyui') {
    saved = await workflowApi.importComfyUi(imported.workflow, imported.name, scopedRoot || undefined, 0)
  } else {
    const normalized = normalizeImportedWorkflow(imported.definition, imported.name || '导入工作流')
    const savedRaw = await workflowApi.create({ ...normalized, work_root: scopedRoot })
    saved = hydrateWorkflowDefinition({ ...savedRaw, canvas_elements: normalized.canvas_elements })
    if (saved.id) writeWorkflowCanvasSidecar(saved.id, saved.canvas_elements ?? [])
  }
  await refreshWorkflows()
  await selectWorkflow(saved.id)
  setRuntimeStatus(`已导入：${saved.name}`, 2500)
}

async function exportWorkflowDefinition(format: WorkflowExportFormat): Promise<boolean> {
  const definition = workflowDefinition.value
  if (!definition) return false
  if (format === 'native-v2') return downloadWorkflowJson(definition, `${definition.name}.workflow.json`)
  const version = format === 'comfyui-v0.4' ? '0.4' : '1'
  const exported = await workflowApi.exportComfyUi(definition.name, version, workflowRoot(definition))
  return downloadJson(exported, `${definition.name}.comfyui-${version}.json`)
}

async function useWorkflowTemplate(template: WorkflowTemplate): Promise<void> {
  const current = workflowDefinition.value
  const root = workflowRoot(current) || selectedProject.value?.workRoot || ''
  const imported = normalizeImportedWorkflow({
    ...template.definition,
    name: `${template.name} ${new Date().toLocaleTimeString().slice(0, 5)}`,
    work_root: root,
  }, template.name)
  const savedRaw = await workflowApi.create(imported)
  const saved = mergeWorkflowCanvasSidecar({ ...savedRaw, canvas_elements: imported.canvas_elements })
  if (saved.id) writeWorkflowCanvasSidecar(saved.id, saved.canvas_elements ?? [])
  await refreshWorkflows()
  await selectWorkflow(saved.id)
  setRuntimeStatus(`已从模板创建：${saved.name}`, 2500)
}

async function selectWorkflow(workflowId: string): Promise<void> {
  if (workflowId === activeWorkflowId.value) return
  const switchChoice = await requestWorkflowSwitch(workflowId)
  if (switchChoice === 'cancel') return
  cancelAutosave()
  if (switchChoice === 'save') {
    if (workflowDirty.value) {
      await saveWorkflow(true)
      if (workflowDirty.value) return
    }
  } else if (switchChoice === 'discard') {
    discardActiveWorkflowDraft()
  }
  if (!workflowId) {
    activeWorkflowId.value = ''
    unsubscribeWorkflowDocument?.()
    unsubscribeWorkflowDocument = null
    workflowDocument = null
    workflowDocumentKey = ''
    workflowDocumentState.value = null
    workflowDefinition.value = null
    selectedNodeId.value = null
    workflowRun.value = null
    workflowContinuation.value = undefined
    workflowTimeline.value = []
    queueItems.value = []
    historyItems.value = []
    selectedQueueItem.value = null
    humanTasks.value = []
    selectedHumanTask.value = null
    return
  }
  const draft = workflowDocuments.get(workflowId)
  const listed = workflows.value.find((item) => item.id === workflowId)
  const workRoot = workflowRoot(listed)
  try {
    const definition = draft?.snapshot().definition
      || (listed ? await workflowApi.getDocumentById(workflowId, workRoot) : null)
    if (!definition) throw new Error('工作流不存在')
    const hydrated = hydrateWorkflowDefinition(definition)
    activeWorkflowId.value = hydrated.id
    rememberOpenWorkflow(hydrated.id)
    attachWorkflowDocument(hydrated)
    workflowNodeStates.value = {}
    workflowRun.value = null
    workflowContinuation.value = undefined
    workflowTimeline.value = []
    selectedNodeId.value = null
    const sessionId = workflowSessionId(hydrated)
    await selectWorkflowSession(hydrated, sessionId)
    await refreshQueue()
    await refreshWorkflowActivations()
    await refreshHumanTasks()
  } catch (error) {
    console.error('[workflow] get failed', error)
    workflowStatusText.value = `加载失败：${messageFromError(error)}`
  }
}

async function selectWorkflowSession(definition: WorkflowDef, sessionId: string): Promise<void> {
  try {
    await selectSession(sessionId)
    return
  } catch (error) {
    if (!isMissingWorkflowThread(error)) throw error
  }
  // document.get repairs the plugin-owned session on current hosts. Retry
  // once after refreshing the host index; old hosts remain a valid empty chat.
  try {
    await workflowApi.getDocumentById(definition.id, workflowRoot(definition))
    await refreshSessions()
    await selectSession(sessionId)
  } catch (error) {
    if (!isMissingWorkflowThread(error)) throw error
    workflowStatusText.value = ''
    setRuntimeStatus('', 0)
  }
}

function selectWorkflowProject(projectId: string): void {
  if (projectId === 'global') return
  const project = projects.value.find((item) => item.id === projectId)
  if (project) setSelectedProjectId(project.id)
}

function openWorkflowCreate(): void {
  workflowNameDraft.value = ''
  workflowCreateError.value = ''
  showWorkflowCreate.value = true
}

function closeWorkflowCreate(): void {
  if (workflowCreateLoading.value) return
  showWorkflowCreate.value = false
  workflowCreateError.value = ''
}

async function createWorkflowFromCard(): Promise<void> {
  const name = workflowNameDraft.value.trim()
  if (!name) return
  workflowCreateLoading.value = true
  workflowCreateError.value = ''
  try {
    const saved = await workflowApi.create({
      ...emptyWorkflow,
      name,
      work_root: selectedProject.value?.workRoot || '',
    })
    await refreshWorkflows()
    closeWorkflowCreate()
    await selectWorkflow(saved.id)
    setRuntimeStatus(`已创建：${saved.name}`, 2500)
  } catch (error) {
    workflowCreateError.value = `创建失败：${messageFromError(error)}`
  } finally {
    workflowCreateLoading.value = false
  }
}

function onWorkflowUpdate(definition: WorkflowDef): void {
  applyWorkflowDocumentUpdate(definition)
  if (definition.id) writeWorkflowCanvasSidecar(definition.id, definition.canvas_elements ?? [])
  // Definition changes generated while a run is active are not expected, but
  // even if a canvas event races the run transition they must not autosave.
  if (!workflowRunning.value) scheduleAutosave()
}

function scheduleAutosave(): void {
  if (workflowRunning.value) return
  cancelAutosave()
  autosaveTimer = setTimeout(() => {
    autosaveTimer = null
    if (workflowRunning.value) return
    lastSelfSaveAt = Date.now()
    void saveWorkflow(true)
  }, 800)
}

function cancelAutosave(): void {
  if (!autosaveTimer) return
  clearTimeout(autosaveTimer)
  autosaveTimer = null
}

function undoWorkflow(): void {
  if (workflowRunning.value || !workflowDocument) return
  if (workflowDocument.undo()) scheduleAutosave()
}

function redoWorkflow(): void {
  if (workflowRunning.value || !workflowDocument) return
  if (workflowDocument.redo()) scheduleAutosave()
}

async function renameWorkflow(title: string): Promise<void> {
  const definition = workflowDefinition.value
  const newName = title.trim()
  if (!definition || !newName || newName === definition.name) return
  try {
    const renamedRaw = await workflowApi.rename(definition.name, newName, workflowRoot(definition))
    const renamed = mergeWorkflowCanvasSidecar({ ...renamedRaw, canvas_elements: definition.canvas_elements })
    if (renamed.id) writeWorkflowCanvasSidecar(renamed.id, renamed.canvas_elements ?? [])
    workflowDocument?.markSaved(renamed, { value: renamed.revision, updatedAt: renamed.updated_at })
    if (!workflowDocument) attachWorkflowDocument(renamed)
    activeWorkflowId.value = renamed.id
    await refreshWorkflows()
    await refreshSessions()
    setRuntimeStatus(`已重命名：${renamed.name}`, 2500)
  } catch (error) {
    setRuntimeStatus(`重命名失败：${messageFromError(error)}`, 4000)
    throw error
  }
}

function onSelectNode(id: string | null): void {
  selectedNodeId.value = id
}

async function runFromNode(nodeId: string): Promise<void> {
  await executeWorkflowRun(undefined, { startNode: nodeId })
}

async function runSingleNode(nodeId: string): Promise<void> {
  await executeWorkflowRun(undefined, { singleNode: nodeId })
}

async function saveWorkflow(silent = false): Promise<void> {
  const definition = workflowDefinition.value
  if (!definition) return
  if (workflowRunning.value) return
  try {
    const saved = await workflowApi.saveDocument(definition, workflowRoot(definition))
    if (workflowDocument) workflowDocument.markSaved(saved, { value: saved.revision, updatedAt: saved.updated_at })
    else attachWorkflowDocument(saved)
    activeWorkflowId.value = saved.id
    if (!silent) setRuntimeStatus(`已保存：${saved.name}`, 2500)
    if (!silent) await refreshWorkflows()
  } catch (error) {
    console.error('[workflow] save failed', error)
    if (await loadWorkflowConflict(error, definition)) return
    workflowDocument?.markSaveError(error)
    if (!silent) setRuntimeStatus(`保存失败：${messageFromError(error)}`, 4000)
  }
}

async function loadWorkflowConflict(error: unknown, local: WorkflowDef): Promise<boolean> {
  if (!isWorkflowRevisionConflict(error)) return false
  try {
    const remote = await workflowApi.getDocumentById(local.id, workflowRoot(local))
    workflowDocument?.markConflict(remote, '保存冲突：远端版本已更新。请选择采用远端，或保留本地后重试。')
    workflowStatusText.value = '保存冲突，请选择处理方式'
  } catch (refreshError) {
    // Keep the conflict signal visible even when a transient read failure
    // prevents loading the canonical remote document.
    workflowDocument?.markSaveError(new Error(`检测到版本冲突，但无法读取远端版本：${messageFromError(refreshError)}`), false)
    workflowStatusText.value = '检测到版本冲突，远端版本暂不可读取'
  }
  return true
}

function acceptRemoteWorkflow(): void {
  const remote = workflowDocumentState.value?.conflict?.remote
  if (!remote || !workflowDocument) return
  workflowDocument.acceptRemote(remote)
  workflowStatusText.value = '已采用远端版本'
}

function keepLocalAndRetryWorkflow(): void {
  if (!workflowDocument?.keepLocalAfterConflict()) return
  workflowStatusText.value = '已保留本地修改，正在重试保存…'
  void saveWorkflow()
}

async function runWorkflow(): Promise<void> {
  const previous = workflowRun.value
  const continuation = previous?.status === 'paused' ? workflowContinuation.value : undefined
  await executeWorkflowRun(undefined, continuation ? { continuation } : {})
}

async function runWorkflowWithInputs(inputs: Record<string, unknown>): Promise<void> {
  const previous = workflowRun.value
  const continuation = previous?.status === 'paused' ? workflowContinuation.value : undefined
  await executeWorkflowRun(undefined, { ...(continuation ? { continuation } : {}), inputs })
}

async function stepWorkflow(): Promise<void> {
  const previous = workflowRun.value
  const continuation = previous?.status === 'paused'
    ? (workflowContinuation.value || { runId: previous.run_id })
    : undefined
  await executeWorkflowRun(1, continuation ? { continuation } : {})
}

async function cancelWorkflowRun(): Promise<void> {
  const definition = workflowDefinition.value
  if (!definition || !workflowRunning.value) return
  const threadId = workflowSessionId(definition)
  workflowStatusText.value = '正在停止…'
  try {
    await workflowApi.cancel(threadId, activeRunId.value || undefined)
    const previousStates = workflowRun.value?.node_states || {}
    const states = Object.fromEntries(definition.nodes.map((node) => {
      const previous = previousStates[node.id] || {
        node_id: node.id,
        status: workflowNodeStates.value[node.id] || 'idle',
        attempts: 0,
      }
      const status = previous.status === 'done' || previous.status === 'skipped' || previous.status === 'error'
        ? previous.status
        : 'cancelled'
      return [node.id, { ...previous, node_id: node.id, status }]
    })) as Record<string, WorkflowNodeState>
    workflowNodeStates.value = Object.fromEntries(Object.entries(states).map(([nodeId, state]) => [nodeId, state.status])) as Record<string, NodeStateStatus>
    workflowRun.value = {
      ...(workflowRun.value || {
        output: null,
        cache: {},
        values: {},
        run_id: activeRunId.value,
        steps_remaining: 0,
        started_at: null,
      }),
      status: 'cancelled',
      error: 'cancelled',
      node_states: states,
      finished_at: new Date().toISOString(),
    }
    workflowContinuation.value = undefined
    workflowRunning.value = false
    workflowStatusText.value = '已取消'
  } catch (error) {
    workflowStatusText.value = `停止失败：${messageFromError(error)}`
  }
}

async function executeWorkflowRun(
  maxSteps: number | undefined,
  options: { startNode?: string; singleNode?: string; continuation?: WorkflowContinuationState; inputs?: Record<string, unknown> } = {},
): Promise<void> {
  const definition = workflowDefinition.value
  if (!definition || !definition.name) {
    setRuntimeStatus('先保存工作流再运行', 3000)
    return
  }
  if (workflowRunning.value) return
  const previous = !options.startNode && !options.singleNode && workflowRun.value?.status === 'paused'
    ? workflowRun.value
    : null
  const continuation = options.continuation
  const resume = Boolean(continuation || previous)
  const runId = resume ? (continuation?.runId || previous?.run_id || newRunId()) : newRunId()
  const threadId = workflowSessionId(definition)
  activeRunId.value = runId
  if (!resume) workflowTimeline.value = []
  workflowRunning.value = true
  workflowStatusText.value = options.singleNode ? '运行节点…' : options.startNode ? '从此节点运行…' : maxSteps !== undefined ? '单步运行中…' : '运行中…'
  const initialStates = resume && previous
    ? Object.fromEntries(Object.entries(previous.node_states).map(([nodeId, state]) => [nodeId, { ...state }])) as Record<string, WorkflowNodeState>
    : Object.fromEntries(definition.nodes.map((node) => [node.id, {
      node_id: node.id,
      status: 'idle' as const,
      attempts: 0,
      started_at: null,
      finished_at: null,
    }])) as Record<string, WorkflowNodeState>
  workflowNodeStates.value = Object.fromEntries(definition.nodes.map((node) => [node.id, initialStates[node.id]?.status || 'idle'])) as Record<string, NodeStateStatus>
  workflowRun.value = {
    status: 'running',
    output: resume && previous ? previous.output : null,
      node_states: initialStates,
      cache: resume && previous ? { ...previous.cache } : {},
      values: resume && previous ? { ...previous.values } : {},
    error: '',
    run_id: runId,
    steps_remaining: resume && previous ? previous.steps_remaining : definition.nodes.length,
    started_at: resume && previous ? previous.started_at : new Date().toISOString(),
    finished_at: null,
  }
  try {
    const result = await workflowApi.run(definition.name, {
      workRoot: workflowRoot(definition),
      modelId: selectedModelId.value,
      permissions: workflowRunPermissions(),
      maxSteps,
      priorValues: resume && previous ? previous.values : undefined,
      priorNodeStates: resume && previous ? previous.node_states : undefined,
      continuation,
      inputs: options.inputs,
      startNode: options.startNode,
      singleNode: options.singleNode,
      threadId,
      runId,
    })
    if (activeRunId.value !== result.run_id && result.run_id) return
    activeRunId.value = result.run_id || runId
    applyWorkflowRunResult(result.run, result.continuation)
    if (result.run.status === 'paused') workflowStatusText.value = '已暂停（单步）'
    else if (result.run.status === 'completed') workflowStatusText.value = '完成'
    else if (result.run.status === 'cancelled') workflowStatusText.value = '已取消'
    else workflowStatusText.value = result.run.status
  } catch (error) {
    if (activeRunId.value === runId) {
      workflowStatusText.value = `运行失败：${messageFromError(error)}`
      workflowRun.value = {
        ...(workflowRun.value || {
          output: null,
          node_states: {},
          cache: {},
          values: {},
          run_id: runId,
          steps_remaining: 0,
          started_at: new Date().toISOString(),
        }),
        status: 'failed',
        error: messageFromError(error),
        finished_at: new Date().toISOString(),
      }
      workflowContinuation.value = undefined
    }
  } finally {
    if (activeRunId.value === runId || !activeRunId.value) workflowRunning.value = false
  }
}

async function toggleExpose(): Promise<void> {
  const definition = workflowDefinition.value
  if (!definition) return
  try {
    const updatedRaw = await workflowApi.setExposed(definition.name, !definition.exposed, workflowRoot(definition))
    const updated = mergeWorkflowCanvasSidecar({ ...updatedRaw, canvas_elements: definition.canvas_elements })
    if (updated.id) writeWorkflowCanvasSidecar(updated.id, updated.canvas_elements ?? [])
    workflowDocument?.markSaved(updated, { value: updated.revision, updatedAt: updated.updated_at })
    if (!workflowDocument) attachWorkflowDocument(updated)
    await refreshWorkflows()
    setRuntimeStatus(updated.exposed ? `已暴露：${updated.tool_name || `workflow_${updated.name}`}` : '已取消暴露', 2500)
  } catch (error) {
    setRuntimeStatus(`操作失败：${messageFromError(error)}`, 4000)
  }
}

function newRunId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return `workflow_run_${crypto.randomUUID()}`
  return `workflow_run_${Date.now()}_${Math.random().toString(16).slice(2)}`
}

function workflowRunPermissions(): Record<string, unknown> {
  return ['auto', 'full_access'].includes(permissionPreset.value)
    ? { run_command: true }
    : {}
}

function messageFromError(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

function isMissingWorkflowThread(error: unknown): boolean {
  return /(?:thread|session)\s+not\s+found/i.test(messageFromError(error))
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object'
}

function handleRuntimeEvent(event: CoreAppEvent | null): void {
  if (!event) return
  if (event.method === 'workflow/changed') {
    const payload = event.payload || {}
    const changedRoot = String(payload.work_root || '')
    const activeRoot = workflowRoot(workflowDefinition.value) || ''
    if (!changedRoot || changedRoot === activeRoot) scheduleGraphReload()
    return
  }
  if (event.method !== 'core/runItem') return
  const envelope = event.payload || {}
  const payload = isRecord(envelope.payload) ? envelope.payload : envelope
  const nested = isRecord(payload.payload) ? payload.payload : payload
  if (String(nested.plugin_id || payload.plugin_id || '') !== 'workflow') return
  const workflowId = String(nested.workflow_id || payload.workflow_id || '')
  const runId = String(nested.run_id || payload.run_id || event.turn_id || '')
  if (!workflowId || workflowId !== activeWorkflowId.value || !activeRunId.value || runId !== activeRunId.value) return
  const status = String(nested.status || payload.status || '')
  const lifecycleStatuses = new Set(['running', 'progress', 'completed', 'failed', 'paused', 'cancelled', 'canceled'])
  const explicitNodeId = nested.node_id || payload.node_id
  const fallbackNodeId = event.item_id && !lifecycleStatuses.has(status.toLowerCase()) ? event.item_id : ''
  const nodeId = String(explicitNodeId || fallbackNodeId || '')
  const runStatus = nested.run_status || payload.run_status || (!nodeId && lifecycleStatuses.has(status.toLowerCase()) ? status : undefined)
  const normalizedRunStatus = runStatus ? normalizeWorkflowRunStatus(runStatus) : undefined
  const metadata = isRecord((event as CoreAppEvent & { metadata?: unknown }).metadata)
    ? (event as CoreAppEvent & { metadata?: Record<string, unknown> }).metadata || {}
    : {}
  if (normalizedRunStatus && workflowRun.value) {
    workflowRun.value = {
      ...workflowRun.value,
      status: normalizedRunStatus,
      ...(normalizedRunStatus !== 'running' && !workflowRun.value.finished_at ? { finished_at: event.created_at } : {}),
      ...(nested.steps_remaining !== undefined ? { steps_remaining: Number(nested.steps_remaining) || 0 } : {}),
    }
    workflowRunning.value = normalizedRunStatus === 'running'
    workflowStatusText.value = workflowRunStatusLabel(normalizedRunStatus)
  }
  if (!status) return
  const detail = normalizeWorkflowNodeState({
    ...nested,
    ...(nested.output !== undefined ? { output: nested.output } : {}),
    ...(nested.attempts !== undefined ? { attempts: nested.attempts } : {}),
  }, nodeId)
  if (nodeId) {
    workflowNodeStates.value = { ...workflowNodeStates.value, [nodeId]: detail.status }
  }
  if (workflowRun.value && nodeId) {
    const previousDetail = workflowRun.value.node_states[nodeId]
    workflowRun.value = {
      ...workflowRun.value,
      node_states: {
        ...workflowRun.value.node_states,
        [nodeId]: { ...previousDetail, ...detail, node_id: nodeId },
      },
      error: String(nested.error || payload.error || workflowRun.value.error || ''),
    }
  }
  if (workflowRun.value && !nodeId && nested.output !== undefined) {
    workflowRun.value = { ...workflowRun.value, output: nested.output }
  }
  const item: WorkflowRunTimelineItem = {
    id: String(event.event_id || `${runId}:${nodeId || 'run'}:${status}:${event.seq}`),
    ...(nodeId ? { node_id: nodeId, title: String(nested.title || workflowNodeTitle(nodeId)) } : { title: status === 'progress' ? '运行进度' : '运行事件' }),
    status: nodeId ? (detail.status || status) : status,
    kind: String(nested.kind || event.event_type || status),
    occurred_at: event.created_at || null,
    ...(detail.input !== undefined ? { input: detail.input } : {}),
    ...(nested.input !== undefined ? { input: nested.input } : {}),
    ...(nested.inputs !== undefined ? { input: nested.inputs } : {}),
    ...(detail.output !== undefined ? { output: detail.output } : {}),
    ...(nested.output !== undefined ? { output: nested.output } : {}),
    ...(detail.error ? { error: detail.error } : nested.error ? { error: String(nested.error) } : {}),
    ...(detail.attempts ? { attempts: detail.attempts } : nested.attempts !== undefined ? { attempts: Number(nested.attempts) || 0 } : {}),
    ...(detail.attempt_id ? { attempt_id: detail.attempt_id } : {}),
    ...(detail.duration_ms !== undefined ? { duration_ms: detail.duration_ms } : {}),
    ...(detail.cache_status ? { cache_status: detail.cache_status } : {}),
    ...(detail.cache_key ? { cache_key: detail.cache_key } : {}),
    ...(detail.tool_calls ? { tool_calls: detail.tool_calls } : Array.isArray(nested.tool_calls) ? { tool_calls: nested.tool_calls } : {}),
    ...(detail.logs ? { logs: detail.logs } : Array.isArray(nested.logs) ? { logs: nested.logs } : {}),
    ...(detail.audit !== undefined ? { audit: detail.audit } : nested.audit !== undefined ? { audit: nested.audit } : {}),
    ...(detail.started_at ? { started_at: detail.started_at } : {}),
    ...(detail.finished_at ? { finished_at: detail.finished_at } : {}),
    ...(metadata.started_at || metadata.startedAt ? { started_at: String(metadata.started_at || metadata.startedAt) } : {}),
    ...(metadata.finished_at || metadata.finishedAt ? { finished_at: String(metadata.finished_at || metadata.finishedAt) } : {}),
  }
  appendWorkflowTimeline(item)
}

function scheduleGraphReload(force = false): void {
  if (!workflowDefinition.value) return
  // A workflow-building turn writes several valid revisions in sequence.
  // Loading an intermediate revision lets Vue Flow produce a local layout
  // edit, which then conflicts with the remaining agent writes. Wait for the
  // turn boundary and load the final graph atomically instead.
  if (chat.activeTurnRunning.value && !force) return
  if (!force && Date.now() - lastSelfSaveAt < 3000) return
  if (graphReloadTimer) clearTimeout(graphReloadTimer)
  graphReloadTimer = setTimeout(() => {
    const definition = workflowDefinition.value
    if (!definition) return
    void workflowApi.getDocumentById(definition.id, workflowRoot(definition))
      .then((fresh) => {
        if (workflowDocumentState.value?.dirty) {
          workflowDocument?.markConflict(fresh)
          workflowStatusText.value = '远端工作流有更新，请处理冲突'
        } else {
          workflowDocument?.acceptRemote(fresh)
        }
      })
      .catch((error) => console.error('[workflow] live graph reload failed', error))
  }, 400)
}

watch(lastEvent, handleRuntimeEvent)
watch(() => chat.messages.value.length, () => {
  if (chat.activeTurnRunning.value) scheduleGraphReload()
})
watch(chat.activeTurnRunning, (running, previous) => {
  if (previous && !running) scheduleGraphReload(true)
})

onMounted(() => {
  ensureRightPanelOpen()
  void refreshWorkflows()
  void loadAvailableTools()
  void loadNodeSchemas()
  void refreshHumanTasks()
  queueRefreshTimer = setInterval(() => {
    if (workflowDefinition.value && !queueLoading.value) void refreshQueue()
    if (workflowDefinition.value && !activationsLoading.value) void refreshWorkflowActivations()
    if (workflowDefinition.value && !humanTaskLoading.value) void refreshHumanTasks()
  }, 4000)
})

onBeforeUnmount(() => {
  unregisterSurface()
  unsubscribeWorkflowDocument?.()
  unsubscribeWorkflowDocument = null
  workflowDocument = null
  cancelAutosave()
  if (graphReloadTimer) clearTimeout(graphReloadTimer)
  if (queueRefreshTimer) clearInterval(queueRefreshTimer)
})
</script>

<style scoped>
.workflow-view {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 0;
}
.wf-workflow-tabs {
  position: relative;
  display: flex;
  align-items: flex-end;
  gap: 0;
  width: 100%;
  height: 100%;
  min-width: 0;
  max-width: none;
  overflow-x: auto;
  padding: 0;
  border-bottom: 0;
  background: transparent;
  pointer-events: auto;
  scrollbar-width: none;
  -webkit-app-region: no-drag;
  app-region: no-drag;
}
.wf-workflow-tabs::-webkit-scrollbar { display: none; }
.wf-workflow-tab {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  min-height: 30px;
  max-width: 220px;
  border: 1px solid transparent;
  border-bottom: 0;
  border-radius: var(--radius) var(--radius) 0 0;
  background: transparent;
  color: var(--theme-main-text);
  padding: 0 var(--space-2);
  font-size: 11px;
  white-space: nowrap;
  cursor: pointer;
}
.wf-workflow-tab:hover { background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), transparent); }
.wf-workflow-tab.active {
  z-index: 1;
  border-color: var(--theme-main-border);
  border-bottom-color: transparent;
  background: var(--theme-main-soft-background);
  color: var(--theme-main-text);
}
.wf-workflow-tab:focus-visible { outline: 2px solid var(--blue); outline-offset: -2px; }
.wf-workflow-tab-title { overflow: hidden; text-overflow: ellipsis; }
.wf-workflow-tab-dirty { display: grid; place-items: center; color: var(--orange); }
.wf-workflow-tab-close { display: inline-grid; place-items: center; width: 18px; height: 18px; border-radius: var(--radius-sm); color: color-mix(in srgb, var(--theme-main-text) 55%, transparent); }
.wf-workflow-tab-close:hover, .wf-workflow-tab-close:focus-visible { background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), transparent); color: var(--theme-main-text); outline: 0; }
.wf-switch-guard { position: fixed; inset: 0; z-index: var(--z-modal); display: grid; place-items: center; background: color-mix(in srgb, var(--theme-main-background) 66%, transparent); backdrop-filter: blur(2px); }
.wf-switch-guard-card { width: 360px; max-width: calc(100vw - 32px); padding: var(--space-4); border: 1px solid var(--theme-main-border); border-radius: var(--radius-md, 12px); background: var(--theme-main-background); color: var(--theme-main-text); box-shadow: var(--shadow-lg, var(--shadow-md)); }
.wf-switch-guard-card h2 { margin: 0 0 var(--space-2); font-size: 14px; }
.wf-switch-guard-card p { margin: 0; color: color-mix(in srgb, var(--theme-main-text) 68%, transparent); font-size: 12px; }
.wf-switch-guard-actions { display: flex; justify-content: flex-end; gap: var(--space-2); margin-top: var(--space-4); }

.wf-create-backdrop {
  position: fixed;
  inset: 0;
  z-index: var(--z-modal);
  display: grid;
  place-items: center;
  background: color-mix(in srgb, var(--theme-main-background) 66%, transparent);
  backdrop-filter: blur(2px);
}
.wf-create-card {
  width: 320px;
  max-width: calc(100vw - 32px);
  padding: var(--space-3);
  border: 1px solid var(--theme-main-border);
  border-radius: var(--radius);
  background: var(--theme-main-background);
  box-shadow: var(--shadow-md);
  display: grid;
  gap: var(--space-2);
}
@media (max-width: 680px) {
  .wf-workflow-tabs { display: none; }
}
.wf-create-head h2 { margin: 0; font-size: 15px; font-weight: 700; color: var(--theme-main-text); }
.wf-create-input {
  width: 100%;
  box-sizing: border-box;
  min-height: 32px;
  border: 1px solid color-mix(in srgb, var(--theme-composer-text) 12%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--theme-composer-background) 70%, transparent);
  color: var(--theme-composer-text);
  caret-color: var(--theme-composer-text);
  padding: 0 var(--space-2);
  font: inherit;
  outline: 0;
}
.wf-create-error { margin: 0; font-size: 11px; color: var(--red); }
.wf-create-actions { display: flex; justify-content: flex-end; gap: var(--space-1); }
.wf-create-actions button { min-height: 28px; padding-inline: var(--space-2); border-radius: var(--radius-sm); border: 0; font-size: 12px; cursor: pointer; }
.wf-create-actions .text-btn { background: transparent; color: color-mix(in srgb, var(--theme-control-text) 65%, transparent); }
.wf-create-actions .primary-btn { background: var(--theme-control-background); color: var(--theme-control-text); font-weight: 600; }
.wf-create-actions .primary-btn:disabled { opacity: .45; cursor: not-allowed; }

.wf-floating-header {
  position: absolute;
  inset: 0 0 auto;
  z-index: var(--z-popover);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  pointer-events: auto;
  background: transparent;
  border: 0;
}
.wf-header-title {
  flex: 1 1 auto;
  min-width: 0;
}

.wf-convo-float {
  position: fixed;
  left: var(--main-left);
  right: var(--main-right);
  bottom: calc(
    var(--composer-bottom-offset, 0px) +
    var(--composer-rest-bottom, 16px) +
    var(--workflow-composer-expanded-height, var(--composer-height, 120px))
  );
  z-index: calc(var(--z-composer, 40) - 1);
  width: min(
    var(--content-width),
    calc(100vw - var(--main-left) - var(--main-right) - var(--main-x-padding) - var(--main-x-padding) - 2px)
  );
  margin-inline: auto;
  height: min(560px, 58vh);
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--theme-main-border);
  border-bottom: 0;
  border-radius: var(--radius-xl) var(--radius-xl) 0 0;
  background: var(--theme-main-background);
  color: var(--theme-main-text);
  box-shadow: var(--shadow-sm);
  opacity: 0;
  visibility: hidden;
  pointer-events: none;
  transition:
    opacity var(--dur-base) var(--ease-out),
    visibility 0s linear var(--dur-morph),
    left var(--dur-morph) var(--ease-inout),
    right var(--dur-morph) var(--ease-inout),
    width var(--dur-morph) var(--ease-inout);
}
.wf-convo-float.is-pinned {
  opacity: 1;
  visibility: visible;
  pointer-events: auto;
  transition-delay: 0s;
}
.wf-convo-float-head {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  min-height: 46px;
  padding: var(--space-2) var(--space-3) var(--space-2) var(--space-4);
  border-bottom: 1px solid var(--theme-main-border);
}
.wf-convo-float-head h3 {
  min-width: 0;
  margin: 0;
  overflow: hidden;
  color: var(--theme-main-text);
  font-size: 14px;
  font-weight: 650;
  line-height: 1.25;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.wf-convo-float-head .text-btn {
  flex: 0 0 auto;
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text) 58%, transparent);
}
.wf-convo-float-head .text-btn:hover {
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), transparent);
  color: var(--theme-main-text);
}
.wf-convo-float-body.thread {
  flex: 1 1 auto;
  width: 100%;
  min-width: 0;
  min-height: 0;
  margin: 0;
  padding: var(--space-4);
  overflow-x: hidden;
  overflow-y: auto;
  box-sizing: border-box;
  -webkit-mask-image: none;
  mask-image: none;
  scrollbar-gutter: stable;
}
.wf-convo-float-body :deep(.chat-thread) {
  width: 100%;
  max-width: none;
  min-width: 0;
  margin: 0;
}
.wf-convo-float-body :deep(.message-view),
.wf-convo-float-body :deep(.assistant-row),
.wf-convo-float-body :deep(.assistant-message),
.wf-convo-float-body :deep(.assistant-reply-bubble) {
  min-width: 0;
  max-width: 100%;
}
.wf-convo-float-body :deep(.markdown-body),
.wf-convo-float-body :deep(pre),
.wf-convo-float-body :deep(code) {
  overflow-wrap: anywhere;
}
@media (max-width: 640px) {
  .wf-convo-float {
    left: var(--space-3);
    right: var(--space-3);
    width: auto;
    margin-inline: 0;
    height: min(52vh, 480px);
  }
}
@media (prefers-reduced-motion: reduce) {
  .wf-convo-float,
  .wf-convo-float * { transition: none; animation: none; }
}
</style>
