<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { ChevronDown, ChevronRight, File, Folder, FolderOpen, RefreshCw } from 'lucide-vue-next'
import { splitNative, type SplitFileEntry } from '@/split/native'
import '@/styles/split-workspace.css'
const props = defineProps<{ root: string; listFiles?: (root: string, path: string) => Promise<SplitFileEntry[]> }>()
const emit = defineEmits<{ open: [path: string] }>()
const entries = ref<Record<string, SplitFileEntry[]>>({}), expanded = ref(new Set<string>()), error = ref(''), loading = ref(new Set<string>())
const failedPath = ref('')
let generation = 0
async function load(path: string) {
  const root = props.root, run = generation
  if (!root) { failedPath.value = ''; error.value = '先选择一个项目，再浏览文件'; return }
  if (loading.value.has(path)) return
  loading.value.add(path); error.value = ''; failedPath.value = ''
  try { const result = props.listFiles ? await props.listFiles(root, path) : await splitNative<SplitFileEntry[]>('split_file_list', { root, path }); if (run === generation) entries.value[path] = result }
  catch (e) { if (run === generation) { error.value = String(e); failedPath.value = path } } finally { if (run === generation) loading.value.delete(path) }
}
async function toggle(entry: SplitFileEntry) {
  if (!entry.directory) { emit('open', entry.path); return }
  if (expanded.value.has(entry.path)) expanded.value.delete(entry.path)
  else { expanded.value.add(entry.path); if (!entries.value[entry.path]) await load(entry.path) }
}
const rows = computed(() => {
  const result: { entry: SplitFileEntry; depth: number }[] = []
  const walk = (path: string, depth: number) => { if (depth > 30) return; for (const entry of entries.value[path] || []) { result.push({ entry, depth }); if (entry.directory && expanded.value.has(entry.path)) walk(entry.path, depth + 1) } }
  walk(props.root, 0); return result
})
const tree = ref<HTMLElement | null>(null), focusedPath = ref('')
const activePath = computed(() => rows.value.some(row => row.entry.path === focusedPath.value) ? focusedPath.value : rows.value[0]?.entry.path)
function focusRow(index: number) {
  const row = rows.value[index]
  if (!row) return
  focusedPath.value = row.entry.path
  void nextTick(() => tree.value?.querySelectorAll<HTMLButtonElement>('[role="treeitem"]')[index]?.focus())
}
// user:“确保视觉、功能和交互不退化”+(文件树支持方向键展开、收起与逐项浏览)。
async function onTreeKeydown(event: KeyboardEvent, index: number) {
  const row = rows.value[index]
  if (!row) return
  if (event.key === 'ArrowDown') { event.preventDefault(); focusRow(Math.min(rows.value.length - 1, index + 1)) }
  else if (event.key === 'ArrowUp') { event.preventDefault(); focusRow(Math.max(0, index - 1)) }
  else if (event.key === 'Home') { event.preventDefault(); focusRow(0) }
  else if (event.key === 'End') { event.preventDefault(); focusRow(rows.value.length - 1) }
  else if (event.key === 'ArrowRight') {
    event.preventDefault()
    if (!row.entry.directory) return
    if (!expanded.value.has(row.entry.path)) await toggle(row.entry)
    else if (rows.value[index + 1]?.depth === row.depth + 1) focusRow(index + 1)
  } else if (event.key === 'ArrowLeft') {
    event.preventDefault()
    if (row.entry.directory && expanded.value.has(row.entry.path)) { expanded.value.delete(row.entry.path); return }
    for (let i = index - 1; i >= 0; i--) if (rows.value[i].depth < row.depth) { focusRow(i); break }
  }
}
// user:“确保视觉、功能和交互不退化”+(切换项目后重新加载，旧项目的迟到结果不能覆盖新界面)。
watch(() => props.root, root => { generation++; entries.value = {}; expanded.value = new Set(); loading.value = new Set(); focusedPath.value = ''; error.value = ''; failedPath.value = ''; void load(root) }, { immediate: true })
onBeforeUnmount(() => { generation++ })
</script>
<template>
  <div class="split-file-tree">
    <div class="split-content-toolbar"><span class="split-path" :title="root">{{ root.split(/[\\/]/).filter(Boolean).pop() || '项目文件' }}</span><button class="split-icon-button" type="button" aria-label="刷新文件树" title="刷新" @click="load(root)"><RefreshCw :size="14" /></button></div>
    <p v-if="error" class="split-content-error" role="alert">{{ error }} <button v-if="failedPath" type="button" class="split-text-button" @click="load(failedPath)">重试</button></p>
    <div ref="tree" class="split-file-rows" role="tree" aria-label="项目文件">
      <button v-for="({entry, depth}, index) in rows" :key="entry.path" type="button" role="treeitem" :tabindex="activePath === entry.path ? 0 : -1" :aria-level="depth + 1" :aria-expanded="entry.directory ? expanded.has(entry.path) : undefined" :style="{ paddingLeft: `${12 + depth * 16}px` }" :title="entry.path" @focus="focusedPath = entry.path" @keydown="onTreeKeydown($event, index)" @click="toggle(entry)">
        <component :is="entry.directory ? expanded.has(entry.path) ? ChevronDown : ChevronRight : File" :size="13" aria-hidden="true" />
        <component v-if="entry.directory" :is="expanded.has(entry.path) ? FolderOpen : Folder" :size="14" aria-hidden="true" /><span>{{ entry.name }}</span>
      </button>
      <p v-if="!rows.length && !error" class="split-content-notice">{{ loading.size ? '正在读取目录…' : '文件夹为空' }}</p>
    </div>
  </div>
</template>
