<template>
  <div ref="searchViewEl" class="search-view" :style="settingsThemeStyle">
    <header class="search-head">
      <div class="search-input-row">
        <button class="search-back" type="button" aria-label="返回会话" title="返回会话" @click="$emit('close')">
          <ArrowLeft :size="16" :stroke-width="1.8" aria-hidden="true" />
        </button>
        <Search :size="15" :stroke-width="1.8" aria-hidden="true" />
            <input
              ref="inputEl"
              :value="query"
              type="text"
              placeholder="搜索任务、插件或文件"
              aria-label="搜索"
              autocomplete="off"
              spellcheck="false"
              @input="onInput"
              @compositionstart="composing = true"
              @compositionend="onCompositionEnd"
              @keydown.enter.prevent="onEnter"
              @keydown.down.prevent="moveCursor(1)"
              @keydown.up.prevent="moveCursor(-1)"
              @keydown.esc.prevent="$emit('close')"
            />
            <button v-if="query" type="button" class="search-clear" aria-label="清除" @click="clearQuery">
              <X :size="13" :stroke-width="1.8" aria-hidden="true" />
            </button>
          </div>
          <nav class="search-tabs" aria-label="搜索范围">
            <button
              v-for="category in CATEGORIES"
              :key="category.id"
              type="button"
              :class="{ active: activeCategory === category.id }"
              :aria-current="activeCategory === category.id ? 'page' : undefined"
              @click="switchCategory(category.id)"
            >
              <span class="search-tab-icon">
                <component :is="category.icon" :size="14" :stroke-width="1.8" aria-hidden="true" />
              </span>
              <span>{{ category.label }}</span>
            </button>
          </nav>
        </header>

        <main class="search-body">
          <p v-if="searching" class="search-status">搜索中…</p>
          <p v-else-if="error" class="search-status search-error" role="alert">{{ error }}</p>
          <p v-else-if="!visibleRows.length" class="search-status search-hint">{{ hintText }}</p>

          <ul v-else class="search-results">
            <template v-for="group in visibleGroups" :key="group.label">
              <li class="search-group-label">{{ group.label }}</li>
              <li
                v-for="row in group.rows"
                :key="row.key"
                class="search-row"
                :class="{ active: row.index === cursor, 'is-static': !row.action }"
                :data-search-row="row.key"
                @mousedown.prevent="activate(row)"
                @mouseenter="cursor = row.index"
              >
                <span class="search-row-icon" aria-hidden="true">
                  <component :is="row.icon" :size="16" :stroke-width="1.8" />
                </span>
                <span class="search-row-copy">
                  <strong v-html="highlight(row.title)"></strong>
                  <small v-if="row.subtitle" v-html="highlight(row.subtitle)"></small>
                </span>
                <span v-if="row.meta" class="search-row-meta">{{ row.meta }}</span>
                <kbd v-if="row.shortcut" class="search-row-shortcut">{{ row.shortcut }}</kbd>
              </li>
            </template>
          </ul>
        </main>

        <div class="search-footer" aria-hidden="true">
          <span><kbd>↑↓</kbd> 移动</span>
          <span><kbd>Enter</kbd> 选择</span>
          <span><kbd>Esc</kbd> 返回</span>
        </div>
  </div>
</template>

<script setup lang="ts">
/**
 * SearchShell — 全局搜索（Ctrl+K / 侧边栏“搜索”）。
 *
 * 分类（用户共识）：全部 / 任务 / 插件 / 文件。原先分散的搜索入口一律归入这四类：
 * - 任务：任务标题（本地即时）+ RAG 消息级命中（lamtools-rag 启用时）
 * - 插件：插件、技能、钩子（命中即打开插件面板的对应分区）
 * - 文件：文件名、文件内容（workspace.search）+ 已索引文档语义命中（rag.docs.search）
 * - Study：节点/笔记/会话，只在 Study 会话里出现，作为“全部”下的独立分组
 *
 * 空查询给“最近任务 / 建议 / 面板”三组。建议与面板里的快捷命令由宿主传入：
 * 桌面有终端与预览、手机没有，所以命令表由调用方决定，不写死在这里。
 */
import { computed, nextTick, onMounted, ref, watch, type Component } from 'vue'
import {
  ArrowLeft,
  File,
  FileText,
  FolderSearch,
  Lightbulb,
  LayoutList,
  ListChecks,
  MessageSquareText,
  Plug,
  Search,
  Sparkles,
  Webhook,
  X,
} from 'lucide-vue-next'
import type { CoreSessionListItem } from '../types'
import { gradientFromStops, relativeLuminance, type ThemeData } from '../helpers/theme'

/** A host-supplied shortcut row, so each host offers only the commands it has. */
export interface SearchCommand {
  id: string
  label: string
  group: '建议' | '面板'
  shortcut?: string
  icon?: Component
  run: () => void
}

export interface SearchPluginTarget {
  section: 'plugins' | 'skills' | 'hooks'
  id?: string
}

const props = defineProps<{
  requestRpc: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>
  sessions: CoreSessionListItem[]
  onJump: (sessionId: string, messageId: string) => void
  /** Study reuses this host search surface; it does not render a parallel search UI. */
  activeModeId?: string | null
  onStudyHit?: (hit: StudySearchHit) => void | Promise<void>
  theme?: ThemeData | null
  /** Open a task by id — a title match has no message to land on. */
  onOpenSession?: (sessionId: string) => void
  /** Open the plugins panel on the section a plugin/skill/hook hit belongs to. */
  onOpenPlugins?: (target: SearchPluginTarget) => void
  commands?: SearchCommand[]
}>()

const emit = defineEmits<{ close: [] }>()

const searchViewEl = ref<HTMLElement | null>(null)

type SearchCategoryId = 'all' | 'tasks' | 'plugins' | 'files'

const CATEGORIES: { id: SearchCategoryId; label: string; icon: Component }[] = [
  { id: 'all', label: '全部', icon: LayoutList },
  { id: 'tasks', label: '任务', icon: ListChecks },
  { id: 'plugins', label: '插件', icon: Plug },
  { id: 'files', label: '文件', icon: File },
]

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
  entity_type?: string
  entity_id?: string
  node_id?: string
  note_id?: string
}
export interface StudySearchHit extends SearchHit {
  entity_type?: 'node' | 'note' | 'session' | string
  entity_id?: string
  session_id?: string
  message_id?: string
}

/** One rendered row. A row without an action is informational (file hits today). */
interface SearchRow {
  key: string
  group: string
  icon: Component
  title: string
  subtitle?: string
  meta?: string
  shortcut?: string
  action?: () => void
  index: number
}

const GROUP_ORDER_QUERY = ['任务', '插件', '文件', 'Study']
const GROUP_ORDER_IDLE = ['最近任务', '建议', '面板']

const activeCategory = ref<SearchCategoryId>('all')
const query = ref('')
const inputEl = ref<HTMLInputElement | null>(null)
const cursor = ref(0)
const searching = ref(false)
const error = ref('')
const ragEnabled = ref(false)
const composing = ref(false)

/** Remote hits for the current query, one bucket per source. */
const messageHits = ref<SearchHit[]>([])
const studyHits = ref<SearchHit[]>([])
const fileHits = ref<SearchHit[]>([])
const contentHits = ref<SearchHit[]>([])
const docHits = ref<SearchHit[]>([])

/** Plugins, skills and hooks: fetched once, filtered locally. */
interface CatalogEntry {
  id: string
  name: string
  description: string
  icon: Component
  section: SearchPluginTarget['section']
  meta?: string
}
const catalog = ref<CatalogEntry[]>([])

let debounceTimer: ReturnType<typeof setTimeout> | null = null
let searchSeq = 0

const commands = computed(() => props.commands || [])
const hasStudy = computed(() => Boolean(props.activeModeId?.startsWith('study:')))

const hintText = computed(() =>
  query.value ? '无匹配结果' : '输入关键词搜索任务、插件或文件',
)

/** Task title matches: instant, and they work without the RAG plugin. */
const sessionTitleMatches = computed(() => {
  const needle = query.value.trim().toLowerCase()
  if (!needle) return []
  return props.sessions
    .filter((session) =>
      String(session.title || '').toLowerCase().includes(needle) ||
      String(session.id).toLowerCase().includes(needle),
    )
    .slice(0, 8)
})

const recentSessions = computed(() => props.sessions.slice(0, 5))

const catalogMatches = computed(() => {
  const needle = query.value.trim().toLowerCase()
  if (!needle) return []
  return catalog.value
    .filter((entry) =>
      `${entry.name} ${entry.description} ${entry.meta || ''}`.toLowerCase().includes(needle),
    )
    .slice(0, 12)
})

function sectionIcon(section: SearchPluginTarget['section']): Component {
  if (section === 'skills') return Sparkles
  if (section === 'hooks') return Webhook
  return Plug
}

/** Every visible row, flattened; `index` is what the keyboard moves over. */
const rows = computed<SearchRow[]>(() => {
  const built: Omit<SearchRow, 'index'>[] = []
  const needle = query.value.trim()

  if (!needle) {
    if (activeCategory.value === 'all' || activeCategory.value === 'tasks') {
      for (const session of recentSessions.value) {
        built.push({
          key: `recent-${session.id}`,
          group: '最近任务',
          icon: MessageSquareText,
          title: String(session.title || session.id),
          meta: relativeTime(session),
          action: () => openSession(session.id),
        })
      }
    }
    if (activeCategory.value === 'all') {
      for (const command of commands.value) {
        built.push({
          key: `command-${command.id}`,
          group: command.group,
          icon: command.icon || Lightbulb,
          title: command.label,
          shortcut: command.shortcut,
          action: command.run,
        })
      }
    }
    return built.map((row, index) => ({ ...row, index }))
  }

  if (activeCategory.value === 'all' || activeCategory.value === 'tasks') {
    for (const session of sessionTitleMatches.value) {
      built.push({
        key: `session-${session.id}`,
        group: '任务',
        icon: MessageSquareText,
        title: String(session.title || session.id),
        subtitle: '任务标题',
        meta: relativeTime(session),
        action: () => openSession(session.id),
      })
    }
    for (const hit of messageHits.value) {
      built.push({
        key: `message-${hit.message_id || built.length}`,
        group: '任务',
        icon: MessageSquareText,
        title: titleOf(hit.session_id),
        subtitle: hit.snippet,
        meta: timeOf(hit.ts),
        action: () => jumpSession(hit),
      })
    }
  }

  if (activeCategory.value === 'all' || activeCategory.value === 'plugins') {
    for (const entry of catalogMatches.value) {
      built.push({
        key: `catalog-${entry.section}-${entry.id}`,
        group: '插件',
        icon: entry.icon,
        title: entry.name,
        subtitle: entry.description,
        meta: entry.meta,
        action: () => props.onOpenPlugins?.({ section: entry.section, id: entry.id }),
      })
    }
  }

  if (activeCategory.value === 'all' || activeCategory.value === 'files') {
    for (const hit of fileHits.value) {
      built.push({
        key: `file-${hit.path}`,
        group: '文件',
        icon: File,
        title: hit.path || '',
        subtitle: '文件名',
      })
    }
    for (const hit of contentHits.value) {
      built.push({
        key: `content-${hit.path}-${hit.line}`,
        group: '文件',
        icon: FileText,
        title: hit.path || '',
        subtitle: hit.content,
        meta: hit.line ? `第 ${hit.line} 行` : undefined,
      })
    }
    for (const hit of docHits.value) {
      built.push({
        key: `doc-${hit.path}-${hit.heading || ''}`,
        group: '文件',
        icon: FolderSearch,
        title: hit.title || hit.path || '',
        subtitle: hit.snippet,
        meta: hit.score ? hit.score.toFixed(3) : '文档',
      })
    }
  }

  if (hasStudy.value && activeCategory.value === 'all') {
    for (const hit of studyHits.value) {
      built.push({
        key: `study-${hit.entity_id || hit.note_id || hit.session_id || built.length}`,
        group: 'Study',
        icon: FolderSearch,
        title: hit.title || hit.path || hit.entity_id || hit.note_id || '',
        subtitle: hit.snippet || hit.content,
        meta: hit.entity_type,
        action: () => jumpStudy(hit as StudySearchHit),
      })
    }
  }

  return built.map((row, index) => ({ ...row, index }))
})

const visibleRows = computed(() => rows.value)

/** Rows grouped for rendering, in a stable order, empty groups dropped. */
const visibleGroups = computed(() => {
  const order = query.value.trim() ? GROUP_ORDER_QUERY : GROUP_ORDER_IDLE
  const byGroup = new Map<string, SearchRow[]>()
  for (const row of rows.value) {
    const list = byGroup.get(row.group) || []
    list.push(row)
    byGroup.set(row.group, list)
  }
  return order
    .filter((label) => byGroup.has(label))
    .map((label) => ({ label, rows: byGroup.get(label) as SearchRow[] }))
})

const selectableIndexes = computed(() =>
  rows.value.filter((row) => Boolean(row.action)).map((row) => row.index),
)

function activate(row: SearchRow): void {
  if (row.action) row.action()
}

function openSession(sessionId: string): void {
  emit('close')
  props.onOpenSession?.(sessionId)
}

function jumpSession(hit: SearchHit): void {
  if (hit.session_id && hit.message_id) {
    emit('close')
    props.onJump(hit.session_id, hit.message_id)
  }
}

function jumpStudy(hit: StudySearchHit): void {
  emit('close')
  void props.onStudyHit?.(hit)
}

function onInput(event: Event): void {
  if (composing.value) return
  query.value = (event.target as HTMLInputElement).value
}

function onCompositionEnd(event: Event): void {
  composing.value = false
  query.value = (event.target as HTMLInputElement).value
}

function clearQuery(): void {
  query.value = ''
  inputEl.value?.focus()
}

function switchCategory(category: SearchCategoryId): void {
  activeCategory.value = category
  cursor.value = selectableIndexes.value[0] ?? 0
  const needle = query.value.trim()
  if (needle) void runSearch(needle)
}

function onEnter(): void {
  const row = visibleRows.value.find((item) => item.index === cursor.value)
  if (row?.action) {
    activate(row)
    return
  }
  const needle = query.value.trim()
  if (needle) void runSearch(needle)
}

function moveCursor(step: number): void {
  const selectable = selectableIndexes.value
  if (!selectable.length) return
  const position = selectable.indexOf(cursor.value)
  const next = position < 0 ? 0 : (position + step + selectable.length) % selectable.length
  cursor.value = selectable[next]
}

watch(query, (value) => {
  if (debounceTimer) clearTimeout(debounceTimer)
  const needle = value.trim()
  cursor.value = 0
  if (!needle) {
    resetRemoteHits()
    return
  }
  searching.value = true
  debounceTimer = setTimeout(() => void runSearch(needle), 300)
})

watch(visibleRows, () => {
  const selectable = selectableIndexes.value
  if (!selectable.includes(cursor.value)) cursor.value = selectable[0] ?? 0
  void nextTick(() => {
    const active = searchViewEl.value?.querySelector('.search-row.active')
    // jsdom has no scrollIntoView; the dialog must not depend on it existing.
    if (active && typeof active.scrollIntoView === 'function') {
      active.scrollIntoView({ block: 'nearest' })
    }
  })
})

function resetRemoteHits(): void {
  messageHits.value = []
  studyHits.value = []
  fileHits.value = []
  contentHits.value = []
  docHits.value = []
  error.value = ''
  searching.value = false
}

async function runSearch(needle: string): Promise<void> {
  const seq = ++searchSeq
  error.value = ''
  searching.value = true
  const category = activeCategory.value
  const wantsTasks = category === 'all' || category === 'tasks'
  const wantsFiles = category === 'all' || category === 'files'
  try {
    const [messages, files, content, docs, study] = await Promise.all([
      wantsTasks && ragEnabled.value ? searchSessions(needle) : Promise.resolve([]),
      wantsFiles ? searchWorkspace(needle, 'files') : Promise.resolve([]),
      wantsFiles ? searchWorkspace(needle, 'content') : Promise.resolve([]),
      wantsFiles && ragEnabled.value ? searchDocs(needle) : Promise.resolve([]),
      hasStudy.value && category === 'all' ? searchStudy(needle) : Promise.resolve([]),
    ])
    if (seq !== searchSeq) return // 过期响应丢弃
    messageHits.value = messages
    fileHits.value = files
    contentHits.value = content
    docHits.value = docs
    studyHits.value = study
  } catch (e) {
    if (seq !== searchSeq) return
    resetRemoteHits()
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    if (seq === searchSeq) searching.value = false
  }
}

async function searchSessions(needle: string): Promise<SearchHit[]> {
  const result = await props.requestRpc('rag.sessions.search', { query: needle, top: 12 })
  return (result.hits || []) as SearchHit[]
}

async function searchWorkspace(needle: string, mode: 'files' | 'content'): Promise<SearchHit[]> {
  const result = await props.requestRpc('workspace.search', { query: needle, mode, limit: 40 })
  return (result.results || []) as SearchHit[]
}

async function searchDocs(needle: string): Promise<SearchHit[]> {
  const result = await props.requestRpc('rag.docs.search', { query: needle, top: 12 })
  return (result.hits || []) as SearchHit[]
}

async function searchStudy(needle: string): Promise<SearchHit[]> {
  const result = await props.requestRpc('study.search', { query: needle, scope: 'study', limit: 30 })
  return (result.results || result.hits || []) as SearchHit[]
}

const settingsThemeStyle = computed(() => {
  if (!props.theme) return {}
  const theme = props.theme
  const lightMain = relativeLuminance(theme.mainText) < 0.45
  return {
    '--settings-backdrop-background': gradientFromStops(theme.backdropAngle, theme.backdropStops, 1),
    '--settings-backdrop-text': theme.backdropText,
    '--settings-main-background': gradientFromStops(theme.mainAngle, theme.mainStops, theme.mainOpacity),
    '--settings-main-text': theme.mainText,
    '--settings-main-solid': theme.mainStops[0]?.color || '#111111',
    '--settings-card-background': 'color-mix(in srgb, var(--settings-main-solid) 96%, var(--settings-main-text) 4%)',
    '--settings-card-text': theme.mainText,
    '--settings-control-background': gradientFromStops(theme.controlAngle, theme.controlStops, theme.controlOpacity),
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

function titleOf(sessionId: string | undefined): string {
  const session = props.sessions.find((item) => item.id === sessionId)
  if (session?.title && session.title !== sessionId) return session.title
  return `任务 ${(sessionId || '').slice(0, 8) || '未知'}…`
}

function timeOf(ts: number | null | undefined): string {
  if (!ts) return ''
  const date = new Date(ts * 1000)
  const pad = (n: number): string => String(n).padStart(2, '0')
  return `${date.getMonth() + 1}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

/** The list's own "how long ago" label: 刚刚 / 50分 / 3小时 / 3天. */
function relativeTime(session: CoreSessionListItem): string {
  const raw = session.updatedAt
  if (!raw) return ''
  const stamp = new Date(raw).getTime()
  if (!Number.isFinite(stamp)) return ''
  const minutes = Math.floor((Date.now() - stamp) / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes}分`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}小时`
  return `${Math.floor(hours / 24)}天`
}

function highlight(text: string | undefined): string {
  const raw = text || ''
  const escaped = raw.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  const needle = query.value.trim()
  if (!needle) return escaped
  const terms = needle
    .split(/\s+/)
    .filter((term) => term.length >= 2)
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
  void loadCatalog()
  try {
    const result = await props.requestRpc('plugin.list')
    const plugins = (result.plugins as { name: string; enabled: boolean }[]) || []
    ragEnabled.value = !!plugins.find((p) => p.name === 'lamtools-rag' && p.enabled)
  } catch {
    ragEnabled.value = false
  }
})

/** Three catalogues, fetched once, filtered locally: typing costs no RPC. */
async function loadCatalog(): Promise<void> {
  const [plugins, skills, hooks] = await Promise.all([
    safeCatalog(() => props.requestRpc('plugin.list')),
    safeCatalog(() => props.requestRpc('skill.list')),
    safeCatalog(() => props.requestRpc('hook.list')),
  ])
  const entries: CatalogEntry[] = []
  for (const item of (plugins.plugins as Record<string, unknown>[]) || []) {
    const name = String(item.name || item.id || '')
    if (!name) continue
    entries.push({
      id: name,
      name,
      description: String(item.description || ''),
      icon: sectionIcon('plugins'),
      section: 'plugins',
      meta: item.enabled === false ? '已停用' : '插件',
    })
  }
  for (const item of (skills.skills as Record<string, unknown>[]) || []) {
    const name = String(item.name || '')
    if (!name) continue
    entries.push({
      id: name,
      name,
      description: String(item.description || ''),
      icon: sectionIcon('skills'),
      section: 'skills',
      meta: item.enabled === false ? '已停用' : '技能',
    })
  }
  for (const item of (hooks.hooks as Record<string, unknown>[]) || []) {
    const name = String(item.name || item.id || '')
    if (!name) continue
    entries.push({
      id: name,
      name,
      description: String(item.description || item.command || ''),
      icon: sectionIcon('hooks'),
      section: 'hooks',
      meta: item.trusted ? '钩子·已信任' : '钩子',
    })
  }
  catalog.value = entries
}

async function safeCatalog(call: () => Promise<Record<string, unknown>>): Promise<Record<string, unknown>> {
  try {
    return await call()
  } catch {
    return {}
  }
}
</script>

<style scoped>
/* 整版界面：占住聊天区域，页面内给输入框与结果；不再是一张悬浮卡片。 */
.search-view {
  --text: var(--settings-card-text, var(--settings-main-text, #fff));
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--theme-main-background, var(--bg, #111111));
  color: var(--text);
}

.search-head {
  flex-shrink: 0;
  border-bottom: 1px solid color-mix(in srgb, var(--settings-main-text, #fff) 10%, transparent);
}

.search-input-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 14px var(--space-4);
  max-width: 720px;
  margin: 0 auto;
  width: 100%;
  box-sizing: border-box;
  color: var(--settings-muted, #a7a29b);
}

.search-back {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border: 1px solid color-mix(in srgb, var(--settings-main-text, #fff) 10%, transparent);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--settings-muted, #a7a29b);
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}

.search-back:hover {
  background: color-mix(in srgb, var(--settings-main-text, #fff) var(--alpha-hover), transparent);
  color: var(--settings-card-text, var(--text));
}

.search-input-row input {
  flex: 1;
  min-width: 0;
  background: transparent;
  border: none;
  outline: none;
  color: var(--theme-composer-text);
  caret-color: var(--theme-composer-text);
  font-size: 15px;
  font-family: inherit;
}

.search-input-row input::placeholder {
  color: color-mix(in srgb, var(--theme-composer-text) 45%, transparent);
}

.search-clear {
  display: inline-flex;
  border: none;
  border-radius: var(--radius-sm);
  padding: 2px;
  background: none;
  color: var(--settings-muted, #a7a29b);
  cursor: pointer;
}

.search-clear:hover {
  color: var(--settings-card-text, var(--text));
}

.search-tabs {
  display: flex;
  gap: var(--space-1);
  padding: 0 var(--space-4) 10px;
  max-width: 720px;
  margin: 0 auto;
}

.search-tabs button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  padding: 6px var(--space-2);
  background: transparent;
  color: var(--settings-muted, #a7a29b);
  font-size: 13px;
  font-family: inherit;
  cursor: pointer;
  transition: background 160ms ease, color 160ms ease;
}

.search-tabs button:hover {
  color: var(--settings-card-text, var(--text));
  background: color-mix(in srgb, var(--settings-main-text, #fff) var(--alpha-hover), transparent);
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
  padding: var(--space-1) var(--space-4) var(--space-2);
  --text: var(--settings-card-text, var(--settings-main-text, #fff));
  color: var(--text);
}

.search-body > * {
  max-width: 720px;
  margin-left: auto;
  margin-right: auto;
}

.search-status {
  margin: 0;
  padding: 28px var(--space-4);
  text-align: center;
  color: var(--settings-muted, #8a8580);
  font-size: 13px;
}

.search-status.search-error {
  color: var(--red);
}

.search-status.search-hint {
  font-size: 12px;
}

.search-results {
  list-style: none;
  margin: 0;
  padding: 0;
}

.search-group-label {
  padding: var(--space-2) var(--space-3) var(--space-1);
  color: color-mix(in srgb, var(--text) 45%, transparent);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .08em;
}

.search-row {
  position: relative;
  display: grid;
  grid-template-columns: var(--space-6) minmax(0, 1fr) auto auto;
  gap: var(--space-2);
  align-items: center;
  min-height: 48px;
  padding: var(--space-2) var(--space-3);
}

/* 行式高亮：无圆角遮罩，hover/active 只作用于背景层并左右渐隐。 */
.search-row::before {
  content: '';
  position: absolute;
  inset: 0;
  background: transparent;
  pointer-events: none;
  -webkit-mask-image: linear-gradient(to right, rgba(0, 0, 0, .2) 0, #000 var(--row-fade), #000 calc(100% - var(--row-fade)), rgba(0, 0, 0, .2) 100%);
  mask-image: linear-gradient(to right, rgba(0, 0, 0, .2) 0, #000 var(--row-fade), #000 calc(100% - var(--row-fade)), rgba(0, 0, 0, .2) 100%);
}

.search-row:not(.is-static) {
  cursor: pointer;
}

.search-row:not(.is-static):hover::before {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
}

.search-row.active::before {
  background: color-mix(in srgb, var(--text) var(--alpha-active), transparent);
}

.search-row-icon {
  position: relative;
  display: grid;
  place-items: center;
  width: var(--space-6);
  height: var(--space-6);
  border: 1px solid color-mix(in srgb, var(--text) 12%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--text) 4%, transparent);
  color: color-mix(in srgb, var(--text) 72%, transparent);
}

.search-row-copy {
  position: relative;
  min-width: 0;
  display: grid;
  gap: 2px;
}

.search-row-copy strong,
.search-row-copy small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.search-row-copy strong {
  color: var(--text);
  font-size: 13px;
  font-weight: 550;
}

.search-row-copy small {
  color: color-mix(in srgb, var(--text) 65%, transparent);
  font-size: 11px;
  line-height: 1.25;
}

.search-row-copy mark {
  border-radius: 2px;
  padding: 0 1px;
  background: color-mix(in srgb, var(--settings-control-background, #ffd166) 55%, transparent);
  color: inherit;
}

.search-row-meta {
  position: relative;
  max-width: 140px;
  overflow: hidden;
  color: color-mix(in srgb, var(--text) 45%, transparent);
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.search-row-shortcut {
  position: relative;
  border: 1px solid color-mix(in srgb, var(--text) 12%, transparent);
  border-radius: var(--radius-sm);
  padding: 1px var(--space-1);
  background: color-mix(in srgb, var(--text) 4%, transparent);
  color: color-mix(in srgb, var(--text) 65%, transparent);
  font: inherit;
  font-size: 10px;
  line-height: 1.25;
}

.search-footer {
  flex-shrink: 0;
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  align-items: center;
  border-top: 1px solid color-mix(in srgb, var(--settings-main-text, #fff) 8%, transparent);
  padding: var(--space-1) var(--space-3) var(--space-2);
  color: color-mix(in srgb, var(--settings-main-text, #fff) 45%, transparent);
  font-size: 10px;
}

.search-footer span {
  display: inline-flex;
  gap: var(--space-1);
  align-items: center;
}

.search-footer kbd {
  min-width: 20px;
  border: 1px solid color-mix(in srgb, var(--settings-main-text, #fff) 12%, transparent);
  border-radius: var(--radius-sm);
  padding: 1px var(--space-1);
  background: color-mix(in srgb, var(--settings-main-text, #fff) 4%, transparent);
  color: color-mix(in srgb, var(--settings-main-text, #fff) 65%, transparent);
  font: inherit;
  line-height: 1.25;
  text-align: center;
}

@media (max-width: 560px) {
  .search-row-meta {
    display: none;
  }

  .search-row {
    grid-template-columns: var(--space-6) minmax(0, 1fr) auto;
  }
}

/* 桌面：返回键在顶部条里；这里只留搜索输入行。 */
@media (min-width: 641px) {
  .search-back {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .search-tabs button {
    transition: none;
  }
}
</style>
