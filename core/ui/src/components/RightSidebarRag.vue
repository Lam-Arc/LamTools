<template>
  <div class="right-sidebar-rag">
    <div class="right-sidebar-rag-status" :data-state="indexState">
      <span class="right-sidebar-rag-dot" aria-hidden="true"></span>
      <span>{{ indexLabel }}</span>
      <span v-if="countsLabel" class="right-sidebar-rag-counts">{{ countsLabel }}</span>
    </div>
    <form class="right-sidebar-rag-search" @submit.prevent="search">
      <input
        v-model="query"
        type="search"
        placeholder="搜索工作区索引"
        aria-label="搜索工作区索引"
        :disabled="!requestRpc || searchLoading"
      />
      <button type="submit" :disabled="!requestRpc || !query.trim() || searchLoading" aria-label="搜索">
        <LoaderCircle v-if="searchLoading" :size="14" :stroke-width="1.8" class="spinning" aria-hidden="true" />
        <Search v-else :size="14" :stroke-width="1.8" aria-hidden="true" />
      </button>
    </form>
    <p v-if="message" class="right-sidebar-rag-message" :data-state="indexState">{{ message }}</p>
    <ul v-if="results.length" class="right-sidebar-rag-results" aria-label="搜索结果">
      <li v-for="(result, index) in results" :key="`${result.key}:${index}`">
        <strong>{{ result.title }}</strong>
        <span v-if="result.detail">{{ result.detail }}</span>
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { LoaderCircle, Search } from 'lucide-vue-next'
import { getPluginWidget } from '../plugins/api'
import type { PluginWidgetEntry, RightSidebarRpc, RightSidebarWidgetSnapshot } from '../right-sidebar/types'

const props = withDefaults(defineProps<{
  requestRpc?: RightSidebarRpc
  projectId?: string | null
  workRoot?: string | null
  widgetEntry?: PluginWidgetEntry | null
  snapshot?: RightSidebarWidgetSnapshot | null
}>(), {
  requestRpc: undefined,
  projectId: null,
  workRoot: null,
  widgetEntry: null,
  snapshot: null,
})

type IndexState = 'unknown' | 'available' | 'error' | 'unavailable'
interface SearchResult { key: string; title: string; detail?: string }
const query = ref('')
const indexState = ref<IndexState>(props.requestRpc ? 'unknown' : 'unavailable')
const message = ref('')
const counts = ref<{ documents?: string; chunks?: string } | null>(null)
const results = ref<SearchResult[]>([])
const searchLoading = ref(false)

const indexLabel = computed(() => {
  switch (indexState.value) {
    case 'available': return '索引可用'
    case 'error': return '索引异常'
    case 'unavailable': return 'RAG 不可用'
    default: return '索引未检查'
  }
})
const countsLabel = computed(() => {
  if (!counts.value) return ''
  const parts: string[] = []
  if (counts.value.documents) parts.push(`${counts.value.documents} 文档`)
  if (counts.value.chunks) parts.push(`${counts.value.chunks} 分段`)
  return parts.join(' · ')
})

function readSnapshot(result: Record<string, unknown>): RightSidebarWidgetSnapshot | null {
  const candidate = result.snapshot || result.widget || result
  if (!candidate || typeof candidate !== 'object') return null
  const value = candidate as RightSidebarWidgetSnapshot
  return { ...value, blocks: Array.isArray(value.blocks) ? value.blocks : [] }
}

function applySnapshot(snapshot: RightSidebarWidgetSnapshot | null): void {
  if (!snapshot) return
  if (snapshot.state === 'ok') indexState.value = 'available'
  else if (snapshot.state === 'error' || snapshot.state === 'warning') indexState.value = 'error'
  else if (snapshot.state === 'disabled') indexState.value = 'unavailable'
  if (snapshot.message) message.value = snapshot.message
  const next: { documents?: string; chunks?: string } = {}
  for (const block of snapshot.blocks || []) {
    if (block.type !== 'metric') continue
    const label = String(block.label || '').toLowerCase()
    const value = block.value === undefined || block.value === null ? '' : String(block.value)
    if (!value) continue
    if (label.includes('document') || label.includes('文档')) next.documents = value
    if (label.includes('chunk') || label.includes('segment') || label.includes('分段')) next.chunks = value
  }
  counts.value = next.documents || next.chunks ? next : null
}

async function loadStatus(): Promise<void> {
  if (!props.requestRpc) return
  if (props.snapshot) {
    applySnapshot(props.snapshot)
    return
  }
  if (!props.widgetEntry) {
    // The repository does not ship a RAG provider.  Do not invent index
    // counts; the legacy search operation is attempted only on user action.
    indexState.value = 'unavailable'
    message.value = '未安装 RAG 插件；可尝试兼容搜索'
    return
  }
  try {
    const result = await getPluginWidget(props.requestRpc, {
      pluginId: props.widgetEntry.pluginId,
      widgetId: props.widgetEntry.id,
      projectId: props.projectId,
      workRoot: props.workRoot,
    })
    applySnapshot(readSnapshot(result))
  } catch (cause) {
    indexState.value = 'unavailable'
    message.value = `暂不可用：${cause instanceof Error ? cause.message : String(cause)}`
  }
}

function readResults(value: unknown): SearchResult[] {
  const raw = value && typeof value === 'object' ? value as Record<string, unknown> : {}
  const list = [raw.results, raw.hits, raw.documents, raw.items].find(Array.isArray) as unknown[] | undefined
  if (!list) return []
  return list.flatMap((item, index) => {
    if (typeof item === 'string') return [{ key: String(index), title: item }]
    if (!item || typeof item !== 'object') return []
    const row = item as Record<string, unknown>
    const title = String(row.title || row.name || row.path || row.text || '').trim()
    if (!title) return []
    const detail = String(row.snippet || row.content || row.excerpt || '').trim()
    return [{ key: String(row.id || row.path || index), title, detail: detail || undefined }]
  }).slice(0, 8)
}

async function search(): Promise<void> {
  if (!props.requestRpc || !query.value.trim() || searchLoading.value) return
  searchLoading.value = true
  message.value = ''
  results.value = []
  try {
    // Legacy operation compatibility: if a future RAG plugin exposes this
    // method, it remains useful even before a widget descriptor is available.
    const result = await props.requestRpc('rag.docs.search', {
      query: query.value.trim(),
      project_id: props.projectId ?? undefined,
      work_root: props.workRoot ?? undefined,
      limit: 8,
    })
    results.value = readResults(result)
    indexState.value = 'available'
    message.value = results.value.length ? '' : '没有匹配结果'
  } catch (cause) {
    indexState.value = 'unavailable'
    message.value = `搜索不可用：${cause instanceof Error ? cause.message : String(cause)}`
  } finally {
    searchLoading.value = false
  }
}

onMounted(() => { void loadStatus() })
</script>

<style scoped>
.right-sidebar-rag { display: grid; gap: var(--space-2); min-width: 0; }
.right-sidebar-rag-status { display: flex; align-items: center; gap: var(--space-2); min-height: 24px; color: color-mix(in srgb, var(--theme-backdrop-text) 68%, transparent); font-size: 12px; }
.right-sidebar-rag-dot { width: 7px; height: 7px; flex: 0 0 auto; border-radius: 50%; background: color-mix(in srgb, var(--theme-backdrop-text) 42%, transparent); }
.right-sidebar-rag-status[data-state="available"] .right-sidebar-rag-dot { background: var(--green); }
.right-sidebar-rag-status[data-state="error"] .right-sidebar-rag-dot { background: var(--red); }
.right-sidebar-rag-status[data-state="unavailable"] .right-sidebar-rag-dot { background: var(--orange); }
.right-sidebar-rag-counts { margin-left: auto; color: color-mix(in srgb, var(--theme-backdrop-text) 50%, transparent); font-family: var(--font-mono); font-size: 11px; }
.right-sidebar-rag-search { display: flex; align-items: stretch; min-width: 0; }
.right-sidebar-rag-search input { min-width: 0; flex: 1 1 auto; height: 32px; padding: 0 var(--space-2); border: 1px solid color-mix(in srgb, var(--theme-control-text) 12%, transparent); border-right: 0; border-radius: var(--radius-sm) 0 0 var(--radius-sm); background: color-mix(in srgb, var(--theme-control-background) 70%, transparent); color: var(--theme-control-text); font-size: 12px; }
.right-sidebar-rag-search button { display: inline-flex; align-items: center; justify-content: center; min-width: 34px; border: 1px solid color-mix(in srgb, var(--theme-control-text) 12%, transparent); border-radius: 0 var(--radius-sm) var(--radius-sm) 0; background: color-mix(in srgb, var(--theme-control-background) 70%, transparent); color: var(--theme-control-text); }
.right-sidebar-rag-search button:hover:not(:disabled) { background: color-mix(in srgb, var(--theme-control-text) var(--alpha-hover), var(--theme-control-background)); }
.right-sidebar-rag-search button:active:not(:disabled) { background: color-mix(in srgb, var(--theme-control-text) var(--alpha-active), var(--theme-control-background)); }
.right-sidebar-rag-search button:disabled { opacity: .45; cursor: default; }
.right-sidebar-rag-message { margin: 0; color: color-mix(in srgb, var(--theme-backdrop-text) 52%, transparent); font-size: 11px; line-height: 1.45; }
.right-sidebar-rag-message[data-state="error"] { color: color-mix(in srgb, var(--red) 72%, var(--theme-backdrop-text) 28%); }
.right-sidebar-rag-results { display: grid; gap: var(--space-1); margin: 0; padding: 0; list-style: none; }
.right-sidebar-rag-results li { display: grid; gap: 2px; min-width: 0; padding-top: var(--space-1); border-top: 1px solid color-mix(in srgb, var(--theme-backdrop-text) 8%, transparent); }
.right-sidebar-rag-results strong { overflow: hidden; color: var(--theme-backdrop-text); font-size: 12px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.right-sidebar-rag-results span { display: -webkit-box; overflow: hidden; color: color-mix(in srgb, var(--theme-backdrop-text) 54%, transparent); font-size: 11px; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.spinning { animation: right-sidebar-rag-spin .8s linear infinite; }
@keyframes right-sidebar-rag-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spinning { animation: none; } }
</style>
