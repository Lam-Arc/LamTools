<template>
  <div class="workflow-inspector">
    <section class="wf-inspector-section wf-exposure-section" aria-labelledby="wf-exposure-title">
      <header class="wf-exposure-head">
        <div>
          <h3 id="wf-exposure-title">Agent 工具</h3>
          <p>{{ workflowDefinition?.exposed ? (workflowDefinition.tool_name || '已暴露') : '仅在需要时暴露给 Agent' }}</p>
        </div>
        <button
          type="button"
          class="text-btn wf-exposure-toggle"
          :class="{ 'is-on': workflowDefinition?.exposed }"
          :disabled="workflowRunning || !workflowDefinition"
          :aria-pressed="workflowDefinition?.exposed ? 'true' : 'false'"
          :aria-label="workflowDefinition?.exposed ? '取消暴露为 Agent 工具' : '暴露为 Agent 工具'"
          :title="workflowDefinition?.exposed ? '取消暴露为 Agent 工具' : '暴露为 Agent 工具'"
          @click="toggleExpose"
        >
          <EyeOff v-if="workflowDefinition?.exposed" :size="14" :stroke-width="1.8" aria-hidden="true" />
          <Eye v-else :size="14" :stroke-width="1.8" aria-hidden="true" />
        </button>
      </header>
    </section>
    <WorkflowTriggersPanel
      :workflow-definition="workflowDefinition"
      :activations="activations"
      :activations-loading="activationsLoading"
      :activation-busy="activationBusy"
      :on-update-definition="onUpdateDefinition"
      :on-refresh-activations="onRefreshActivations"
      :on-activate="onActivateTrigger"
      :on-deactivate="onDeactivateTrigger"
    />
    <WorkflowPoliciesPanel
      :workflow-definition="workflowDefinition"
      :disabled="workflowRunning"
      :on-update-definition="onUpdateDefinition"
    />
    <HumanTaskPanel
      :tasks="humanTasks"
      :selected-task="selectedHumanTask"
      :loading="humanTaskLoading"
      :busy="humanTaskBusy"
      :error="humanTaskError"
      :on-refresh="refreshHumanTasks"
      :on-select="selectHumanTask"
      :on-complete="completeHumanTask"
    />
    <WorkflowNodeCatalog :schemas="nodeSchemas" @add="addNode" />
    <WorkflowRunInputForm
      v-if="workflowDefinition?.input_params?.length"
      :params="workflowDefinition.input_params"
      :disabled="workflowRunning"
      @submit="runWithInputs"
    />
    <WorkflowQueuePanel
      :items="queueItems"
      :history="historyItems"
      :selected-item="selectedQueueItem"
      :loading="queueLoading"
      :disabled="workflowRunning"
      :on-refresh="refreshQueue"
      :on-enqueue="enqueueWorkflow"
      :on-cancel="cancelQueuedRun"
      :on-inspect="inspectQueuedRun"
      :on-clear="clearQueue"
    />
    <WorkflowResourcesPanel
      :workflow="workflowDefinition"
      :templates="templates"
      :on-import="importWorkflow"
      :on-export="exportWorkflow"
      :on-template="useTemplate"
    />
    <section class="wf-inspector-section wf-right-nodes">
      <h3>节点</h3>
      <ul v-if="workflowDefinition?.nodes.length" class="wf-node-list">
        <li
          v-for="node in workflowDefinition.nodes"
          :key="node.id"
          class="wf-node-list-item"
          :class="{ active: node.id === selectedNodeId }"
          :aria-current="node.id === selectedNodeId ? 'true' : undefined"
          tabindex="0"
          @click="selectNode(node.id)"
          @keydown.enter.prevent="selectNode(node.id)"
          @keydown.space.prevent="selectNode(node.id)"
        >
          <span class="wf-node-list-kind" aria-hidden="true">
            <component :is="nodeKindIcon(node.type_id || node.kind)" :size="12" :stroke-width="1.8" />
          </span>
          <span class="wf-node-list-title" :title="node.title || node.id">{{ node.title || node.id }}</span>
        </li>
      </ul>
      <p v-else class="wf-right-empty">暂无节点</p>
    </section>

    <section class="wf-right-info wf-inspector-section">
      <template v-if="selectedNodeId">
        <div class="wf-right-info-head">
          <h3>{{ selectedNode?.title || selectedNodeId }}</h3>
          <button type="button" class="text-btn" title="返回对话" @click="selectNode(null)">
            <ArrowLeft :size="14" :stroke-width="1.8" aria-hidden="true" />
          </button>
        </div>
        <div v-if="selectedNode" class="wf-node-info-body">
          <p class="wf-node-info-row"><span>类型</span><strong>{{ selectedNode.type_id || selectedNode.kind }}</strong></p>
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
            <button type="button" class="text-btn" title="放大" aria-label="放大对话" @click="expandConversation">
              <Maximize2 :size="14" :stroke-width="1.8" aria-hidden="true" />
            </button>
          </header>
          <div class="wf-convo-body">
            <ChatThread
              :messages="chat.messages.value"
              :process-expanded-ids="chat.processExpandedIds.value"
              :message-actions="true"
              :transport="transport"
              :project-id="projectId"
              :work-root="workRoot || undefined"
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
        </div>
      </template>
    </section>
  </div>
</template>

<script setup lang="ts">
import {
  ArrowDownToLine,
  ArrowLeft,
  ArrowUpFromLine,
  Blocks,
  Bot,
  Braces,
  BrainCircuit,
  Clock3,
  Combine,
  Eye,
  EyeOff,
  FileCode2,
  GitBranch,
  GitMerge,
  Maximize2,
  Sparkles,
  Terminal,
  TextQuote,
  UserCheck,
  Variable,
  Workflow,
  type LucideIcon,
} from 'lucide-vue-next'
import type { CorePluginChatContext } from '../../../../../../ui/src/plugins/context'
import type { LamToolsTransport } from '../../../../../../ui/src/transport'
import ChatThread from '../../../../../../ui/src/components/ChatThread.vue'
import type {
  WorkflowDef,
  WorkflowNodeSchema,
  WorkflowNode,
  WorkflowNodeState,
  WorkflowQueueItem,
  WorkflowRunResult,
  WorkflowActivation,
} from './types'
import WorkflowNodeCatalog from './WorkflowNodeCatalog.vue'
import WorkflowRunInputForm from './WorkflowRunInputForm.vue'
import WorkflowQueuePanel from './WorkflowQueuePanel.vue'
import WorkflowResourcesPanel from './WorkflowResourcesPanel.vue'
import WorkflowTriggersPanel from './WorkflowTriggersPanel.vue'
import WorkflowPoliciesPanel from './WorkflowPoliciesPanel.vue'
import HumanTaskPanel from './HumanTaskPanel.vue'
import type { WorkflowExportFormat, WorkflowImportSource, WorkflowTemplate } from './resources'

const props = withDefaults(defineProps<{
  workflowDefinition?: WorkflowDef | null
  selectedNodeId?: string | null
  selectedNode?: WorkflowNode | null
  workflowRun?: WorkflowRunResult | null
  workflowNodeStateEntries?: WorkflowNodeState[]
  nodeSchemas?: Record<string, WorkflowNodeSchema>
  workflowRunning?: boolean
  queueItems?: WorkflowQueueItem[]
  historyItems?: WorkflowQueueItem[]
  selectedQueueItem?: WorkflowQueueItem | null
  queueLoading?: boolean
  activations?: WorkflowActivation[]
  activationsLoading?: boolean
  activationBusy?: boolean
  templates?: WorkflowTemplate[]
  chat: CorePluginChatContext
  transport: LamToolsTransport
  projectId?: string | null
  workRoot?: string | null
  onSelectNode?: (id: string | null) => void
  onExpandConversation?: () => void
  onAddNode?: (schema: WorkflowNodeSchema) => void | Promise<void>
  onRunWithInputs?: (inputs: Record<string, unknown>) => void | Promise<void>
  onRefreshQueue?: () => void | Promise<void>
  onEnqueueWorkflow?: () => void | Promise<void>
  onCancelQueuedRun?: (item: WorkflowQueueItem) => void | Promise<void>
  onInspectQueuedRun?: (item: WorkflowQueueItem) => void | Promise<void>
  onClearQueue?: (all: boolean) => void | Promise<void>
  onImportWorkflow?: (source: WorkflowImportSource) => void | Promise<void>
  onExportWorkflow?: (format: WorkflowExportFormat) => boolean | void | Promise<boolean | void>
  onUseTemplate?: (template: WorkflowTemplate) => void | Promise<void>
  onToggleExpose?: () => void | Promise<void>
  onUpdateDefinition?: (definition: WorkflowDef) => void | Promise<void>
  onRefreshActivations?: () => void | Promise<void>
  onActivateTrigger?: (triggerId: string, replace: boolean) => void | Promise<void>
  onDeactivateTrigger?: (triggerId: string) => void | Promise<void>
  humanTasks?: import('./types').WorkflowHumanTask[]
  selectedHumanTask?: import('./types').WorkflowHumanTask | null
  humanTaskLoading?: boolean
  humanTaskBusy?: boolean
  humanTaskError?: string
  onRefreshHumanTasks?: () => void | Promise<void>
  onSelectHumanTask?: (taskId: string) => void | Promise<void>
  onCompleteHumanTask?: (task: import('./types').WorkflowHumanTask, decision: string, payload: Record<string, unknown>) => void | Promise<void>
}>(), {
  workflowDefinition: null,
  selectedNodeId: null,
  selectedNode: null,
  workflowRun: null,
  workflowNodeStateEntries: () => [],
  nodeSchemas: () => ({}),
  workflowRunning: false,
  queueItems: () => [],
  historyItems: () => [],
  selectedQueueItem: null,
  queueLoading: false,
  activations: () => [],
  activationsLoading: false,
  activationBusy: false,
  templates: () => [],
  projectId: null,
  workRoot: null,
  onSelectNode: undefined,
  onExpandConversation: undefined,
  onAddNode: undefined,
  onRunWithInputs: undefined,
  onRefreshQueue: undefined,
  onEnqueueWorkflow: undefined,
  onCancelQueuedRun: undefined,
  onInspectQueuedRun: undefined,
  onClearQueue: undefined,
  onImportWorkflow: undefined,
  onExportWorkflow: undefined,
  onUseTemplate: undefined,
  onToggleExpose: undefined,
  onUpdateDefinition: undefined,
  onRefreshActivations: undefined,
  onActivateTrigger: undefined,
  onDeactivateTrigger: undefined,
  humanTasks: () => [],
  selectedHumanTask: null,
  humanTaskLoading: false,
  humanTaskBusy: false,
  humanTaskError: '',
  onRefreshHumanTasks: undefined,
  onSelectHumanTask: undefined,
  onCompleteHumanTask: undefined,
})

function selectNode(id: string | null): void {
  props.onSelectNode?.(id)
}

function expandConversation(): void {
  props.onExpandConversation?.()
}

function addNode(schema: WorkflowNodeSchema): void {
  void props.onAddNode?.(schema)
}

function runWithInputs(inputs: Record<string, unknown>): void {
  void props.onRunWithInputs?.(inputs)
}

function refreshQueue(): void { void props.onRefreshQueue?.() }
function enqueueWorkflow(): void { void props.onEnqueueWorkflow?.() }
function cancelQueuedRun(item: WorkflowQueueItem): void { void props.onCancelQueuedRun?.(item) }
function inspectQueuedRun(item: WorkflowQueueItem): void { void props.onInspectQueuedRun?.(item) }
function clearQueue(all: boolean): void { void props.onClearQueue?.(all) }
function importWorkflow(source: WorkflowImportSource): void { void props.onImportWorkflow?.(source) }
function exportWorkflow(format: WorkflowExportFormat): boolean | void | Promise<boolean | void> { return props.onExportWorkflow?.(format) }
function useTemplate(template: WorkflowTemplate): void { void props.onUseTemplate?.(template) }
function toggleExpose(): void { void props.onToggleExpose?.() }
function onUpdateDefinition(definition: WorkflowDef): void { void props.onUpdateDefinition?.(definition) }
function onRefreshActivations(): void { void props.onRefreshActivations?.() }
function onActivateTrigger(triggerId: string, replace: boolean): void { void props.onActivateTrigger?.(triggerId, replace) }
function onDeactivateTrigger(triggerId: string): void { void props.onDeactivateTrigger?.(triggerId) }
function refreshHumanTasks(): void { void props.onRefreshHumanTasks?.() }
function selectHumanTask(taskId: string): void { void props.onSelectHumanTask?.(taskId) }
function completeHumanTask(task: import('./types').WorkflowHumanTask, decision: string, payload: Record<string, unknown>): void {
  void props.onCompleteHumanTask?.(task, decision, payload)
}

function workflowNodeTitle(nodeId: string): string {
  const node = props.workflowDefinition?.nodes.find((item) => item.id === nodeId)
  return node?.title || nodeId
}

function nodeKindIcon(kind: string): LucideIcon {
  const icons: Record<string, LucideIcon> = {
    model: BrainCircuit,
    agent: Bot,
    approval: UserCheck,
    command: Terminal,
    python: FileCode2,
    constant: Variable,
    input: ArrowDownToLine,
    output: ArrowUpFromLine,
    template: TextQuote,
    condition: GitBranch,
    merge: GitMerge,
    join: Combine,
    wait_event: Clock3,
    subgraph: Workflow,
    // Compatibility ids remain visible when they already exist in a graph.
    ai: Sparkles,
    script: FileCode2,
    content: Braces,
  }
  return icons[String(kind || '').trim().toLowerCase()] || Blocks
}
</script>

<style scoped>
.workflow-inspector { --inspector-text: var(--theme-backdrop-text); display: flex; flex-direction: column; min-width: 0; color: var(--inspector-text); font-size: 12px; line-height: 1.45; }
.wf-inspector-section { display: flex; flex-direction: column; min-height: 0; border-bottom: 1px solid color-mix(in srgb, var(--inspector-text) 10%, transparent); }
.workflow-inspector h3 { margin: 0 0 var(--space-2); color: var(--inspector-text); font-size: 12px; font-weight: 700; }
.wf-exposure-section { flex: 0 0 auto; padding: var(--space-3); }
.wf-exposure-head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); }
.wf-exposure-head h3 { margin: 0; }
.wf-exposure-head p { margin: var(--space-1) 0 0; color: color-mix(in srgb, var(--inspector-text) 58%, transparent); font-size: 10px; }
.wf-exposure-toggle.is-on { color: var(--green); }
.wf-exposure-toggle:disabled { opacity: .45; cursor: default; }
.wf-right-nodes { flex: 0 0 auto; max-height: 38vh; padding: var(--space-3); overflow: auto; }
.wf-node-list { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--space-1); }
.wf-node-list-item { display: flex; align-items: center; gap: var(--space-2); min-width: 0; padding: var(--space-1) var(--space-2); border-radius: var(--radius-sm); color: var(--inspector-text); cursor: pointer; outline: 0; }
.wf-node-list-item:hover { background: color-mix(in srgb, var(--inspector-text) var(--alpha-hover), transparent); }
.wf-node-list-item.active { background: color-mix(in srgb, var(--blue) 22%, transparent); }
.wf-node-list-item:focus-visible { box-shadow: 0 0 0 2px color-mix(in srgb, var(--blue) 60%, transparent); }
.wf-node-list-kind { color: color-mix(in srgb, var(--inspector-text) 68%, transparent); display: inline-flex; }
.wf-node-list-title { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wf-right-info { flex: 1 1 auto; padding: var(--space-3); overflow: auto; }
.wf-right-info-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: var(--space-2); }
.wf-right-info-head h3 { margin: 0; }
.wf-right-empty { margin: 0; color: color-mix(in srgb, var(--inspector-text) 42%, transparent); font-size: 12px; }
.wf-node-info-body { display: grid; gap: var(--space-2); font-size: 12px; }
.wf-node-info-row { display: flex; justify-content: space-between; gap: var(--space-2); margin: 0; }
.wf-node-info-row > span, .wf-node-info-block > span { color: color-mix(in srgb, var(--inspector-text) 56%, transparent); }
.wf-node-info-block { margin: 0; display: grid; gap: var(--space-1); }
.wf-node-info-block pre { margin: 0; max-height: 160px; overflow: auto; padding: var(--space-2); border-radius: var(--radius-sm); background: color-mix(in srgb, var(--theme-backdrop-background) 82%, var(--theme-main-background)); font-size: 11px; white-space: pre-wrap; word-break: break-word; }
.wf-node-info-block code { font-size: 11px; word-break: break-all; }
.wf-convo-card { display: flex; flex-direction: column; min-height: 320px; border: 1px solid color-mix(in srgb, var(--inspector-text) 12%, transparent); border-radius: var(--radius); background: color-mix(in srgb, var(--theme-backdrop-background) 72%, transparent); overflow: hidden; }
.wf-convo-head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); padding: var(--space-2) var(--space-3); border-bottom: 1px solid color-mix(in srgb, var(--inspector-text) 10%, transparent); }
.wf-convo-head h3 { margin: 0; }
.wf-convo-body { flex: 1 1 auto; min-height: 0; max-height: 46vh; overflow: auto; padding: var(--space-2); }
.text-btn { display: inline-flex; align-items: center; justify-content: center; min-width: 28px; min-height: 28px; padding: 0 var(--space-1); border: 0; border-radius: var(--radius-sm); background: transparent; color: color-mix(in srgb, var(--inspector-text) 68%, transparent); cursor: pointer; }
.text-btn:hover { background: color-mix(in srgb, var(--inspector-text) var(--alpha-hover), transparent); color: var(--inspector-text); }
.text-btn:active { background: color-mix(in srgb, var(--inspector-text) var(--alpha-active), transparent); }
.text-btn:focus-visible { outline: 2px solid color-mix(in srgb, var(--blue) 75%, transparent); outline-offset: 1px; }
@media (max-width: 640px) { .text-btn { min-width: 44px; min-height: 44px; } }
@media (prefers-reduced-motion: reduce) { .workflow-inspector *, .workflow-inspector { transition: none; animation: none; } }
</style>
