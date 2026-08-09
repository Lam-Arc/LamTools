<template>
  <div class="artifact-panel">
    <header class="artifact-panel-head">
      <div class="artifact-panel-title">
        <strong>Artifacts</strong>
        <span class="muted">{{ activeCount }} 个</span>
      </div>
      <div class="artifact-actions">
        <button
          v-if="!cleanupMode"
          class="text-btn danger"
          type="button"
          title="进入清理模式：勾选后统一删除"
          @click="enterCleanup"
        >清理</button>
        <template v-else>
          <button
            class="text-btn danger"
            type="button"
            :disabled="!selected.length"
            @click="deleteSelected"
          >删除 ({{ selected.length }})</button>
          <button class="text-btn" type="button" @click="exitCleanup">取消</button>
        </template>
        <button class="text-btn" type="button" title="刷新" @click="fetchArtifacts">↻</button>
      </div>
    </header>

    <p v-if="error" class="artifact-error" role="alert">{{ error }}</p>

    <div v-if="loading" class="artifact-empty">加载中…</div>
    <div v-else-if="!rows.length" class="artifact-empty">
      暂无 artifact。Agent 生成的图片或用户上传的附件会自动登记到这里。
    </div>
    <ul v-else class="artifact-tree">
      <li
        v-for="row in rows"
        :key="row.item.artifact_id"
        class="artifact-node"
        :class="{ 'artifact-node--selected': selectedArtifact?.artifact_id === row.item.artifact_id }"
        :style="{ paddingLeft: `${10 + row.depth * 14}px` }"
        @click="selectArtifact(row.item)"
      >
        <label v-if="cleanupMode" class="artifact-check" @click.stop>
          <input
            v-model="selectedSet"
            type="checkbox"
            :value="row.item.artifact_id"
            :aria-label="`选择 ${row.item.name}`"
          />
        </label>
        <span class="artifact-kind" :title="row.item.kind">{{ kindIcon(row.item.kind) }}</span>
        <span class="artifact-name" :title="row.item.path">{{ row.item.name }}</span>
        <span v-if="row.item.source === 'agent_generated'" class="artifact-badge artifact-badge--agent" title="Agent 生成">AI</span>
        <span v-else class="artifact-badge artifact-badge--user" title="用户上传">↑</span>
      </li>
    </ul>

    <div v-if="selectedArtifact" class="artifact-detail">
      <template v-if="previewUrl(selectedArtifact)">
        <img
          v-if="selectedArtifact.kind === 'image'"
          :src="previewUrl(selectedArtifact)"
          :alt="selectedArtifact.name"
          class="artifact-preview artifact-preview--image"
          loading="lazy"
        />
        <video
          v-else-if="selectedArtifact.kind === 'video'"
          :src="previewUrl(selectedArtifact)"
          class="artifact-preview"
          controls
          preload="metadata"
        />
        <audio
          v-else-if="selectedArtifact.kind === 'audio'"
          :src="previewUrl(selectedArtifact)"
          class="artifact-preview"
          controls
        />
        <iframe
          v-else-if="selectedArtifact.kind === 'pdf'"
          :src="previewUrl(selectedArtifact)"
          class="artifact-preview artifact-preview--pdf"
          title="PDF 预览"
        />
      </template>
      <dl class="artifact-meta">
        <template v-if="selectedArtifact.prompt">
          <dt>prompt</dt>
          <dd>{{ selectedArtifact.prompt }}</dd>
        </template>
        <dt>来源</dt>
        <dd>{{ selectedArtifact.source === 'agent_generated' ? 'Agent 生成' : '用户上传' }}</dd>
        <template v-if="selectedArtifact.parent_ids.length">
          <dt>参考图</dt>
          <dd>{{ selectedArtifact.parent_ids.map(id => id.slice(0, 8)).join(', ') }}</dd>
        </template>
        <dt>创建</dt>
        <dd>{{ formatTime(selectedArtifact.created_at) }}</dd>
      </dl>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

interface ArtifactItem {
  artifact_id: string
  kind: string
  mime_type: string
  name: string
  path: string
  source: string
  prompt?: string
  parent_ids: string[]
  children_ids: string[]
  created_at: string
  deleted: boolean
}

interface ArtifactRow {
  item: ArtifactItem
  depth: number
}

const props = defineProps<{
  projectId: string | null
  apiBase?: string
  requestRpc: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>
}>()

const artifacts = ref<ArtifactItem[]>([])
const loading = ref(false)
const error = ref('')
const cleanupMode = ref(false)
const selectedSet = ref<Set<string>>(new Set())
const selectedArtifact = ref<ArtifactItem | null>(null)

const activeCount = computed(() => artifacts.value.length)

const rows = computed<ArtifactRow[]>(() => {
  const byId = new Map(artifacts.value.map(item => [item.artifact_id, item]))
  const childrenOf = new Map<string, ArtifactItem[]>()
  for (const item of artifacts.value) {
    const parentId = item.parent_ids.find(id => byId.has(id))
    if (parentId) {
      const list = childrenOf.get(parentId) || []
      list.push(item)
      childrenOf.set(parentId, list)
    }
  }
  const result: ArtifactRow[] = []
  const visit = (item: ArtifactItem, depth: number) => {
    result.push({ item, depth })
    for (const child of childrenOf.get(item.artifact_id) || []) visit(child, depth + 1)
  }
  for (const item of artifacts.value) {
    if (!item.parent_ids.some(id => byId.has(id))) visit(item, 0)
  }
  return result
})

const selected = computed(() => Array.from(selectedSet.value))

function kindIcon(kind: string): string {
  return ({ image: '🖼', video: '🎞', audio: '🎵', pdf: '📕', document: '📄', file: '📦' } as Record<string, string>)[kind] || '📦'
}

function previewUrl(item: ArtifactItem): string {
  const base = (props.apiBase || '/api/core').replace(/\/+$/, '')
  if (item.path.startsWith('attachment://')) {
    return `${base}/attachments/${encodeURIComponent(item.path.slice('attachment://'.length))}/download`
  }
  if (item.path.startsWith('workspace://') && props.projectId) {
    const rel = item.path.slice('workspace://'.length)
    return `${base}/projects/${encodeURIComponent(props.projectId)}/files/raw?path=${encodeURIComponent(rel)}`
  }
  return ''
}

function formatTime(value: string): string {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function selectArtifact(item: ArtifactItem): void {
  selectedArtifact.value = item
}

function enterCleanup(): void {
  cleanupMode.value = true
  selectedSet.value = new Set()
}

function exitCleanup(): void {
  cleanupMode.value = false
  selectedSet.value = new Set()
}

async function deleteSelected(): Promise<void> {
  if (!selected.value.length || !props.projectId) return
  error.value = ''
  try {
    await props.requestRpc('artifact.delete', {
      project_id: props.projectId,
      artifact_ids: selected.value,
    })
    await fetchArtifacts()
    selectedArtifact.value = null
    exitCleanup()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

async function fetchArtifacts(): Promise<void> {
  if (!props.projectId) {
    artifacts.value = []
    return
  }
  loading.value = true
  error.value = ''
  try {
    const result = await props.requestRpc('artifact.list', { project_id: props.projectId })
    artifacts.value = (result.artifacts as ArtifactItem[]) || []
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

watch(() => props.projectId, () => {
  selectedArtifact.value = null
  exitCleanup()
  fetchArtifacts()
})

onMounted(fetchArtifacts)
</script>

<style scoped>
.artifact-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.artifact-panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 4px 2px 8px;
}

.artifact-panel-title {
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.artifact-panel-title strong {
  font-size: 13px;
}

.artifact-actions {
  display: flex;
  gap: 4px;
}

.artifact-tree {
  list-style: none;
  margin: 0;
  padding: 0;
  overflow: auto;
  flex: 1 1 auto;
  min-height: 60px;
}

.artifact-node {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 6px;
  border-radius: var(--radius-sm, 6px);
  cursor: pointer;
  font-size: 12px;
  line-height: 1.4;
  white-space: nowrap;
}

.artifact-node:hover {
  background: color-mix(in srgb, var(--theme-main-text, #f2efeb) var(--alpha-hover), transparent);
}

.artifact-node--selected {
  background: color-mix(in srgb, var(--theme-main-text, #f2efeb) var(--alpha-active), transparent);
}

.artifact-check {
  display: inline-flex;
  flex: 0 0 auto;
}

.artifact-kind {
  flex: 0 0 auto;
  font-size: 13px;
}

.artifact-name {
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1 1 auto;
  min-width: 0;
}

.artifact-badge {
  flex: 0 0 auto;
  font-size: 10px;
  padding: 0 4px;
  border-radius: var(--radius-sm, 4px);
  line-height: 1.5;
}

.artifact-badge--agent {
  color: var(--green, #46a758);
  background: color-mix(in srgb, var(--green, #46a758) 16%, transparent);
}

.artifact-badge--user {
  color: var(--blue, #79bcff);
  background: color-mix(in srgb, var(--blue, #79bcff) 16%, transparent);
}

.artifact-detail {
  flex: 0 0 auto;
  max-height: 45%;
  overflow: auto;
  padding: 10px 8px;
  border-top: 1px solid color-mix(in srgb, var(--theme-main-text, #f2efeb) 16%, transparent);
}

.artifact-preview {
  width: 100%;
  max-height: 180px;
  object-fit: contain;
  border-radius: var(--radius-sm, 6px);
  margin-bottom: 8px;
}

/* PDF 预览是文档内容底色（白纸），非界面表面层，不随主题 */
.artifact-preview--pdf {
  height: 180px;
  border: 1px solid color-mix(in srgb, var(--theme-main-text, #f2efeb) 18%, transparent);
  background: #fff;
}

.artifact-meta {
  margin: 0;
  font-size: 11px;
  color: color-mix(in srgb, var(--theme-main-text, #f2efeb) 56%, transparent);
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 3px 10px;
}

.artifact-meta dt {
  opacity: .75;
}

.artifact-meta dd {
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: inherit;
}

.artifact-error {
  margin: 0 0 8px;
  padding: 7px 10px;
  border-radius: var(--radius-sm, 6px);
  border: 1px solid color-mix(in srgb, var(--red, #f5555d) 22%, transparent);
  background: color-mix(in srgb, var(--red, #f5555d) 10%, transparent);
  color: color-mix(in srgb, var(--red, #f5555d) 64%, #fff);
  font-size: 12px;
}

.artifact-empty {
  padding: 14px 8px;
  color: color-mix(in srgb, var(--theme-main-text, #f2efeb) 56%, transparent);
  font-size: 12px;
  line-height: 1.6;
}
</style>
