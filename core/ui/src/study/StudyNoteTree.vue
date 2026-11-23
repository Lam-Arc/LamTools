<script setup lang="ts">
import { t } from '@/i18n/index.ts'

import { computed, defineComponent, h, nextTick, ref, type PropType, type VNode } from 'vue'
import { ArrowLeft, ChevronDown, ChevronRight, FileText, Folder, FolderOpen, RefreshCw } from 'lucide-vue-next'
import type { StudyNoteTreeNode } from '@/study/types.ts'

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
const treeRoot = ref<HTMLElement | null>(null)
const focusedId = ref('')

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

const visibleRows = computed(() => {
  const rows: Array<{ node: StudyNoteTreeNode; depth: number }> = []
  const walk = (nodes: StudyNoteTreeNode[], depth: number) => {
    for (const node of nodes) {
      rows.push({ node, depth })
      if (isFolder(node) && isExpanded(node) && node.children) walk(node.children, depth + 1)
    }
  }
  walk(roots.value, 0)
  return rows
})
const activeFocusId = computed(() => visibleRows.value.some(row => row.node.id === focusedId.value) ? focusedId.value : visibleRows.value[0]?.node.id)
function focusRow(index: number): void {
  const row = visibleRows.value[index]
  if (!row) return
  focusedId.value = row.node.id
  void nextTick(() => treeRoot.value?.querySelectorAll<HTMLButtonElement>('[role="treeitem"]')[index]?.focus({ preventScroll: true }))
}
// user:“确保视觉、功能和交互不退化”+(方向键浏览笔记树，选择笔记仍走原有草稿保护流程)。
function onTreeKeydown(event: KeyboardEvent, node: StudyNoteTreeNode): void {
  const index = visibleRows.value.findIndex(row => row.node.id === node.id)
  if (index < 0) return
  if (event.key === 'ArrowDown') { event.preventDefault(); focusRow(Math.min(visibleRows.value.length - 1, index + 1)) }
  else if (event.key === 'ArrowUp') { event.preventDefault(); focusRow(Math.max(0, index - 1)) }
  else if (event.key === 'Home') { event.preventDefault(); focusRow(0) }
  else if (event.key === 'End') { event.preventDefault(); focusRow(visibleRows.value.length - 1) }
  else if (event.key === 'ArrowRight' && isFolder(node)) {
    event.preventDefault()
    if (!isExpanded(node)) toggle(node)
    else if (visibleRows.value[index + 1]?.depth === visibleRows.value[index].depth + 1) focusRow(index + 1)
  } else if (event.key === 'ArrowLeft') {
    event.preventDefault()
    if (isFolder(node) && isExpanded(node)) { toggle(node); return }
    for (let i = index - 1; i >= 0; i--) if (visibleRows.value[i].depth < visibleRows.value[index].depth) { focusRow(i); break }
  }
}

function renderRows(nodes: StudyNoteTreeNode[], depth = 0): VNode {
  return h('ul', { class: ['study-note-tree-list', { 'study-note-tree-list--nested': depth > 0 }], role: depth ? 'group' : 'tree', ref: depth ? undefined : treeRoot }, nodes.map(node => {
    const folder = isFolder(node)
    const activeId = node.noteId || node.note_id || node.id
    return h('li', { key: node.id, class: 'study-note-tree-item', role: 'none' }, [
      h('button', {
        class: ['study-note-tree-row', { 'is-active': props.activeId === activeId, 'is-folder': folder }],
        type: 'button',
        role: 'treeitem',
        tabindex: activeFocusId.value === node.id ? 0 : -1,
        'aria-level': depth + 1,
        title: node.path,
        'aria-current': props.activeId === activeId ? 'page' : undefined,
        'aria-expanded': folder ? isExpanded(node) : undefined,
        onFocus: () => { focusedId.value = node.id },
        onKeydown: (event: KeyboardEvent) => onTreeKeydown(event, node),
        onClick: () => select(node),
      }, [
        h('span', { class: 'study-note-tree-toggle', 'aria-hidden': 'true' }, [folder ? h(isExpanded(node) ? ChevronDown : ChevronRight, { size: 13 }) : null]),
        h(folder ? (isExpanded(node) ? FolderOpen : Folder) : FileText, { size: 14, 'aria-hidden': 'true' }),
        h('span', { class: 'study-note-tree-label' }, label(node)),
      ]),
      folder && isExpanded(node) && node.children?.length ? renderRows(node.children, depth + 1) : null,
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
  <nav class="study-note-tree" :aria-label="t('笔记文件树')">
    <button v-if="onBack" class="study-note-tree-row study-note-tree-back" type="button" @click="onBack">
      <ArrowLeft :size="16" aria-hidden="true" /><span>{{ t("返回学习") }}</span>
    </button>
    <header class="study-note-tree-head">
      <span class="study-note-tree-title">{{ t("笔记库") }}</span>
      <button v-if="onRefresh" class="study-sidebar-icon-button" type="button" :aria-label="t('刷新笔记文件树')" :title="t('刷新')" :disabled="loading" @click="onRefresh">
        <RefreshCw :size="14" aria-hidden="true" />
      </button>
    </header>
    <p v-if="error" class="study-note-tree-error" role="alert">{{ error }}</p>
    <p v-else-if="loading && !tree.length" class="study-note-tree-status" role="status">{{ t("加载中…") }}</p>
    <p v-else-if="!tree.length" class="study-note-tree-status">{{ t("还没有 Markdown 笔记。") }}</p>
    <TreeRows v-else :nodes="roots" />
  </nav>
</template>
