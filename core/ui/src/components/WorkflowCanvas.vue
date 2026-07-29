<template>
  <div class="wf-canvas">
    <VueFlow
      v-model:nodes="vfNodes"
      v-model:edges="vfEdges"
      :node-types="nodeTypes"
      :default-viewport="{ zoom: 1 }"
      fit-view-on-init
      @pane-context-menu="onPaneContextMenu"
      @node-context-menu="onNodeContextMenu"
      @node-click="onNodeClick"
    >
      <Background />
      <Controls />
    </VueFlow>
    <div v-if="menu" class="wf-context-menu" :style="{ left: menu.x + 'px', top: menu.y + 'px' }" @pointerdown.stop>
      <button class="menu-item" type="button" @click="addNode('llm'); menu = null">添加 LLM 节点</button>
      <button class="menu-item" type="button" @click="addNode('agent'); menu = null">添加 Agent 节点</button>
      <button class="menu-item" type="button" @click="addNode('action'); menu = null">添加 Action 节点</button>
      <button class="menu-item" type="button" @click="emit('save'); menu = null">保存工作流</button>
    </div>

    <NodeEditCard
      v-if="editNode"
      :node="editNode"
      :anchor="editAnchor"
      @close="editNode = null"
      @update="onUpdateNode"
    />

    <WorkflowControlBar
      :running="running"
      :status-text="statusText"
      @run="emit('run')"
      @step="emit('step')"
      @save="emit('save')"
      @add-node="addNode('action')"
      @zoom-in="zoomBy(1.2)"
      @zoom-out="zoomBy(0.8)"
      @zoom-reset="resetZoom"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, markRaw, ref, watch } from 'vue'
import { VueFlow, useVueFlow, type Node, type Edge } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import WorkflowNodeComp from './WorkflowNode.vue'
import NodeEditCard from './NodeEditCard.vue'
import WorkflowControlBar from './WorkflowControlBar.vue'
import type { WorkflowDef, WorkflowNodeKind, WorkflowNode as WorkflowNodeData, NodeStateStatus } from '../workflow/types'

const props = defineProps<{
  definition: WorkflowDef
  nodeStates: Record<string, NodeStateStatus>
  running?: boolean
  statusText?: string
}>()
const emit = defineEmits<{
  'update:definition': [def: WorkflowDef]
  run: []
  step: []
  save: []
}>()

const { zoomIn, zoomOut, setViewport } = useVueFlow()

const nodeTypes = { workflow: markRaw(WorkflowNodeComp) } as any

// ---- WorkflowDef <-> VueFlow mapping ----
const vfNodes = ref<Node[]>([])
const vfEdges = ref<Edge[]>([])
// Re-entrancy guard: while we sync VueFlow from the prop, suppress the
// internal watchers' emits so we don't get definition->sync->emit->definition loops.
let syncing = false

function syncFromDefinition() {
  syncing = true
  vfNodes.value = props.definition.nodes.map((n): Node => ({
    id: n.id,
    type: 'workflow',
    position: n.position ?? { x: 0, y: 0 },
    data: { node: n, state: props.nodeStates[n.id] ?? 'idle' },
  })) as Node[]
  vfEdges.value = props.definition.edges.map((e): Edge => ({
    id: e.id,
    source: e.source,
    target: e.target,
    sourceHandle: e.source_port,
    targetHandle: e.target_port,
  })) as Edge[]
  // release on next tick so VueFlow's internal mutations land before we listen again
  queueMicrotask(() => { syncing = false })
}

// Only resync when the definition's node/edge identity changes (by length + ids),
// NOT on every prop reference change (the parent reassigns the object on our own emits).
watch(
  () => props.definition,
  () => {
    const curIds = vfNodes.value.map((n) => n.id).join(',')
    const newIds = props.definition.nodes.map((n) => n.id).join(',')
    const curEdges = vfEdges.value.map((e) => e.id).join(',')
    const newEdges = props.definition.edges.map((e) => e.id).join(',')
    const statesChanged = props.definition.nodes.some((n) => (props.nodeStates[n.id] ?? 'idle') !== ((vfNodes.value.find((v) => v.id === n.id)?.data as { state?: string } | undefined)?.state ?? 'idle'))
    if (curIds !== newIds || curEdges !== newEdges || statesChanged) {
      syncFromDefinition()
    }
  },
  { deep: false, immediate: true },
)

// Emit node position changes back (only on real drag, not during sync).
watch(vfNodes, (nodes) => {
  if (syncing) return
  const posById = new Map(nodes.map((n) => [n.id, n.position]))
  const updated = props.definition.nodes.map((n) => ({
    ...n,
    position: posById.get(n.id) ?? n.position,
  }))
  emit('update:definition', { ...props.definition, nodes: updated })
}, { deep: true })

watch(vfEdges, (edges) => {
  if (syncing) return
  const mapped = edges.map((e) => ({
    id: e.id,
    source: e.source,
    source_port: e.sourceHandle ?? '',
    target: e.target,
    target_port: e.targetHandle ?? '',
  }))
  emit('update:definition', { ...props.definition, edges: mapped })
}, { deep: true })

// ---- right-click + node click ----
const menu = ref<{ x: number; y: number } | null>(null)
const editNode = ref<WorkflowNodeData | null>(null)
const editAnchor = ref({ x: 0, y: 0 })

function onPaneContextMenu(evt: any) {
  if (evt && typeof evt.preventDefault === 'function') evt.preventDefault()
  const x = evt?.clientX ?? 0
  const y = evt?.clientY ?? 0
  menu.value = { x, y }
}
function onNodeContextMenu(params: any) {
  const ev = params?.event
  if (ev && typeof ev.preventDefault === 'function') ev.preventDefault()
  openEdit(params?.node?.id, ev?.clientX ?? 0, ev?.clientY ?? 0)
}
function onNodeClick(params: any) {
  const ev = params?.event
  const x = ev?.clientX ?? window.innerWidth / 2
  const y = ev?.clientY ?? 120
  openEdit(params?.node?.id, x, y)
}
function openEdit(id: string, x: number, y: number) {
  const n = props.definition.nodes.find((node) => node.id === id)
  if (n) {
    editNode.value = n
    editAnchor.value = { x, y }
  }
}

function addNode(kind: WorkflowNodeKind) {
  const id = `${kind}-${Math.random().toString(36).slice(2, 7)}`
  const node: WorkflowNodeData = {
    id,
    kind,
    title: kind === 'llm' ? '新 LLM 节点' : kind === 'agent' ? '新 Agent 节点' : '新 Action 节点',
    config: kind === 'action' ? { action_type: 'shell', command: '' } : {},
    ports: [
      { name: 'out', type: 'text', direction: 'out' },
    ],
    position: { x: 200 + Math.random() * 200, y: 120 + Math.random() * 160 },
  }
  emit('update:definition', { ...props.definition, nodes: [...props.definition.nodes, node] })
}

function onUpdateNode(updated: WorkflowNodeData) {
  const nodes = props.definition.nodes.map((n) => (n.id === updated.id ? updated : n))
  emit('update:definition', { ...props.definition, nodes })
  editNode.value = null
}

// ---- zoom ----
function zoomBy(factor: number) {
  if (factor > 1) zoomIn()
  else zoomOut()
}
function resetZoom() {
  setViewport({ x: 0, y: 0, zoom: 1 })
}
</script>

<style scoped>
@import '@vue-flow/core/dist/style.css';
@import '@vue-flow/core/dist/theme-default.css';
@import '@vue-flow/controls/dist/style.css';

.wf-canvas {
  position: relative;
  width: 100%;
  height: 100%;
  background: color-mix(in srgb, var(--theme-backdrop-background, #111) 60%, #000);
}
.wf-canvas :deep(.vue-flow) {
  background: transparent;
}
/* Ensure nodes render above the background pattern and are clickable. */
.wf-canvas :deep(.vue-flow__nodes) {
  z-index: 5;
}
.wf-canvas :deep(.vue-flow__node) {
  width: auto;
  z-index: 10;
}
.wf-context-menu {
  position: fixed;
  z-index: var(--z-popover, 60);
  display: flex;
  flex-direction: column;
  padding: 4px;
  border-radius: var(--radius, 12px);
  border: 1px solid color-mix(in srgb, var(--theme-main-text, #fff) 14%, transparent);
  background: var(--theme-main-background, #1d1e1e);
  color: var(--theme-main-text, #f2efeb);
  box-shadow: var(--shadow, 0 8px 32px rgba(0, 0, 0, 0.5));
}
.menu-item {
  border: 0;
  background: transparent;
  color: inherit;
  text-align: left;
  padding: 6px 10px;
  border-radius: var(--radius-sm, 6px);
  font-size: 12px;
  cursor: pointer;
}
.menu-item:hover {
  background: color-mix(in srgb, var(--theme-main-text, #fff) 10%, transparent);
}
</style>
