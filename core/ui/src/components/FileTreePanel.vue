<template>
  <div class="file-tree-panel">
    <div class="file-tree-header">
      <strong>文件</strong>
      <button type="button" class="file-tree-refresh" title="刷新" @click="refresh">↻</button>
    </div>
    <div class="file-tree-body">
      <div v-if="loading && rootEntries.length === 0" class="file-tree-loading">加载中...</div>
      <div v-else-if="error" class="file-tree-error">{{ error }}</div>
      <template v-else>
        <FileTreeNode
          v-for="entry in rootEntries"
          :key="entry.name"
          :entry="entry"
          :project-id="projectId"
          :client="client"
          :base-path="''"
          :depth="0"
          @open-file="onOpenFile"
        />
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import type { CoreProjectClient, CoreFileEntry } from '../projects/client'
import FileTreeNode from './FileTreeNode.vue'

const props = defineProps<{
  projectId: string
  client: CoreProjectClient
}>()

const emit = defineEmits<{
  'open-file': [entry: { path: string; name: string; ext: string }]
}>()

const rootEntries = ref<CoreFileEntry[]>([])
const loading = ref(false)
const error = ref('')

async function loadRoot() {
  loading.value = true
  error.value = ''
  try {
    const result = await props.client.listFiles(props.projectId, '')
    rootEntries.value = result.entries
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function refresh() {
  loadRoot()
}

function onOpenFile(entry: { path: string; name: string; ext: string }) {
  emit('open-file', entry)
}

onMounted(loadRoot)

watch(() => props.projectId, () => {
  loadRoot()
})
</script>

<style scoped>
.file-tree-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  color: var(--theme-backdrop-text, #f2efeb);
}
.file-tree-header {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 0 8px;
}
.file-tree-header strong { font-size: 14px; }
.file-tree-refresh {
  width: 24px;
  height: 24px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: inherit;
  cursor: pointer;
  font-size: 14px;
  opacity: 0.6;
}
.file-tree-refresh:hover { opacity: 1; background: rgba(255,255,255,0.08); }
.file-tree-body {
  flex: 1;
  overflow: auto;
  scrollbar-width: none;
  -ms-overflow-style: none;
}
.file-tree-body::-webkit-scrollbar { width: 0; height: 0; display: none; }
.file-tree-loading, .file-tree-error {
  padding: 8px 4px;
  font-size: 12px;
  color: rgba(255,255,255,0.5);
}
.file-tree-error { color: var(--orange, #e07a5b); }
</style>
