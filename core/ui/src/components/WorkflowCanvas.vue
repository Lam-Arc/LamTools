<template>
  <div class="wf-canvas" @contextmenu.prevent="onContextMenu">
    <VueFlow
      v-model:nodes="vfNodes"
      v-model:edges="vfEdges"
      :node-types="nodeTypes"
      :pan-on-drag="[2]"
      :selection-on-drag="false"
      :default-viewport="{ zoom: 1 }"
      fit-view-on-init
      @node-click="onNodeClick"
      @connect="onConnect"
    >
      <Background :gap="22" :size="1" pattern-color="transparent" />
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
          <button class="menu-item" type="button" role="menuitem" @click="addNodeAt('ai', paneMenu)">AI</button>
          <button class="menu-item" type="button" role="menuitem" @click="addNodeAt('command', paneMenu)">Command</button>
          <button class="menu-item" type="button" role="menuitem" @click="addNodeAt('script', paneMenu)">Script</button>
          <button class="menu-item" type="button" role="menuitem" @click="addNodeAt('content', paneMenu)">Content</button>
          <button class="menu-item" type="button" role="menuitem" @click="addNodeAt('subgraph', paneMenu)">Subgraph</button>
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
      <button class="menu-item" type="button" role="menuitem" @click="configNode(nodeMenu.id)">配置</button>
      <button class="menu-item" type="button" role="menuitem" @click="copyNode(nodeMenu.id)">复制</button>
      <button class="menu-item" type="button" role="menuitem" @click="cutNode(nodeMenu.id)">剪切</button>
      <span class="wf-menu-sep" />
      <button class="menu-item" type="button" role="menuitem" @click="addPort(nodeMenu.id, 'in')">+ 输入端口</button>
      <button class="menu-item" type="button" role="menuitem" @click="addPort(nodeMenu.id, 'out')">+ 输出端口</button>
      <span class="wf-menu-sep" />
      <button class="menu-item danger" type="button" role="menuitem" @click="deleteNode(nodeMenu.id)">删除</button>
    </div>

    <!-- edge context menu -->
    <div
      v-if="edgeMenu"
      class="wf-context-menu"
      role="menu"
      :style="{ left: edgeMenu.x + 'px', top: edgeMenu.y + 'px' }"
      @pointerdown.stop
      @click.stop
      @keydown.escape.prevent="closeMenus"
    >
      <div class="wf-menu-group">
        <div class="wf-menu-label">连线条件</div>
        <input
          class="wf-edge-cond-input"
          type="text"
          placeholder="Python 表达式（空=无条件）"
          :value="edgeCondition(edgeMenu.id)"
          @input="setEdgeCondition(edgeMenu.id, ($event.target as HTMLInputElement).value)"
        />
      </div>
      <span class="wf-menu-sep" />
      <button class="menu-item danger" type="button" role="menuitem" @click="deleteEdge(edgeMenu.id)">删除连线</button>
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
import { markRaw, provide, ref, watch } from 'vue'
import { VueFlow, useVueFlow, type Node, type Edge } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
// Vue Flow styles must load as global CSS (not inside <style scoped> @import,
// which Vite scopes and breaks internal class selectors + load order).
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import WorkflowNodeComp from './WorkflowNode.vue'
import NodeEditCard from './NodeEditCard.vue'
import type { WorkflowDef, WorkflowNodeKind, WorkflowNodeData, NodeStateStatus, WorkflowPort } from '../workflow/types'

const props = defineProps<{
  definition: WorkflowDef
  nodeStates: Record<string, NodeStateStatus>
  selectedNodeId?: string
  availableTools?: Array<{ name: string; description: string }>
  availableModels?: Array<{ id: string; display_name?: string; model_id?: string }>
  locked?: boolean
}>()
const emit = defineEmits<{
  'update:definition': [def: WorkflowDef]
  'select-node': [id: string | null]
  'run-from': [nodeId: string]
  'run-node': [nodeId: string]
}>()

const { screenToFlowCoordinate, setInteractive } = useVueFlow()
const nodeTypes = { workflow: markRaw(WorkflowNodeComp) as any }
watch(() => props.locked, (val) => { setInteractive(!val) }, { immediate: true })

// Provide an update callback so WorkflowNode components can edit fields inline.
provide('wf-update-node', (nodeId: string, patch: Partial<WorkflowNodeData>) => {
  const nodes = props.definition.nodes.map((n) =>
    n.id === nodeId ? { ...n, ...patch, config: { ...n.config, ...(patch.config || {}) } } : n
  )
  emit('update:definition', { ...props.definition, nodes })
})
// Provide available models so WorkflowNode can render a model dropdown.
provide('wf-models', () => props.availableModels ?? [])

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
  return [n.id, n.kind, n.title, sortedConfig, n.ports.map((p) => `${p.name}:${p.direction}:${p.type}`).join(',')].join('::')
}
function syncFromDefinition() {
  const sig = props.definition.nodes.map(_nodeSignature).join('||') + '##' + props.definition.edges.map((e) => e.id).join('|')
  if (sig === lastSignature) {
    return
  }
  lastSignature = sig
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
// Node-state changes (runtime status) update each node's data.state in place
// WITHOUT touching positions or structure (so a running node doesn't reset
// dragged positions).
watch(() => props.nodeStates, () => {
  vfNodes.value = vfNodes.value.map((n) => ({
    ...n,
    data: { ...n.data, state: props.nodeStates[n.id] ?? (n.data as any)?.state ?? 'idle' },
  }))
}, { deep: false })
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
    edges: edges.map((e) => {
      const existing = props.definition.edges.find((de) => de.id === e.id)
      return {
        id: e.id,
        source: e.source,
        source_port: e.sourceHandle ?? '',
        target: e.target,
        target_port: e.targetHandle ?? '',
        transform: existing?.transform ?? '',
        condition: existing?.condition ?? '',
      }
    }),
  })
}, { deep: true })

// ---- edge condition helpers ----
function edgeCondition(edgeId: string): string {
  const e = props.definition.edges.find((ed) => ed.id === edgeId)
  return e?.condition ?? ''
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
const paneMenu = ref<MenuPos | null>(null)
const nodeMenu = ref<MenuPos & { id: string } | null>(null)
const edgeMenu = ref<MenuPos & { id: string } | null>(null)
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
  let edgeId = ''
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
  paneMenu.value = null
  nodeMenu.value = null
  edgeMenu.value = null
  if (edgeId && props.definition.edges.some((e) => e.id === edgeId)) {
    edgeMenu.value = { x, y, id: edgeId }
  } else if (nodeId && props.definition.nodes.some((n) => n.id === nodeId)) {
    nodeMenu.value = { x, y, id: nodeId }
  } else {
    paneMenu.value = { x, y }
  }
}
function closeMenus() {
  paneMenu.value = null
  nodeMenu.value = null
  edgeMenu.value = null
}

// ---- node click → select + config ----
// Left-click and right-click "配置" share this path: select the node and
// open the edit card. The card uses a centered, screen-safe position (not
// the mouse coords) so it never overflows the viewport regardless of where
// the click landed.
function onNodeClick(params: any) {
  const id = params?.node?.id
  if (!id) return
  emit('select-node', id)
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
  closeMenus()
}

// ---- node mutations ----
// Vue Flow fires `connect` when the user finishes dragging a handle-to-handle
// connection; it does NOT auto-create an edge, so we add it here.
function onConnect(params: { source: string; target: string; sourceHandle?: string | null; targetHandle?: string | null }) {
  const id = `e-${params.source}-${params.sourceHandle ?? ''}-${params.target}-${params.targetHandle ?? ''}`
  if (vfEdges.value.some((e) => e.id === id)) return
  // Type validation: look up source output port and target input port types.
  const srcNode = props.definition.nodes.find((n) => n.id === params.source)
  const tgtNode = props.definition.nodes.find((n) => n.id === params.target)
  if (srcNode && tgtNode) {
    const srcPort = srcNode.ports.find((p) => p.name === params.sourceHandle && p.direction === 'out')
    const tgtPort = tgtNode.ports.find((p) => p.name === params.targetHandle && p.direction === 'in')
    if (srcPort && tgtPort && !_typesCompatible(srcPort.type, tgtPort.type)) return
  }
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
function addNodeAt(kind: WorkflowNodeKind, pos: MenuPos) {
  const flowPos = safeScreenToFlow(pos)
  const id = `${kind}-${Math.random().toString(36).slice(2, 6)}`
  const config: Record<string, unknown> = kind === 'command'
    ? { command: '' }
    : kind === 'script'
      ? { script: scaffoldScript(defaultTitle(kind), defaultPorts(kind)) }
      : kind === 'ai'
        ? { instruction: '', mode: 'single' }
        : kind === 'subgraph'
          ? { workflow_name: '', iterate: 'none' }
          : {}
  const node: WorkflowNodeData = {
    id,
    kind,
    title: defaultTitle(kind),
    config,
    ports: defaultPorts(kind),
    position: flowPos,
  }
  emit('update:definition', { ...props.definition, nodes: [...props.definition.nodes, node] })
  closeMenus()
}

function defaultTitle(kind: WorkflowNodeKind): string {
  const count = props.definition.nodes.filter((n) => n.kind === kind).length + 1
  return `${kind}.${count}`
}
// Default ports per kind — content has output-only; subgraph has in/result;
// ai/command/script get a generic in/out pair.
function defaultPorts(kind: WorkflowNodeKind) {
  if (kind === 'content') {
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
function scaffoldScript(title: string, ports: WorkflowPort[]): string {
  const inPorts = ports.filter((p) => p.direction === 'in')
  const outPorts = ports.filter((p) => p.direction === 'out')
  const safeId = (n: string) => (/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(n || '') ? (n || 'value') : (n || 'value').replace(/[^a-zA-Z0-9_]/g, '_') || 'value')
  const lines = [`# ${title || 'script'}.py — script 节点脚手架`, '#']
  if (inPorts.length) {
    lines.push('# 输入端口（运行时已绑定为变量，直接用，勿重新赋值）：')
    for (const p of inPorts) lines.push(`#   ${safeId(p.name)} : ${p.type || 'any'}`)
  } else {
    lines.push('# 输入端口：（无）')
  }
  if (outPorts.length) {
    lines.push('# 输出端口（给这些变量赋值即作为该端口输出）：')
    for (const p of outPorts) lines.push(`#   ${safeId(p.name)} : ${p.type || 'any'}`)
  } else {
    lines.push('# 输出端口：（无）')
  }
  lines.push('#', '# 不要 print（会被忽略）、不要解析 stdin。直接写逻辑。', '')
  for (const p of outPorts) lines.push(`${safeId(p.name)} = None  # TODO: 计算 ${safeId(p.name)}`)
  if (!outPorts.length) lines.push('# TODO: 声明输出端口并在此赋值')
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
  emit('update:definition', { ...props.definition, nodes: props.definition.nodes.map((n) => (n.id === updated.id ? updated : n)) })
  editNode.value = null
}

function addPort(id: string, direction: 'in' | 'out') {
  const node = props.definition.nodes.find((n) => n.id === id)
  if (!node) return
  const existing = node.ports.filter((p) => p.direction === direction)
  const newPort = { name: `${direction}${existing.length + 1}`, type: 'any', direction }
  emit('update:definition', {
    ...props.definition,
    nodes: props.definition.nodes.map((n) =>
      n.id === id ? { ...n, ports: [...n.ports, newPort] } : n
    ),
  })
  closeMenus()
}

function deleteNode(id: string) {
  emit('update:definition', {
    ...props.definition,
    nodes: props.definition.nodes.filter((n) => n.id !== id),
    edges: props.definition.edges.filter((e) => e.source !== id && e.target !== id),
  })
  closeMenus()
}
function deleteEdge(id: string) {
  emit('update:definition', {
    ...props.definition,
    edges: props.definition.edges.filter((e) => e.id !== id),
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
.wf-canvas :deep(.vue-flow__background circle) { fill: color-mix(in srgb, var(--theme-main-text) 14%, transparent); }
.wf-canvas :deep(.vue-flow__nodes) { z-index: 5; }
.wf-canvas :deep(.vue-flow__node) { width: auto; z-index: 10; }
.wf-canvas :deep(.vue-flow__node.selected .wf-node) {
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--blue) 70%, transparent), var(--shadow);
}
.wf-canvas :deep(.vue-flow__node.wf-node-selected .wf-node) {
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--blue) 70%, transparent), var(--shadow);
}
.wf-context-menu {
  position: fixed;
  z-index: var(--z-popover, 60);
  min-width: 150px;
  padding: 4px;
  border-radius: 10px;
  border: 1px solid var(--theme-main-border);
  background: var(--theme-main-background);
  color: var(--theme-main-text);
  box-shadow: var(--shadow);
}
.wf-menu-group { display: flex; flex-direction: column; }
.wf-menu-label { font-size: 10px; opacity: 0.4; padding: 4px 8px 2px; text-transform: uppercase; letter-spacing: 0.04em; }
.wf-menu-sep { display: block; height: 1px; margin: 4px 6px; background: var(--theme-main-border); }
.wf-edge-cond-input {
  width: 100%;
  background: var(--theme-main-subtle-background, transparent);
  border: 1px solid var(--theme-main-border);
  border-radius: 5px;
  color: inherit;
  padding: 5px 8px;
  font-size: 11px;
  font-family: var(--font-mono, monospace);
  box-sizing: border-box;
}
.menu-item {
  border: 0; background: transparent; color: inherit; text-align: left;
  padding: 6px 10px; border-radius: 6px; font-size: 12px; cursor: pointer;
}
.menu-item:hover:not(:disabled) { background: var(--theme-main-soft-background); }
.menu-item:disabled { opacity: 0.35; cursor: default; }
.menu-item.danger { color: var(--red); }
</style>
