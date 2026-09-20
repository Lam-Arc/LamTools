<script setup lang="ts">
import { BookOpen, ChartNoAxesCombined, ChevronDown, ChevronRight, FileText, GitBranch, Pin, PinOff, Search } from 'lucide-vue-next'
import { ref } from 'vue'
import { openContextMenu } from '../components/context-menu'
import type { Course, KnowledgeItem, StudyPin } from './types'

type TreeParent = { id: string; kind: 'course' | 'module'; courseId?: string }

const props = withDefaults(defineProps<{
  courses: Course[]
  active: string
  select: (id: string) => void | Promise<void>
  loadChildren?: (parent: TreeParent) => Promise<KnowledgeItem[]>
  openNode?: (node: KnowledgeItem) => void | Promise<void>
  openPin?: (pin: StudyPin) => void | Promise<void>
  openSearch?: () => void
  pins?: StudyPin[]
  togglePin?: (pin: StudyPin) => void | Promise<void>
}>(), {
  loadChildren: undefined,
  openNode: undefined,
  openPin: undefined,
  openSearch: undefined,
  pins: () => [],
  togglePin: undefined,
})

const expanded = ref<Set<string>>(new Set())
const children = ref<Record<string, KnowledgeItem[]>>({})
const loading = ref<Set<string>>(new Set())

function isGroup(item: KnowledgeItem | Course): boolean {
  if ('learnable' in item) return item.entity === 'course' || !item.learnable
  return true
}

function hasChildren(item: KnowledgeItem | Course): boolean {
  if (children.value[item.id]?.length) return true
  if ('childCount' in item && Number(item.childCount || item.child_count || 0) > 0) return true
  return isGroup(item)
}

function keyFor(parent: { id: string; kind: string }): string {
  return `${parent.kind}:${parent.id}`
}

async function toggle(parent: TreeParent): Promise<void> {
  const key = keyFor(parent)
  if (expanded.value.has(key)) {
    const next = new Set(expanded.value)
    next.delete(key)
    expanded.value = next
    return
  }
  const next = new Set(expanded.value)
  next.add(key)
  expanded.value = next
  if (!props.loadChildren || children.value[key] || loading.value.has(key)) return
  loading.value = new Set(loading.value).add(key)
  try {
    children.value = { ...children.value, [key]: await props.loadChildren(parent) }
  } finally {
    const pending = new Set(loading.value)
    pending.delete(key)
    loading.value = pending
  }
}

function activateNode(node: KnowledgeItem): void {
  if (isGroup(node) && !node.learnable) {
    void toggle({ id: node.id, kind: 'module', courseId: node.course_id })
    return
  }
  if (props.openNode) void props.openNode(node)
  else void props.select(node.id)
}

function activateCourse(course: Course): void {
  // A course is always a grouping row. The map manager is the explicit graph
  // entry above; the course label never opens a session.
  void toggle({ id: course.id, kind: 'course' })
}

function pinMenu(event: MouseEvent, pin: StudyPin): void {
  if (!props.togglePin) return
  const pinned = props.pins.some(candidate => candidate.kind === pin.kind && candidate.id === pin.id)
  openContextMenu({
    event,
    ariaLabel: 'Study 置顶操作',
    items: [{
      label: pinned ? '取消置顶' : '置顶',
      icon: pinned ? PinOff : Pin,
      action: () => props.togglePin?.(pin),
    }],
  })
}

function visibleChildren(course: Course): Array<{ node: KnowledgeItem; depth: number }> {
  const rows: Array<{ node: KnowledgeItem; depth: number }> = []
  const append = (parent: TreeParent, depth: number): void => {
    for (const node of children.value[keyFor(parent)] || []) {
      rows.push({ node, depth })
      const moduleParent: TreeParent = { id: node.id, kind: 'module', courseId: node.course_id || course.id }
      if (expanded.value.has(keyFor(moduleParent))) append(moduleParent, depth + 1)
    }
  }
  append({ id: course.id, kind: 'course' }, 1)
  return rows
}

</script>

<template>
  <nav class="study-sidebar" aria-label="Study">
    <button class="sidebar-action study-sidebar-action" :class="{ active: active === 'search' }" type="button" @click="openSearch ? openSearch() : undefined">
      <Search :size="15" aria-hidden="true" /><span>搜索</span>
    </button>
    <button class="sidebar-action study-sidebar-action" :class="{ active: active === 'manage' }" type="button" @click="select('manage')">
      <ChartNoAxesCombined :size="15" aria-hidden="true" /><span>管理你的知识</span>
    </button>
    <button class="sidebar-action study-sidebar-action" :class="{ active: active === 'map' }" type="button" @click="select('map')">
      <GitBranch :size="15" aria-hidden="true" /><span>图谱</span>
    </button>
    <button class="sidebar-action study-sidebar-action" :class="{ active: active === 'notes' }" type="button" @click="select('notes')">
      <FileText :size="15" aria-hidden="true" /><span>笔记</span>
    </button>
    <div class="study-sidebar-divider" role="separator" />
    <section v-if="pins.length" class="study-pinned" aria-label="置顶">
      <span class="study-pinned-label">置顶</span>
      <button v-for="pin in pins" :key="`${pin.kind}:${pin.id}`" class="study-pinned-item" type="button" :title="pin.title" @click="openPin ? openPin(pin) : select(pin.id)">
        <Pin :size="13" aria-hidden="true" /><span>{{ pin.title }}</span>
      </button>
    </section>
    <section class="study-subject-tree" aria-label="学科">
      <div v-for="course in courses" :key="course.id" class="study-tree-group">
        <div class="study-tree-row study-tree-row--course">
          <button
            class="study-tree-arrow"
            type="button"
            :aria-label="(expanded.has(keyFor({ id: course.id, kind: 'course' })) ? '收起 ' : '展开 ') + course.name"
            :aria-expanded="expanded.has(keyFor({ id: course.id, kind: 'course' }))"
            @click.stop="toggle({ id: course.id, kind: 'course' })"
          ><ChevronDown v-if="expanded.has(keyFor({ id: course.id, kind: 'course' }))" :size="14" /><ChevronRight v-else :size="14" /></button>
          <button class="study-tree-label" type="button" @click="activateCourse(course)"><BookOpen :size="14" aria-hidden="true" /><span>{{ course.name }}</span></button>
        </div>
        <div v-if="expanded.has(keyFor({ id: course.id, kind: 'course' }))" class="study-tree-children">
          <template v-for="entry in visibleChildren(course)" :key="entry.node.id">
            <div class="study-tree-item" :style="{ '--study-tree-depth': entry.depth }">
              <div class="study-tree-row" :class="{ 'study-tree-row--learnable': entry.node.learnable }">
                <button
                  v-if="hasChildren(entry.node)"
                  class="study-tree-arrow"
                  type="button"
                  :aria-label="(expanded.has(keyFor({ id: entry.node.id, kind: 'module' })) ? '收起 ' : '展开 ') + entry.node.name"
                  :aria-expanded="expanded.has(keyFor({ id: entry.node.id, kind: 'module' }))"
                  @click.stop="toggle({ id: entry.node.id, kind: 'module', courseId: entry.node.course_id })"
                ><ChevronDown v-if="expanded.has(keyFor({ id: entry.node.id, kind: 'module' }))" :size="14" /><ChevronRight v-else :size="14" /></button>
                <span v-else class="study-tree-arrow study-tree-arrow--placeholder" aria-hidden="true" />
                <button class="study-tree-label" type="button" :title="entry.node.name" @click="activateNode(entry.node)" @contextmenu.prevent="pinMenu($event, { id: entry.node.id, kind: 'node', title: entry.node.name })">
                  <span class="study-tree-status" :class="`study-tree-status--${entry.node.assessment}`" aria-hidden="true" />
                  <span>{{ entry.node.name }}</span>
                </button>
              </div>
              <span v-if="loading.has(keyFor({ id: entry.node.id, kind: 'module' }))" class="study-tree-loading" role="status">加载中…</span>
            </div>
          </template>
          <span v-if="loading.has(keyFor({ id: course.id, kind: 'course' }))" class="study-tree-loading" role="status">加载中…</span>
        </div>
      </div>
    </section>
  </nav>
</template>

<style scoped>
.study-sidebar { display: flex; flex-direction: column; gap: var(--space-1); padding: var(--space-2); color: var(--theme-backdrop-text); min-width: 0; overflow: auto; }
.study-sidebar-action { display: flex; gap: var(--space-2); width: 100%; text-align: left; }
.study-sidebar-action.active { background: color-mix(in srgb, var(--theme-backdrop-text) var(--alpha-active), transparent); }
.study-sidebar-divider { height: 1px; margin: var(--space-2) var(--space-1); background: color-mix(in srgb, var(--theme-backdrop-text) 12%, transparent); }
.study-pinned { display: flex; flex-direction: column; gap: var(--space-1); }
.study-pinned-label { padding: 0 var(--space-2); color: color-mix(in srgb, var(--theme-backdrop-text) 55%, transparent); font-size: 11px; }
.study-pinned-item { display: flex; gap: var(--space-2); align-items: flex-start; width: 100%; padding: 5px var(--space-2); border: 0; border-radius: var(--radius-sm); background: transparent; color: color-mix(in srgb, var(--theme-backdrop-text) 78%, transparent); text-align: left; cursor: pointer; overflow-wrap: anywhere; }
.study-pinned-item:hover { background: color-mix(in srgb, var(--theme-backdrop-text) var(--alpha-hover), transparent); color: var(--theme-backdrop-text); }
.study-subject-tree { display: flex; flex-direction: column; gap: var(--space-1); min-width: 0; }
.study-tree-group, .study-tree-children { display: flex; flex-direction: column; gap: var(--space-1); min-width: 0; }
.study-tree-children { padding-left: var(--space-3); }
.study-tree-item { padding-left: calc((var(--study-tree-depth) - 1) * var(--space-3)); }
.study-tree-row { display: flex; align-items: flex-start; gap: var(--space-1); min-width: 0; min-height: 30px; padding: 2px 0; }
.study-tree-row--child { padding-left: var(--space-2); }
.study-tree-arrow { display: inline-flex; flex: 0 0 24px; align-items: center; justify-content: center; min-height: 26px; padding: 0; border: 0; border-radius: var(--radius-sm); background: transparent; color: color-mix(in srgb, var(--theme-backdrop-text) 68%, transparent); cursor: pointer; }
.study-tree-arrow:hover { background: color-mix(in srgb, var(--theme-backdrop-text) var(--alpha-hover), transparent); color: var(--theme-backdrop-text); }
.study-tree-arrow--placeholder { cursor: default; }
.study-tree-label { display: inline-flex; flex: 1 1 auto; align-items: flex-start; gap: var(--space-2); min-width: 0; padding: 5px 6px; border: 0; border-radius: var(--radius-sm); background: transparent; color: color-mix(in srgb, var(--theme-backdrop-text) 78%, transparent); cursor: pointer; text-align: left; white-space: normal; overflow-wrap: anywhere; line-height: 1.35; }
.study-tree-label:hover { background: color-mix(in srgb, var(--theme-backdrop-text) var(--alpha-hover), transparent); color: var(--theme-backdrop-text); }
.study-tree-row--course .study-tree-label { color: var(--theme-backdrop-text); font-weight: 650; }
.study-tree-status { flex: 0 0 8px; width: 8px; height: 8px; margin-top: 5px; border: 1px solid currentColor; border-radius: 50%; color: color-mix(in srgb, var(--theme-backdrop-text) 45%, transparent); }
.study-tree-status--pass { color: var(--green); }
.study-tree-status--fail { color: color-mix(in srgb, var(--theme-backdrop-text) 45%, transparent); border-style: dashed; }
.study-tree-loading { padding: var(--space-1) var(--space-4); color: color-mix(in srgb, var(--theme-backdrop-text) 60%, transparent); font-size: 12px; }
@media (prefers-reduced-motion: reduce) { .study-tree-label, .study-tree-arrow { transition: none; } }
</style>
