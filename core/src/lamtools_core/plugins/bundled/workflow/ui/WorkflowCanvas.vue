<template>
  <div
    ref="canvasRoot"
    class="wf-canvas"
    role="region"
    aria-label="工作流画布"
    tabindex="0"
    @contextmenu="onContextMenu"
  >
    <div class="wf-canvas-toolbar" role="toolbar" aria-label="画布布局工具">
      <slot name="controls" />
      <span v-if="$slots.controls" class="wf-canvas-toolbar-divider" aria-hidden="true" />
      <button type="button" class="wf-canvas-tool" :class="{ active: gridEnabled }" data-workflow-action="toggle-grid" :aria-pressed="gridEnabled ? 'true' : 'false'" :aria-label="gridEnabled ? '关闭网格吸附' : '开启网格吸附'" :title="gridEnabled ? '关闭网格吸附' : '开启网格吸附'" @click="toggleGrid">
        <Grid2x2 :size="15" :stroke-width="1.8" aria-hidden="true" />
      </button>
      <button type="button" class="wf-canvas-tool" data-workflow-action="align-left" :disabled="layoutSelectionCount < 2 || locked" aria-label="左对齐" title="左对齐" @click="alignSelection('left')">
        <AlignHorizontalJustifyStart :size="15" :stroke-width="1.8" aria-hidden="true" />
      </button>
      <button type="button" class="wf-canvas-tool" data-workflow-action="align-top" :disabled="layoutSelectionCount < 2 || locked" aria-label="顶对齐" title="顶对齐" @click="alignSelection('top')">
        <AlignVerticalJustifyStart :size="15" :stroke-width="1.8" aria-hidden="true" />
      </button>
      <button type="button" class="wf-canvas-tool" data-workflow-action="distribute-horizontal" :disabled="layoutSelectionCount < 3 || locked" aria-label="横向分布" title="横向分布" @click="distributeSelection('horizontal')">
        <AlignHorizontalSpaceBetween :size="15" :stroke-width="1.8" aria-hidden="true" />
      </button>
      <button type="button" class="wf-canvas-tool" data-workflow-action="focus-selected" :disabled="!selectedNodeIds.size && !selectedCanvasElementIds.size" aria-label="聚焦选中" title="聚焦选中" @click="focusSelected">
        <Focus :size="15" :stroke-width="1.8" aria-hidden="true" />
      </button>
      <button type="button" class="wf-canvas-tool" data-workflow-action="fit-view" aria-label="适应画布" title="适应画布" @click="fitCanvas">
        <Maximize2 :size="15" :stroke-width="1.8" aria-hidden="true" />
      </button>
    </div>
    <VueFlow
      v-model:nodes="vfNodes"
      v-model:edges="vfEdges"
      :node-types="nodeTypes"
      :pan-on-drag="[1]"
      :selection-key-code="true"
      :select-nodes-on-drag="false"
      :snap-to-grid="gridEnabled"
      :snap-grid="snapGrid"
      :edges-updatable="!locked"
      :edges-focusable="true"
      :nodes-focusable="true"
      :elevate-nodes-on-select="false"
      :default-viewport="{ zoom: 1 }"
      fit-view-on-init
      @node-click="onNodeClick"
      @connect="onConnect"
      @edge-update="onEdgeUpdate"
      @selection-end="onSelectionEnd"
      @pane-click="handlePaneClick"
      @move-start="handleCanvasInteraction"
      @node-drag-start="handleCanvasInteraction"
    >
      <Background :gap="22" :size="1" pattern-color="transparent" />
      <MiniMap position="bottom-right" :pannable="true" :zoomable="true" aria-label="工作流缩略图" />
    </VueFlow>

    <!-- The pane menu opens the same registry-backed catalog used by the
         inspector. Keeping the picker as a real component gives it search,
         category filters, keyboard focus, and recent/favorite state without
         duplicating node metadata in a context-menu array. -->
    <div
      v-if="nodePickerPos"
      class="wf-node-picker"
      :style="nodePickerStyle"
      @pointerdown.stop
      @click.stop
      @contextmenu.stop
    >
      <WorkflowNodeCatalog
        :schemas="nodeSchemas || {}"
        variant="popover"
        closeable
        @add="addSchemaAtPicker"
        @close="closeNodePicker"
      />
    </div>

    <NodeEditCard
      v-if="editNode"
      :node="editNode"
      :anchor="editAnchor"
      :available-tools="availableTools"
      :schema="schemaForNode(editNode)"
      @close="editNode = null"
      @update="onUpdateNode"
    />
    <EdgeConditionEditor
      v-if="edgeConditionEditor"
      :value="edgeConditionEditor.value"
      :anchor="edgeConditionAnchor"
      @close="edgeConditionEditor = null"
      @save="saveEdgeCondition"
    />
    <CoreConfirmDialog
      :open="bulkDeleteConfirmOpen"
      title="删除容器及其内容"
      :description="bulkDeleteDescription"
      :detail="bulkDeleteDetail"
      :confirm-label="bulkDeleteConfirmLabel"
      :confirm-disabled="bulkDeleteCountdown > 0"
      @confirm="confirmDeleteAllCanvasElement"
      @cancel="cancelDeleteAllCanvasElement"
    />
    <p v-if="portError" class="wf-port-error" role="alert">{{ portError }}</p>
    <p class="wf-canvas-live" role="status" aria-live="polite">{{ canvasLiveMessage }}</p>
  </div>
</template>

<script setup lang="ts">
import { computed, markRaw, onBeforeUnmount, onMounted, provide, ref, watch } from 'vue'
import { VueFlow, useVueFlow, type Node, type Edge } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { MiniMap } from '@vue-flow/minimap'
import {
  AlignHorizontalJustifyStart,
  AlignHorizontalSpaceBetween,
  AlignVerticalJustifyStart,
  Copy,
  Focus,
  Grid2x2,
  Maximize2,
  Pencil,
  Play,
  Plus,
  Scissors,
  Settings,
  Trash2,
} from 'lucide-vue-next'
// Vue Flow styles must load as global CSS (not inside <style scoped> @import,
// which Vite scopes and breaks internal class selectors + load order).
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import WorkflowNodeComp from './WorkflowNode.vue'
import WorkflowCanvasElementComp from './WorkflowCanvasElement.vue'
import WorkflowNodeCatalog from './WorkflowNodeCatalog.vue'
import NodeEditCard from './NodeEditCard.vue'
import EdgeConditionEditor from './EdgeConditionEditor.vue'
import CoreConfirmDialog from '../../../../../../ui/src/components/CoreConfirmDialog.vue'
import { closeContextMenu, contextMenuState, isNativeContextTarget, openContextMenu } from '../../../../../../ui/src/components/context-menu/context-menu'
import type { ContextMenuEntry } from '../../../../../../ui/src/components/context-menu/types'
import type {
  NodeStateStatus,
  WorkflowDef,
  WorkflowHumanTask,
  WorkflowNodeData,
  WorkflowNodeKind,
  WorkflowNodeSchema,
  WorkflowNodeState,
  WorkflowPort,
  WorkflowRunTimelineItem,
} from './types'
import { reconcileWorkflowNodePorts } from './document'
import {
  createWorkflowNodeFromSchema,
  workflowNodeTypeId,
} from './catalog'
import {
  alignWorkflowNodes,
  createWorkflowClipboardPayload,
  deleteWorkflowCanvasElementContents,
  distributeWorkflowNodes,
  hasWorkflowClipboardPayload,
  isWorkflowCanvasContainer,
  readWorkflowClipboardPayload,
  remapWorkflowClipboard,
  workflowCanvasElementContents,
  workflowCanvasElementZIndex,
  writeWorkflowClipboardPayload,
  type WorkflowCanvasElement,
  type WorkflowCanvasElementKind,
  type WorkflowCanvasClipboardPayload,
  type WorkflowNodeAlignment,
  type WorkflowNodeDistribution,
} from './canvas'

const props = defineProps<{
  definition: WorkflowDef
  nodeStates: Record<string, NodeStateStatus>
  nodeStateDetails?: Record<string, WorkflowNodeState>
  timeline?: WorkflowRunTimelineItem[]
  humanTasks?: WorkflowHumanTask[]
  selectedHumanTask?: WorkflowHumanTask | null
  humanTaskLoading?: boolean
  humanTaskBusy?: boolean
  humanTaskError?: string
  onRefreshHumanTasks?: () => void | Promise<void>
  onSelectHumanTask?: (taskId: string) => void | Promise<void>
  onCompleteHumanTask?: (task: WorkflowHumanTask, decision: string, payload: Record<string, unknown>) => void | Promise<void>
  selectedNodeId?: string
  availableTools?: Array<{ name: string; description: string }>
  availableModels?: Array<{ id: string; display_name?: string; model_id?: string }>
  nodeSchemas?: Record<string, WorkflowNodeSchema>
  locked?: boolean
}>()
const emit = defineEmits<{
  'update:definition': [def: WorkflowDef]
  'select-node': [id: string | null]
  'run-from': [nodeId: string]
  'run-node': [nodeId: string]
}>()

const { screenToFlowCoordinate, setInteractive, fitView, setCenter, getSelectedNodes } = useVueFlow()
const nodeTypes = {
  workflow: markRaw(WorkflowNodeComp) as any,
  'workflow-decoration': markRaw(WorkflowCanvasElementComp) as any,
}
watch(() => props.locked, (val) => { setInteractive(!val) }, { immediate: true })

const canvasRoot = ref<HTMLElement | null>(null)
const selectedNodeIds = ref<Set<string>>(new Set())
const selectedCanvasElementIds = ref<Set<string>>(new Set())
const portError = ref('')
const canvasLiveMessage = ref('')
const layoutSelectionCount = computed(() => selectedNodeIds.value.size)
const gridEnabled = ref(true)
const snapGrid = [22, 22] as [number, number]
const workflowEdgeZIndex = 10
const workflowNodeZIndex = 20
const nodePickerPos = ref<MenuPos | null>(null)
const viewportRevision = ref(0)

function readLayoutPixels(name: string, fallback: number): number {
  if (typeof window === 'undefined') return fallback
  const target = canvasRoot.value || document.documentElement
  const value = Number.parseFloat(window.getComputedStyle(target).getPropertyValue(name))
  return Number.isFinite(value) ? Math.max(0, value) : fallback
}

function activeWorkflowNodeZIndex(): number {
  return Math.max(workflowNodeZIndex + 1, readLayoutPixels('--z-composer', 40) - 1)
}

function nodeZIndex(nodeId: string): number {
  const status = props.nodeStates[nodeId] ?? 'idle'
  return status === 'running' || status === 'waiting' ? activeWorkflowNodeZIndex() : workflowNodeZIndex
}

function nodeRuntimeData(node: WorkflowNodeData): Record<string, unknown> {
  return {
    node,
    state: props.nodeStates[node.id] ?? 'idle',
    stateDetail: props.nodeStateDetails?.[node.id] ?? null,
    timeline: (props.timeline ?? []).filter((item) => item.node_id === node.id),
    humanTasks: (props.humanTasks ?? []).filter((task) => task.node_id === node.id),
    selectedHumanTask: props.selectedHumanTask?.node_id === node.id ? props.selectedHumanTask : null,
    humanTaskLoading: props.humanTaskLoading ?? false,
    humanTaskBusy: props.humanTaskBusy ?? false,
    humanTaskError: props.humanTaskError ?? '',
    onRefreshHumanTasks: props.onRefreshHumanTasks,
    onSelectHumanTask: props.onSelectHumanTask,
    onCompleteHumanTask: props.onCompleteHumanTask,
  }
}

function onViewportResize(): void {
  viewportRevision.value += 1
}

const nodePickerStyle = computed(() => {
  const anchor = nodePickerPos.value
  if (!anchor) return {}
  // Keep the popover above the floating composer.  The revision ref makes the
  // computed position follow viewport changes (including mobile rotation).
  void viewportRevision.value
  const viewportWidth = typeof window === 'undefined' ? 1200 : window.innerWidth
  const viewportHeight = typeof window === 'undefined' ? 800 : window.innerHeight
  const panelWidth = Math.min(380, Math.max(320, viewportWidth - 24))
  const titlebarOffset = readLayoutPixels('--titlebar-offset', 0)
  const composerHeight = readLayoutPixels('--composer-height', 120)
  const composerBottomOffset = readLayoutPixels('--composer-bottom-offset', 0)
  const composerRestBottom = readLayoutPixels('--composer-rest-bottom', 16)
  const edgePadding = 12
  const safeTop = Math.max(edgePadding, titlebarOffset + edgePadding)
  const safeBottom = Math.max(safeTop, viewportHeight - composerHeight - composerBottomOffset - composerRestBottom - edgePadding)
  const panelHeight = Math.min(620, Math.max(0, safeBottom - safeTop))
  return {
    left: `${Math.max(12, Math.min(anchor.x, viewportWidth - panelWidth - 12))}px`,
    top: `${Math.max(safeTop, Math.min(anchor.y, safeBottom - panelHeight))}px`,
    maxHeight: `${panelHeight}px`,
  }
})

// Provide an update callback so WorkflowNode components can edit fields inline.
provide('wf-update-node', (nodeId: string, patch: Partial<WorkflowNodeData>) => {
  const previous = props.definition.nodes.find((node) => node.id === nodeId)
  if (!previous) return
  const next = { ...previous, ...patch, config: { ...previous.config, ...(patch.config || {}) } }
  const reconciled = reconcileWorkflowNodePorts(props.definition, previous, next)
  if (!reconciled.ok) {
    portError.value = reconciled.reason
    return
  }
  portError.value = ''
  emit('update:definition', reconciled.definition)
})
// Provide available models so WorkflowNode can render a model dropdown.
provide('wf-models', () => props.availableModels ?? [])
provide('wf-node-schemas', () => props.nodeSchemas ?? {})
provide('wf-canvas-locked', () => props.locked === true)
provide('wf-update-canvas-element', (elementId: string, patch: Partial<WorkflowCanvasElement>) => {
  const elements = props.definition.canvas_elements ?? []
  if (!elements.some((element) => element.id === elementId)) return
  emit('update:definition', {
    ...props.definition,
    canvas_elements: elements.map((element) => element.id === elementId ? { ...element, ...patch } : element),
  })
})
provide('wf-select-canvas-element-contents', (elementId: string) => selectCanvasElementContents(elementId, true))

// ---- WorkflowDef <-> VueFlow mapping ----
const vfNodes = ref<Node[]>([])
const vfEdges = ref<Edge[]>([])
let syncing = false

// Re-sync from the definition only when the structural identity (node/edge
// ids) or node content (title/config/ports) changes — NOT on every position
// update. Otherwise dragging a node emits update:definition, the parent
// rewrites the def ref, this watch fires, and syncFromDefinition resets
// vfNodes positions mid-drag (causing flicker/jump back). Position is owned
// by Vue Flow during drag and only emitted outward.
let lastSignature = ''
function _nodeSignature(n: WorkflowNodeData): string {
  // position intentionally excluded — it's owned by the canvas during drag.
  // Config keys are sorted so a server round-trip that reorders them doesn't
  // trigger a spurious re-sync (which would reset dragged positions).
  const sortedConfig = JSON.stringify(n.config, Object.keys(n.config).sort())
  return [n.id, n.kind, n.type_id, n.type_version, n.title, n.parent_id, sortedConfig, n.ports.map((p) => `${p.id || p.name}:${p.name}:${p.direction}:${p.type}:${p.required ? 'required' : ''}:${p.lazy ? 'lazy' : ''}`).join(',')].join('::')
}
function _canvasElementSignature(element: WorkflowCanvasElement): string {
  return [element.id, element.kind, element.title, element.text, element.width, element.height, element.parent_id, element.color, element.collapsed].join('::')
}
function syncFromDefinition() {
  const sig = props.definition.nodes.map(_nodeSignature).join('||')
    + '##' + props.definition.edges.map((e) => [e.id, e.source, e.source_port, e.target, e.target_port, e.transform, e.condition].join(':')).join('|')
    + '##' + (props.definition.canvas_elements ?? []).map(_canvasElementSignature).join('||')
  if (sig === lastSignature) {
    return
  }
  lastSignature = sig
  syncing = true
  const knownNodeIds = new Set(props.definition.nodes.map((node) => node.id))
  const canvasElements = props.definition.canvas_elements ?? []
  const knownCanvasIds = new Set(canvasElements.map((element) => element.id))
  selectedNodeIds.value = new Set([...selectedNodeIds.value].filter((id) => knownNodeIds.has(id)))
  selectedCanvasElementIds.value = new Set([...selectedCanvasElementIds.value].filter((id) => knownCanvasIds.has(id)))
  if (props.selectedNodeId && knownNodeIds.has(props.selectedNodeId)) selectedNodeIds.value.add(props.selectedNodeId)
  const decorationNodes = canvasElements.map((element) => ({
    id: element.id,
    type: 'workflow-decoration',
    position: element.position ?? { x: 0, y: 0 },
    width: element.width,
    height: element.height,
    zIndex: element.z_index ?? workflowCanvasElementZIndex(element.kind),
    data: { element },
    selected: selectedCanvasElementIds.value.has(element.id),
    draggable: selectedCanvasElementIds.value.has(element.id),
    class: selectedCanvasElementIds.value.has(element.id) ? 'wf-canvas-element-selected' : '',
    ariaLabel: `${element.title || element.id}，${element.kind}`,
  } as Node & { selected: boolean }))
  const workflowNodes = props.definition.nodes.map((n) => ({
    id: n.id,
    type: 'workflow',
    position: n.position ?? { x: 0, y: 0 },
    zIndex: nodeZIndex(n.id),
    data: nodeRuntimeData(n),
    selected: selectedNodeIds.value.has(n.id),
    draggable: selectedNodeIds.value.has(n.id),
    class: selectedNodeIds.value.has(n.id) ? 'wf-node-selected' : '',
  } as Node & { selected: boolean }))
  // Frames are emitted first so they remain visually behind executable nodes.
  vfNodes.value = [...decorationNodes, ...workflowNodes] as Node[]
  vfEdges.value = props.definition.edges.map((e): Edge => ({
    id: e.id,
    source: e.source,
    target: e.target,
    sourceHandle: edgePortHandle(e, 'source'),
    targetHandle: edgePortHandle(e, 'target'),
    zIndex: workflowEdgeZIndex,
    updatable: !props.locked,
    focusable: true,
    ariaLabel: `${e.source}.${e.source_port} → ${e.target}.${e.target_port}`,
  })) as Edge[]
  queueMicrotask(() => { syncing = false })
}

watch(() => props.definition, syncFromDefinition, { deep: false, immediate: true })
// Runtime changes update node data and active z-order in place WITHOUT
// touching positions or graph structure.
watch(() => [
  props.nodeStates,
  props.nodeStateDetails,
  props.timeline,
  props.humanTasks,
  props.selectedHumanTask,
  props.humanTaskLoading,
  props.humanTaskBusy,
  props.humanTaskError,
], () => {
  vfNodes.value = vfNodes.value.map((n) => ({
    ...n,
    ...(n.type === 'workflow'
      ? {
          zIndex: nodeZIndex(n.id),
          data: nodeRuntimeData((n.data as { node: WorkflowNodeData }).node),
        }
      : {}),
  }))
}, { deep: false })
watch(() => props.selectedNodeId, (id) => {
  if (!id) selectedNodeIds.value = new Set()
  else if (!selectedNodeIds.value.has(id)) selectedNodeIds.value = new Set([id])
  vfNodes.value = vfNodes.value.map((n) => ({
    ...n,
    selected: n.type === 'workflow-decoration'
      ? selectedCanvasElementIds.value.has(n.id)
      : selectedNodeIds.value.has(n.id),
    draggable: n.type === 'workflow-decoration'
      ? selectedCanvasElementIds.value.has(n.id)
      : selectedNodeIds.value.has(n.id),
    class: n.type === 'workflow-decoration'
      ? (selectedCanvasElementIds.value.has(n.id) ? 'wf-canvas-element-selected' : '')
      : (selectedNodeIds.value.has(n.id) ? 'wf-node-selected' : ''),
  }))
})

watch(vfNodes, (nodes) => {
  if (syncing) return
  const posById = new Map(nodes.map((n) => [n.id, n.position]))
  emit('update:definition', {
    ...props.definition,
    nodes: props.definition.nodes.map((n) => ({ ...n, position: posById.get(n.id) ?? n.position })),
    ...(props.definition.canvas_elements
      ? { canvas_elements: props.definition.canvas_elements.map((element) => ({ ...element, position: posById.get(element.id) ?? element.position })) }
      : {}),
  })
}, { deep: true })

watch(vfEdges, (edges) => {
  if (syncing) return
  emit('update:definition', {
    ...props.definition,
    edges: edges.map((e) => {
      const existing = props.definition.edges.find((de) => de.id === e.id)
      const sourceHandle = String(e.sourceHandle ?? '')
      const targetHandle = String(e.targetHandle ?? '')
      const sourcePortId = workflowPortId(e.source, sourceHandle, 'out', existing?.source_port_id)
      const targetPortId = workflowPortId(e.target, targetHandle, 'in', existing?.target_port_id)
      return {
        id: e.id,
        source: e.source,
        source_port: workflowPortName(e.source, sourceHandle, 'out', existing?.source_port ?? ''),
        ...(sourcePortId ? { source_port_id: sourcePortId } : {}),
        target: e.target,
        target_port: workflowPortName(e.target, targetHandle, 'in', existing?.target_port ?? ''),
        ...(targetPortId ? { target_port_id: targetPortId } : {}),
        transform: existing?.transform ?? '',
        condition: existing?.condition ?? '',
      }
    }),
  })
}, { deep: true })

// ---- edge condition helpers ----
function edgeCondition(edgeId: string): string {
  const e = props.definition.edges.find((ed) => ed.id === edgeId)
  if (!e?.condition) return ''
  return typeof e.condition === 'string' ? e.condition : JSON.stringify(e.condition)
}
function setEdgeCondition(edgeId: string, value: string) {
  emit('update:definition', {
    ...props.definition,
    edges: props.definition.edges.map((e) =>
      e.id === edgeId ? { ...e, condition: value } : e
    ),
  })
}

// ---- context menus ----
type MenuPos = { x: number; y: number }
const editNode = ref<WorkflowNodeData | null>(null)
const editAnchor = ref<MenuPos>({ x: 0, y: 0 })
const clipboard = ref<WorkflowCanvasClipboardPayload | null>(null)
const edgeConditionEditor = ref<{ id: string; value: string } | null>(null)
const edgeConditionAnchor = ref<MenuPos>({ x: 0, y: 0 })
const clipboardAvailable = computed(() => Boolean(clipboard.value) || hasWorkflowClipboardPayload())
const bulkDeleteTargetId = ref<string | null>(null)
const bulkDeleteCountdown = ref(0)
const bulkDeleteConfirmOpen = computed(() => bulkDeleteTargetId.value !== null)
const bulkDeleteTarget = computed(() => (props.definition.canvas_elements ?? [])
  .find((element) => element.id === bulkDeleteTargetId.value))
const bulkDeleteContents = computed(() => bulkDeleteTarget.value
  ? workflowCanvasElementContents(props.definition, bulkDeleteTarget.value.id)
  : { nodeIds: [], canvasElementIds: [] })
const bulkDeleteDescription = computed(() => {
  const title = bulkDeleteTarget.value?.title || bulkDeleteTarget.value?.id || '此容器'
  const count = bulkDeleteContents.value.nodeIds.length + bulkDeleteContents.value.canvasElementIds.length
  return `确定删除“${title}”及其内部 ${count} 个元素？此操作不可撤销。`
})
const bulkDeleteDetail = computed(() => {
  const { nodeIds, canvasElementIds } = bulkDeleteContents.value
  return `节点 ${nodeIds.length} · 画布元素 ${canvasElementIds.length}`
})
const bulkDeleteConfirmLabel = computed(() => bulkDeleteCountdown.value > 0
  ? `确认（${bulkDeleteCountdown.value}秒）`
  : '确认删除')
let bulkDeleteTimer: number | null = null

function clearBulkDeleteTimer(): void {
  if (bulkDeleteTimer !== null) {
    window.clearInterval(bulkDeleteTimer)
    bulkDeleteTimer = null
  }
}

function closeBulkDeleteConfirm(): void {
  clearBulkDeleteTimer()
  bulkDeleteTargetId.value = null
  bulkDeleteCountdown.value = 0
}

function requestDeleteAllCanvasElement(id: string): void {
  if (props.locked) return
  const element = (props.definition.canvas_elements ?? []).find((item) => item.id === id)
  if (!isWorkflowCanvasContainer(element)) return
  clearBulkDeleteTimer()
  bulkDeleteTargetId.value = id
  bulkDeleteCountdown.value = 3
  bulkDeleteTimer = window.setInterval(() => {
    bulkDeleteCountdown.value = Math.max(0, bulkDeleteCountdown.value - 1)
    if (bulkDeleteCountdown.value === 0) clearBulkDeleteTimer()
  }, 1000)
  closeContextMenu()
}

function cancelDeleteAllCanvasElement(): void {
  closeBulkDeleteConfirm()
}

function confirmDeleteAllCanvasElement(): void {
  if (bulkDeleteCountdown.value > 0) return
  const id = bulkDeleteTargetId.value
  closeBulkDeleteConfirm()
  if (id) deleteCanvasElementContents(id)
}

onBeforeUnmount(() => {
  closeBulkDeleteConfirm()
  if (contextMenuState.ownerId?.startsWith('workflow:')) closeContextMenu()
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('resize', onViewportResize)
  window.visualViewport?.removeEventListener('resize', onViewportResize)
})

// Single native contextmenu handler on the canvas root. Detects whether the
// right-click hit a Vue Flow node (DOM traversal to .vue-flow__node[data-id])
// and shows the node menu, otherwise the pane menu. Vue Flow is configured to
// pan only with the middle mouse button (`pan-on-drag="[1]"`); the right
// button is reserved for this context menu and never starts a canvas pan.
function workflowMenuOwner(kind: 'pane' | 'node' | 'edge' | 'element', id = ''): string {
  return `workflow:${kind}${id ? `:${id}` : ''}`
}

function workflowMenuAttributes(kind: 'pane' | 'node' | 'edge' | 'element', id = ''): Record<string, string> {
  return { 'data-workflow-context-menu': id ? `${kind}:${id}` : kind }
}

function handleCanvasInteraction(): void {
  closeContextMenu()
  edgeConditionEditor.value = null
  closeNodePicker()
}

function handlePaneClick(): void {
  handleCanvasInteraction()
  setSelection([])
}

function buildPaneMenu(pos: MenuPos): ContextMenuEntry[] {
  const selectedCount = selectedNodeIds.value.size + selectedCanvasElementIds.value.size
  return [
    { type: 'label', label: '新建节点' },
    { id: 'add-node-catalog', label: '添加节点…', icon: Plus, action: () => openNodePicker(pos) },
    { type: 'separator', id: 'decoration-separator' },
    { type: 'label', label: '画布元素' },
    { id: 'frame', label: '框架', action: () => addCanvasElementAt('frame', pos) },
    { id: 'group', label: '分组', action: () => addCanvasElementAt('group', pos) },
    { id: 'note', label: '便签', action: () => addCanvasElementAt('note', pos) },
    { id: 'comment', label: '注释', action: () => addCanvasElementAt('comment', pos) },
    { id: 'reroute', label: '中继点', action: () => addCanvasElementAt('reroute', pos) },
    { type: 'separator', id: 'paste-separator' },
    { id: 'paste', label: '粘贴', shortcut: '⌘/Ctrl V', disabled: !clipboardAvailable.value, action: () => pasteAt(pos) },
    ...(selectedCount > 0 ? [
      { type: 'separator' as const, id: 'selection-separator' },
      { id: 'delete-selection', label: `删除选中元素（${selectedCount}）`, icon: Trash2, destructive: true, disabled: props.locked === true, action: deleteSelectedNodes },
      { type: 'submenu' as const, id: 'layout', label: '布局', children: [
        { id: 'align-left', label: '左对齐', disabled: selectedNodeIds.value.size < 2, action: () => alignSelection('left') },
        { id: 'align-center', label: '水平居中', disabled: selectedNodeIds.value.size < 2, action: () => alignSelection('center') },
        { id: 'align-top', label: '顶对齐', disabled: selectedNodeIds.value.size < 2, action: () => alignSelection('top') },
        { id: 'distribute-horizontal', label: '横向分布', disabled: selectedNodeIds.value.size < 3, action: () => distributeSelection('horizontal') },
        { id: 'distribute-vertical', label: '纵向分布', disabled: selectedNodeIds.value.size < 3, action: () => distributeSelection('vertical') },
        { id: 'focus-selected', label: '聚焦选中', action: focusSelected },
      ] },
    ] : []),
  ]
}

function buildNodeMenu(id: string): ContextMenuEntry[] {
  return [
    { type: 'label', label: '运行' },
    { id: 'run-from', label: '从此节点运行', icon: Play, action: () => runFromNode(id) },
    { id: 'run-node', label: '运行此节点', icon: Play, action: () => runNode(id) },
    { type: 'separator', id: 'node-config-separator' },
    { id: 'configure', label: '配置', icon: Settings, action: () => configNode(id) },
    { id: 'copy', label: '复制', shortcut: '⌘/Ctrl C', icon: Copy, action: () => copyNode(id) },
    { id: 'cut', label: '剪切', icon: Scissors, action: () => cutNode(id) },
    { type: 'separator', id: 'node-port-separator' },
    { id: 'add-input', label: '+ 输入端口', icon: Plus, action: () => addPort(id, 'in') },
    { id: 'add-output', label: '+ 输出端口', icon: Plus, action: () => addPort(id, 'out') },
    { type: 'separator', id: 'node-danger-separator' },
    { id: 'delete', label: '删除', icon: Trash2, destructive: true, action: () => deleteNode(id) },
  ]
}

function buildCanvasElementMenu(id: string): ContextMenuEntry[] {
  const element = (props.definition.canvas_elements ?? []).find((item) => item.id === id)
  if (isWorkflowCanvasContainer(element)) {
    return [
      { id: 'select-contents', label: '全选', action: () => selectCanvasElementContents(id) },
      { type: 'separator', id: 'element-copy-separator' },
      { id: 'copy', label: '复制', shortcut: '⌘/Ctrl C', icon: Copy, action: () => copyCanvasElement(id) },
      { id: 'cut', label: '剪切', shortcut: '⌘/Ctrl X', icon: Scissors, action: () => cutCanvasElement(id) },
      { type: 'separator', id: 'element-danger-separator' },
      { id: 'delete', label: '删除', icon: Trash2, destructive: true, disabled: props.locked === true, action: () => deleteCanvasElements(new Set([id])) },
      { id: 'delete-all', label: '全部删除', icon: Trash2, destructive: true, disabled: props.locked === true, action: () => requestDeleteAllCanvasElement(id) },
    ]
  }
  return [
    { id: 'copy', label: '复制', shortcut: '⌘/Ctrl C', icon: Copy, action: () => copyCanvasElement(id) },
    { id: 'cut', label: '剪切', shortcut: '⌘/Ctrl X', icon: Scissors, action: () => cutCanvasElement(id) },
    { type: 'separator', id: 'element-danger-separator' },
    { id: 'delete', label: '删除', icon: Trash2, destructive: true, disabled: props.locked === true, action: () => deleteCanvasElements(new Set([id])) },
  ]
}

function editEdgeCondition(id: string, anchor: MenuPos): void {
  edgeConditionEditor.value = { id, value: edgeCondition(id) }
  edgeConditionAnchor.value = anchor
  closeContextMenu()
}

function buildEdgeMenu(id: string, anchor: MenuPos): ContextMenuEntry[] {
  return [
    { id: 'condition', label: '编辑条件', icon: Pencil, action: () => editEdgeCondition(id, anchor) },
    { type: 'separator', id: 'edge-danger-separator' },
    { id: 'delete', label: '删除连线', icon: Trash2, destructive: true, action: () => deleteEdge(id) },
  ]
}

function setSelection(ids: Iterable<string>): void {
  const selected = new Set(ids)
  const nodeIds = new Set(props.definition.nodes.map((node) => node.id))
  const elementIds = new Set((props.definition.canvas_elements ?? []).map((element) => element.id))
  selectedNodeIds.value = new Set([...selected].filter((id) => nodeIds.has(id)))
  selectedCanvasElementIds.value = new Set([...selected].filter((id) => elementIds.has(id)))
  const selectedFlowNodes: Node[] = []
  for (const node of vfNodes.value as unknown as Array<Record<string, any>>) {
    const isSelected = node.type === 'workflow-decoration'
      ? selectedCanvasElementIds.value.has(String(node.id))
      : selectedNodeIds.value.has(String(node.id))
    selectedFlowNodes.push({
      ...node,
      selected: isSelected,
      draggable: isSelected,
      class: node.type === 'workflow-decoration'
        ? (selectedCanvasElementIds.value.has(String(node.id)) ? 'wf-canvas-element-selected' : '')
        : (selectedNodeIds.value.has(String(node.id)) ? 'wf-node-selected' : ''),
    } as unknown as Node)
  }
  vfNodes.value = selectedFlowNodes
  emit('select-node', [...selectedNodeIds.value].at(-1) ?? null)
}

function selectCanvasElementContents(elementId: string, includeContainer = false): void {
  const element = (props.definition.canvas_elements ?? []).find((item) => item.id === elementId)
  if (!isWorkflowCanvasContainer(element)) return
  handleCanvasInteraction()
  const contents = workflowCanvasElementContents(props.definition, elementId)
  setSelection([...(includeContainer ? [elementId] : []), ...contents.nodeIds, ...contents.canvasElementIds])
  const count = contents.nodeIds.length + contents.canvasElementIds.length
  canvasLiveMessage.value = includeContainer
    ? (count ? `已选中容器及其 ${count} 个内部元素` : '已选中容器')
    : (count ? `已全选 ${count} 个内部元素` : '容器内没有可选元素')
}

function onContextMenu(evt: MouseEvent) {
  if (isNativeContextTarget(evt.target)) return
  const x = evt.clientX
  const y = evt.clientY
  edgeConditionEditor.value = null
  closeNodePicker()
  let el = evt.target as HTMLElement | null
  let nodeId = ''
  let edgeId = ''
  let canvasElementId = ''
  while (el && el !== evt.currentTarget) {
    if (el.classList?.contains('vue-flow__node')) {
      nodeId = el.getAttribute('data-id') || ''
      break
    }
    if (el.classList?.contains('vue-flow__edge')) {
      edgeId = el.getAttribute('data-id') || ''
      break
    }
    el = el.parentElement
  }
  let items: ContextMenuEntry[]
  let ownerId: string
  let menuKind: 'pane' | 'node' | 'edge' | 'element'
  if (edgeId && props.definition.edges.some((e) => e.id === edgeId)) {
    menuKind = 'edge'
    ownerId = workflowMenuOwner(menuKind, edgeId)
    items = buildEdgeMenu(edgeId, { x, y })
  } else if (nodeId && props.definition.nodes.some((n) => n.id === nodeId)) {
    menuKind = 'node'
    ownerId = workflowMenuOwner(menuKind, nodeId)
    items = buildNodeMenu(nodeId)
  } else if (nodeId && (props.definition.canvas_elements ?? []).some((element) => element.id === nodeId)) {
    canvasElementId = nodeId
    menuKind = 'element'
    ownerId = workflowMenuOwner(menuKind, canvasElementId)
    items = buildCanvasElementMenu(canvasElementId)
  } else {
    menuKind = 'pane'
    ownerId = workflowMenuOwner(menuKind)
    items = buildPaneMenu({ x, y })
  }
  openContextMenu({
    event: evt,
    items,
    ownerId,
    ariaLabel: menuKind === 'pane' ? '工作流画布操作' : menuKind === 'node' ? '工作流节点操作' : menuKind === 'edge' ? '工作流连线操作' : '画布元素操作',
    panelAttributes: workflowMenuAttributes(menuKind, menuKind === 'pane' ? '' : menuKind === 'node' ? nodeId : menuKind === 'edge' ? edgeId : canvasElementId),
  })
}

// ---- node click → select + config ----
// Left-click and right-click "配置" share this path: select the node and
// open the edit card. The card uses a centered, screen-safe position (not
// the mouse coords) so it never overflows the viewport regardless of where
// the click landed.
function onNodeClick(params: any) {
  const id = params?.node?.id
  if (!id) return
  const event = params?.event as MouseEvent | undefined
  const additive = Boolean(event?.metaKey || event?.ctrlKey || event?.shiftKey)
  const isDecoration = (props.definition.canvas_elements ?? []).some((element) => element.id === id)
  const next = new Set([...selectedNodeIds.value, ...selectedCanvasElementIds.value])
  if (additive) {
    if (next.has(id)) next.delete(id)
    else next.add(id)
  } else {
    next.clear()
    next.add(id)
  }
  setSelection(next)
  if (isDecoration) emit('select-node', null)
}

function onSelectionEnd(): void {
  const next = new Set(getSelectedNodes.value.map((node) => node.id))
  setSelection(next)
}
function configNode(id: string) {
  if (!props.definition.nodes.some((n) => n.id === id)) return
  emit('select-node', id)
  openEdit(id)
}
function openEdit(id: string, x?: number, y?: number) {
  const n = props.definition.nodes.find((node) => node.id === id)
  if (n) {
    editNode.value = n
    editAnchor.value = { x: x ?? window.innerWidth / 2, y: y ?? 120 }
  }
  portError.value = ''
  edgeConditionEditor.value = null
  closeContextMenu()
}

function schemaForNode(node: WorkflowNodeData | null | undefined): WorkflowNodeSchema | null {
  if (!node) return null
  const schemas = props.nodeSchemas || {}
  const typeId = String(node.type_id || '').trim()
  return (typeId && schemas[typeId]) || schemas[node.kind] || null
}

function saveEdgeCondition(value: string): void {
  const editor = edgeConditionEditor.value
  if (!editor) return
  setEdgeCondition(editor.id, value)
  edgeConditionEditor.value = null
}

// ---- node mutations ----
// Vue Flow fires `connect` when the user finishes dragging a handle-to-handle
// connection; it does NOT auto-create an edge, so we add it here.
function onConnect(params: { source: string; target: string; sourceHandle?: string | null; targetHandle?: string | null }) {
  if (!connectionIsValid(params)) {
    canvasLiveMessage.value = '无法连接：端口类型不兼容或端口不存在'
    return
  }
  const sourceHandle = params.sourceHandle ?? ''
  const targetHandle = params.targetHandle ?? ''
  if (vfEdges.value.some((edge) => edge.source === params.source
    && edge.target === params.target
    && (edge.sourceHandle ?? '') === sourceHandle
    && (edge.targetHandle ?? '') === targetHandle)) return
  const id = `e-${params.source}-${params.sourceHandle ?? ''}-${params.target}-${params.targetHandle ?? ''}`
  if (vfEdges.value.some((e) => e.id === id)) return
  const edge = {
    id,
    source: params.source,
    target: params.target,
    sourceHandle: params.sourceHandle ?? undefined,
    targetHandle: params.targetHandle ?? undefined,
  }
  // Cast through unknown to avoid Vue Flow's deeply-recursive Edge generic
  // (TS2589); the shape is correct at runtime.
  ;(vfEdges.value as Edge[]).push(edge as unknown as Edge)
}

/** Vue Flow emits this when either end of an existing edge is dragged. */
function onEdgeUpdate(params: any): void {
  if (props.locked) return
  const edgeId = String(params?.edge?.id || '')
  const connection = params?.connection
  if (!edgeId || !connection || !connectionIsValid(connection)) {
    canvasLiveMessage.value = '无法更新连线：端口类型不兼容或端口不存在'
    return
  }
  if (vfEdges.value.some((edge) => edge.id !== edgeId
    && edge.source === connection.source
    && edge.sourceHandle === connection.sourceHandle
    && edge.target === connection.target
    && edge.targetHandle === connection.targetHandle)) {
    canvasLiveMessage.value = '该连线已经存在'
    return
  }
  const updatedEdges: Edge[] = []
  for (const edge of vfEdges.value as unknown as Array<Record<string, any>>) {
    updatedEdges.push((edge.id === edgeId ? {
      ...edge,
      source: connection.source,
      target: connection.target,
      sourceHandle: connection.sourceHandle ?? undefined,
      targetHandle: connection.targetHandle ?? undefined,
    } : edge) as unknown as Edge)
  }
  vfEdges.value = updatedEdges
  canvasLiveMessage.value = '连线已更新'
}

function connectionIsValid(params: { source?: string | null; target?: string | null; sourceHandle?: string | null; targetHandle?: string | null }): boolean {
  const source = props.definition.nodes.find((node) => node.id === params.source)
  const target = props.definition.nodes.find((node) => node.id === params.target)
  if (!source || !target || !params.sourceHandle || !params.targetHandle) return false
  const sourcePort = source.ports.find((port) => (port.id === params.sourceHandle || port.name === params.sourceHandle) && port.direction === 'out')
  const targetPort = target.ports.find((port) => (port.id === params.targetHandle || port.name === params.targetHandle) && port.direction === 'in')
  return Boolean(sourcePort && targetPort && _typesCompatible(sourcePort.type, targetPort.type))
}

type WorkflowEdgeWithPortIds = WorkflowDef['edges'][number] & {
  source_port_id?: string
  target_port_id?: string
}

function edgePortHandle(edge: WorkflowEdgeWithPortIds, side: 'source' | 'target'): string {
  const id = side === 'source' ? edge.source_port_id : edge.target_port_id
  const name = side === 'source' ? edge.source_port : edge.target_port
  return String(id || name || '')
}

function workflowPortForHandle(
  nodeId: string,
  handle: string,
  direction: 'in' | 'out',
): WorkflowPort | undefined {
  const node = props.definition.nodes.find((item) => item.id === nodeId)
  return node?.ports.find((port) => port.direction === direction && (port.id === handle || port.name === handle))
}

function workflowPortName(
  nodeId: string,
  handle: string,
  direction: 'in' | 'out',
  fallback: string,
): string {
  return workflowPortForHandle(nodeId, handle, direction)?.name || fallback || handle
}

function workflowPortId(
  nodeId: string,
  handle: string,
  direction: 'in' | 'out',
  fallback?: string,
): string | undefined {
  const port = workflowPortForHandle(nodeId, handle, direction)
  return String(port?.id || fallback || '') || undefined
}

function openNodePicker(pos: MenuPos): void {
  if (props.locked) return
  closeContextMenu({ restoreFocus: false })
  nodePickerPos.value = { ...pos }
}

function closeNodePicker(): void {
  nodePickerPos.value = null
}

function addSchemaAtPicker(schema: WorkflowNodeSchema): void {
  const pos = nodePickerPos.value
  if (!pos) return
  addNodeFromSchema(schema, pos)
}

function addNodeFromSchema(schema: WorkflowNodeSchema, pos: MenuPos): void {
  if (props.locked) return
  const flowPos = safeScreenToFlow(pos)
  const typeId = workflowNodeTypeId(schema) || 'node'
  const base = typeId.replace(/[^a-zA-Z0-9_-]/g, '-').toLowerCase() || 'node'
  let id = `${base}-${props.definition.nodes.length + 1}`
  let serial = props.definition.nodes.length + 1
  while (props.definition.nodes.some((node) => node.id === id)) id = `${base}-${++serial}`
  const node = createWorkflowNodeFromSchema(schema, id, flowPos)
  if (node.kind === 'script' || node.kind === 'python') {
    node.config.script = scaffoldScript(node.title, node.ports)
  }
  emit('update:definition', { ...props.definition, nodes: [...props.definition.nodes, node] })
  setSelection([node.id])
  canvasLiveMessage.value = `已添加节点：${node.title}`
  closeNodePicker()
  closeContextMenu()
}

function addCanvasElementAt(kind: WorkflowCanvasElementKind, pos: MenuPos): void {
  if (props.locked) return
  const flowPos = safeScreenToFlow(pos)
  const count = (props.definition.canvas_elements ?? []).filter((element) => element.kind === kind).length + 1
  const defaults: Record<WorkflowCanvasElementKind, { width: number; height: number; title: string }> = {
    group: { width: 420, height: 260, title: `分组.${count}` },
    frame: { width: 420, height: 260, title: `框架.${count}` },
    reroute: { width: 28, height: 28, title: `中继.${count}` },
    note: { width: 240, height: 130, title: `便签.${count}` },
    comment: { width: 280, height: 110, title: `注释.${count}` },
  }
  const id = `${kind}-${newIdSuffix()}`
  const preset = defaults[kind]
  const element: WorkflowCanvasElement = {
    id,
    kind,
    position: flowPos,
    width: preset.width,
    height: preset.height,
    title: preset.title,
    text: kind === 'reroute' ? '' : '',
    z_index: workflowCanvasElementZIndex(kind),
    ...(kind === 'note' ? { color: '#d59f27' } : {}),
  }
  emit('update:definition', { ...props.definition, canvas_elements: [...(props.definition.canvas_elements ?? []), element] })
  setSelection([id])
  closeContextMenu()
}

function newIdSuffix(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID().slice(0, 8)
  return Math.random().toString(36).slice(2, 10)
}

function alignSelection(alignment: WorkflowNodeAlignment): void {
  if (props.locked || selectedNodeIds.value.size < 2) return
  const selected = props.definition.nodes.filter((node) => selectedNodeIds.value.has(node.id))
  const aligned = alignWorkflowNodes(selected, alignment)
  const positions = new Map(aligned.map((node) => [node.id, node.position]))
  emit('update:definition', { ...props.definition, nodes: props.definition.nodes.map((node) => ({ ...node, position: positions.get(node.id) ?? node.position })) })
  canvasLiveMessage.value = '节点已对齐'
  closeContextMenu()
}

function distributeSelection(direction: WorkflowNodeDistribution): void {
  if (props.locked || selectedNodeIds.value.size < 3) return
  const selected = props.definition.nodes.filter((node) => selectedNodeIds.value.has(node.id))
  const distributed = distributeWorkflowNodes(selected, direction)
  const positions = new Map(distributed.map((node) => [node.id, node.position]))
  emit('update:definition', { ...props.definition, nodes: props.definition.nodes.map((node) => ({ ...node, position: positions.get(node.id) ?? node.position })) })
  canvasLiveMessage.value = direction === 'horizontal' ? '节点已横向分布' : '节点已纵向分布'
  closeContextMenu()
}

function focusSelected(): void {
  const ids = [...selectedNodeIds.value, ...selectedCanvasElementIds.value]
  if (!ids.length) return fitCanvas()
  const flowNodes = getSelectedNodes.value.filter((node) => ids.includes(node.id))
  if (flowNodes.length > 1) {
    void fitView({ nodes: flowNodes.map((node) => node.id), padding: 0.25, duration: 0 })
    return
  }
  const node = flowNodes[0]
  if (!node) return
  const width = Number(node.dimensions?.width || node.width || 180)
  const height = Number(node.dimensions?.height || node.height || 100)
  const position = node.computedPosition || node.position
  void setCenter(position.x + width / 2, position.y + height / 2, { zoom: 1.1, duration: 0 })
}

function defaultTitle(kind: WorkflowNodeKind): string {
  const count = props.definition.nodes.filter((n) => n.kind === kind).length + 1
  return `${kind}.${count}`
}
// Default ports per kind — content has output-only; subgraph has in/result;
// ai/command/script get a generic in/out pair.
function defaultPorts(kind: WorkflowNodeKind) {
  if (kind === 'content' || kind === 'constant' || kind === 'input') {
    return [{ name: 'out', type: 'string', direction: 'out' as const, value: '' }]
  }
  if (kind === 'subgraph') {
    return [
      { name: 'in', type: 'any', direction: 'in' as const },
      { name: 'result', type: 'any', direction: 'out' as const },
    ]
  }
  return [
    { name: 'in', type: 'string', direction: 'in' as const },
    { name: 'out', type: 'string', direction: 'out' as const },
  ]
}

// Starter Python scaffold for a new script node: lists input port names
// (available as variables) and output port names (assign to produce output)
// as comments + a TODO placeholder per output. Mirrors the backend scaffold
// in workflow_build_tools._scaffold_script.
function scaffoldScript(_title: string, ports: WorkflowPort[]): string {
  const inPorts = ports.filter((p) => p.direction === 'in')
  const outPorts = ports.filter((p) => p.direction === 'out')
  const safeId = (n: string) => (/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(n || '') ? (n || 'value') : (n || 'value').replace(/[^a-zA-Z0-9_]/g, '_') || 'value')
  const inNames = inPorts.map((p) => safeId(p.name))
  const outNames = outPorts.map((p) => safeId(p.name))
  const lines = [
    `# 输入：${inNames.length ? inNames.join(', ') : '（无）'}`,
    `# 输出：${outNames.length ? outNames.join(', ') : '（无）'}`,
    '',
  ]
  for (const name of outNames) lines.push(`${name} = None`)
  return lines.join('\n') + '\n'
}

// Type compatibility check mirroring the backend _types_compatible.
function _typesCompatible(src: string, dst: string): boolean {
  const norm = (t: string) => {
    const aliases: Record<string, string> = { text: 'string', str: 'string', int: 'number', integer: 'number', float: 'number', bool: 'boolean', dict: 'object', list: 'array' }
    const lower = (t || 'any').toLowerCase().trim()
    return aliases[lower] ?? (['string', 'number', 'boolean', 'object', 'array', 'any'].includes(lower) ? lower : 'any')
  }
  const s = norm(src), d = norm(dst)
  if (s === 'any' || d === 'any' || s === d) return true
  if ((s === 'number' || s === 'boolean') && d === 'string') return true
  return false
}

function onUpdateNode(updated: WorkflowNodeData) {
  const previous = props.definition.nodes.find((node) => node.id === updated.id)
  if (!previous) return
  const reconciled = reconcileWorkflowNodePorts(props.definition, previous, updated)
  if (!reconciled.ok) {
    portError.value = reconciled.reason
    return
  }
  portError.value = ''
  emit('update:definition', reconciled.definition)
  editNode.value = null
}

function addPort(id: string, direction: 'in' | 'out') {
  const node = props.definition.nodes.find((n) => n.id === id)
  if (!node) return
  const existing = node.ports.filter((p) => p.direction === direction)
  const newPort = { id: `${direction}-${newIdSuffix()}`, name: `${direction}${existing.length + 1}`, type: 'any', direction }
  emit('update:definition', {
    ...props.definition,
    nodes: props.definition.nodes.map((n) =>
      n.id === id ? { ...n, ports: [...n.ports, newPort] } : n
    ),
  })
  closeContextMenu()
}

function deleteNode(id: string) {
  deleteNodes(new Set([id]))
}

function deleteSelectedNodes(): void {
  if (props.locked || (!selectedNodeIds.value.size && !selectedCanvasElementIds.value.size)) return
  const deletedNodes = new Set(selectedNodeIds.value)
  const deletedElements = new Set(selectedCanvasElementIds.value)
  emit('update:definition', {
    ...props.definition,
    nodes: props.definition.nodes
      .filter((node) => !deletedNodes.has(node.id))
      .map((node) => deletedElements.has(node.parent_id || '') || deletedNodes.has(node.parent_id || '')
        ? { ...node, parent_id: undefined }
        : node),
    edges: props.definition.edges.filter((edge) => !deletedNodes.has(edge.source) && !deletedNodes.has(edge.target)),
    ...(props.definition.canvas_elements
      ? { canvas_elements: props.definition.canvas_elements.filter((element) => !deletedElements.has(element.id)).map((element) => deletedElements.has(element.parent_id || '') ? { ...element, parent_id: undefined } : element) }
      : {}),
  })
  selectedNodeIds.value = new Set()
  selectedCanvasElementIds.value = new Set()
  emit('select-node', null)
  closeContextMenu()
}

function deleteNodes(ids: Set<string>): void {
  if (props.locked || !ids.size) return
  const existing = new Set(props.definition.nodes.map((node) => node.id))
  const deleted = new Set([...ids].filter((id) => existing.has(id)))
  if (!deleted.size) return
  emit('update:definition', {
    ...props.definition,
    nodes: props.definition.nodes
      .filter((node) => !deleted.has(node.id))
      .map((node) => deleted.has(node.parent_id || '') ? { ...node, parent_id: undefined } : node),
    edges: props.definition.edges.filter((edge) => !deleted.has(edge.source) && !deleted.has(edge.target)),
  })
  selectedNodeIds.value = new Set([...selectedNodeIds.value].filter((id) => !deleted.has(id)))
  if (!selectedNodeIds.value.size) emit('select-node', null)
  closeContextMenu()
}
function deleteCanvasElements(ids: Set<string>): void {
  if (props.locked || !ids.size) return
  const existing = props.definition.canvas_elements ?? []
  const deleted = new Set([...ids].filter((id) => existing.some((element) => element.id === id)))
  if (!deleted.size) return
  emit('update:definition', {
    ...props.definition,
    nodes: props.definition.nodes.map((node) => deleted.has(node.parent_id || '') ? { ...node, parent_id: undefined } : node),
    canvas_elements: existing
      .filter((element) => !deleted.has(element.id))
      .map((element) => deleted.has(element.parent_id || '') ? { ...element, parent_id: undefined } : element),
  })
  selectedCanvasElementIds.value = new Set([...selectedCanvasElementIds.value].filter((id) => !deleted.has(id)))
  closeContextMenu()
}

function deleteCanvasElementContents(id: string): void {
  if (props.locked) return
  const result = deleteWorkflowCanvasElementContents(props.definition, id)
  if (!result.deletedCanvasElementIds.includes(id)) return
  emit('update:definition', {
    ...props.definition,
    nodes: result.nodes,
    edges: result.edges,
    canvas_elements: result.canvas_elements,
  })
  const deletedNodes = new Set(result.deletedNodeIds)
  const deletedElements = new Set(result.deletedCanvasElementIds)
  selectedNodeIds.value = new Set([...selectedNodeIds.value].filter((nodeId) => !deletedNodes.has(nodeId)))
  selectedCanvasElementIds.value = new Set([...selectedCanvasElementIds.value].filter((elementId) => !deletedElements.has(elementId)))
  emit('select-node', [...selectedNodeIds.value].at(-1) ?? null)
  canvasLiveMessage.value = `已全部删除容器及其 ${result.deletedNodeIds.length + result.deletedCanvasElementIds.length - 1} 个内部元素`
  closeContextMenu()
}

function deleteEdge(id: string) {
  emit('update:definition', {
    ...props.definition,
    edges: props.definition.edges.filter((e) => e.id !== id),
  })
  closeContextMenu()
}

function copyNode(id: string) {
  copySelection(id)
}
function cutNode(id: string) {
  void copySelection(id).then(() => deleteNodes(new Set([id])))
}
function copyCanvasElement(id: string): void {
  void copySelection(id)
}
function cutCanvasElement(id: string): void {
  void copySelection(id).then(() => deleteCanvasElements(new Set([id])))
}
async function copySelection(singleId?: string): Promise<void> {
  const ids = singleId
    ? new Set([singleId, ...(selectedNodeIds.value.has(singleId) || selectedCanvasElementIds.value.has(singleId) ? [...selectedNodeIds.value, ...selectedCanvasElementIds.value] : [])])
    : new Set([...selectedNodeIds.value, ...selectedCanvasElementIds.value])
  if (!ids.size) return
  const payload = createWorkflowClipboardPayload(props.definition, ids)
  if (!payload.nodes.length && !payload.canvas_elements.length) return
  clipboard.value = payload
  await writeWorkflowClipboardPayload(payload)
  canvasLiveMessage.value = `已复制 ${payload.nodes.length + payload.canvas_elements.length} 个元素`
  closeContextMenu()
}
async function pasteAt(pos?: MenuPos): Promise<void> {
  const payload = await readWorkflowClipboardPayload()
  if (!payload) return
  clipboard.value = payload
  const flowPos = pos ? safeScreenToFlow(pos) : undefined
  const existingIds = [
    ...props.definition.nodes.map((node) => node.id),
    ...(props.definition.canvas_elements ?? []).map((element) => element.id),
    ...props.definition.edges.map((edge) => edge.id),
  ]
  const pasted = remapWorkflowClipboard(payload, existingIds, flowPos)
  if (!pasted.nodes.length && !pasted.canvas_elements.length) return
  emit('update:definition', {
    ...props.definition,
    nodes: [...props.definition.nodes, ...pasted.nodes],
    edges: [...props.definition.edges, ...pasted.edges],
    canvas_elements: [...(props.definition.canvas_elements ?? []), ...pasted.canvas_elements],
  })
  setSelection([...pasted.nodes.map((node) => node.id), ...pasted.canvas_elements.map((element) => element.id)])
  canvasLiveMessage.value = `已粘贴 ${pasted.nodes.length + pasted.canvas_elements.length} 个元素`
  closeContextMenu()
}

function runFromNode(id: string) { emit('run-from', id); closeContextMenu() }
function runNode(id: string) { emit('run-node', id); closeContextMenu() }

watch(() => props.definition.edges, (edges) => {
  if (edgeConditionEditor.value && !edges.some((edge) => edge.id === edgeConditionEditor.value?.id)) {
    edgeConditionEditor.value = null
  }
}, { deep: false })

function safeScreenToFlow(pos: MenuPos): { x: number; y: number } {
  try { return screenToFlowCoordinate(pos) } catch { return { x: 100 + Math.random() * 200, y: 80 + Math.random() * 120 } }
}

function isEditableTarget(target: EventTarget | null): boolean {
  const element = target as HTMLElement | null
  return Boolean(element?.closest('input, textarea, select, [contenteditable="true"]'))
}

function fitCanvas(): void {
  void fitView({ padding: 0.2, duration: 0 })
}

function toggleGrid(): void {
  gridEnabled.value = !gridEnabled.value
  canvasLiveMessage.value = gridEnabled.value ? '网格吸附已开启' : '网格吸附已关闭'
}

function nudgeSelection(dx: number, dy: number): void {
  if (props.locked || !selectedNodeIds.value.size) return
  emit('update:definition', {
    ...props.definition,
    nodes: props.definition.nodes.map((node) => selectedNodeIds.value.has(node.id)
      ? { ...node, position: { x: node.position.x + dx, y: node.position.y + dy } }
      : node),
  })
}

function onKeydown(event: KeyboardEvent): void {
  if (!canvasRoot.value?.contains(event.target as unknown as globalThis.Node)) return
  if (isEditableTarget(event.target)) return
  const modifier = event.metaKey || event.ctrlKey
  const key = event.key.toLowerCase()
  if ((event.key === 'Delete' || event.key === 'Backspace') && (selectedNodeIds.value.size || selectedCanvasElementIds.value.size)) {
    event.preventDefault()
    deleteSelectedNodes()
    return
  }
  if (event.key === 'Escape') {
    event.preventDefault()
    setSelection([])
    edgeConditionEditor.value = null
    closeNodePicker()
    closeContextMenu()
    return
  }
  if (modifier && key === 'a') {
    event.preventDefault()
    setSelection([...props.definition.nodes.map((node) => node.id), ...(props.definition.canvas_elements ?? []).map((element) => element.id)])
    return
  }
  if (modifier && key === 'c') {
    event.preventDefault()
    void copySelection()
    return
  }
  if (modifier && key === 'x') {
    event.preventDefault()
    void copySelection().then(deleteSelectedNodes)
    return
  }
  if (modifier && key === 'v') {
    event.preventDefault()
    void pasteAt()
    return
  }
  if (!modifier && ['arrowleft', 'arrowright', 'arrowup', 'arrowdown'].includes(key)) {
    event.preventDefault()
    const step = event.shiftKey ? 10 : 1
    nudgeSelection(key === 'arrowleft' ? -step : key === 'arrowright' ? step : 0, key === 'arrowup' ? -step : key === 'arrowdown' ? step : 0)
    return
  }
  if (!modifier && key === 'g') {
    event.preventDefault()
    toggleGrid()
    return
  }
  if (modifier && event.shiftKey && key === 'f') {
    event.preventDefault()
    focusSelected()
    return
  }
  if (modifier && key === '0') {
    event.preventDefault()
    fitCanvas()
  }
}

async function refreshClipboard(): Promise<void> {
  const payload = await readWorkflowClipboardPayload()
  if (payload) clipboard.value = payload
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  window.addEventListener('resize', onViewportResize)
  window.visualViewport?.addEventListener('resize', onViewportResize)
  void refreshClipboard()
})

</script>

<style scoped>

.wf-canvas {
  /* Fill the entire workspace-main (ignore its padding) so the whole main
     area is the canvas, not a small sub-region. Background is transparent so
     the canvas blends with the main surface (simple/restrained). */
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  background: transparent;
  outline: 0;
}
.wf-canvas:focus-visible { box-shadow: inset 0 0 0 2px color-mix(in srgb, var(--blue) 50%, transparent); }
.wf-canvas-toolbar {
  position: absolute;
  top: calc(var(--space-6) * 3);
  bottom: calc(var(--space-6) * 3);
  left: var(--space-3);
  z-index: var(--z-main-surface);
  display: flex;
  width: 36px;
  flex-direction: column;
  align-items: center;
  gap: var(--space-1);
  overflow-x: hidden;
  overflow-y: auto;
  padding: var(--space-1);
  border: 1px solid var(--theme-main-border);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--theme-main-background) 92%, transparent);
  box-shadow: var(--shadow-sm);
  transform: none;
}
.wf-canvas-toolbar-divider {
  flex: 0 0 1px;
  width: calc(100% - var(--space-2));
  background: var(--theme-main-border);
}
.wf-canvas-tool {
  display: grid;
  place-items: center;
  flex: 0 0 28px;
  width: 28px;
  height: 28px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--theme-main-text);
  padding: 0;
  cursor: pointer;
}
.wf-canvas-tool:hover:not(:disabled) { background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), transparent); }
.wf-canvas-tool.active { background: color-mix(in srgb, var(--blue) 14%, transparent); color: var(--blue); }
.wf-canvas-tool:focus-visible { outline: 2px solid var(--blue); outline-offset: -2px; }
.wf-canvas-tool:disabled { cursor: not-allowed; opacity: .42; }
.wf-canvas-live { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; }
.wf-canvas :deep(.vue-flow) { background: transparent; }
.wf-canvas :deep(.vue-flow__background circle) { fill: color-mix(in srgb, var(--theme-main-text) 14%, transparent); }
.wf-canvas :deep(.vue-flow__node) { width: auto; }
.wf-node-picker {
  position: fixed;
  z-index: var(--z-popover);
  pointer-events: auto;
}
.wf-canvas :deep(.vue-flow__node.selected .wf-node) {
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--blue) 70%, transparent), var(--shadow);
}
.wf-canvas :deep(.vue-flow__node.wf-node-selected .wf-node) {
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--blue) 70%, transparent), var(--shadow-sm);
}
.wf-canvas :deep(.vue-flow__node.wf-canvas-element-selected .wf-canvas-element) {
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--blue) 70%, transparent), var(--shadow-sm);
}
.wf-canvas :deep(.vue-flow__minimap) {
  border: 1px solid var(--theme-main-border);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--theme-main-background) 92%, transparent);
  box-shadow: var(--shadow-sm);
}
.wf-port-error {
  position: absolute;
  left: var(--space-3);
  right: var(--space-3);
  bottom: var(--space-3);
  z-index: var(--z-toast);
  margin: 0;
  padding: var(--space-2) var(--space-3);
  border: 1px solid color-mix(in srgb, var(--red) 45%, var(--theme-main-border));
  border-radius: var(--radius-sm);
  background: var(--theme-main-background);
  color: var(--red);
  box-shadow: var(--shadow-md);
  font-size: 12px;
}
@media (prefers-reduced-motion: reduce) {
  .wf-canvas :deep(.vue-flow__node),
  .wf-canvas :deep(.vue-flow__minimap) {
    transition: none;
    animation: none;
  }
}
@media (max-width: 680px) {
  .wf-canvas :deep(.vue-flow__minimap) { display: none; }
}
</style>
