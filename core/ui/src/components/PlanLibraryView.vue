<template>
  <div class="plan-library-view">
    <header class="library-head">
      <div class="library-head-lead">
        <button class="library-back" type="button" aria-label="返回会话" title="返回会话" @click="emit('back')">
          <ArrowLeft :size="16" :stroke-width="1.8" aria-hidden="true" />
        </button>
        <div>
          <h1 class="library-title">资料库</h1>
          <p class="library-subtitle">「{{ dirName }}」文件夹里的方案 — 点开读全文，就绪后开工。</p>
        </div>
      </div>
      <div class="library-head-actions">
        <button class="library-quiet-button" :disabled="loading" @click="reload">
          {{ loading ? '刷新中…' : '刷新' }}
        </button>
      </div>
    </header>

    <p v-if="!projectId" class="library-notice" role="note">先在左侧选择一个项目 — 资料库跟随项目文件夹。</p>

    <div v-else class="library-columns" :class="{ 'library-columns--reader-open': narrow && selected }">
      <!-- ── 列表：先看到全部方案，再决定读哪一份 ── -->
      <aside class="library-list">
        <p v-if="loading && !entries.length" class="library-notice" role="status">正在读取方案…</p>
        <div v-else-if="error" class="library-notice library-notice--error" role="alert">
          <span>{{ error }}</span>
          <button class="library-quiet-button" type="button" @click="reload">重试</button>
        </div>
        <div v-else-if="!entries.length" class="library-empty" data-library-empty>
          <p class="library-empty-title">还没有方案。</p>
          <p class="library-empty-hint">
            在聊天里说出你的想法，助手会一边问一边把方案写进「{{ dirName }}」文件夹；写好后就出现在这里。
          </p>
        </div>
        <ul v-else class="library-items" aria-label="方案列表">
          <li v-for="entry in entries" :key="entry.path">
            <button
              class="library-item"
              type="button"
              :class="{ 'is-active': selected?.path === entry.path }"
              :data-library-entry="entry.name"
              @click="select(entry)"
            >
              <span class="library-item-title">{{ entry.title }}</span>
              <span v-if="entry.summary" class="library-item-summary">{{ entry.summary }}</span>
              <span class="library-item-meta">
                <span class="library-status-chip" :data-plan-status="entry.status">{{ statusLabel(entry.status) }}</span>
                <span class="library-item-time">{{ updatedLabel(entry.updated_at) }}</span>
              </span>
            </button>
          </li>
        </ul>
      </aside>

      <!-- ── 阅读页：像读一篇文档一样读方案 ── -->
      <section class="library-reader" aria-label="方案阅读">
        <template v-if="selected">
          <header class="library-reader-head">
            <button
              v-if="narrow"
              class="library-back"
              type="button"
              aria-label="返回列表"
              title="返回列表"
              @click="clearSelection"
            >
              <ArrowLeft :size="16" :stroke-width="1.8" aria-hidden="true" />
            </button>
            <div class="library-reader-titles">
              <h2 class="library-reader-title">{{ selected.title }}</h2>
              <p v-if="contentUpdatedAt" class="library-reader-time">更新于 {{ contentUpdatedAt }}</p>
            </div>
            <div class="library-reader-actions">
              <button
                class="library-primary-button"
                type="button"
                :disabled="selected.status !== 'ready'"
                :title="startTitle"
                data-library-start
                @click="emit('start-plan', selected)"
              >
                开工
              </button>
              <button class="library-quiet-button" type="button" title="在文件编辑页中打开" @click="emit('edit-plan', selected.path)">
                编辑
              </button>
              <button
                class="library-quiet-button library-danger-button"
                type="button"
                :data-library-delete="confirmingDelete ? 'confirm' : 'arm'"
                @click="removeSelected"
                @blur="confirmingDelete = false"
              >
                {{ confirmingDelete ? '确认删除' : '删除' }}
              </button>
            </div>
          </header>
          <p v-if="contentLoading" class="library-notice" role="status">正在打开…</p>
          <p v-else-if="contentError" class="library-notice library-notice--error" role="alert">
            <span>{{ contentError }}</span>
            <button class="library-quiet-button" type="button" @click="loadContent">重试</button>
          </p>
          <article v-else class="library-reader-body">
            <MarkdownRenderer :content="content" />
          </article>
        </template>
        <div v-else class="library-reader-empty" data-library-reader-empty>
          <p>从左侧选一份方案开始读；没有的话，对助手说出你的想法就好。</p>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * PlanLibraryView — the 资料库 as one full-area view.
 *
 * A plan (方案) is a markdown document in the project's 「方案/」 folder; the
 * agent drafts and edits those files during ordinary conversation. This view
 * is the reader: list first, document on click, and the two actions that make
 * sense in place — 开工 (a ready plan becomes one ordinary session turn) and
 * 编辑 (the file in the stage editor). Everything else happens in the chat.
 *
 * The list comes from the plan-library scan (one call, newest first). A turn
 * finishing while the library is open bumps the host's refresh signal, so a
 * plan the agent just wrote shows up without leaving the view.
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ArrowLeft } from 'lucide-vue-next'
import type { CorePlanLibraryEntry, CoreProjectClient } from '../projects/client'
import { useNarrowViewport } from '../composables/useNarrowViewport'
import MarkdownRenderer from './MarkdownRenderer.vue'

export type PlanLibraryEntry = CorePlanLibraryEntry

const props = defineProps<{
  /** The switchable project client (desktop HTTP or the phone's standalone bridge). */
  client: CoreProjectClient
  /** The project whose 「方案/」 folder this library reads. */
  projectId?: string | null
  /** Bumped by the host when a turn finishes — the cue to rescan the folder. */
  refreshSignal?: number
}>()

const emit = defineEmits<{
  back: []
  'start-plan': [entry: PlanLibraryEntry]
  'edit-plan': [path: string]
}>()

const narrow = useNarrowViewport()

const dirName = '方案'
const entries = ref<PlanLibraryEntry[]>([])
const loading = ref(false)
const error = ref('')
const selected = ref<PlanLibraryEntry | null>(null)
const content = ref('')
const contentLoading = ref(false)
const contentError = ref('')
const contentUpdatedAt = ref('')
const confirmingDelete = ref(false)

const STATUS_LABELS: Record<PlanLibraryEntry['status'], string> = {
  draft: '草稿',
  ready: '就绪',
  executing: '执行中',
  done: '完成',
}

function statusLabel(status: PlanLibraryEntry['status']): string {
  return STATUS_LABELS[status] ?? status
}

const startTitle = computed(() => {
  if (!selected.value) return ''
  if (selected.value.status === 'ready') return '把这份方案交给当前会话执行'
  return '方案就绪后才能开工 — 在聊天里对助手说"可以开工了"，它会更新方案状态'
})

function updatedLabel(epochSeconds: number): string {
  if (!epochSeconds) return ''
  const date = new Date(epochSeconds * 1000)
  const pad = (n: number): string => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

async function reload(): Promise<void> {
  if (!props.projectId) return
  loading.value = true
  error.value = ''
  try {
    const response = await props.client.listPlanLibrary(props.projectId)
    entries.value = response.entries
    if (selected.value && !entries.value.some((entry) => entry.path === selected.value?.path)) {
      clearSelection()
    } else if (selected.value) {
      const fresh = entries.value.find((entry) => entry.path === selected.value?.path)
      if (fresh) selected.value = fresh
      void loadContent()
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    loading.value = false
  }
}

async function loadContent(): Promise<void> {
  const entry = selected.value
  if (!entry || !props.projectId) return
  contentLoading.value = true
  contentError.value = ''
  try {
    const response = await props.client.readFile(props.projectId, entry.path)
    content.value = response.content
    contentUpdatedAt.value = updatedLabel(entry.updated_at)
  } catch (cause) {
    contentError.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    contentLoading.value = false
  }
}

function select(entry: PlanLibraryEntry): void {
  confirmingDelete.value = false
  selected.value = entry
  content.value = ''
  void loadContent()
}

function clearSelection(): void {
  selected.value = null
  content.value = ''
  contentError.value = ''
  confirmingDelete.value = false
}

async function removeSelected(): Promise<void> {
  const entry = selected.value
  if (!entry || !props.projectId) return
  // 两段式确认：第一击蓄势，第二击删除；失焦即解除。
  if (!confirmingDelete.value) {
    confirmingDelete.value = true
    return
  }
  confirmingDelete.value = false
  try {
    await props.client.deletePlanLibraryFile(props.projectId, entry.path)
  } catch (cause) {
    contentError.value = cause instanceof Error ? cause.message : String(cause)
    return
  }
  clearSelection()
  await reload()
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    if (narrow.value && selected.value) {
      clearSelection()
      return
    }
    emit('back')
  }
}

watch(
  () => props.projectId,
  () => {
    clearSelection()
    entries.value = []
    void reload()
  },
)

watch(
  () => props.refreshSignal,
  () => {
    void reload()
  },
)

onMounted(() => {
  document.addEventListener('keydown', onKeydown)
  void reload()
})

onUnmounted(() => {
  document.removeEventListener('keydown', onKeydown)
})
</script>

<style scoped>
/* main area：资料库占住主卡内容区；列表与阅读双栏，窄屏合成单栏。 */
.plan-library-view {
  --text: var(--theme-main-text);
  display: flex;
  flex-direction: column;
  height: 100%;
  color: var(--text);
}

.library-head {
  flex-shrink: 0;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-3) clamp(var(--space-4), 4vw, var(--space-6)) var(--space-3);
  border-bottom: 1px solid color-mix(in srgb, var(--text) 10%, transparent);
}

.library-head-lead {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  min-width: 0;
}

.library-back,
.library-item,
.library-quiet-button,
.library-primary-button,
.library-danger-button {
  font: inherit;
}

.library-back {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  width: 30px;
  height: 30px;
  margin-top: 2px;
  border: 1px solid color-mix(in srgb, var(--text) 10%, transparent);
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--text) 65%, transparent);
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}

.library-back:hover {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  color: var(--text);
}

.library-title {
  margin: 0 0 2px;
  font-size: 20px;
  font-weight: 760;
  letter-spacing: -.02em;
}

.library-subtitle {
  margin: 0;
  color: color-mix(in srgb, var(--text) 65%, transparent);
  font-size: 12px;
}

.library-head-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
}

.library-columns {
  flex: 1 1 auto;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(240px, 320px) minmax(0, 1fr);
}

/* ── 列表 ── */
.library-list {
  min-height: 0;
  overflow-y: auto;
  border-right: 1px solid color-mix(in srgb, var(--text) 10%, transparent);
  padding: var(--space-3);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.library-items {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.library-item {
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 4px;
  padding: var(--space-2) var(--space-3);
  border: 1px solid transparent;
  border-radius: var(--radius);
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out), border-color var(--dur-fast) var(--ease-out);
}

.library-item:hover {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
}

.library-item.is-active {
  background: color-mix(in srgb, var(--text) var(--alpha-active), transparent);
  border-color: color-mix(in srgb, var(--text) 10%, transparent);
}

.library-item-title {
  font-weight: 640;
  font-size: 14px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.library-item-summary {
  color: color-mix(in srgb, var(--text) 65%, transparent);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.library-item-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

.library-status-chip {
  display: inline-flex;
  align-items: center;
  padding: 1px var(--space-2);
  border-radius: 999px;
  font-size: 11px;
  line-height: 18px;
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  color: color-mix(in srgb, var(--text) 65%, transparent);
}

.library-status-chip[data-plan-status='ready'] {
  background: color-mix(in srgb, var(--green) 18%, transparent);
  color: var(--green);
}

.library-status-chip[data-plan-status='executing'] {
  background: color-mix(in srgb, var(--orange) 18%, transparent);
  color: var(--orange);
}

.library-status-chip[data-plan-status='done'] {
  background: color-mix(in srgb, var(--blue) 18%, transparent);
  color: var(--blue);
}

.library-item-time {
  color: color-mix(in srgb, var(--text) 45%, transparent);
  font-size: 11px;
}

.library-empty {
  margin: auto;
  max-width: 320px;
  text-align: center;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.library-empty-title {
  margin: 0;
  font-weight: 640;
}

.library-empty-hint {
  margin: 0;
  color: color-mix(in srgb, var(--text) 65%, transparent);
  font-size: 12px;
  line-height: 1.7;
}

/* ── 阅读页 ── */
.library-reader {
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}

.library-reader-head {
  position: sticky;
  top: 0;
  z-index: 1;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) clamp(var(--space-4), 4vw, var(--space-6));
  background: color-mix(in srgb, var(--theme-main-background) 92%, transparent);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  border-bottom: 1px solid color-mix(in srgb, var(--text) 8%, transparent);
}

.library-reader-titles {
  min-width: 0;
  flex: 1 1 auto;
}

.library-reader-title {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.library-reader-time {
  margin: 0;
  color: color-mix(in srgb, var(--text) 45%, transparent);
  font-size: 11px;
}

.library-reader-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
}

.library-primary-button {
  padding: 6px var(--space-3);
  border: 0;
  border-radius: var(--radius-sm);
  background: var(--theme-control-background);
  color: var(--theme-control-text);
  font-weight: 600;
  cursor: pointer;
  transition: filter var(--dur-fast) var(--ease-out);
}

.library-primary-button:hover:not(:disabled) {
  filter: brightness(.94);
}

.library-primary-button:disabled {
  opacity: .45;
  cursor: default;
}

.library-quiet-button {
  padding: 6px var(--space-2);
  border: 1px solid color-mix(in srgb, var(--text) 10%, transparent);
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--text) 65%, transparent);
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}

.library-quiet-button:hover:not(:disabled) {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  color: var(--text);
}

.library-danger-button:hover:not(:disabled),
.library-danger-button[data-library-delete='confirm'] {
  border-color: color-mix(in srgb, var(--red) 40%, transparent);
  color: var(--red);
  background: color-mix(in srgb, var(--red) 10%, transparent);
}

.library-reader-body {
  width: 100%;
  max-width: 760px;
  margin: 0 auto;
  padding: var(--space-4) clamp(var(--space-4), 4vw, var(--space-6)) var(--space-6);
}

.library-reader-empty {
  margin: auto;
  padding: var(--space-6);
  text-align: center;
  color: color-mix(in srgb, var(--text) 45%, transparent);
  font-size: 13px;
}

/* ── 通用提示 ── */
.library-notice {
  margin: 0;
  padding: var(--space-3) clamp(var(--space-4), 4vw, var(--space-6));
  color: color-mix(in srgb, var(--text) 65%, transparent);
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.library-notice--error {
  color: var(--red);
}

/* 桌面：标题与返回键由顶部条承担，这里只留动作。 */
@media (min-width: 641px) {
  .library-head-lead {
    display: none;
  }
}

/* 窄屏：单栏，列表与阅读页互斥呈现。 */
@media (max-width: 640px) {
  .library-columns {
    grid-template-columns: minmax(0, 1fr);
  }

  .library-columns--reader-open .library-list {
    display: none;
  }

  .library-columns:not(.library-columns--reader-open) .library-reader {
    display: none;
  }

  .library-head {
    padding: var(--space-2) var(--space-3);
  }
}

@media (prefers-reduced-motion: reduce) {
  .library-item,
  .library-back,
  .library-quiet-button,
  .library-primary-button {
    transition: none;
  }
}
</style>
