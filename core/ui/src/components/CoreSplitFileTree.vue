<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ChevronDown, ChevronRight, File, Folder, FolderOpen, RefreshCw } from 'lucide-vue-next'
import { splitNative, type SplitFileEntry } from '@/split/native'
const props = defineProps<{ root: string }>()
const emit = defineEmits<{ open: [path: string] }>()
const entries = ref<Record<string, SplitFileEntry[]>>({}), expanded = ref(new Set<string>()), error = ref(''), loading = ref(new Set<string>())
async function load(path: string) {
  if (!props.root) { error.value = '先选择一个项目，再浏览文件'; return }
  if (loading.value.has(path)) return
  loading.value.add(path); error.value = ''
  try { entries.value[path] = await splitNative<SplitFileEntry[]>('split_file_list', { root: props.root, path }) }
  catch (e) { error.value = String(e) } finally { loading.value.delete(path) }
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
onMounted(() => load(props.root))
</script>
<template>
  <div class="split-file-tree">
    <div class="split-content-toolbar"><span class="split-path" :title="root">{{ root.split(/[\\/]/).filter(Boolean).pop() || '项目文件' }}</span><button class="split-icon-button" type="button" aria-label="刷新文件树" title="刷新" @click="load(root)"><RefreshCw :size="14" /></button></div>
    <p v-if="error" class="split-content-error" role="alert">{{ error }}</p>
    <div class="split-file-rows" role="tree" aria-label="项目文件">
      <button v-for="{entry, depth} in rows" :key="entry.path" type="button" role="treeitem" :aria-level="depth + 1" :aria-expanded="entry.directory ? expanded.has(entry.path) : undefined" :style="{ paddingLeft: `${12 + depth * 16}px` }" :title="entry.path" @click="toggle(entry)">
        <component :is="entry.directory ? expanded.has(entry.path) ? ChevronDown : ChevronRight : File" :size="13" aria-hidden="true" />
        <component v-if="entry.directory" :is="expanded.has(entry.path) ? FolderOpen : Folder" :size="14" aria-hidden="true" /><span>{{ entry.name }}</span>
      </button>
      <p v-if="!rows.length && !error" class="split-content-notice">{{ loading.size ? '正在读取目录…' : '文件夹为空' }}</p>
    </div>
  </div>
</template>
