<script setup lang="ts">
import { computed } from 'vue'
import { GitBranch, LoaderCircle } from 'lucide-vue-next'
import type { StudyNoteGraph } from './types'

const props = withDefaults(defineProps<{
  graph: StudyNoteGraph
  activeId?: string
  loading?: boolean
  error?: string
  onOpenNote?: (id: string) => void | Promise<void>
}>(), { activeId: '', loading: false, error: '', onOpenNote: undefined })

const noteNodes = computed(() => props.graph.nodes.filter(node => node.kind === 'note' || !node.kind))
const noteIds = computed(() => new Set(noteNodes.value.map(node => node.id)))
const noteEdges = computed(() => props.graph.edges.filter(edge => noteIds.value.has(edge.source) && noteIds.value.has(edge.target)))
const positionedNodes = computed(() => noteNodes.value.map((node, index) => ({
  ...node,
  x: index % 2 === 0 ? 72 : 208,
  y: 36 + Math.floor(index / 2) * 64,
})))
const graphHeight = computed(() => Math.max(104, Math.ceil(positionedNodes.value.length / 2) * 64 + 20))
const positionById = computed(() => new Map(positionedNodes.value.map(node => [node.id, node])))
const edgeLabel = (source: string, target: string): string => {
  const from = noteNodes.value.find(node => node.id === source)?.title || source
  const to = noteNodes.value.find(node => node.id === target)?.title || target
  return `${from} → ${to}`
}
function activate(id: string): void { void props.onOpenNote?.(id) }
</script>

<template>
  <section class="study-note-relation-graph" aria-label="笔记总体关系图">
    <header class="study-note-relation-graph-head">
      <span><GitBranch :size="14" aria-hidden="true" />关系图</span>
      <LoaderCircle v-if="loading" class="study-note-graph-loading" :size="13" aria-label="关系图加载中" />
    </header>
    <p v-if="error" class="study-note-graph-error" role="alert">{{ error }}</p>
    <p v-else-if="!noteNodes.length && !loading" class="study-note-graph-empty">暂无笔记关系。</p>
    <div v-else class="study-note-graph-body">
      <svg v-if="positionedNodes.length" class="study-note-graph-svg" data-note-graph-svg :viewBox="`0 0 280 ${graphHeight}`" role="img" aria-label="笔记总体关系图">
        <g v-for="edge in noteEdges" :key="`svg-${edge.id}`" class="study-note-graph-svg-edge" :data-edge-type="edge.type">
          <line v-if="positionById.get(edge.source) && positionById.get(edge.target)" :x1="positionById.get(edge.source)!.x" :y1="positionById.get(edge.source)!.y" :x2="positionById.get(edge.target)!.x" :y2="positionById.get(edge.target)!.y" />
        </g>
        <g v-for="node in positionedNodes" :key="`svg-node-${node.id}`" class="study-note-graph-svg-node" :class="{ 'is-active': activeId === node.id }" :data-note-graph-node="node.id" role="button" tabindex="0" :aria-label="`打开笔记 ${node.title}`" @click="activate(node.id)" @keydown.enter.prevent="activate(node.id)" @keydown.space.prevent="activate(node.id)">
          <circle :cx="node.x" :cy="node.y" r="9" />
          <text :x="node.x" :y="node.y + 25" text-anchor="middle">{{ node.title }}</text>
        </g>
      </svg>
      <ul class="study-note-graph-nodes" aria-label="笔记节点">
        <li v-for="node in noteNodes" :key="node.id">
          <button class="study-note-graph-node" :class="{ 'is-active': activeId === node.id }" type="button" :aria-current="activeId === node.id ? 'page' : undefined" @click="onOpenNote?.(node.id)">{{ node.title }}</button>
        </li>
      </ul>
      <ul v-if="noteEdges.length" class="study-note-graph-edges" aria-label="笔记关联">
        <li v-for="edge in noteEdges" :key="edge.id"><button class="study-note-graph-edge" type="button" @click="onOpenNote?.(edge.target)">{{ edgeLabel(edge.source, edge.target) }}<small>{{ edge.type === 'parent' ? '子文档' : '链接' }}</small></button></li>
      </ul>
    </div>
  </section>
</template>
