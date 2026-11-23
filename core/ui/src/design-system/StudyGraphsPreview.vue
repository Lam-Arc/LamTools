<script setup lang="ts">
import { ref } from 'vue'
import type { Node, ViewportTransform } from '@vue-flow/core'
import StudyGraph from '@/study/StudyGraph.vue'
import StudyNoteRelationGraph from '@/study/StudyNoteRelationGraph.vue'
import type { KnowledgeItem, StudyNoteGraph } from '@/study/types'
import '@/study/study.css'

// user:“交互测试”+(图谱拖动、缩放和打开仅修改展厅内存)。
defineProps<{ view: 'knowledge' | 'notes' }>()
const item: KnowledgeItem = { id: 'concept', name: '示例知识点', entity: 'node', learnable: true, progressRole: 'unit', assessment: 'pass', mastery: 'medium' }
const course: KnowledgeItem = { id: 'course', name: '示例课程', entity: 'course', learnable: false, progressRole: 'none', assessment: 'unassessed', mastery: null, total: 2, progressPassed: 1 }
const nodes = ref<Node<KnowledgeItem>[]>([{ id: 'course', type: 'knowledge', data: course, position: { x: 80, y: 80 } }, { id: 'concept', type: 'knowledge', data: item, position: { x: 350, y: 100 } }])
const viewport = ref<ViewportTransform>({ x: 0, y: 0, zoom: 1 })
const net = { revision: 1, total: 2, relations: [{ id: 'edge', source: 'course', target: 'concept', type: 'contains' }] }
const graph: StudyNoteGraph = { revision: 1, nodes: [{ id: 'a', title: '笔记 A', kind: 'note' }, { id: 'b', title: '笔记 B', kind: 'note' }], edges: [{ id: 'ab', source: 'a', target: 'b', type: 'wikilink' }] }
const empty = ref(false), opened = ref(''), count = ref(0)
function openNode(value: KnowledgeItem) { opened.value = value.name; count.value++ }
</script>

<template>
  <div class="study-graphs-preview">
    <template v-if="view === 'knowledge'">
      <div class="study-view study-graphs-preview__canvas"><StudyGraph v-model:nodes="nodes" v-model:viewport="viewport" :net="net" :loading="false" graph-focus-id="" graph-selected-id="" :inspected="null" layout-notice="" @open-node="openNode" /></div>
      <span>本地缩放：{{ viewport.zoom.toFixed(2) }}</span><span v-if="opened">本地打开：{{ opened }} · {{ count }} 次</span>
    </template>
    <template v-else>
      <label><input v-model="empty" type="checkbox" class="sunday-checkbox" />空关系图</label>
      <div class="study-graphs-preview__relations"><StudyNoteRelationGraph :graph="empty ? { revision: 1, nodes: [], edges: [] } : graph" :active-id="opened" :on-open-note="id => { opened = id }" /></div>
      <span v-if="opened">本地打开：{{ opened }}</span>
    </template>
  </div>
</template>

<style scoped>
.study-graphs-preview { display: grid; gap: var(--space-3); width: 100%; }
.study-graphs-preview__canvas { height: 480px; display: flex; background: var(--theme-main-background); }
.study-graphs-preview__relations { background: var(--theme-backdrop-background); border-radius: var(--radius); }
</style>
