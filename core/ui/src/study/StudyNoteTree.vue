<script setup lang="ts">
import { computed, defineComponent, h, ref, type PropType, type VNode } from 'vue'
import { ArrowLeft, ChevronDown, ChevronRight, FileText, Folder, FolderOpen, RefreshCw } from 'lucide-vue-next'
import type { StudyNoteTreeNode } from './types'

const props = withDefaults(defineProps<{
  tree: StudyNoteTreeNode[]
  activeId?: string
  loading?: boolean
  error?: string
  onSelect?: (node: StudyNoteTreeNode) => void | Promise<void>
  onRefresh?: () => void | Promise<void>
  onBack?: () => void | Promise<void>
}>(), { activeId: '', loading: false, error: '', onSelect: undefined, onRefresh: undefined, onBack: undefined })

const expanded = ref<Set<string>>(new Set())
const roots = computed(() => props.tree)

function isFolder(node: StudyNoteTreeNode): boolean { return node.kind === 'folder' || Boolean(node.children?.length) || node.hasChildren === true }
function isExpanded(node: StudyNoteTreeNode): boolean { return expanded.value.has(node.id) }
function toggle(node: StudyNoteTreeNode): void {
  const next = new Set(expanded.value)
  if (next.has(node.id)) next.delete(node.id)
  else next.add(node.id)
  expanded.value = next
}
function select(node: StudyNoteTreeNode): void {
  if (isFolder(node)) { toggle(node); return }
  void props.onSelect?.(node)
}
function label(node: StudyNoteTreeNode): string { return node.title || node.path || node.id }

function renderRows(nodes: StudyNoteTreeNode[]): VNode {
  return h('ul', { class: 'study-note-tree-list' }, nodes.map(node => {
    const folder = isFolder(node)
    const activeId = node.noteId || node.note_id || node.id
    return h('li', { key: node.id, class: 'study-note-tree-item' }, [
      h('button', {
        class: ['study-note-tree-row', { 'is-active': props.activeId === activeId, 'is-folder': folder }],
        type: 'button',
        title: node.path,
        'aria-current': props.activeId === activeId ? 'page' : undefined,
        'aria-expanded': folder ? isExpanded(node) : undefined,
        onClick: () => select(node),
      }, [
        h('span', { class: 'study-note-tree-toggle', 'aria-hidden': 'true' }, [folder ? h(isExpanded(node) ? ChevronDown : ChevronRight, { size: 13 }) : null]),
        h(folder ? (isExpanded(node) ? FolderOpen : Folder) : FileText, { size: 14, 'aria-hidden': 'true' }),
        h('span', { class: 'study-note-tree-label' }, label(node)),
      ]),
      folder && isExpanded(node) && node.children?.length ? renderRows(node.children) : null,
    ])
  }))
}

const TreeRows = defineComponent({
  name: 'StudyNoteTreeRows',
  props: {
    nodes: { type: Array as PropType<StudyNoteTreeNode[]>, required: true },
  },
  setup(rowProps) {
    return () => renderRows(rowProps.nodes)
  },
})
</script>

<template>
  <nav class="study-note-tree" aria-label="笔记文件树">
    <button v-if="onBack" class="study-note-tree-row study-note-tree-back" type="button" @click="onBack">
      <ArrowLeft :size="16" aria-hidden="true" /><span>返回学习</span>
    </button>
    <header class="study-note-tree-head">
      <span class="study-note-tree-title">笔记库</span>
      <button v-if="onRefresh" class="study-sidebar-icon-button" type="button" aria-label="刷新笔记文件树" title="刷新" :disabled="loading" @click="onRefresh">
        <RefreshCw :size="14" aria-hidden="true" />
      </button>
    </header>
    <p v-if="error" class="study-note-tree-error" role="alert">{{ error }}</p>
    <p v-else-if="loading && !tree.length" class="study-note-tree-status" role="status">加载中…</p>
    <p v-else-if="!tree.length" class="study-note-tree-status">还没有 Markdown 笔记。</p>
    <TreeRows v-else :nodes="roots" />
  </nav>
</template>
