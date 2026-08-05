<template>
  <div class="file-tree-node">
    <button
      type="button"
      class="file-tree-row"
      :style="{ paddingLeft: `${depth * 14 + 4}px` }"
      @click="onClick"
    >
      <span class="file-tree-icon" aria-hidden="true">{{ icon }}</span>
      <span class="file-tree-name" :title="entry.name">{{ entry.name }}</span>
    </button>
    <template v-if="entry.type === 'directory' && expanded">
      <div v-if="loading" class="file-tree-loading" :style="{ paddingLeft: `${(depth + 1) * 14 + 4}px` }">...</div>
      <template v-else>
        <FileTreeNode
          v-for="child in children"
          :key="child.name"
          :entry="child"
          :project-id="projectId"
          :client="client"
          :base-path="childPath"
          :depth="depth + 1"
          @open-file="onChildOpenFile"
        />
      </template>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import type { CoreProjectClient, CoreFileEntry } from '../projects/client'
import FileTreeNode from './FileTreeNode.vue'

const props = defineProps<{
  entry: CoreFileEntry
  projectId: string
  client: CoreProjectClient
  basePath: string
  depth: number
}>()

const emit = defineEmits<{
  'open-file': [entry: { path: string; name: string; ext: string }]
}>()

const expanded = ref(false)
const loading = ref(false)
const children = ref<CoreFileEntry[]>([])

const childPath = computed(() => {
  if (props.basePath) return `${props.basePath}/${props.entry.name}`
  return props.entry.name
})

const icon = computed(() => {
  if (props.entry.type === 'directory') return expanded.value ? '▾' : '▸'
  return fileIcon(props.entry.ext)
})

function fileIcon(ext: string): string {
  const map: Record<string, string> = {
    ts: 'TS', tsx: 'TS', js: 'JS', jsx: 'JS', mjs: 'JS',
    vue: 'V', py: 'PY', json: '{}', css: '#', scss: '#',
    html: '<>', md: 'M', yml: 'Y', yaml: 'Y', toml: 'T',
    png: '🖼', jpg: '🖼', jpeg: '🖼', gif: '🖼', webp: '🖼', svg: '🖼',
    mp4: '▶', webm: '▶', mov: '▶', mp3: '♪', wav: '♪',
    pdf: 'P',
  }
  return map[ext] ?? '·'
}

async function onClick() {
  if (props.entry.type === 'directory') {
    expanded.value = !expanded.value
    if (expanded.value && children.value.length === 0) {
      await loadChildren()
    }
  } else {
    emit('open-file', {
      path: childPath.value,
      name: props.entry.name,
      ext: props.entry.ext,
    })
  }
}

async function loadChildren() {
  loading.value = true
  try {
    const result = await props.client.listFiles(props.projectId, childPath.value)
    children.value = result.entries
  } catch {
    children.value = []
  } finally {
    loading.value = false
  }
}

function onChildOpenFile(entry: { path: string; name: string; ext: string }) {
  emit('open-file', entry)
}
</script>

<style scoped>
.file-tree-node {
  user-select: none;
}
.file-tree-row {
  width: 100%;
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding: 3px 8px 3px 4px;
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  font-size: 13px;
  text-align: left;
  cursor: pointer;
  border-radius: 0;
  position: relative;
}
.file-tree-row::before {
  content: ""; position: absolute; inset: 0;
  border-radius: 0; background: transparent; pointer-events: none;
  -webkit-mask-image: linear-gradient(to right, rgba(0,0,0,.2) 0, #000 var(--row-fade), #000 calc(100% - var(--row-fade)), rgba(0,0,0,.2) 100%);
  mask-image: linear-gradient(to right, rgba(0,0,0,.2) 0, #000 var(--row-fade), #000 calc(100% - var(--row-fade)), rgba(0,0,0,.2) 100%);
}
.file-tree-row:hover::before {
  background: color-mix(in srgb, currentColor var(--alpha-hover), transparent);
}
.file-tree-icon {
  flex: 0 0 auto;
  width: 16px;
  text-align: center;
  font-size: 11px;
  opacity: 0.7;
}
.file-tree-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.file-tree-loading {
  padding: 2px 8px;
  font-size: 12px;
  color: color-mix(in srgb, currentColor 55%, transparent);
}
</style>
