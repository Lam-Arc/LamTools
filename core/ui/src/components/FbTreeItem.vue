<template>
  <div class="fb-tree-item">
    <button
      type="button"
      class="fb-tree-row"
      :class="{ selected: isSelected }"
      :style="{ paddingLeft: `${depth * varIndent + 6}px` }"
      @click="onClick"
    >
      <span class="fb-tree-icon" aria-hidden="true">
        <component v-if="typeof icon !== 'string'" :is="icon" :size="13" :stroke-width="1.8" />
        <template v-else>{{ icon }}</template>
      </span>
      <span class="fb-tree-name" :title="entry.name">{{ entry.name }}</span>
    </button>
    <template v-if="expanded && entry.type === 'directory'">
      <div v-if="loadingChildren" class="fb-tree-item-loading" :style="{ paddingLeft: `${(depth + 1) * varIndent + 6}px` }">...</div>
      <div v-else-if="loadError" class="fb-tree-item-loading" :style="{ paddingLeft: `${(depth + 1) * varIndent + 6}px` }" role="alert">加载失败：{{ loadError }}</div>
      <template v-else>
        <FbTreeItem
          v-for="child in children"
          :key="child.name"
          :entry="child"
          :base-path="childBase"
          :selected-path="selectedPath"
          :api-base="apiBase"
          :depth="depth + 1"
          @select="onChildSelect"
          @navigate="onChildNavigate"
        />
      </template>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { ChevronDown, ChevronRight, EyeOff, FileText, Image, Lock, Music, Video, type LucideIcon } from 'lucide-vue-next'

const props = defineProps<{
  entry: { name: string; type: 'directory' | 'file'; size: number; ext: string; path?: string }
  basePath: string
  selectedPath: string
  apiBase: string
  depth: number
}>()

const emit = defineEmits<{
  select: [path: string]
  navigate: [path: string]
}>()

const expanded = ref(false)
const loadingChildren = ref(false)
const loadError = ref('')
let loadGeneration = 0
const children = ref<Array<{ name: string; type: 'directory' | 'file'; size: number; ext: string; path?: string }>>([])

const varIndent = 18

const childBase = computed(() => {
  // Drive entries from root carry an explicit path (e.g. "C:\\")
  if (props.entry.path) return props.entry.path
  if (!props.basePath) return props.entry.name
  const sep = props.basePath.includes('\\') ? '\\' : '/'
  return `${props.basePath}${sep}${props.entry.name}`
})

const isSelected = computed(() => {
  if (props.entry.type !== 'directory') return false
  const slashed = (p: string) => p.replace(/[\\/]+$/, '')
  return slashed(props.selectedPath) === slashed(childBase.value)
})

const icon = computed<LucideIcon | string>(() => {
  if (props.entry.type === 'directory') {
    return expanded.value ? ChevronDown : ChevronRight
  }
  return fileIcon(props.entry.ext)
})

function fileIcon(ext: string): LucideIcon | string {
  const map: Record<string, string> = {
    ts: 'TS', tsx: 'TS', js: 'JS', jsx: 'JS', mjs: 'JS', cjs: 'JS',
    vue: 'V', py: 'PY', rs: 'RS', go: 'GO', java: 'JV', c: 'C', cpp: 'C+',
    json: '{}', css: '#', scss: '#', less: '#',
    html: '<>', xml: '<>', md: 'M', yml: 'Y', yaml: 'Y', toml: 'T',
    pdf: 'P',
  }
  if (map[ext]) return map[ext]
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'ico'].includes(ext)) return Image
  if (['mp4', 'webm', 'mov', 'avi'].includes(ext)) return Video
  if (['mp3', 'wav', 'ogg'].includes(ext)) return Music
  if (ext === 'lock') return Lock
  if (ext === 'gitignore') return EyeOff
  if (ext === 'txt' || ext === 'log') return FileText
  return '·'
}

async function onClick() {
  if (props.entry.type === 'directory') {
    emit('select', childBase.value)

    if (!expanded.value) {
      expanded.value = true
      if (children.value.length === 0) {
        await loadChildren()
      }
    } else {
      expanded.value = false
    }
  }
}

async function loadChildren() {
  const generation = ++loadGeneration
  loadingChildren.value = true
  loadError.value = ''
  try {
    const res = await fetch(`${props.apiBase}/browse-directory?path=${encodeURIComponent(childBase.value)}`)
    if (!res.ok) throw new Error(`${res.status}`)
    const data = await res.json()
    if (generation === loadGeneration) {
      children.value = (data.entries || []).filter((e: { type: string }) => e.type === 'directory')
    }
  } catch (e) {
    // Surface the failure instead of silently showing an empty directory
    // (audit 19 S3).
    if (generation === loadGeneration) {
      children.value = []
      loadError.value = e instanceof Error ? e.message : String(e)
    }
  } finally {
    if (generation === loadGeneration) loadingChildren.value = false
  }
}

function onChildSelect(path: string) {
  emit('select', path)
}

function onChildNavigate(path: string) {
  emit('navigate', path)
}
</script>

<style scoped>
.fb-tree-item {
  user-select: none;
}

.fb-tree-row {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 8px 3px 6px;
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  font-size: 13px;
  text-align: left;
  cursor: pointer;
  border-radius: var(--radius-sm);
  transition: background 100ms ease;
}

.fb-tree-row:hover {
  background: color-mix(in srgb, currentColor var(--alpha-hover), transparent);
}

.fb-tree-row.selected {
  background: color-mix(in srgb, currentColor var(--alpha-active), transparent);
  color: var(--blue);
}

.fb-tree-icon {
  flex: 0 0 auto;
  width: 18px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  opacity: 0.7;
}

.fb-tree-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.fb-tree-item-loading {
  padding: 2px 8px;
  font-size: 12px;
  color: color-mix(in srgb, currentColor 40%, transparent);
}
</style>