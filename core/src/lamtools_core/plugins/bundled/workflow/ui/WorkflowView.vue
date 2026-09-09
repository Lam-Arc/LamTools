<template>
  <div class="workflow-view" data-plugin-mode="workflow">
    <WorkflowCanvas
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
    <WorkflowControlBar
      :running="workflowRunning"
      :exposed="workflowDefinition?.exposed"
      :status-text="workflowStatusText"
      @run="runWorkflow"
      @step="stepWorkflow"
      @save="saveWorkflow"
      @cancel="cancelWorkflowRun"
      @toggle-exposed="toggleExpose"
    />
  </div>

  <Teleport v-if="workflowDefinition" defer to=".workspace-plugin-header">
    <div class="thread-header wf-floating-header" data-workflow-header>
      <CoreSessionTitleEditor
        :title="workflowDefinition.name"
        :session-id="workflowSessionId(workflowDefinition)"
        :rename="renameWorkflow"
      />
      <button
        type="button"
        class="stage-toggle-btn"
        :class="{ active: canvasLocked }"
        :title="canvasLocked ? '解锁画布' : '锁定画布'"
        :aria-label="canvasLocked ? '解锁画布' : '锁定画布'"
        @click="canvasLocked = !canvasLocked"
      >
        <svg v-if="canvasLocked" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>
        <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 7.5-2"/></svg>
      </button>
    </div>
  </Teleport>

  <Teleport defer to=".workspace-plugin-right-panel">
    <div class="wf-right-panel">
      <section class="wf-right-nodes">
        <h3>节点</h3>
        <ul v-if="workflowDefinition?.nodes.length" class="wf-node-list">
          <li
            v-for="node in workflowDefinition.nodes"
            :key="node.id"
            class="wf-node-list-item"
            :class="{ active: node.id === selectedNodeId }"
            @click="onSelectNode(node.id)"
          >
            <span class="wf-node-list-kind" aria-hidden="true">
              <component :is="nodeKindIcon(node.kind)" :size="12" :stroke-width="1.8" />
            </span>
            <span class="wf-node-list-title" :title="node.title || node.id">{{ node.title || node.id }}</span>
          </li>
        </ul>
        <p v-else class="wf-right-empty">暂无节点</p>
      </section>

      <section class="wf-right-info">
        <template v-if="selectedNodeId">
          <div class="wf-right-info-head">
            <h3>{{ selectedNode?.title || selectedNodeId }}</h3>
            <button type="button" class="text-btn" title="返回对话" @click="onSelectNode(null)">
              <ArrowLeft :size="14" :stroke-width="1.8" aria-hidden="true" />
            </button>
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
            <p class="wf-node-info-row"><span>端口</span><strong>{{ selectedNode.ports.map((port) => port.name).join(', ') || '—' }}</strong></p>
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
                :messages="chat.messages.value"
                :process-expanded-ids="chat.processExpandedIds.value"
                :message-actions="true"
                :transport="transport"
                :project-id="activeProjectId ?? selectedProjectId"
                :work-root="activeProject?.workRoot"
                :active-turn-id="chat.activeTurnId.value"
                :turn-active="chat.activeTurnRunning.value"
                :checkpoint-turn-ids="chat.checkpointTurnIds.value"
                @toggle-process="chat.toggleProcess"
                @decision-select="chat.onDecisionSelect"
                @fork-message="chat.onForkMessage"
                @rollback-message="chat.onRollbackMessage"
                @edit-message="chat.onEditMessage"
              />
            </div>
          </div>
        </template>
      </section>
    </div>
  </Teleport>

  <Teleport v-if="conversationExpanded" defer to=".workspace-plugin-modal">
    <section class="wf-convo-float" role="dialog" aria-modal="false" aria-label="工作流对话">
      <header class="wf-convo-float-head">
        <h3>{{ workflowDefinition?.name || '工作流' }} · 对话</h3>
        <button type="button" class="text-btn" title="收起" @click="conversationExpanded = false">
          <X :size="14" :stroke-width="1.8" aria-hidden="true" />
        </button>
      </header>
      <div class="wf-convo-float-body">
        <ChatThread
          :messages="chat.messages.value"
          :process-expanded-ids="chat.processExpandedIds.value"
          :message-actions="true"
          :transport="transport"
          :project-id="activeProjectId ?? selectedProjectId"
          :work-root="activeProject?.workRoot"
          :active-turn-id="chat.activeTurnId.value"
          :turn-active="chat.activeTurnRunning.value"
          :checkpoint-turn-ids="chat.checkpointTurnIds.value"
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
import { ArrowLeft, Boxes, Command, Cpu, FileCode2, FileText, X, type LucideIcon } from 'lucide-vue-next'
import type { CoreAppEvent } from '../../../../../../ui/src/appServer'
import type { ProjectGroup, SessionItem } from '../../../../../../ui/src/components/SessionSidebar.vue'
import type { PluginModeSurface } from '../../../../../../ui/src/plugins/context'
import { useCorePluginModeContext, usePluginModeRuntime } from '../../../../../../ui/src/plugins/context'
import type { NodeStateStatus, WorkflowDef, WorkflowNode } from './types'
import { createWorkflowApi, type WorkflowApi } from './api'
import WorkflowCanvas from './WorkflowCanvas.vue'
import WorkflowControlBar from './WorkflowControlBar.vue'
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
  composerText,
  ensureRightPanelOpen,
  lastEvent,
  chat,
} = context

const workflows = ref<WorkflowDef[]>([])
const workflowGroups = ref<Record<string, WorkflowDef[]>>({})
const activeWorkflowId = ref('')
const workflowDefinition = ref<WorkflowDef | null>(null)
const workflowNodeStates = ref<Record<string, NodeStateStatus>>({})
const selectedNodeId = ref<string | null>(null)
const selectedNode = computed<WorkflowNode | null>(() => (
  workflowDefinition.value?.nodes.find((node) => node.id === selectedNodeId.value) || null
))
const availableTools = ref<Array<{ name: string; description: string }>>([])
const workflowRunning = ref(false)
const workflowStatusText = ref('')
const activeRunId = ref('')
const canvasLocked = ref(false)
const conversationExpanded = ref(false)
const showWorkflowCreate = ref(false)
const workflowCreateLoading = ref(false)
const workflowCreateError = ref('')
const workflowNameDraft = ref('')
let autosaveTimer: ReturnType<typeof setTimeout> | null = null
let graphReloadTimer: ReturnType<typeof setTimeout> | null = null
let lastSelfSaveAt = 0

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
    '节点类型有五种：ai、command、script、content、subgraph。',
    '- ai：AI 处理。config.mode 区分 single（单次生成）/ loop（自判断反复迭代）/ agent（多轮自主+工具）。有命名输出端口→强制 JSON 输出，端口名=字段名。指令支持 {{端口名}} 插值。',
    '- command：跑 shell 命令调用 CLI 工具（curl/git/ffmpeg 等）。config.command 是 shell 命令，用与 run_command 相同的 shell（Windows 下 Git Bash）。stdin 收 {"inputs":{端口名:值}} JSON，同时设 INPUT_<端口名> 环境变量。stdout 是 JSON 对象则按 key 拆到同名输出端口，否则整段放默认端口。command 图灵完备，http/file-data 一律用 command（curl/cat/jq）。',
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
  composerDisabled: computed(() => workflowRunning.value || !composerText.value.trim() || !activeWorkflowId.value),
  turnOptions: () => ({
    active_mode: 'workflow:workflow',
    instructions: workflowModeInstructions.value,
  }),
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

async function refreshWorkflows(): Promise<void> {
  try {
    const roots = projects.value.map((project) => project.workRoot).filter(Boolean)
    workflowGroups.value = await workflowApi.listGrouped(roots)
    workflows.value = Object.values(workflowGroups.value).flat()
    if (activeWorkflowId.value) {
      const current = workflows.value.find((item) => item.id === activeWorkflowId.value)
      if (current && workflowDefinition.value?.updated_at !== current.updated_at) {
        workflowDefinition.value = current
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

async function selectWorkflow(workflowId: string): Promise<void> {
  if (!workflowId) {
    activeWorkflowId.value = ''
    workflowDefinition.value = null
    selectedNodeId.value = null
    return
  }
  const listed = workflows.value.find((item) => item.id === workflowId)
  const workRoot = workflowRoot(listed)
  try {
    const definition = listed && listed.updated_at ? await workflowApi.getById(workflowId, workRoot) : listed
    if (!definition) throw new Error('工作流不存在')
    activeWorkflowId.value = definition.id
    workflowDefinition.value = definition
    workflowNodeStates.value = {}
    selectedNodeId.value = null
    const sessionId = workflowSessionId(definition)
    await selectSession(sessionId)
  } catch (error) {
    console.error('[workflow] get failed', error)
    workflowStatusText.value = `加载失败：${messageFromError(error)}`
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
  workflowDefinition.value = definition
  scheduleAutosave()
}

function scheduleAutosave(): void {
  if (autosaveTimer) clearTimeout(autosaveTimer)
  autosaveTimer = setTimeout(() => {
    lastSelfSaveAt = Date.now()
    void saveWorkflow(true)
  }, 800)
}

async function renameWorkflow(title: string): Promise<void> {
  const definition = workflowDefinition.value
  const newName = title.trim()
  if (!definition || !newName || newName === definition.name) return
  try {
    const renamed = await workflowApi.rename(definition.name, newName, workflowRoot(definition))
    workflowDefinition.value = renamed
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
  try {
    const saved = await workflowApi.save(definition, workflowRoot(definition))
    workflowDefinition.value = saved
    activeWorkflowId.value = saved.id
    if (!silent) setRuntimeStatus(`已保存：${saved.name}`, 2500)
    if (!silent) await refreshWorkflows()
  } catch (error) {
    console.error('[workflow] save failed', error)
    if (!silent) setRuntimeStatus(`保存失败：${messageFromError(error)}`, 4000)
  }
}

async function runWorkflow(): Promise<void> {
  await executeWorkflowRun(undefined)
}

async function stepWorkflow(): Promise<void> {
  await executeWorkflowRun(1)
}

async function cancelWorkflowRun(): Promise<void> {
  const definition = workflowDefinition.value
  if (!definition || !workflowRunning.value) return
  const threadId = workflowSessionId(definition)
  workflowStatusText.value = '正在停止…'
  try {
    await workflowApi.cancel(threadId, activeRunId.value || undefined)
    workflowNodeStates.value = Object.fromEntries(
      definition.nodes.map((node) => [node.id, workflowNodeStates.value[node.id] === 'done' ? 'done' : 'cancelled']),
    ) as Record<string, NodeStateStatus>
    workflowRunning.value = false
    workflowStatusText.value = '已取消'
  } catch (error) {
    workflowStatusText.value = `停止失败：${messageFromError(error)}`
  }
}

async function executeWorkflowRun(
  maxSteps: number | undefined,
  options: { startNode?: string; singleNode?: string } = {},
): Promise<void> {
  const definition = workflowDefinition.value
  if (!definition || !definition.name) {
    setRuntimeStatus('先保存工作流再运行', 3000)
    return
  }
  if (workflowRunning.value) return
  const runId = newRunId()
  const threadId = workflowSessionId(definition)
  activeRunId.value = runId
  workflowRunning.value = true
  workflowStatusText.value = options.singleNode ? '运行节点…' : options.startNode ? '从此节点运行…' : '运行中…'
  workflowNodeStates.value = Object.fromEntries(definition.nodes.map((node) => [node.id, 'idle'])) as Record<string, NodeStateStatus>
  try {
    const result = await workflowApi.run(definition.name, {
      workRoot: workflowRoot(definition),
      maxSteps,
      startNode: options.startNode,
      singleNode: options.singleNode,
      threadId,
      runId,
    })
    if (activeRunId.value !== result.run_id && result.run_id) return
    activeRunId.value = result.run_id || runId
    workflowNodeStates.value = Object.fromEntries(
      Object.entries(result.run.node_states || {}).map(([nodeId, state]) => [nodeId, state.status || 'idle']),
    ) as Record<string, NodeStateStatus>
    if (result.run.status === 'paused') workflowStatusText.value = '已暂停（单步）'
    else if (result.run.status === 'completed') workflowStatusText.value = '完成'
    else if (result.run.status === 'cancelled') workflowStatusText.value = '已取消'
    else workflowStatusText.value = result.run.status
  } catch (error) {
    if (activeRunId.value === runId) workflowStatusText.value = `运行失败：${messageFromError(error)}`
  } finally {
    if (activeRunId.value === runId || !activeRunId.value) workflowRunning.value = false
  }
}

async function toggleExpose(): Promise<void> {
  const definition = workflowDefinition.value
  if (!definition) return
  try {
    const updated = await workflowApi.setExposed(definition.name, !definition.exposed, workflowRoot(definition))
    workflowDefinition.value = updated
    await refreshWorkflows()
    setRuntimeStatus(updated.exposed ? `已暴露：${updated.tool_name || `workflow_${updated.name}`}` : '已取消暴露', 2500)
  } catch (error) {
    setRuntimeStatus(`操作失败：${messageFromError(error)}`, 4000)
  }
}

function nodeKindIcon(kind: string): LucideIcon {
  if (kind === 'ai') return Cpu
  if (kind === 'command') return Command
  if (kind === 'script') return FileCode2
  if (kind === 'content') return FileText
  if (kind === 'subgraph') return Boxes
  return Command
}

function newRunId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return `workflow_run_${crypto.randomUUID()}`
  return `workflow_run_${Date.now()}_${Math.random().toString(16).slice(2)}`
}

function messageFromError(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
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
  const nodeId = String(nested.node_id || payload.node_id || event.item_id || '')
  const status = String(nested.status || payload.status || '') as NodeStateStatus
  if (!nodeId || !status) return
  workflowNodeStates.value = { ...workflowNodeStates.value, [nodeId]: status }
}

function scheduleGraphReload(): void {
  if (!workflowDefinition.value) return
  if (Date.now() - lastSelfSaveAt < 3000) return
  if (graphReloadTimer) clearTimeout(graphReloadTimer)
  graphReloadTimer = setTimeout(() => {
    const definition = workflowDefinition.value
    if (!definition) return
    void workflowApi.getById(definition.id, workflowRoot(definition))
      .then((fresh) => { workflowDefinition.value = fresh })
      .catch((error) => console.error('[workflow] live graph reload failed', error))
  }, 400)
}

watch(lastEvent, handleRuntimeEvent)
watch(() => chat.messages.value.length, () => {
  if (chat.activeTurnRunning.value) scheduleGraphReload()
})
watch(chat.activeTurnRunning, (running, previous) => {
  if (previous && !running) scheduleGraphReload()
})

onMounted(() => {
  ensureRightPanelOpen()
  void refreshWorkflows()
  void loadAvailableTools()
})

onBeforeUnmount(() => {
  unregisterSurface()
  if (autosaveTimer) clearTimeout(autosaveTimer)
  if (graphReloadTimer) clearTimeout(graphReloadTimer)
})
</script>

<style scoped>
.workflow-view {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 0;
}

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
.wf-create-head h2 { margin: 0; font-size: 15px; font-weight: 700; color: var(--theme-main-text); }
.wf-create-input {
  width: 100%;
  box-sizing: border-box;
  min-height: 32px;
  border: 1px solid color-mix(in srgb, var(--theme-control-text) 12%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--theme-control-background) 70%, transparent);
  color: var(--theme-control-text);
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
.stage-toggle-btn {
  flex: 0 0 auto;
  width: 30px;
  height: 30px;
  border: 1px solid color-mix(in srgb, var(--theme-main-text) 12%, transparent);
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text) 65%, transparent);
  cursor: pointer;
  display: grid;
  place-items: center;
}
.stage-toggle-btn:hover { background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), transparent); }
.stage-toggle-btn.active { background: color-mix(in srgb, var(--theme-main-text) var(--alpha-active), transparent); }

.wf-right-panel { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.wf-right-panel > section { display: flex; flex-direction: column; min-height: 0; }
.wf-right-panel h3 { margin: 0 0 var(--space-2); font-size: 12px; font-weight: 700; color: color-mix(in srgb, var(--theme-main-text) 50%, transparent); }
.wf-right-nodes { flex: 0 0 auto; max-height: 45%; padding: var(--space-3); border-bottom: 1px solid var(--theme-main-border); overflow: auto; }
.wf-node-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 2px; }
.wf-node-list-item { display: flex; align-items: center; gap: var(--space-2); padding: 5px var(--space-2); border-radius: var(--radius-sm); cursor: pointer; font-size: 13px; color: var(--theme-main-text); }
.wf-node-list-item:hover { background: var(--theme-main-soft-background); }
.wf-node-list-item.active { background: color-mix(in srgb, var(--blue) 22%, transparent); }
.wf-node-list-kind { opacity: .7; font-size: 12px; }
.wf-node-list-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wf-right-info { flex: 1 1 auto; padding: var(--space-3); overflow: auto; }
.wf-right-info-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: var(--space-2); }
.wf-right-info-head h3 { margin: 0; color: var(--theme-main-text); }
.wf-right-empty { margin: 0; font-size: 12px; color: color-mix(in srgb, var(--theme-main-text) 40%, transparent); }
.wf-node-info-body { display: grid; gap: var(--space-2); font-size: 12px; }
.wf-node-info-row { display: flex; justify-content: space-between; gap: var(--space-2); margin: 0; }
.wf-node-info-row > span, .wf-node-info-block > span { color: color-mix(in srgb, var(--theme-main-text) 50%, transparent); }
.wf-node-info-block { margin: 0; display: grid; gap: var(--space-1); }
.wf-node-info-block pre { margin: 0; padding: var(--space-2); border-radius: var(--radius-sm); background: var(--theme-main-subtle-background); font-size: 11px; white-space: pre-wrap; word-break: break-word; max-height: 160px; overflow: auto; }
.wf-node-info-block code { font-size: 11px; word-break: break-all; }
.wf-convo-card { display: flex; flex-direction: column; height: 100%; min-height: 0; border: 1px solid var(--theme-main-border); border-radius: var(--radius); background: var(--theme-main-background); overflow: hidden; }
.wf-convo-head, .wf-convo-float-head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--theme-main-border); }
.wf-convo-head h3, .wf-convo-float-head h3 { margin: 0; color: var(--theme-main-text); }
.wf-convo-body { flex: 1 1 auto; min-height: 0; overflow: auto; padding: var(--space-2); }
.wf-convo-float { position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%); z-index: var(--z-modal); width: min(640px, 70vw); height: min(560px, 76vh); display: flex; flex-direction: column; background: var(--theme-main-background); border: 1px solid var(--theme-main-border); border-radius: var(--radius-lg); box-shadow: var(--shadow-lg); pointer-events: auto; }
.wf-convo-float-body { flex: 1 1 auto; min-height: 0; overflow: auto; padding: var(--space-3); }
@media (max-width: 640px) { .wf-convo-float { width: calc(100vw - var(--space-4)); height: calc(100vh - 96px); } }
</style>
