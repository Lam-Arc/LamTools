<template>
  <Teleport to="body">
    <div v-if="open" class="session-search-overlay" @click.self="close">
      <div
        class="session-search-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="搜索会话历史"
      >
        <div class="session-search-input-row">
          <Search :size="15" :stroke-width="1.8" aria-hidden="true" />
          <input
            ref="inputEl"
            :value="query"
            type="text"
            placeholder="搜索历史会话消息…"
            aria-label="搜索历史会话消息"
            autocomplete="off"
            @input="onInput"
            @compositionstart="composing = true"
            @compositionend="onCompositionEnd"
            @keydown.down.prevent="moveCursor(1)"
            @keydown.up.prevent="moveCursor(-1)"
            @keydown.enter.prevent="jumpCurrent"
            @keydown.esc.prevent="close"
          />
          <button type="button" class="session-search-close" aria-label="关闭" @click="close">
            <X :size="13" :stroke-width="1.8" aria-hidden="true" />
          </button>
        </div>

        <div v-if="searching" class="session-search-status">搜索中…</div>
        <p v-else-if="error" class="session-search-status session-search-error" role="alert">{{ error }}</p>
        <p v-else-if="searched && !hits.length" class="session-search-status">
          无命中。会话历史由 Stop hook 自动索引——尚无索引的会话搜不到，可先与 Agent 对话。
        </p>
        <ul v-else-if="hits.length" class="session-search-results">
          <li
            v-for="(hit, idx) in hits"
            :key="hit.message_id"
            class="session-search-hit"
            :class="{ 'is-active': idx === cursor }"
            @mousedown.prevent="jumpTo(hit)"
            @mouseenter="cursor = idx"
          >
            <div class="session-search-hit-head">
              <span class="session-search-hit-title">{{ titleOf(hit.session_id) }}</span>
              <span class="session-search-hit-role" :class="hit.role">{{ roleLabel(hit.role) }}</span>
              <span class="session-search-hit-time">{{ timeOf(hit.ts) }}</span>
            </div>
            <p class="session-search-hit-snippet" v-html="snippetHtml(hit.snippet)"></p>
          </li>
        </ul>
        <div v-else class="session-search-status session-search-hint">
          输入关键词搜索历史会话（消息级索引，UI 直搜不经 Agent）
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { Search, X } from 'lucide-vue-next'
import type { CoreSessionListItem } from '../types'

interface SessionHit {
  message_id: string
  session_id: string
  role: string
  turn_index?: number
  score?: number
  snippet?: string
  ts?: number | null
}

const props = defineProps<{
  requestRpc: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>
  sessions: CoreSessionListItem[]
  onJump: (sessionId: string, messageId: string) => void
}>()

const open = ref(false)
const query = ref('')
const inputEl = ref<HTMLInputElement | null>(null)
const hits = ref<SessionHit[]>([])
const searching = ref(false)
const searched = ref(false)
const error = ref('')
const cursor = ref(0)
// IME 合成标志：手动管理（不用 v-model 的 composition 拦截——WebView2 上
// compositionend 偶发不触发，v-model 内部标志卡死 → 退格后 modelValue 不
// 更新、渲染时字符回弹 = "无法退格"）。合成中不更新 query，合成结束强制同步。
const composing = ref(false)

let debounceTimer: ReturnType<typeof setTimeout> | null = null
let searchSeq = 0

function onInput(event: Event): void {
  if (composing.value) return
  query.value = (event.target as HTMLInputElement).value
}

function onCompositionEnd(event: Event): void {
  composing.value = false
  query.value = (event.target as HTMLInputElement).value
}

function onGlobalKeydown(event: KeyboardEvent): void {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    open.value = !open.value
    return
  }
  if (event.key === 'Escape' && open.value) {
    close()
  }
}

function close(): void {
  open.value = false
}

async function ensureFocus(): Promise<void> {
  await nextTick()
  inputEl.value?.focus()
}

watch(open, async (now) => {
  if (now) {
    await ensureFocus()
  } else {
    cursor.value = 0
    searched.value = false
    hits.value = []
    error.value = ''
  }
})

watch(query, (value) => {
  if (debounceTimer) clearTimeout(debounceTimer)
  const q = value.trim()
  if (!q) {
    searched.value = false
    hits.value = []
    return
  }
  searching.value = true
  debounceTimer = setTimeout(() => runSearch(q), 300)
})

async function runSearch(q: string): Promise<void> {
  const seq = ++searchSeq
  error.value = ''
  try {
    const result = await props.requestRpc('rag.sessions.search', { query: q, top: 12 })
    if (seq !== searchSeq) return // 过期响应丢弃
    const list = (result.hits as SessionHit[]) || []
    hits.value = list
    cursor.value = 0
    searched.value = true
  } catch (e) {
    if (seq !== searchSeq) return
    error.value = e instanceof Error ? e.message : String(e)
    hits.value = []
  } finally {
    if (seq === searchSeq) searching.value = false
  }
}

function moveCursor(step: number): void {
  if (!hits.value.length) return
  cursor.value = (cursor.value + step + hits.value.length) % hits.value.length
}

function jumpCurrent(): void {
  const hit = hits.value[cursor.value]
  if (hit) jumpTo(hit)
}

function jumpTo(hit: SessionHit): void {
  close()
  props.onJump(hit.session_id, hit.message_id)
}

function titleOf(sessionId: string): string {
  const session = props.sessions.find((item) => item.id === sessionId)
  if (session?.title && session.title !== sessionId) return session.title
  return `会话 ${sessionId.slice(0, 8)}…`
}

function roleLabel(role: string): string {
  return role === 'user' ? '我' : 'Agent'
}

function timeOf(ts: number | null | undefined): string {
  if (!ts) return ''
  const date = new Date(ts * 1000)
  const pad = (n: number): string => String(n).padStart(2, '0')
  return `${date.getMonth() + 1}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function snippetHtml(snippet: string | undefined): string {
  const text = snippet || ''
  const escaped = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
  const q = query.value.trim()
  if (!q) return escaped
  const terms = q.split(/\s+/).filter(Boolean).sort((a, b) => b.length - a.length)
  let html = escaped
  for (const term of terms) {
    html = html.replace(new RegExp(escapeRegExp(term), 'gi'), (match) => `<mark>${match}</mark>`)
  }
  return html
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

onMounted(() => window.addEventListener('keydown', onGlobalKeydown))
onUnmounted(() => window.removeEventListener('keydown', onGlobalKeydown))
</script>

<style scoped>
.session-search-overlay {
  position: fixed;
  inset: 0;
  z-index: 200;
  background: transparent;
  /* 透明遮罩（与配置卡片同一共识）：不压暗不 blur，弹层独立呈现 */
}

.session-search-dialog {
  position: absolute;
  top: min(14vh, 160px);
  left: 50%;
  transform: translateX(-50%);
  width: min(620px, calc(100% - 32px));
  max-height: min(60vh, 480px);
  display: flex;
  flex-direction: column;
  border-radius: var(--radius);
  background: var(--settings-card-background, var(--theme-main-background, #161616));
  border: 1px solid color-mix(in srgb, var(--settings-main-text, #fff) 14%, transparent);
  box-shadow: 0 12px 40px rgb(0 0 0 / 0.4);
  color: var(--settings-card-text, var(--settings-main-text, var(--text)));
  --muted: var(--settings-muted, #a7a29b);
  overflow: hidden;
}

.session-search-input-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border-bottom: 1px solid color-mix(in srgb, var(--settings-main-text, #fff) 10%, transparent);
  color: var(--muted);
}

.session-search-input-row input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: transparent;
  color: inherit;
  font-size: 14px;
  font-family: inherit;
}

.session-search-input-row input::placeholder {
  color: var(--muted);
  opacity: 0.75;
}

.session-search-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  padding: 0;
}

.session-search-close:hover {
  background: color-mix(in srgb, var(--settings-main-text, #fff) 10%, transparent);
}

.session-search-status {
  margin: 0;
  padding: 14px 16px;
  font-size: 12.5px;
  color: var(--muted);
}

.session-search-error {
  color: var(--red, #e5484d);
}

.session-search-results {
  list-style: none;
  margin: 0;
  padding: 6px;
  overflow-y: auto;
}

.session-search-hit {
  padding: 9px 10px;
  border-radius: var(--radius-sm);
  cursor: pointer;
}

.session-search-hit.is-active,
.session-search-hit:hover {
  background: color-mix(in srgb, var(--settings-main-text, #fff) 8%, transparent);
}

.session-search-hit-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 3px;
}

.session-search-hit-title {
  font-size: 12.5px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-search-hit-role {
  flex: none;
  font-size: 10.5px;
  padding: 1px 7px;
  border-radius: 999px;
  border: 1px solid color-mix(in srgb, var(--settings-main-text, #fff) 16%, transparent);
  color: var(--muted);
}

.session-search-hit-role.user {
  color: var(--green, #4cb782);
}

.session-search-hit-time {
  margin-left: auto;
  flex: none;
  font-size: 11px;
  color: var(--muted);
  opacity: 0.8;
}

.session-search-hit-snippet {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.55;
  color: var(--muted);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.session-search-hit-snippet :deep(mark) {
  background: color-mix(in srgb, var(--accent, #4f8cff) 35%, transparent);
  color: inherit;
  border-radius: 2px;
  padding: 0 1px;
}

.session-search-hint {
  text-align: center;
}
</style>
