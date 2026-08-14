<template>
  <div class="file-tree-node">
    <button
      type="button"
      class="file-tree-row"
      :style="{ paddingLeft: `${depth * 14 + 4}px` }"
      @click="onClick"
    >
      <span class="file-tree-icon" aria-hidden="true">
        <component v-if="typeof icon !== 'string'" :is="icon" :size="13" :stroke-width="1.8" />
        <template v-else>{{ icon }}</template>
      </span>
      <span class="file-tree-name" :title="entry.name">{{ entry.name }}</span>
    </button>
    <template v-if="entry.type === 'directory' && expanded">
      <div v-if="loading" class="file-tree-loading" :style="{ paddingLeft: `${(depth + 1) * 14 + 4}px` }">...</div>
      <div v-else-if="loadError" class="file-tree-loading" :style="{ paddingLeft: `${(depth + 1) * 14 + 4}px` }" role="alert">加载失败：{{ loadError }}</div>
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
import { ChevronDown, ChevronRight, Image, Music, Video, type LucideIcon } from 'lucide-vue-next'
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
const loadError = ref('')
let loadGeneration = 0

const childPath = computed(() => {
  if (props.basePath) return `${props.basePath}/${props.entry.name}`
  return props.entry.name
})

const icon = computed<LucideIcon | string>(() => {
  if (props.entry.type === 'directory') return expanded.value ? ChevronDown : ChevronRight
  return fileIcon(props.entry.ext)
})

function fileIcon(ext: string): LucideIcon | string {
  const map: Record<string, string> = {
    ts: 'TS', tsx: 'TS', js: 'JS', jsx: 'JS', mjs: 'JS',
    vue: 'V', py: 'PY', json: '{}', css: '#', scss: '#',
    html: '<>', md: 'M', yml: 'Y', yaml: 'Y', toml: 'T',
    pdf: 'P',
  }
  if (map[ext]) return map[ext]
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'].includes(ext)) return Image
  if (['mp4', 'webm', 'mov'].includes(ext)) return Video
  if (['mp3', 'wav'].includes(ext)) return Music
  return '·'
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
  const generation = ++loadGeneration
  loading.value = true
  loadError.value = ''
  try {
    const result = await props.client.listFiles(props.projectId, childPath.value)
    if (generation === loadGeneration) children.value = result.entries
  } catch (e) {
    // Surface the failure instead of silently showing an empty directory
    // (audit 19 S3).
    if (generation === loadGeneration) {
      children.value = []
      loadError.value = e instanceof Error ? e.message : String(e)
    }
  } finally {
    if (generation === loadGeneration) loading.value = false
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
  display: inline-flex;
  align-items: center;
  justify-content: center;
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
