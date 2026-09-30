<template>
  <div class="plan-library-view full-area-view">
    <FullAreaActions :to-band="bandActions">
      <button class="library-button" type="button" :disabled="loading" data-library-refresh @click="reload">
        {{ loading ? '刷新中…' : '刷新' }}
      </button>
    </FullAreaActions>

    <p v-if="!projectId" class="full-area-note">先在左侧选择一个项目 — 资料库跟随项目文件夹。</p>

    <div v-else-if="!entries.length && !loading && !error" class="full-area-column">
      <div class="full-area-empty" data-library-empty>
        <span class="full-area-empty-icon" aria-hidden="true"><BookOpen :size="18" :stroke-width="1.8" /></span>
        <h2 class="full-area-empty-title">还没有方案</h2>
        <p class="full-area-empty-hint">
          在聊天里说出你的想法，助手会一边问一边把方案写进「{{ dirName }}」文件夹；写好后就出现在这里。
          方案是一篇普通的 Markdown 文档，你也可以直接编辑它。
        </p>
      </div>
    </div>

    <div v-else class="full-area-column library-columns" :class="{ 'library-columns--reader-open': narrow && selected }">
      <aside class="library-list" aria-label="方案列表">
        <p v-if="error" class="full-area-note full-area-note--error" role="alert">
          {{ error }}<button class="library-link" type="button" @click="reload">重试</button>
        </p>
        <p v-else-if="loading && !entries.length" class="full-area-note" role="status">正在读取方案…</p>
        <ul v-else class="library-items">
          <li v-for="entry in entries" :key="entry.path">
            <button
              class="library-item"
              type="button"
              :class="{ 'is-active': selected?.path === entry.path }"
              :data-library-entry="entry.name"
              @click="select(entry)"
            >
              <span class="library-item-top">
                <span class="library-item-title">{{ entry.title }}</span>
                <span class="library-status" :data-plan-status="entry.status">{{ statusLabel(entry.status) }}</span>
              </span>
              <span class="library-item-bottom">
                <span class="library-item-summary">{{ entry.summary || '（还没有摘要）' }}</span>
                <span class="library-item-time">{{ updatedLabel(entry.updated_at) }}</span>
              </span>
            </button>
          </li>
        </ul>
      </aside>

      <section class="library-reader" aria-label="方案阅读">
        <template v-if="selected">
          <header class="library-reader-head">
            <h2 class="library-reader-title">{{ selected.title }}</h2>
            <p class="library-reader-meta">
              {{ statusLabel(selected.status) }}<template v-if="contentUpdatedAt"> · 更新于 {{ contentUpdatedAt }}</template>
            </p>
            <div class="library-reader-actions">
              <button
                class="library-button library-button--primary"
                type="button"
                :disabled="selected.status !== 'ready'"
                :title="startTitle"
                data-library-start
                @click="emit('start-plan', selected)"
              >
                开工
              </button>
              <button class="library-button" type="button" @click="emit('edit-plan', selected.path)">编辑</button>
              <button
                class="library-button library-button--danger"
                type="button"
                :data-library-delete="confirmingDelete ? 'confirm' : 'arm'"
                @click="removeSelected"
                @blur="confirmingDelete = false"
              >
                {{ confirmingDelete ? '确认删除' : '删除' }}
              </button>
            </div>
          </header>
          <p v-if="contentLoading" class="full-area-note" role="status">正在打开…</p>
          <p v-else-if="contentError" class="full-area-note full-area-note--error" role="alert">{{ contentError }}</p>
          <article v-else class="library-document">
            <MarkdownRenderer :content="documentBody" />
          </article>
        </template>
        <p v-else class="full-area-note library-reader-empty" data-library-reader-empty>
          从左侧选一份方案开始读。
        </p>
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
 * is the reader: the list on one axis, the document on the next, and the three
 * actions that make sense in place — 开工 (a ready plan becomes one ordinary
 * session turn), 编辑 (the file in the stage editor), 删除.
 *
 * The list comes from the plan-library scan (one call, newest first). A turn
 * finishing while the library is open bumps the host's refresh signal, so a
 * plan the agent just wrote shows up without leaving the view.
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { BookOpen } from 'lucide-vue-next'
import type { CorePlanLibraryEntry, CoreProjectClient } from '../projects/client'
import { useNarrowViewport } from '../composables/useNarrowViewport'
import FullAreaActions from './FullAreaActions.vue'
import MarkdownRenderer from './MarkdownRenderer.vue'

export type PlanLibraryEntry = CorePlanLibraryEntry

const props = defineProps<{
  /** The switchable project client (desktop HTTP or the phone's standalone bridge). */
  client: CoreProjectClient
  /** The project whose 「方案/」 folder this library reads. */
  projectId?: string | null
  /** Bumped by the host when a turn finishes — the cue to rescan the folder. */
  refreshSignal?: number
  /** Desktop sends actions into the header band; phones render them in place. */
  bandActions?: boolean
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

/**
 * 正文：去掉开头的 frontmatter（状态/摘要已在标题行给出）与首个 H1（标题行已给出），
 * 让读者看到的是一篇干净的文档，而不是带着元数据的一大块粗体。
 */
const documentBody = computed(() => stripPlanChrome(content.value))

function stripPlanChrome(markdown: string): string {
  let body = markdown
  if (body.startsWith('---')) {
    const close = body.indexOf(closingFence, 3)
    if (close !== -1) body = body.slice(body.indexOf(newline, close + 1) + 1)
  }
  return body.replace(leadingHeading, '')
}

/** Markdown 里的三处字面量：收尾分隔线、换行、首个标题行。 */
const closingFence = '\n---'
const newline = '\n'
const leadingHeading = /^\s*#\s+[^\n]*\n/

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
.plan-library-view {
  display: flex;
  flex-direction: column;
  padding-top: var(--space-4);
}

.library-columns {
  display: grid;
  grid-template-columns: minmax(200px, 236px) minmax(0, 1fr);
  gap: var(--space-5);
  padding-bottom: var(--space-5);
  align-items: start;
}

/* ── 列表 ── */
.library-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding-right: var(--space-4);
  border-right: 1px solid color-mix(in srgb, var(--text) 9%, transparent);
  min-height: 0;
}

.library-items {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.library-item {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: var(--space-2) var(--space-3);
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out);
}

.library-item:hover {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
}

.library-item.is-active {
  background: color-mix(in srgb, var(--text) var(--alpha-active), transparent);
}

.library-item-top {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  min-width: 0;
}

.library-item-title {
  flex: 1 1 auto;
  min-width: 0;
  font-size: 13.5px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.library-item-bottom {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  min-width: 0;
}

.library-item-summary {
  flex: 1 1 auto;
  min-width: 0;
  color: color-mix(in srgb, var(--text) 62%, transparent);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.library-item-time {
  flex: 0 0 auto;
  color: color-mix(in srgb, var(--text) 42%, transparent);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.library-status {
  flex: 0 0 auto;
  font-size: 11px;
  line-height: 16px;
  padding: 0 var(--space-1);
  border-radius: 999px;
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  color: color-mix(in srgb, var(--text) 62%, transparent);
}

.library-status[data-plan-status='ready'] {
  background: color-mix(in srgb, var(--green) 16%, transparent);
  color: var(--green);
}

.library-status[data-plan-status='executing'] {
  background: color-mix(in srgb, var(--orange) 16%, transparent);
  color: var(--orange);
}

.library-status[data-plan-status='done'] {
  background: color-mix(in srgb, var(--blue) 16%, transparent);
  color: var(--blue);
}

/* ── 阅读页 ── */
.library-reader {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  min-width: 0;
}

.library-reader-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  grid-template-areas:
    'title actions'
    'meta actions';
  gap: 2px var(--space-4);
  align-items: center;
  padding-bottom: var(--space-3);
  border-bottom: 1px solid color-mix(in srgb, var(--text) 9%, transparent);
}

.library-reader-title {
  grid-area: title;
  margin: 0;
  font-size: 19px;
  font-weight: 700;
  letter-spacing: -0.01em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.library-reader-meta {
  grid-area: meta;
  margin: 0;
  font-size: 12px;
  color: color-mix(in srgb, var(--text) 52%, transparent);
  font-variant-numeric: tabular-nums;
}

.library-reader-actions {
  grid-area: actions;
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.library-reader-empty {
  padding-top: var(--space-4);
}

.library-document {
  max-width: 68ch;
  font-size: 14px;
  line-height: 1.75;
}

/* 文档排版：标签页的标题行已经给过标题，正文里不再抢戏。 */
.library-document :deep(h1),
.library-document :deep(h2),
.library-document :deep(h3) {
  margin: var(--space-5) 0 var(--space-2);
  font-weight: 650;
  letter-spacing: 0;
  line-height: 1.35;
}

.library-document :deep(h1) { font-size: 17px; }
.library-document :deep(h2) { font-size: 15px; }
.library-document :deep(h3) { font-size: 13.5px; color: color-mix(in srgb, var(--text) 82%, transparent); }
.library-document :deep(> :first-child) { margin-top: 0; }

.library-document :deep(p) { margin: 0 0 var(--space-3); }
.library-document :deep(ul),
.library-document :deep(ol) { margin: 0 0 var(--space-3); padding-left: 1.25em; }
.library-document :deep(li) { margin-bottom: 4px; }
.library-document :deep(li > ul),
.library-document :deep(li > ol) { margin-top: 4px; }
.library-document :deep(code) {
  font-family: var(--font-mono);
  font-size: 12.5px;
  padding: 1px 5px;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--text) 6%, transparent);
}
.library-document :deep(pre) {
  margin: 0 0 var(--space-3);
  padding: var(--space-3);
  border-radius: var(--radius);
  background: var(--theme-main-sunken-background, color-mix(in srgb, var(--text) 6%, transparent));
  overflow-x: auto;
}
.library-document :deep(pre code) { padding: 0; background: none; }
.library-document :deep(blockquote) {
  margin: 0 0 var(--space-3);
  padding-left: var(--space-3);
  border-left: 2px solid color-mix(in srgb, var(--text) 18%, transparent);
  color: color-mix(in srgb, var(--text) 72%, transparent);
}
.library-document :deep(hr) {
  margin: var(--space-5) 0;
  border: 0;
  border-top: 1px solid color-mix(in srgb, var(--text) 10%, transparent);
}
.library-document :deep(table) { width: 100%; border-collapse: collapse; margin: 0 0 var(--space-3); font-size: 13px; }
.library-document :deep(th),
.library-document :deep(td) { padding: 6px var(--space-2); border-bottom: 1px solid color-mix(in srgb, var(--text) 10%, transparent); text-align: left; }

/* ── 按钮：一种配方，两种语气 ── */
.library-button {
  padding: 5px var(--space-3);
  min-height: 28px;
  border: 1px solid color-mix(in srgb, var(--text) 12%, transparent);
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--text) 78%, transparent);
  font: inherit;
  font-size: 12.5px;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}

.library-button:hover:not(:disabled) {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  color: var(--text);
}

.library-button--primary {
  border-color: transparent;
  background: var(--theme-control-background);
  color: var(--theme-control-text);
  font-weight: 600;
}

.library-button--primary:hover:not(:disabled) {
  background: var(--theme-control-background);
  filter: brightness(0.94);
}

.library-button:disabled {
  opacity: 0.45;
  cursor: default;
}

.library-button--danger:hover:not(:disabled),
.library-button--danger[data-library-delete='confirm'] {
  border-color: color-mix(in srgb, var(--red) 45%, transparent);
  background: color-mix(in srgb, var(--red) 10%, transparent);
  color: var(--red);
}

.library-link {
  margin-left: var(--space-2);
  padding: 0;
  border: 0;
  background: none;
  color: inherit;
  text-decoration: underline;
  cursor: pointer;
  font: inherit;
}

/* 窄屏：单栏，列表与阅读页互斥呈现。 */
@media (max-width: 640px) {
  .library-columns {
    grid-template-columns: minmax(0, 1fr);
    gap: var(--space-3);
  }

  .library-list {
    padding-right: 0;
    border-right: 0;
  }

  .library-columns--reader-open .library-list {
    display: none;
  }

  .library-columns:not(.library-columns--reader-open) .library-reader {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .library-item,
  .library-button {
    transition: none;
  }
}
</style>
