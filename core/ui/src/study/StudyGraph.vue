<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { VueFlow, Handle, Position, MarkerType, type Node, type ViewportTransform, type VueFlowStore } from '@vue-flow/core'
import '@vue-flow/core/dist/style.css'
import { Check, Circle, Folder, Minus, Plus, Maximize2 } from 'lucide-vue-next'
import type { KnowledgeItem, Net, Relation } from './types'

type StudyGraphNode = Node<KnowledgeItem>
type InspectedNode = { node: KnowledgeItem; neighbors: KnowledgeItem[]; relations: Relation[] } | null

const props = defineProps<{
  net: Net
  nodes: StudyGraphNode[]
  viewport: ViewportTransform
  loading: boolean
  graphFocusId: string
  graphSelectedId: string
  inspected: InspectedNode
  layoutNotice: string
}>()

const emit = defineEmits<{
  'update:nodes': [value: StudyGraphNode[]]
  'update:viewport': [value: ViewportTransform]
  'open-node': [item: KnowledgeItem]
  'focus-node': [item: KnowledgeItem]
  'blur-node': [item: KnowledgeItem]
  'save-layout': []
  'sync-viewport': [value: ViewportTransform]
  report: [cause: unknown]
}>()

const graphViewport = ref<VueFlowStore | null>(null)
const graphNodes = computed<StudyGraphNode[]>({
  get: () => props.nodes,
  set: value => emit('update:nodes', value),
})

const relationLabels: Record<string, string> = { prerequisite: '前置', advances: '进阶', advanced: '进阶', contains: '包含', related: '关联' }
const relationLegend = computed(() => Array.from(new Set((props.net.relations || []).map(relation => relation.type).filter(Boolean)))
  .map(type => ({ type, label: relationLabels[type] || type })))

const edges = computed(() => {
  const focus = props.graphFocusId || props.graphSelectedId
  return (props.net.relations || []).map(relation => ({
    ...relation,
    label: relationLabels[relation.type] || relation.type,
    class: `study-edge study-edge--${relation.type}${focus ? (relation.source === focus || relation.target === focus ? ' study-edge--emphasized' : ' study-edge--muted') : ''}`,
    type: 'default',
    markerEnd: relation.type === 'related' ? undefined : MarkerType.ArrowClosed,
  }))
})

function setGraphViewport(next: ViewportTransform): void {
  emit('update:viewport', { ...next })
  void graphViewport.value?.setViewport(next)
}

function bindGraphViewport(store: VueFlowStore): void {
  graphViewport.value = store
  void store.setViewport(props.viewport)
}

function isGroup(item: KnowledgeItem): boolean { return item.entity === 'course' || !item.learnable }
function isCourse(item: KnowledgeItem): boolean { return item.entity === 'course' }

function courseProgress(item: KnowledgeItem): number {
  const total = Number(item.total)
  const passed = Number(item.progressPassed ?? item.passed)
  if (!Number.isFinite(total) || total <= 0 || !Number.isFinite(passed)) return 0
  return Math.round(Math.min(1, Math.max(0, passed / total)) * 100)
}

function courseProgressTitle(item: KnowledgeItem): string {
  return `${item.name} 学习进度 ${courseProgress(item)}%`
}

function statusFor(item: KnowledgeItem): { label: string; icon: 'check' | 'circle' } {
  if (item.progressRole === 'aggregate' && item.assessment === 'unassessed') return { label: '范围进度，尚未独立评估', icon: 'circle' }
  if (item.assessment === 'pass') return { label: `已通过，掌握${item.mastery === 'low' ? '低' : item.mastery === 'medium' ? '中' : item.mastery === 'high' ? '高' : '待评定'}`, icon: 'check' }
  if (item.assessment === 'fail') return { label: '已评估但未通过', icon: 'circle' }
  return { label: '尚未评估', icon: 'circle' }
}

function neighborLabel(id: string): string {
  const relation = props.inspected?.relations.find(candidate => candidate.source === id || candidate.target === id)
  if (!relation) return '关联'
  if (relation.type === 'prerequisite' || relation.type === 'advanced' || relation.type === 'advances') return relation.source === id ? '前置' : '进阶'
  return relationLabels[relation.type] || relation.type
}

function focusGraphNode(item: KnowledgeItem): void { emit('focus-node', item) }
function blurGraphNode(item: KnowledgeItem): void { emit('blur-node', item) }
function openGraphNode(value: unknown): void { emit('open-node', value as KnowledgeItem) }
function syncGraphViewport(event: { flowTransform: ViewportTransform }): void { emit('sync-viewport', event.flowTransform) }

watch(() => props.viewport, viewport => {
  const current = graphViewport.value?.viewport
  if (graphViewport.value && (!current || current.x !== viewport.x || current.y !== viewport.y || current.zoom !== viewport.zoom)) void graphViewport.value.setViewport(viewport)
})
</script>

<template>
  <div class="study-graph">
    <div class="study-graph-meta" aria-live="polite"><span>{{ nodes.length }} 个节点</span><span>{{ edges.length }} 条关系</span><span v-if="layoutNotice" :title="layoutNotice">分层</span></div>
    <div class="study-graph-controls">
      <button class="text-btn" title="缩小" aria-label="缩小" @click="setGraphViewport({ ...viewport, zoom: Math.max(.25, viewport.zoom / 1.2) })"><Minus :size="15" /></button>
      <button class="text-btn" title="放大" aria-label="放大" @click="setGraphViewport({ ...viewport, zoom: Math.min(2, viewport.zoom * 1.2) })"><Plus :size="15" /></button>
      <button class="text-btn" title="复位" aria-label="复位" @click="setGraphViewport({ x: 24, y: 24, zoom: 1 })"><Maximize2 :size="15" /></button>
    </div>
    <aside v-if="relationLegend.length" class="study-graph-legend" aria-label="关系图例"><strong>关系</strong><span v-for="relation in relationLegend" :key="relation.type" class="study-graph-legend-item"><i :class="['study-edge-swatch', `study-edge-swatch--${relation.type}`]" aria-hidden="true"></i>{{ relation.label }}</span></aside>
    <p v-if="!nodes.length && !loading" class="study-empty">这里还没有可显示的知识点；先在学习会话中让 AI 建立知识网。</p>
    <VueFlow v-model:nodes="graphNodes" :edges="edges" data-study-layout="layered" aria-label="知识图谱" :min-zoom=".25" :max-zoom="2" :nodes-connectable="false" @init="bindGraphViewport" @node-click="openGraphNode($event.node.data)" @node-drag-stop="emit('save-layout')" @move-end="syncGraphViewport($event)">
      <template #node-knowledge="{ data, selected: nodeSelected }">
        <Handle type="target" :position="Position.Left" />
        <button
          :class="['study-node', isCourse(data) ? 'study-node--course' : isGroup(data) ? 'study-node--module' : 'study-node--knowledge', !isCourse(data) && data.assessment === 'pass' ? 'study-node--passed' : '', !isCourse(data) && data.assessment !== 'pass' ? 'study-node--incomplete' : '', !isCourse(data) && data.assessment === 'pass' && data.mastery ? `study-node--mastery-${data.mastery}` : '', { 'is-focused': graphFocusId === data.id, 'is-selected': nodeSelected || graphSelectedId === data.id }]"
          :data-study-node="data.id"
          :title="isCourse(data) ? courseProgressTitle(data) : statusFor(data).label"
          :aria-label="isCourse(data) ? courseProgressTitle(data) : data.name + (isGroup(data) ? ' 分组' : ' ' + statusFor(data).label)"
          @mouseenter="focusGraphNode(data)" @mouseleave="blurGraphNode(data)" @focus="focusGraphNode(data)" @blur="blurGraphNode(data)" @keydown.enter.stop="emit('open-node', data)"
        >
          <template v-if="isCourse(data)">
            <svg class="study-course-ring" viewBox="0 0 120 120" aria-hidden="true" focusable="false">
              <circle class="study-course-ring-track" cx="60" cy="60" r="52" pathLength="100" />
              <circle class="study-course-ring-value" cx="60" cy="60" r="52" pathLength="100" :stroke-dasharray="`${courseProgress(data)} ${100 - courseProgress(data)}`" />
            </svg>
            <span class="study-course-sphere">
              <span class="study-course-name">{{ data.name }}</span>
              <span class="study-course-percentage">{{ courseProgress(data) }}%</span>
            </span>
          </template>
          <template v-else>
            <span class="study-node-dot" aria-hidden="true"><Folder v-if="isGroup(data)" :size="12" /><Check v-else-if="statusFor(data).icon === 'check'" :size="12" /><Circle v-else :size="10" /></span>
            <span class="study-node-label">{{ data.name }}</span>
          </template>
        </button>
        <Handle type="source" :position="Position.Right" />
      </template>
    </VueFlow>
    <aside v-if="inspected?.relations.length" class="study-related" aria-label="知识关系"><strong>{{ inspected.node.name }}</strong><button v-for="neighbor in inspected.neighbors.filter(n => n.id !== inspected?.node.id)" :key="neighbor.id" class="text-btn" @click="emit('open-node', neighbor)"><span>{{ neighborLabel(neighbor.id) }}</span>{{ neighbor.name }}</button></aside>
  </div>
</template>
