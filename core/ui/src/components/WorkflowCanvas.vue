<template>
  <div class="wf-canvas" @contextmenu.prevent>
    <VueFlow
      v-model:nodes="vfNodes"
      v-model:edges="vfEdges"
      :node-types="nodeTypes"
      :pan-on-drag="[2]"
      :selection-on-drag="false"
      :default-viewport="{ zoom: 1 }"
      fit-view-on-init
      @pane-context-menu="onPaneContextMenu"
      @node-context-menu="onNodeContextMenu"
      @node-click="onNodeClick"
    >
      <Background />
      <Controls />
    </VueFlow>

    <!-- pane (empty-space) context menu -->
    <div
      v-if="paneMenu"
      class="wf-context-menu"
      role="menu"
      :style="{ left: paneMenu.x + 'px', top: paneMenu.y + 'px' }"
      @pointerdown.stop
      @click.stop
      @keydown.escape.prevent="closeMenus"
    >
      <div class="wf-menu-group">
        <div class="wf-menu-label">新建节点</div>
        <button class="menu-item" type="button" role="menuitem" @click="addNodeAt('llm', paneMenu)">LLM</button>
        <button class="menu-item" type="button" role="menuitem" @click="addNodeAt('agent', paneMenu)">Agent</button>
        <button class="menu-item" type="button" role="menuitem" @click="addNodeAt('action', paneMenu)">Action</button>
        <button class="menu-item" type="button" role="menuitem" @click="addNodeAt('input', paneMenu)">Input</button>
        <button class="menu-item" type="button" role="menuitem" @click="addNodeAt('output', paneMenu)">Output</button>
      </div>
      <span class="wf-menu-sep" />
      <button class="menu-item" type="button" role="menuitem" :disabled="!clipboard" @click="pasteAt(paneMenu)">粘贴</button>
    </div>

    <!-- node context menu -->
    <div
      v-if="nodeMenu"
      class="wf-context-menu"
      role="menu"
      :style="{ left: nodeMenu.x + 'px', top: nodeMenu.y + 'px' }"
      @pointerdown.stop
      @click.stop
      @keydown.escape.prevent="closeMenus"
    >
      <div class="wf-menu-group">
        <div class="wf-menu-label">运行</div>
        <button class="menu-item" type="button" role="menuitem" @click="runFromNode(nodeMenu.id)">从此节点运行</button>
        <button class="menu-item" type="button" role="menuitem" @click="runNode(nodeMenu.id)">运行此节点</button>
      </div>
      <span class="wf-menu-sep" />
      <button class="menu-item" type="button" role="menuitem" @click="openEdit(nodeMenu.id)">配置</button>
      <button class="menu-item" type="button" role="menuitem" @click="copyNode(nodeMenu.id)">复制</button>
      <button class="menu-item" type="button" role="menuitem" @click="cutNode(nodeMenu.id)">剪切</button>
      <span class="wf-menu-sep" />
      <button class="menu-item danger" type="button" role="menuitem" @click="deleteNode(nodeMenu.id)">删除</button>
    </div>

    <NodeEditCard
      v-if="editNode"
      :node="editNode"
      :anchor="editAnchor"
      @close="editNode = null"
      @update="onUpdateNode"
    />
  </div>
</template>

<script setup lang="ts">
import { markRaw, ref, watch } from 'vue'
import { VueFlow, useVueFlow, type Node, type Edge } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import WorkflowNodeComp from './WorkflowNode.vue'
import NodeEditCard from './NodeEditCard.vue'
import type { WorkflowDef, WorkflowNodeKind, WorkflowNodeData, NodeStateStatus } from '../workflow/types'

const props = defineProps<{
  definition: WorkflowDef
  nodeStates: Record<string, NodeStateStatus>
  selectedNodeId?: string
}>()
const emit = defineEmits<{
  'update:definition': [def: WorkflowDef]
  'select-node': [id: string | null]
  'run-from': [nodeId: string]
  'run-node': [nodeId: string]
}>()

const { screenToFlowCoordinate } = useVueFlow()
const nodeTypes = { workflow: markRaw(WorkflowNodeComp) as any }

// ---- WorkflowDef <-> VueFlow mapping ----
const vfNodes = ref<Node[]>([])
const vfEdges = ref<Edge[]>([])
let syncing = false

function syncFromDefinition() {
  syncing = true
  vfNodes.value = props.definition.nodes.map((n): Node => ({
    id: n.id,
    type: 'workflow',
    position: n.position ?? { x: 0, y: 0 },
    data: { node: n, state: props.nodeStates[n.id] ?? 'idle' },
    class: n.id === props.selectedNodeId ? 'wf-node-selected' : '',
  })) as Node[]
  vfEdges.value = props.definition.edges.map((e): Edge => ({
    id: e.id,
    source: e.source,
    target: e.target,
    sourceHandle: e.source_port,
    targetHandle: e.target_port,
  })) as Edge[]
  queueMicrotask(() => { syncing = false })
}

watch(() => props.definition, syncFromDefinition, { deep: false, immediate: true })
watch(() => props.nodeStates, syncFromDefinition, { deep: false })
watch(() => props.selectedNodeId, () => {
  vfNodes.value = vfNodes.value.map((n) => ({ ...n, class: n.id === props.selectedNodeId ? 'wf-node-selected' : '' }))
})

watch(vfNodes, (nodes) => {
  if (syncing) return
  const posById = new Map(nodes.map((n) => [n.id, n.position]))
  emit('update:definition', {
    ...props.definition,
    nodes: props.definition.nodes.map((n) => ({ ...n, position: posById.get(n.id) ?? n.position })),
  })
}, { deep: true })

watch(vfEdges, (edges) => {
  if (syncing) return
  emit('update:definition', {
    ...props.definition,
    edges: edges.map((e) => ({ id: e.id, source: e.source, source_port: e.sourceHandle ?? '', target: e.target, target_port: e.targetHandle ?? '' })),
  })
}, { deep: true })

// ---- context menus ----
type MenuPos = { x: number; y: number }
const paneMenu = ref<MenuPos | null>(null)
const nodeMenu = ref<MenuPos & { id: string } | null>(null)
const editNode = ref<WorkflowNodeData | null>(null)
const editAnchor = ref<MenuPos>({ x: 0, y: 0 })
const clipboard = ref<WorkflowNodeData | null>(null)

function onPaneContextMenu(evt: any) {
  const x = evt?.clientX ?? 0
  const y = evt?.clientY ?? 0
  nodeMenu.value = null
  paneMenu.value = { x, y }
}
function onNodeContextMenu(params: any) {
  const ev = params?.event
  paneMenu.value = null
  nodeMenu.value = { x: ev?.clientX ?? 0, y: ev?.clientY ?? 0, id: params?.node?.id ?? '' }
}
function closeMenus() {
  paneMenu.value = null
  nodeMenu.value = null
}

// ---- node click → select + config ----
function onNodeClick(params: any) {
  const id = params?.node?.id
  if (id) {
    emit('select-node', id)
    const ev = params?.event
    openEdit(id, ev?.clientX ?? window.innerWidth / 2, ev?.clientY ?? 120)
  }
}
function openEdit(id: string, x?: number, y?: number) {
  const n = props.definition.nodes.find((node) => node.id === id)
  if (n) {
    editNode.value = n
    editAnchor.value = { x: x ?? window.innerWidth / 2, y: y ?? 120 }
  }
  closeMenus()
}

// ---- node mutations ----
function addNodeAt(kind: WorkflowNodeKind, pos: MenuPos) {
  const flowPos = safeScreenToFlow(pos)
  const id = `${kind}-${Math.random().toString(36).slice(2, 6)}`
  const node: WorkflowNodeData = {
    id,
    kind,
    title: defaultTitle(kind),
    config: kind === 'action' ? { action_type: 'shell', command: '' } : kind === 'llm' ? { instruction: '', mode: 'single' } : {},
    ports: defaultPorts(kind),
    position: flowPos,
  }
  emit('update:definition', { ...props.definition, nodes: [...props.definition.nodes, node] })
  closeMenus()
}

function defaultTitle(kind: WorkflowNodeKind): string {
  return kind === 'llm' ? 'LLM' : kind === 'agent' ? 'Agent' : kind === 'input' ? 'Input' : kind === 'output' ? 'Output' : 'Action'
}
function defaultPorts(kind: WorkflowNodeKind) {
  if (kind === 'input') return [{ name: 'value', type: 'text', direction: 'out' as const }]
  if (kind === 'output') return [{ name: 'value', type: 'text', direction: 'in' as const }]
  if (kind === 'action' || kind === 'llm') return [{ name: 'out', type: 'text', direction: 'out' as const }]
  return [{ name: 'out', type: 'text', direction: 'out' as const }]
}

function onUpdateNode(updated: WorkflowNodeData) {
  emit('update:definition', { ...props.definition, nodes: props.definition.nodes.map((n) => (n.id === updated.id ? updated : n)) })
  editNode.value = null
}

function deleteNode(id: string) {
  emit('update:definition', {
    ...props.definition,
    nodes: props.definition.nodes.filter((n) => n.id !== id),
    edges: props.definition.edges.filter((e) => e.source !== id && e.target !== id),
  })
  closeMenus()
}

function copyNode(id: string) {
  const n = props.definition.nodes.find((node) => node.id === id)
  if (n) clipboard.value = JSON.parse(JSON.stringify(n))
  closeMenus()
}
function cutNode(id: string) {
  copyNode(id)
  deleteNode(id)
}
function pasteAt(pos: MenuPos) {
  if (!clipboard.value) return
  const flowPos = safeScreenToFlow(pos)
  const copy: WorkflowNodeData = JSON.parse(JSON.stringify(clipboard.value))
  copy.id = `${copy.kind}-${Math.random().toString(36).slice(2, 6)}`
  copy.position = flowPos
  emit('update:definition', { ...props.definition, nodes: [...props.definition.nodes, copy] })
  closeMenus()
}

function runFromNode(id: string) { emit('run-from', id); closeMenus() }
function runNode(id: string) { emit('run-node', id); closeMenus() }

function safeScreenToFlow(pos: MenuPos): { x: number; y: number } {
  try { return screenToFlowCoordinate(pos) } catch { return { x: 100 + Math.random() * 200, y: 80 + Math.random() * 120 } }
}

// close menus on outside pointerdown / Esc
if (typeof document !== 'undefined') {
  document.addEventListener('pointerdown', closeMenus)
  document.addEventListener('keydown', (e: KeyboardEvent) => { if (e.key === 'Escape') closeMenus() })
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
.wf-canvas :deep(.vue-flow) { background: transparent; }
.wf-canvas :deep(.vue-flow__nodes) { z-index: 5; }
.wf-canvas :deep(.vue-flow__node) { width: auto; z-index: 10; }
.wf-canvas :deep(.vue-flow__node.selected .wf-node) {
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--blue, #79bcff) 70%, transparent), var(--shadow, 0 2px 8px rgba(0,0,0,0.35));
}
.wf-canvas :deep(.vue-flow__node.wf-node-selected .wf-node) {
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--blue, #79bcff) 70%, transparent), var(--shadow, 0 2px 8px rgba(0,0,0,0.35));
}
.wf-context-menu {
  position: fixed;
  z-index: var(--z-popover, 60);
  min-width: 150px;
  padding: 4px;
  border-radius: 10px;
  border: 1px solid color-mix(in srgb, var(--theme-main-text, #fff) 12%, transparent);
  background: var(--theme-main-background, #1d1e1e);
  color: var(--theme-main-text, #f2efeb);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
}
.wf-menu-group { display: flex; flex-direction: column; }
.wf-menu-label { font-size: 10px; opacity: 0.4; padding: 4px 8px 2px; text-transform: uppercase; letter-spacing: 0.04em; }
.wf-menu-sep { display: block; height: 1px; margin: 4px 6px; background: color-mix(in srgb, var(--theme-main-text, #fff) 10%, transparent); }
.menu-item {
  border: 0; background: transparent; color: inherit; text-align: left;
  padding: 6px 10px; border-radius: 6px; font-size: 12px; cursor: pointer;
}
.menu-item:hover:not(:disabled) { background: color-mix(in srgb, var(--theme-main-text, #fff) 8%, transparent); }
.menu-item:disabled { opacity: 0.35; cursor: default; }
.menu-item.danger { color: var(--red, #f5555d); }
</style>
