<template>
  <div class="fb-tree-item">
    <button
      type="button"
      class="fb-tree-row"
      :class="{ selected: isSelected }"
      :style="{ paddingLeft: `${depth * varIndent + 6}px` }"
      @click="onClick"
    >
      <span class="fb-tree-icon" aria-hidden="true">{{ icon }}</span>
      <span class="fb-tree-name" :title="entry.name">{{ entry.name }}</span>
    </button>
    <template v-if="expanded && entry.type === 'directory'">
      <div v-if="loadingChildren" class="fb-tree-item-loading" :style="{ paddingLeft: `${(depth + 1) * varIndent + 6}px` }">...</div>
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

const icon = computed(() => {
  if (props.entry.type === 'directory') {
    return expanded.value ? '▾' : '▸'
  }
  return fileIcon(props.entry.ext)
})

function fileIcon(ext: string): string {
  const map: Record<string, string> = {
    ts: 'TS', tsx: 'TS', js: 'JS', jsx: 'JS', mjs: 'JS', cjs: 'JS',
    vue: 'V', py: 'PY', rs: 'RS', go: 'GO', java: 'JV', c: 'C', cpp: 'C+',
    json: '{}', css: '#', scss: '#', less: '#',
    html: '<>', xml: '<>', md: 'M', yml: 'Y', yaml: 'Y', toml: 'T',
    png: '🖼', jpg: '🖼', jpeg: '🖼', gif: '🖼', webp: '🖼', svg: '🖼', ico: '🖼',
    mp4: '▶', webm: '▶', mov: '▶', avi: '▶', mp3: '♪', wav: '♪', ogg: '♪',
    pdf: 'P', txt: '¶', log: '¶',
    lock: '🔒', gitignore: '🙈',
  }
  return map[ext] ?? '·'
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
  loadingChildren.value = true
  try {
    const res = await fetch(`${props.apiBase}/browse-directory?path=${encodeURIComponent(childBase.value)}`)
    if (!res.ok) throw new Error(`${res.status}`)
    const data = await res.json()
    children.value = (data.entries || []).filter((e: { type: string }) => e.type === 'directory')
  } catch {
    children.value = []
  } finally {
    loadingChildren.value = false
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
  font-size: var(--fb-font-size, 13px);
  text-align: left;
  cursor: pointer;
  border-radius: 4px;
  transition: background 100ms ease;
}

.fb-tree-row:hover {
  background: var(--fb-hover-bg, color-mix(in srgb, currentColor 6%, transparent));
}

.fb-tree-row.selected {
  background: var(--fb-selected-bg, color-mix(in srgb, currentColor 10%, transparent));
  color: var(--fb-accent, var(--blue));
}

.fb-tree-icon {
  flex: 0 0 auto;
  width: 18px;
  text-align: center;
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
  color: var(--fb-muted, color-mix(in srgb, currentColor 40%, transparent));
}
</style>