<template>
  <Teleport to="body">
    <div class="settings-overlay" @click.self="$emit('close')">
      <div class="settings-card" :style="settingsThemeStyle">
        <header class="search-head">
          <div class="search-input-row">
            <Search :size="15" :stroke-width="1.8" aria-hidden="true" />
            <input
              ref="inputEl"
              :value="query"
              type="text"
              :placeholder="inputPlaceholder"
              aria-label="搜索"
              autocomplete="off"
              spellcheck="false"
              @input="onInput"
              @compositionstart="composing = true"
              @compositionend="onCompositionEnd"
              @keydown.enter.prevent="enterFirst"
              @keydown.esc.prevent="$emit('close')"
            />
            <button type="button" class="search-clear" aria-label="清除" @click="query = ''">
              <X :size="13" :stroke-width="1.8" aria-hidden="true" />
            </button>
          </div>
          <nav class="search-tabs" aria-label="搜索范围">
            <button
              v-for="tab in availableTabs"
              :key="tab.id"
              type="button"
              :class="{ active: activeTab === tab.id }"
              :aria-current="activeTab === tab.id ? 'page' : undefined"
              @click="switchTab(tab.id)"
            >
              <span class="search-tab-icon">
                <component :is="tab.icon" :size="14" :stroke-width="1.8" aria-hidden="true" />
              </span>
              <span>{{ tab.label }}</span>
            </button>
          </nav>
        </header>

        <main class="search-body">
          <p v-if="searching" class="search-status">搜索中…</p>
          <p v-else-if="error" class="search-status search-error" role="alert">{{ error }}</p>
          <p v-else-if="searched && !results.length" class="search-status">无</p>

          <ul v-else-if="results.length" class="search-results">
            <!-- 文件：文件名匹配 -->
            <template v-if="activeTab === 'files'">
              <li v-for="(hit, idx) in results" :key="'f' + idx" class="search-hit file-hit">
                <span class="search-hit-icon"><FileText :size="14" :stroke-width="1.8" aria-hidden="true" /></span>
                <span class="search-hit-path" v-html="highlight(hit.path)" />
              </li>
            </template>

            <!-- 内容：行内匹配 -->
            <template v-else-if="activeTab === 'content'">
              <li v-for="(hit, idx) in results" :key="'c' + idx" class="search-hit">
                <div class="search-hit-head">
                  <span class="search-hit-title" v-html="highlight(hit.path)"></span>
                  <span class="search-hit-role content-line">{{ hit.line }}</span>
                </div>
                <p class="search-hit-snippet" v-html="highlight(hit.content)"></p>
              </li>
            </template>

            <!-- 会话：历史消息命中 -->
            <template v-else-if="activeTab === 'sessions'">
              <li v-for="hit in results" :key="hit.message_id" class="search-hit" @mousedown.prevent="jumpSession(hit)">
                <div class="search-hit-head">
                  <span class="search-hit-title">{{ titleOf(hit.session_id) }}</span>
                  <span class="search-hit-role" :class="hit.role">{{ roleLabel(hit.role) }}</span>
                  <span class="search-hit-time">{{ timeOf(hit.ts) }}</span>
                </div>
                <p class="search-hit-snippet" v-html="highlight(hit.snippet)"></p>
              </li>
            </template>

            <!-- 文档：RAG 语义命中 -->
            <template v-else>
              <li v-for="(hit, idx) in results" :key="'d' + idx" class="search-hit">
                <div class="search-hit-head">
                  <span class="search-hit-title">{{ hit.title || hit.path }}</span>
                  <span v-if="hit.score" class="search-hit-score">{{ hit.score.toFixed(3) }}</span>
                </div>
                <p v-if="hit.heading" class="search-hit-heading">{{ hit.heading }}</p>
                <p class="search-hit-snippet" v-html="highlight(hit.snippet)"></p>
              </li>
            </template>
          </ul>

          <div v-else class="search-status search-hint">
            {{ hintText }}
          </div>
        </main>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
/**
 * SearchShell — 全局搜索全屏页（与插件 / 设置 / 长期安排并列的顶层入口，侧边栏"搜索"打开）。
 *
 * Tab 分层（用户共识：搜索放在插件上面的顶层入口）：
 * - 文件：workspace.search mode=files —— 工作区文件名匹配（core 内置，不经 Agent）
 * - 内容：workspace.search mode=content —— 工作区文件内容行匹配
 * - 会话：rag.sessions.search —— RAG 插件索引的历史会话消息（命中可跳转会话，复用 onJump）
 * - 文档：rag.docs.search —— RAG 插件索引的工作区文档语义检索
 * 会话/文档两个 Tab 仅在 lamtools-rag 插件启用时展示（mount 时查 plugin.list）。
 * 复用 SettingsShell 骨架（.settings-overlay/.settings-card + --settings-* token）。
 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import {
  File,
  FileText,
  MessageSquareText,
  Search,
  X,
} from 'lucide-vue-next'
import type { Component } from 'vue'
import type { CoreSessionListItem } from '../types'
import { gradientFromStops, relativeLuminance, type ThemeData } from '../helpers/theme'

const props = defineProps<{
  requestRpc: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>
  sessions: CoreSessionListItem[]
  onJump: (sessionId: string, messageId: string) => void
  theme?: ThemeData | null
}>()

defineEmits<{ close: [] }>()

type SearchTabId = 'files' | 'content' | 'sessions' | 'docs'
interface SearchHit {
  path?: string
  line?: number
  content?: string
  message_id?: string
  session_id?: string
  role?: string
  snippet?: string
  ts?: number | null
  title?: string
  heading?: string
  score?: number
}

const TAB_DEFS: { id: SearchTabId; label: string; icon: Component }[] = [
  { id: 'files', label: '文件', icon: File },
  { id: 'content', label: '内容', icon: FileText },
  { id: 'sessions', label: '会话', icon: MessageSquareText },
  { id: 'docs', label: '文档', icon: Search },
]

const activeTab = ref<SearchTabId>('files')
const query = ref('')
const inputEl = ref<HTMLInputElement | null>(null)
const results = ref<SearchHit[]>([])
const searching = ref(false)
const searched = ref(false)
const error = ref('')
const ragEnabled = ref(false)
// IME 合成标志：与 SessionSearchDialog 同一手动管理策略（WebView2 compositionend 偶发不触发）
const composing = ref(false)

let debounceTimer: ReturnType<typeof setTimeout> | null = null
let searchSeq = 0

const pluginTabs = computed<{ id: SearchTabId; label: string; icon: Component }[]>(
  () => (ragEnabled.value ? TAB_DEFS : TAB_DEFS.filter((t) => t.id !== 'sessions' && t.id !== 'docs')),
)
const availableTabs = computed(() => pluginTabs.value)

const inputPlaceholder = computed(() => {
  switch (activeTab.value) {
    case 'files':
      return '按文件名搜索工作区…'
    case 'content':
      return '搜索工作区文件内容…'
    case 'sessions':
      return '搜索历史会话消息…'
    default:
      return '语义搜索已索引文档…'
  }
})

const hintText = computed(() => {
  if (searched.value) return '直接输入关键词开始搜索'
  switch (activeTab.value) {
    case 'sessions':
      return ragEnabled.value
        ? '输入关键词搜索历史会话（消息级索引，UI 直搜不经 Agent）'
        : '会话搜索需要 lamtools-rag 插件'
    case 'docs':
      return '输入关键词语义检索已索引的工作区文档'
    default:
      return '输入关键词搜索工作区文件'
  }
})

const settingsThemeStyle = computed(() => {
  if (!props.theme) return {}
  const theme = props.theme
  const lightMain = relativeLuminance(theme.mainText) < 0.45
  return {
    '--settings-backdrop-background': gradientFromStops(
      theme.backdropAngle,
      theme.backdropStops,
      1,
    ),
    '--settings-backdrop-text': theme.backdropText,
    '--settings-main-background': gradientFromStops(
      theme.mainAngle,
      theme.mainStops,
      theme.mainOpacity,
    ),
    '--settings-main-text': theme.mainText,
    '--settings-main-solid': theme.mainStops[0]?.color || '#111111',
    '--settings-card-background': 'color-mix(in srgb, var(--settings-main-solid) 96%, var(--settings-main-text) 4%)',
    '--settings-card-text': theme.mainText,
    '--settings-control-background': gradientFromStops(
      theme.controlAngle,
      theme.controlStops,
      theme.controlOpacity,
    ),
    '--settings-control-text': theme.controlText,
    '--settings-control-solid': theme.controlStops[0]?.color || '#3a3834',
    ...(lightMain
      ? {
          '--settings-panel-2': '#f0efeb',
          '--settings-line': '#d4d0cc',
          '--settings-muted': '#8a8580',
        }
      : {}),
  } as Record<string, string>
})

function onInput(event: Event): void {
  if (composing.value) return
  query.value = (event.target as HTMLInputElement).value
}

function onCompositionEnd(event: Event): void {
  composing.value = false
  query.value = (event.target as HTMLInputElement).value
}

function switchTab(tab: SearchTabId): void {
  activeTab.value = tab
  runSearch(query.value.trim())
}

function enterFirst(): void {
  if (activeTab.value === 'sessions') {
    const hit = results.value[0] as SearchHit | undefined
    if (hit?.session_id && hit?.message_id) jumpSession(hit)
    return
  }
  const q = query.value.trim()
  if (q) runSearch(q)
}

watch(query, (value) => {
  if (debounceTimer) clearTimeout(debounceTimer)
  const q = value.trim()
  resetForQuery(q)
  if (!q) return
  searching.value = true
  debounceTimer = setTimeout(() => runSearch(q), 300)
})

function resetForQuery(q: string): void {
  if (!q) {
    searched.value = false
    results.value = []
    error.value = ''
  }
}

async function runSearch(q: string): Promise<void> {
  if (!q) {
    searched.value = false
    results.value = []
    return
  }
  const seq = ++searchSeq
  error.value = ''
  searching.value = true
  try {
    const result = await callForTab(activeTab.value, q)
    if (seq !== searchSeq) return // 过期响应丢弃
    results.value = result
    searched.value = true
  } catch (e) {
    if (seq !== searchSeq) return
    error.value = e instanceof Error ? e.message : String(e)
    results.value = []
  } finally {
    if (seq === searchSeq) searching.value = false
  }
}

async function callForTab(tab: SearchTabId, q: string): Promise<SearchHit[]> {
  switch (tab) {
    case 'files':
    case 'content':
      return (await props.requestRpc('workspace.search', { query: q, mode: tab, limit: 50 }))
        .results as SearchHit[]
    case 'sessions':
      return ((await props.requestRpc('rag.sessions.search', { query: q, top: 12 })).hits ||
        []) as SearchHit[]
    default: {
      const hits = (await props.requestRpc('rag.docs.search', { query: q, top: 12 }))
        .hits as SearchHit[]
      return hits || []
    }
  }
}

function jumpSession(hit: SearchHit): void {
  if (hit.session_id && hit.message_id) props.onJump(hit.session_id, hit.message_id)
}

function titleOf(sessionId: string | undefined): string {
  const session = props.sessions.find((item) => item.id === sessionId)
  if (session?.title && session.title !== sessionId) return session.title
  return `会话 ${(sessionId || '').slice(0, 8) || '未知'}…`
}

function roleLabel(role: string | undefined): string {
  return role === 'user' ? '我' : 'Agent'
}

function timeOf(ts: number | null | undefined): string {
  if (!ts) return ''
  const date = new Date(ts * 1000)
  const pad = (n: number): string => String(n).padStart(2, '0')
  return `${date.getMonth() + 1}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function highlight(text: string | undefined): string {
  const raw = text || ''
  const escaped = raw
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
  const q = query.value.trim()
  if (!q) return escaped
  const terms = q
    .split(/\s+/)
    .filter((t) => t.length >= 2)
    .sort((a, b) => b.length - a.length)
  let html = escaped
  for (const term of terms) {
    html = html.replace(new RegExp(escapeRegExp(term), 'gi'), (match) => `<mark>${match}</mark>`)
  }
  return html
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

onMounted(async () => {
  await nextTick()
  inputEl.value?.focus()
  try {
    const result = await props.requestRpc('plugin.list')
    const plugins = (result.plugins as { name: string; enabled: boolean }[]) || []
    ragEnabled.value = !!plugins.find((p) => p.name === 'lamtools-rag' && p.enabled)
    if (ragEnabled.value && activeTab.value === 'files') {
      // 默认落在内容 Tab（文件仅按文件名匹配，覆盖窄）
      activeTab.value = 'content'
    }
  } catch {
    ragEnabled.value = false
  }
})
</script>

<style scoped>
.search-head {
  flex-shrink: 0;
  border-bottom: 1px solid color-mix(in srgb, var(--settings-main-text, #fff) 10%, transparent);
}

.search-input-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px;
  color: var(--settings-muted, #a7a29b);
}

.search-input-row input {
  flex: 1;
  min-width: 0;
  background: transparent;
  border: none;
  outline: none;
  color: var(--settings-card-text, var(--settings-main-text, var(--text)));
  font-size: 15px;
  font-family: inherit;
}
.search-input-row input::placeholder {
  color: var(--settings-muted, #8a8580);
}

.search-clear {
  border: none;
  background: none;
  color: var(--settings-muted, #a7a29b);
  cursor: pointer;
  padding: 2px;
  display: inline-flex;
  border-radius: var(--radius-sm);
}
.search-clear:hover {
  color: var(--settings-card-text, var(--text));
}

.search-tabs {
  display: flex;
  gap: 4px;
  padding: 0 12px 10px;
}
.search-tabs button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border: 1px solid transparent;
  border-radius: 999px;
  background: transparent;
  color: var(--settings-muted, #a7a29b);
  font-size: 13px;
  font-family: inherit;
  cursor: pointer;
  transition: background 160ms ease, color 160ms ease;
}
.search-tabs button:hover {
  color: var(--settings-card-text, var(--text));
  background: color-mix(in srgb, var(--settings-main-text, #fff) 6%, transparent);
}
.search-tabs button.active {
  background: var(--settings-control-background, #343331);
  color: var(--settings-control-text, var(--text));
  border-color: color-mix(in srgb, var(--settings-main-text, #fff) 12%, transparent);
}
.search-tab-icon {
  display: inline-flex;
}

.search-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 10px 0;
  color: var(--settings-card-text, var(--settings-main-text, var(--text)));
  --muted: var(--settings-muted, #a7a29b);
}

.search-status {
  margin: 0;
  padding: 28px 20px;
  text-align: center;
  color: var(--settings-muted, #8a8580);
  font-size: 13px;
}
.search-status.search-error {
  color: #e57373;
}
.search-status.search-hint {
  padding: 20px;
  text-align: center;
  font-size: 12px;
  color: var(--settings-muted, #8a8580);
}

.search-results {
  list-style: none;
  margin: 0;
  padding: 0;
}

.search-hit {
  padding: 10px 18px;
  cursor: pointer;
  border-left: 2px solid transparent;
}
.search-hit:hover {
  background: color-mix(in srgb, var(--settings-main-text, #fff) 5%, transparent);
  border-left-color: var(--settings-control-background, #3a3834);
}

.file-hit {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--settings-card-text, var(--text));
}
.search-hit-icon {
  display: inline-flex;
  color: var(--settings-muted, #a7a29b);
  flex-shrink: 0;
}
.search-hit-path {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--font-mono);
  font-size: 12px;
}

.search-hit-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.search-hit-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  font-weight: 500;
}
.search-hit-role {
  flex-shrink: 0;
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--settings-main-text, #fff) 10%, transparent);
}
.search-hit-role.user {
  color: #8ab4f8;
}
.search-hit-role.assistant {
  color: #81c995;
}
.content-line {
  font-family: var(--font-mono);
  color: var(--settings-muted, #8a8580);
}
.search-hit-time,
.search-hit-score {
  margin-left: auto;
  flex-shrink: 0;
  font-size: 11px;
  color: var(--settings-muted, #8a8580);
}
.search-hit-score {
  font-family: var(--font-mono);
}
.search-hit-heading {
  margin: 2px 0 4px;
  font-size: 12px;
  color: var(--settings-muted, #a7a29b);
}
.search-hit-snippet {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.55;
  color: var(--settings-card-text, var(--text));
  opacity: 0.92;
}
.search-hit-snippet mark {
  background: color-mix(in srgb, var(--settings-control-background, #ffd166) 55%, transparent);
  color: inherit;
  border-radius: 2px;
  padding: 0 1px;
}

@media (prefers-reduced-motion: reduce) {
  .search-tabs button {
    transition: none;
  }
}
</style>