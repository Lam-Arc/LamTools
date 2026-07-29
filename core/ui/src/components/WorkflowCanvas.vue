<template>
  <div class="wf-canvas" @contextmenu.prevent="onContextMenu">
    <button
      type="button"
      class="wf-lock-btn"
      :class="{ locked }"
      :title="locked ? '已锁定（拖拽/缩放不可用）' : '锁定画布'"
      @click="toggleLock"
    >{{ locked ? '🔒' : '🔓' }}</button>
    <VueFlow
      v-model:nodes="vfNodes"
      v-model:edges="vfEdges"
      :node-types="nodeTypes"
      :pan-on-drag="[2]"
      :selection-on-drag="false"
      :default-viewport="{ zoom: 1 }"
      fit-view-on-init
      @node-click="onNodeClick"
    >
      <Background :gap="22" :size="1" pattern-color="rgba(130,130,140,0.22)" />
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
      <button class="menu-item" type="button" role="menuitem" @click="configNode(nodeMenu.id, nodeMenu.x, nodeMenu.y)">配置</button>
      <button class="menu-item" type="button" role="menuitem" @click="copyNode(nodeMenu.id)">复制</button>
      <button class="menu-item" type="button" role="menuitem" @click="cutNode(nodeMenu.id)">剪切</button>
      <span class="wf-menu-sep" />
      <button class="menu-item danger" type="button" role="menuitem" @click="deleteNode(nodeMenu.id)">删除</button>
    </div>

    <NodeEditCard
      v-if="editNode"
      :node="editNode"
      :anchor="editAnchor"
      :available-tools="availableTools"
      @close="editNode = null"
      @update="onUpdateNode"
    />
  </div>
</template>

<script setup lang="ts">
import { markRaw, ref, watch } from 'vue'
import { VueFlow, useVueFlow, type Node, type Edge } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
// Vue Flow styles must load as global CSS (not inside <style scoped> @import,
// which Vite scopes and breaks internal class selectors + load order).
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import WorkflowNodeComp from './WorkflowNode.vue'
import NodeEditCard from './NodeEditCard.vue'
import type { WorkflowDef, WorkflowNodeKind, WorkflowNodeData, NodeStateStatus } from '../workflow/types'

const props = defineProps<{
  definition: WorkflowDef
  nodeStates: Record<string, NodeStateStatus>
  selectedNodeId?: string
  availableTools?: Array<{ name: string; description: string }>
}>()
const emit = defineEmits<{
  'update:definition': [def: WorkflowDef]
  'select-node': [id: string | null]
  'run-from': [nodeId: string]
  'run-node': [nodeId: string]
}>()

const { screenToFlowCoordinate, setInteractive } = useVueFlow()
const nodeTypes = { workflow: markRaw(WorkflowNodeComp) as any }
const locked = ref(false)
function toggleLock() {
  locked.value = !locked.value
  setInteractive(!locked.value)
}

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

// Single native contextmenu handler on the canvas root. Detects whether the
// right-click hit a Vue Flow node (DOM traversal to .vue-flow__node[data-id])
// and shows the node menu, otherwise the pane menu. This avoids relying on
// Vue Flow's pane/node context-menu events, which are unreliable with
// panOnDrag={[2]} (right-button drag is interpreted as panning).
function onContextMenu(evt: MouseEvent) {
  const x = evt.clientX
  const y = evt.clientY
  let el = evt.target as HTMLElement | null
  let nodeId = ''
  while (el && el !== evt.currentTarget) {
    if (el.classList?.contains('vue-flow__node')) {
      nodeId = el.getAttribute('data-id') || ''
      break
    }
    el = el.parentElement
  }
  if (nodeId && props.definition.nodes.some((n) => n.id === nodeId)) {
    paneMenu.value = null
    nodeMenu.value = { x, y, id: nodeId }
  } else {
    nodeMenu.value = null
    paneMenu.value = { x, y }
  }
}
function closeMenus() {
  paneMenu.value = null
  nodeMenu.value = null
}

// ---- node click → select + config ----
// Left-click and right-click "配置" share this path so both select the node
// and open the edit card identically.
function onNodeClick(params: any) {
  const id = params?.node?.id
  if (!id) return
  const ev = params?.event
  configNode(id, ev?.clientX ?? window.innerWidth / 2, ev?.clientY ?? 120)
}
function configNode(id: string, x?: number, y?: number) {
  if (!props.definition.nodes.some((n) => n.id === id)) return
  emit('select-node', id)
  openEdit(id, x, y)
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
  return kind === 'llm' ? 'LLM' : kind === 'agent' ? 'Agent' : 'Action'
}
// Every node carries both an input and an output port — ports (not separate
// Input/Output nodes) are how data flows in and out of a node.
function defaultPorts(_kind: WorkflowNodeKind) {
  return [
    { name: 'in', type: 'text', direction: 'in' as const },
    { name: 'out', type: 'text', direction: 'out' as const },
  ]
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

.wf-lock-btn {
  position: absolute;
  top: 10px;
  left: 12px;
  z-index: var(--z-popover, 60);
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border: 0;
  border-radius: 8px;
  background: transparent;
  font-size: 15px;
  cursor: pointer;
  opacity: 0.55;
  transition: opacity 0.15s, background 0.15s;
}
.wf-lock-btn:hover { opacity: 1; background: rgba(255, 255, 255, 0.06); }
.wf-lock-btn.locked { opacity: 0.9; }

.wf-canvas {
  /* Fill the entire workspace-main (ignore its padding) so the whole main
     area is the canvas, not a small sub-region. Background is transparent so
     the canvas blends with the main surface (simple/restrained). */
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  background: transparent;
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
