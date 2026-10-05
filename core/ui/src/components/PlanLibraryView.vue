<template>
  <div
    class="plan-library-view library-surface full-area-view"
    :aria-busy="loading"
    :style="{ '--library-zoom': String(zoom) }"
    @wheel="onZoomWheel"
  >
    <FullAreaActions :to-band="bandActions">
      <!-- 编辑：一个「确认」收尾——保存（若有改动）并直接回到阅读 -->
      <template v-if="mode === 'editor' && selected">
        <button
          class="library-button library-button--primary"
          type="button"
          :disabled="saving"
          data-library-editor-confirm
          @click="confirmEditor"
        >{{ saving ? '保存中…' : '确认' }}</button>
      </template>
      <!-- 列表 / 文件夹：工具栏动作；阅读：文档动作 -->
      <template v-else-if="mode === 'reader' && selected">
        <button
          class="library-button library-button--primary"
          type="button"
          :disabled="selected.status !== 'ready'"
          :title="startTitle"
          data-library-start
          @click="emit('start-plan', selected)"
        >开工</button>
        <button class="library-button" type="button" @click="openEditor(selected)">编辑</button>
        <button
          class="library-button library-button--danger"
          type="button"
          :data-library-delete="confirmingDelete ? 'confirm' : 'arm'"
          @click="removeSelected"
          @blur="confirmingDelete = false"
        >{{ confirmingDelete ? '确认删除' : '删除' }}</button>
      </template>
      <template v-else>
        <button class="icon-button" type="button" :disabled="loading" aria-label="刷新" title="刷新" data-library-refresh @click="reload">
          <RefreshCw :size="14" :stroke-width="1.8" aria-hidden="true" />
        </button>
        <!-- 资料库跟随项目文件夹：没选项目就没有可写的位置，按钮先别装作能按。 -->
        <button class="library-button" type="button" :disabled="!projectId" :title="projectId ? '' : '先在左侧选择一个项目'" data-library-create-folder @click="openDialog('create-folder')">新建文件夹</button>
        <button class="library-button library-button--primary" type="button" :disabled="!projectId" :title="projectId ? '' : '先在左侧选择一个项目'" data-library-create @click="openDialog('create-plan')">
          <Plus :size="14" :stroke-width="1.8" aria-hidden="true" />
          新建方案
        </button>
      </template>
    </FullAreaActions>

    <div class="library-mobile-head">
      <button class="library-back" type="button" aria-label="返回" title="返回" @click="onBackClick">
        <ArrowLeft :size="16" :stroke-width="1.8" aria-hidden="true" />
      </button>
      <p v-if="mode === 'reader' && selected" class="library-crumb" data-library-crumb>
        资料库 <span class="crumb-sep" aria-hidden="true">›</span> {{ truncateTitle(displayTitle(selected)) }}
      </p>
      <!-- 文件夹可以嵌套：面包屑逐层可点，最后一段是当前层。 -->
      <nav v-else-if="openFolder" class="library-crumb" data-library-crumb aria-label="位置">
        <button type="button" class="crumb-link" @click="goToFolder('')">资料库</button>
        <template v-for="(step, index) in folderTrail" :key="step.dir">
          <span class="crumb-sep" aria-hidden="true">›</span>
          <button
            type="button"
            class="crumb-link"
            :class="{ 'crumb-link--current': index === folderTrail.length - 1 }"
            :aria-current="index === folderTrail.length - 1 ? 'page' : undefined"
            :data-library-crumb-step="step.dir"
            @click="goToFolder(step.dir)"
          >{{ step.name }}</button>
        </template>
      </nav>
      <div v-else class="library-head-copy">
        <h1 class="library-title">资料库</h1>
        <p class="library-subtitle">「{{ dirName }}」文件夹里的方案 — 点开读全文，就绪后开工。</p>
      </div>
    </div>

    <p v-if="!projectId" class="full-area-note">先在左侧选择一个项目 — 资料库跟随项目文件夹。</p>

    <!-- ── 阅读子页 ── -->
    <section v-else-if="mode === 'reader' && selected" class="library-reader" aria-label="方案阅读" data-library-reader>
      <header class="library-reader-head">
        <h2 class="library-reader-title">{{ displayTitle(selected) }}</h2>
        <p class="library-reader-meta">
          <span class="library-status" :data-plan-status="selected.status">{{ statusLabel(selected.status) }}</span>
          <span v-if="contentUpdatedAt">更新于 {{ contentUpdatedAt }}</span>
        </p>
      </header>
      <p v-if="contentLoading" class="full-area-note" role="status">正在打开…</p>
      <p v-else-if="contentError" class="full-area-note full-area-note--error" role="alert">{{ contentError }}</p>
      <article v-else class="library-document">
        <MarkdownRenderer :content="documentBody" />
      </article>
    </section>

    <!-- ── 编辑子页：资料库自己的编辑器，写方案原文，不跳文件工作台 ── -->
    <section v-else-if="mode === 'editor' && selected" class="library-editor" aria-label="方案编辑" data-library-editor>
      <header class="library-editor-head">
        <h2 class="library-editor-title">{{ displayTitle(selected) }}</h2>
        <p class="library-editor-meta">
          <span :class="dirty ? 'library-editor-state library-editor-state--dirty' : 'library-editor-state'" data-library-editor-state>
            {{ dirty ? '未保存' : '已保存' }}
          </span>
          <span class="library-editor-path">{{ selected.path }}</span>
        </p>
      </header>
      <p v-if="editorLoading" class="full-area-note" role="status">正在打开…</p>
      <template v-else>
        <DocumentEditor ref="editorInput" id-prefix="library-editor" :title="displayTitle(selected)" v-model="draft">
          <template #preview="{ content }">
            <MarkdownRenderer :content="content" />
          </template>
        </DocumentEditor>
        <p v-if="saveError" class="full-area-note full-area-note--error" role="alert">{{ saveError }}</p>
      </template>
    </section>

    <template v-else>
      <!-- ── 工具栏：搜索 + 视图切换 ── -->
      <div class="library-toolbar" data-library-toolbar>
        <div class="library-search">
          <Search :size="14" :stroke-width="1.8" aria-hidden="true" />
          <input
            v-model="query"
            type="search"
            placeholder="搜索资料库"
            aria-label="搜索资料库"
            data-library-search
          />
        </div>
        <div class="library-view-toggle" role="group" aria-label="视图切换" data-library-view-toggle>
          <button
            type="button"
            :class="{ active: viewMode === 'grid' }"
            :aria-pressed="viewMode === 'grid'"
            aria-label="网格视图"
            title="网格视图"
            @click="viewMode = 'grid'"
          ><LayoutGrid :size="14" :stroke-width="1.8" aria-hidden="true" /></button>
          <button
            type="button"
            :class="{ active: viewMode === 'list' }"
            :aria-pressed="viewMode === 'list'"
            aria-label="列表视图"
            title="列表视图"
            @click="viewMode = 'list'"
          ><List :size="14" :stroke-width="1.8" aria-hidden="true" /></button>
        </div>
      </div>

      <!-- ── 筛选页签 ── -->
      <div class="filter-tabs" role="group" aria-label="筛选资料库" data-library-tabs>
        <button
          v-for="tab in TABS"
          :key="tab.id"
          type="button"
          :class="{ active: activeTab === tab.id }"
          :aria-pressed="activeTab === tab.id"
          :data-library-tab="tab.id"
          @click="activeTab = tab.id"
        >{{ tab.label }}</button>
      </div>

      <p v-if="loading && !entries.length && !folders.length" class="full-area-note" role="status">正在读取资料库…</p>
      <p v-else-if="error" class="full-area-note full-area-note--error" role="alert">
        {{ error }}<button class="library-link" type="button" @click="reload">重试</button>
      </p>

      <template v-else>
        <!-- ── 子文件夹：根上的「文件夹」页签，以及文件夹详情里的下一层 ── -->
        <div v-if="showFolderGrid" class="folder-grid" role="list" data-library-folders>
          <article
            v-for="folder in childFolders"
            :key="folder.path"
            class="folder-card"
            role="listitem"
            tabindex="0"
            :aria-label="`打开文件夹 ${folder.name}`"
            :data-library-folder="folder.dir"
            @click="goToFolder(folder.dir)"
            @keydown.enter.prevent="goToFolder(folder.dir)"
            @contextmenu="openFolderMenu($event, folder)"
          >
            <span class="folder-card-icon" aria-hidden="true"><Folder :size="18" :stroke-width="1.6" /></span>
            <span class="folder-card-name">{{ folder.name }}</span>
            <span class="folder-card-count">{{ folder.count }} 份方案</span>
            <button class="card-menu-btn" type="button" :aria-label="`${folder.name} 的操作`" @click.stop="openFolderMenu($event, folder)">
              <MoreHorizontal :size="15" :stroke-width="1.8" aria-hidden="true" />
            </button>
          </article>
        </div>

        <!-- ── 空态 ── -->
        <div v-if="folderTabActive && childFolders.length === 0" class="full-area-empty" data-folders-empty>
          <span class="full-area-empty-icon" aria-hidden="true"><Folder :size="18" :stroke-width="1.8" /></span>
          <h2 class="full-area-empty-title">{{ openFolder ? '这里还没有子文件夹' : '创建你的第一个文件夹' }}</h2>
          <p class="full-area-empty-hint">创建文件夹，整理资料库中的方案。</p>
          <button class="library-button library-button--primary" type="button" data-folders-create @click="openDialog('create-folder')">创建文件夹</button>
        </div>
        <div v-else-if="openFolder && !showFolderGrid && folderEntries.length === 0" class="folder-empty" data-folder-empty>
          <Upload :size="18" :stroke-width="1.6" aria-hidden="true" />
          <p>这个文件夹还是空的 — 点右上角「新建方案」，它会建在这里。</p>
        </div>
        <div v-else-if="!openFolder && entries.length === 0" class="full-area-empty" data-library-empty>
          <span class="full-area-empty-icon" aria-hidden="true"><BookOpen :size="18" :stroke-width="1.8" /></span>
          <h2 class="full-area-empty-title">还没有方案</h2>
          <p class="full-area-empty-hint">
            在聊天里说出你的想法，助手会一边问一边把方案写进「{{ dirName }}」文件夹；写好后就出现在这里。
            方案是一篇普通的 Markdown 文档，你也可以直接新建一篇来写。
          </p>
          <button class="library-button library-button--primary" type="button" data-library-empty-create @click="openDialog('create-plan')">新建方案</button>
        </div>
        <p v-else-if="!openFolder && filteredEntries.length === 0" class="full-area-note tab-empty" data-library-tab-empty>
          {{ activeTab === 'favorites' ? '还没有收藏的方案 — 在方案卡片的菜单里「添加到收藏」。' : '这个状态下暂无方案。' }}
        </p>

        <!-- ── 方案本体（网格 / 列表）：文件夹详情与主列表共用一块 ── -->
        <template v-if="!folderTabActive && listEntries.length">
        <div v-if="viewMode === 'grid'" class="plan-grid" role="list">
          <article
            v-for="entry in listEntries"
            :key="entry.path"
            class="plan-card"
            role="listitem"
            tabindex="0"
            :aria-label="`打开 ${displayTitle(entry)}`"
            :data-library-entry="entry.name"
            @click="openEntry(entry)"
            @keydown.enter.prevent="openEntry(entry)"
            @contextmenu="openEntryMenu($event, entry)"
          >
            <div class="plan-card-preview">
              <p class="plan-card-summary">{{ entry.summary || '还没有摘要 — 打开写第一段。' }}</p>
              <FileText :size="26" :stroke-width="1.4" aria-hidden="true" class="plan-card-glyph" />
            </div>
            <button class="card-menu-btn" type="button" :aria-label="`${displayTitle(entry)} 的操作`" @click.stop="openEntryMenu($event, entry)">
              <MoreHorizontal :size="15" :stroke-width="1.8" aria-hidden="true" />
            </button>
            <h4 class="plan-card-title">{{ displayTitle(entry) }}</h4>
            <div class="plan-card-foot">
              <span class="library-status" :data-plan-status="entry.status">{{ statusLabel(entry.status) }}</span>
              <Star v-if="entry.favorite" :size="12" :stroke-width="1.8" aria-label="已收藏" class="plan-card-star" />
              <span class="plan-card-time">{{ shortDate(entry.updated_at) }}</span>
            </div>
          </article>
        </div>

        <ul v-else class="library-items" role="list">
          <li v-for="entry in listEntries" :key="entry.path">
            <div
              class="library-row"
              role="button"
              tabindex="0"
              :data-library-entry="entry.name"
              @click="openEntry(entry)"
              @keydown.enter.prevent="openEntry(entry)"
              @contextmenu="openEntryMenu($event, entry)"
            >
              <div class="library-item-top">
                <span class="library-item-title">{{ displayTitle(entry) }}</span>
                <Star v-if="entry.favorite" :size="12" :stroke-width="1.8" aria-label="已收藏" class="plan-card-star" />
                <span class="library-status" :data-plan-status="entry.status">{{ statusLabel(entry.status) }}</span>
              </div>
              <div class="library-item-bottom">
                <span class="library-item-summary">{{ entry.summary || '（还没有摘要）' }}</span>
                <span class="library-item-time">{{ updatedLabel(entry.updated_at) }}</span>
              </div>
              <button class="card-menu-btn" type="button" :aria-label="`${displayTitle(entry)} 的操作`" @click.stop="openEntryMenu($event, entry)">
                <MoreHorizontal :size="15" :stroke-width="1.8" aria-hidden="true" />
              </button>
            </div>
          </li>
        </ul>
        </template>
      </template>
    </template>

    <!-- ── 新建 / 重命名对话框 ── -->
    <Transition name="library-dialog">
      <div v-if="dialog" class="dialog-dimmer" @click.self="closeDialog">
        <div class="dialog-card" role="dialog" aria-modal="true" :aria-label="dialogTitle" data-library-dialog>
          <div class="dialog-body">
            <h3 class="dialog-title">{{ dialogTitle }}</h3>
            <label class="dialog-field">
              <span>{{ dialog.kind === 'create-folder' ? '文件夹名称' : '方案名称' }}</span>
              <input
                ref="dialogInput"
                v-model="dialog.value"
                type="text"
                :placeholder="dialog.kind === 'create-folder' ? '例如：迭代计划' : '例如：导出显示进度'"
                :data-library-dialog-input="dialog.kind"
                @keydown.enter.prevent="submitDialog"
                @keydown.escape.prevent="closeDialog"
              />
            </label>
            <p v-if="dialog.error" class="dialog-error" role="alert">{{ dialog.error }}</p>
          </div>
          <div class="dialog-actions">
            <button class="library-button" type="button" @click="closeDialog">取消</button>
            <button
              class="library-button library-button--primary"
              type="button"
              :disabled="dialog.busy || !dialog.value.trim()"
              data-library-dialog-submit
              @click="submitDialog"
            >{{ dialog.busy ? '处理中…' : dialog.kind === 'rename' ? '重命名' : '创建' }}</button>
          </div>
        </div>
      </div>
    </Transition>

    <!-- ── 放弃未保存修改的确认 ── -->
    <Transition name="library-dialog">
      <div v-if="pendingDiscard" class="dialog-dimmer" @click.self="pendingDiscard = false">
        <div class="dialog-card" role="dialog" aria-modal="true" aria-label="确认放弃修改" data-library-discard>
          <div class="dialog-body">
            <h3 class="dialog-title">放弃修改</h3>
            <p class="dialog-text">「{{ displayTitle(selected!) }}」还有没保存的内容，离开就会丢掉。</p>
          </div>
          <div class="dialog-actions">
            <button class="library-button" type="button" @click="pendingDiscard = false">继续编辑</button>
            <button class="library-button library-button--danger" type="button" data-library-discard-confirm @click="discardEditor">放弃修改</button>
          </div>
        </div>
      </div>
    </Transition>

    <!-- ── 删除确认 ── -->
    <Transition name="library-dialog">
      <div v-if="pendingDelete" class="dialog-dimmer" @click.self="pendingDelete = null">
        <div class="dialog-card" role="dialog" aria-modal="true" aria-label="确认删除" data-library-confirm>
          <div class="dialog-body">
            <h3 class="dialog-title">删除方案</h3>
            <p class="dialog-text">「{{ displayTitle(pendingDelete) }}」将被删除，且无法恢复。</p>
          </div>
          <div class="dialog-actions">
            <button class="library-button" type="button" @click="pendingDelete = null">取消</button>
            <button class="library-button library-button--danger" type="button" data-library-confirm-delete @click="confirmDelete">删除</button>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup lang="tsx">
/**
 * PlanLibraryView — the 资料库 as one full-area view.
 *
 * A plan (方案) is a markdown document in the project's 「方案/」 folder; the
 * agent drafts and edits those files during ordinary conversation. The view
 * follows the library standard: toolbar (search + view toggle + create),
 * filter tabs (全部 / 收藏 / 文件夹 / 状态), a card grid with a list variant,
 * a per-item context menu, folder detail pages, and a reader sub-page — the
 * header band tracks where you are via `heading`.
 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  ArrowLeft,
  BookOpen,
  FileText,
  Folder,
  LayoutGrid,
  List,
  MoreHorizontal,
  Plus,
  RefreshCw,
  Search,
  Star,
  Trash2,
  Upload,
} from 'lucide-vue-next'
import type { CorePlanLibraryEntry, CorePlanLibraryFolder, CoreProjectClient } from '../projects/client'
import FullAreaActions from './FullAreaActions.vue'
import DocumentEditor from './DocumentEditor.vue'
import MarkdownRenderer from './MarkdownRenderer.vue'
import { useLibraryZoom } from '../composables/useLibraryZoom'
import { openContextMenu, type ContextMenuEntry } from './context-menu'

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
  /** 顶部条标题的根名：在资料库里这项叫「方案」。 */
  rootLabel?: string
}>()

const emit = defineEmits<{
  back: []
  'start-plan': [entry: PlanLibraryEntry]
  /** 顶部条标题跟随内部子页（列表 / 文件夹 / 阅读 / 编辑）。 */
  heading: [payload: { title: string; subtitle: string }]
}>()

const dirName = '方案'
const rootLabel = computed(() => props.rootLabel || '资料库')

/* ---- 卡片墙缩放：Ctrl+滚轮增减，资料与方案共用一档 ---- */
const { zoom, onZoomWheel } = useLibraryZoom()
const entries = ref<PlanLibraryEntry[]>([])
const folders = ref<CorePlanLibraryFolder[]>([])
const loading = ref(false)
const error = ref('')

const TABS = [
  { id: 'all', label: '全部' },
  { id: 'favorites', label: '收藏' },
  { id: 'folders', label: '文件夹' },
  { id: 'draft', label: '草稿' },
  { id: 'ready', label: '就绪' },
  { id: 'executing', label: '执行中' },
  { id: 'done', label: '完成' },
] as const
type TabId = (typeof TABS)[number]['id']
const activeTab = ref<TabId>('all')
const query = ref('')

type ViewMode = 'grid' | 'list'
const VIEW_STORAGE_KEY = 'lamtools.core.library.view'
const viewMode = ref<ViewMode>(readStoredView())
function readStoredView(): ViewMode {
  try {
    return window.localStorage.getItem(VIEW_STORAGE_KEY) === 'list' ? 'list' : 'grid'
  } catch {
    return 'grid'
  }
}
watch(viewMode, (value) => {
  try {
    window.localStorage.setItem(VIEW_STORAGE_KEY, value)
  } catch { /* 无存储时仅当前会话生效 */ }
})

/* ---- 子页导航：列表 ↔ 文件夹 ↔ 阅读 ↔ 编辑，顶部条标题随动 ---- */
const mode = ref<'listing' | 'reader' | 'editor'>('listing')
const openFolder = ref('')
const readerFrom = ref<'listing' | 'folder'>('listing')
const selected = ref<PlanLibraryEntry | null>(null)
const content = ref('')
const contentLoading = ref(false)
const contentError = ref('')
const contentUpdatedAt = ref('')
const confirmingDelete = ref(false)

/* ---- 编辑子页：写方案原文，资料库自己的编辑器 ---- */
const draft = ref('')
const editorBaseline = ref('')
const editorLoading = ref(false)
const saving = ref(false)
const saveError = ref('')
const pendingDiscard = ref(false)
const editorInput = ref<{ focus: () => void; setPreviewing: (value: boolean) => void } | null>(null)
const dirty = computed(() => draft.value !== editorBaseline.value)

/* ---- 对话框（新建 / 新建文件夹 / 重命名）与删除确认 ---- */
type DialogKind = 'create-plan' | 'create-folder' | 'rename'
const dialog = ref<{ kind: DialogKind; value: string; error: string; busy: boolean; target?: PlanLibraryEntry } | null>(null)
const dialogInput = ref<HTMLInputElement | null>(null)
const pendingDelete = ref<PlanLibraryEntry | null>(null)

const STATUS_LABELS: Record<PlanLibraryEntry['status'], string> = {
  draft: '草稿',
  ready: '就绪',
  executing: '执行中',
  done: '完成',
}

function statusLabel(status: PlanLibraryEntry['status']): string {
  return STATUS_LABELS[status] ?? status
}

function displayTitle(entry: PlanLibraryEntry): string {
  return entry.title || entry.name.replace(/\.md$/i, '')
}

function truncateTitle(text: string): string {
  return text.length > 24 ? `${text.slice(0, 24)}…` : text
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

function shortDate(epochSeconds: number): string {
  if (!epochSeconds) return ''
  const date = new Date(epochSeconds * 1000)
  const pad = (n: number): string => String(n).padStart(2, '0')
  return `${pad(date.getMonth() + 1)}月${pad(date.getDate())}日`
}

/* ---- 数据 ---- */
async function reload(): Promise<void> {
  if (!props.projectId) return
  loading.value = true
  error.value = ''
  try {
    const response = await props.client.listPlanLibrary(props.projectId)
    entries.value = response.entries
    folders.value = response.folders || []
    // 当前这一层可能在别处被删了；别把用户留在一间不存在的房间里。
    if (openFolder.value && !folders.value.some((folder) => folder.dir === openFolder.value)) {
      openFolder.value = ''
    }
    if (selected.value) {
      const fresh = entries.value.find((entry) => entry.path === selected.value?.path)
      if (!fresh) {
        clearSelection()
      } else {
        selected.value = fresh
        void loadContent()
      }
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

function openEntry(entry: PlanLibraryEntry): void {
  confirmingDelete.value = false
  readerFrom.value = openFolder.value ? 'folder' : 'listing'
  selected.value = entry
  content.value = ''
  contentError.value = ''
  mode.value = 'reader'
  void loadContent()
}

/** 进编辑子页：写出方案原文，确认后回到阅读页看排版结果。 */
async function openEditor(entry: PlanLibraryEntry): Promise<void> {
  readerFrom.value = openFolder.value ? 'folder' : 'listing'
  selected.value = entry
  content.value = ''
  contentError.value = ''
  saveError.value = ''
  pendingDiscard.value = false
  mode.value = 'editor'
  draft.value = ''
  editorBaseline.value = ''
  editorLoading.value = true
  editorInput.value?.setPreviewing(false)
  try {
    const response = await props.client.readFile(props.projectId!, entry.path)
    content.value = response.content
    draft.value = response.content
    editorBaseline.value = response.content
  } catch (cause) {
    saveError.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    editorLoading.value = false
    void nextTick(() => editorInput.value?.focus())
  }
}

/**
 * 编辑页的唯一收尾动作：确认 = 保存（有改动才写盘）并直接回到阅读。
 * 写盘失败时留在编辑页，错误就近显示，改动不丢。
 */
async function confirmEditor(): Promise<void> {
  if (saving.value) return
  if (!dirty.value) {
    leaveEditor()
    return
  }
  await saveEditor()
}

async function saveEditor(): Promise<void> {
  const entry = selected.value
  if (!entry || !props.projectId || saving.value || !dirty.value) return
  saving.value = true
  saveError.value = ''
  try {
    await props.client.writeFile(props.projectId, entry.path, draft.value)
  } catch (cause) {
    saveError.value = cause instanceof Error ? cause.message : String(cause)
    return
  } finally {
    saving.value = false
  }
  content.value = draft.value
  editorBaseline.value = draft.value
  await reload()
  // 回到阅读页：保存后该看的是排版结果，而不是刚写完的原文。
  const fresh = entries.value.find((item) => item.path === entry.path)
  if (fresh) selected.value = fresh
  mode.value = 'reader'
  contentError.value = ''
  contentUpdatedAt.value = updatedLabel(selected.value?.updated_at ?? 0)
}

/** 离开编辑页；有未保存内容先问一句。 */
function requestCloseEditor(): void {
  if (dirty.value) {
    pendingDiscard.value = true
    return
  }
  leaveEditor()
}

function discardEditor(): void {
  pendingDiscard.value = false
  leaveEditor()
}

function leaveEditor(): void {
  draft.value = ''
  editorBaseline.value = ''
  saveError.value = ''
  editorInput.value?.setPreviewing(false)
  mode.value = 'reader'
}

function clearSelection(): void {
  selected.value = null
  content.value = ''
  contentError.value = ''
  draft.value = ''
  editorBaseline.value = ''
  saveError.value = ''
  pendingDiscard.value = false
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

/** 菜单里发起的删除走这个确认框。 */
async function confirmDelete(): Promise<void> {
  const entry = pendingDelete.value
  if (!entry || !props.projectId) return
  pendingDelete.value = null
  error.value = ''
  try {
    await props.client.deletePlanLibraryFile(props.projectId, entry.path)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
    return
  }
  if (selected.value?.path === entry.path) {
    mode.value = 'listing'
    clearSelection()
  }
  await reload()
}

/* ---- 列表筛选 ---- */
const filteredEntries = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  let list = entries.value
  if (activeTab.value === 'favorites') list = list.filter(entry => entry.favorite)
  else if (activeTab.value !== 'all' && activeTab.value !== 'folders') {
    list = list.filter(entry => entry.status === activeTab.value)
  }
  if (keyword) {
    list = list.filter(entry =>
      entry.title.toLowerCase().includes(keyword)
      || entry.summary.toLowerCase().includes(keyword)
      || entry.name.toLowerCase().includes(keyword))
  }
  return list
})

const folderEntries = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  let list = entries.value.filter(entry => entry.folder === openFolder.value)
  if (keyword) {
    list = list.filter(entry =>
      entry.title.toLowerCase().includes(keyword)
      || entry.summary.toLowerCase().includes(keyword)
      || entry.name.toLowerCase().includes(keyword))
  }
  return list
})

/** 网格 / 列表同一块渲染：文件夹详情看夹内，其余看当前筛选结果。 */
const listEntries = computed(() => openFolder.value ? folderEntries.value : filteredEntries.value)

/* ---- 逐层导航：文件夹可以嵌套，openFolder 存库内相对目录（'' = 库根） ---- */
/** 根上的「文件夹」页签：只列这一层的文件夹，不混方案。 */
const folderTabActive = computed(() => !openFolder.value && activeTab.value === 'folders')
const childFolders = computed(() => folders.value.filter(folder => folder.parent === openFolder.value))
const showFolderGrid = computed(() =>
  childFolders.value.length > 0 && (folderTabActive.value || Boolean(openFolder.value)))

/** 从库根到当前层的路径，每一段都能点回去。 */
const folderTrail = computed(() => {
  const parts = openFolder.value ? openFolder.value.split('/') : []
  return parts.map((name, index) => ({ name, dir: parts.slice(0, index + 1).join('/') }))
})

function goToFolder(dir: string): void {
  openFolder.value = dir
  query.value = ''
}

/** 空文件夹：这一层没有方案，也没有下一层文件夹。 */
function isFolderEmpty(folder: CorePlanLibraryFolder): boolean {
  return folder.count === 0 && !folders.value.some(child => child.parent === folder.dir)
}

/* ---- 收藏 ---- */
async function toggleFavorite(entry: PlanLibraryEntry): Promise<void> {
  if (!props.projectId) return
  error.value = ''
  try {
    const { entry: updated } = await props.client.favoritePlanLibraryFile(props.projectId, entry.path, !entry.favorite)
    entries.value = entries.value.map(item => item.path === updated.path ? updated : item)
    if (selected.value?.path === updated.path) selected.value = updated
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}

/* ---- 对话框 ---- */
const dialogTitle = computed(() => {
  if (!dialog.value) return ''
  if (dialog.value.kind === 'create-folder') return '新建文件夹'
  if (dialog.value.kind === 'rename') return '重命名方案'
  return '新建方案'
})

function openDialog(kind: DialogKind, target?: PlanLibraryEntry): void {
  dialog.value = {
    kind,
    value: kind === 'rename' ? (target ? displayTitle(target) : '') : '',
    error: '',
    busy: false,
    target,
  }
  void nextTick(() => dialogInput.value?.focus())
}

function closeDialog(): void {
  dialog.value = null
}

async function submitDialog(): Promise<void> {
  const current = dialog.value
  if (!current || current.busy || !current.value.trim()) return
  if (!props.projectId) {
    // 按钮已禁用；这里再兜一次，避免对话框以任何方式被打开时静默什么都不做。
    current.error = '先在左侧选择一个项目'
    return
  }
  const name = current.value.trim()
  current.busy = true
  current.error = ''
  try {
    if (current.kind === 'create-plan') {
      // 在当前上下文里创建：文件夹详情中建进该文件夹，否则建在根目录。
      const { entry } = await props.client.createPlanLibraryFile(props.projectId, name, openFolder.value)
      await reload()
      closeDialog()
      openEntry(entry)
      return
    }
    if (current.kind === 'create-folder') {
      // 建在当前这一层里；库根就是「方案/」本身。
      const path = openFolder.value ? `${openFolder.value}/${name}` : name
      await props.client.createPlanLibraryFolder(props.projectId, path)
      // 新文件夹建在当前层：切换回文件夹页，让这次操作当场看得见。
      activeTab.value = 'folders'
      await reload()
      closeDialog()
      return
    }
    if (current.kind === 'rename' && current.target) {
      const { entry } = await props.client.renamePlanLibraryFile(props.projectId, current.target.path, name)
      if (selected.value?.path === current.target.path || selected.value?.path === entry.path) selected.value = entry
      await reload()
      closeDialog()
      return
    }
  } catch (cause) {
    if (dialog.value) dialog.value.error = cause instanceof Error ? cause.message : String(cause)
  } finally {
    if (dialog.value) dialog.value.busy = false
  }
}

/* ---- 右键菜单 ---- */
function entryMenuItems(entry: PlanLibraryEntry): ContextMenuEntry[] {
  const moveChildren = [
    { id: 'move-root', label: '库根', disabled: !entry.folder, action: () => void moveEntry(entry, '') },
    ...folders.value.map(folder => ({
      id: `move-${folder.path}`,
      // 按层级缩进，嵌套时看得出目标在哪儿。
      label: `${'　'.repeat(folder.dir.split('/').length - 1)}${folder.name}`,
      disabled: entry.folder === folder.dir,
      action: () => void moveEntry(entry, folder.dir),
    })),
  ]
  return [
    {
      id: 'start',
      label: '开工',
      disabled: entry.status !== 'ready',
      action: () => emit('start-plan', entry),
    },
    { id: 'edit', label: '编辑', action: () => void openEditor(entry) },
    { type: 'separator' as const, id: 'sep-favorite' },
    {
      id: 'favorite',
      label: entry.favorite ? '从收藏移除' : '添加到收藏',
      action: () => void toggleFavorite(entry),
    },
    {
      id: 'move',
      type: 'submenu',
      label: '添加到文件夹',
      disabled: folders.value.length === 0,
      children: moveChildren,
    },
    { type: 'separator' as const, id: 'sep-danger' },
    { id: 'rename', label: '重命名', action: () => openDialog('rename', entry) },
    { id: 'delete', label: '删除', destructive: true, action: () => { pendingDelete.value = entry } },
  ]
}

async function moveEntry(entry: PlanLibraryEntry, folder: string): Promise<void> {
  if (!props.projectId) return
  error.value = ''
  try {
    const { entry: updated } = await props.client.movePlanLibraryFile(props.projectId, entry.path, folder)
    entries.value = entries.value.map(item => item.path === entry.path ? updated : item)
    await reload()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}

function openEntryMenu(event: MouseEvent, entry: PlanLibraryEntry): void {
  openContextMenu({
    event,
    items: entryMenuItems(entry),
    ownerId: `library-entry:${entry.path}`,
    ariaLabel: `${displayTitle(entry)} 的操作`,
    panelAttributes: { 'data-library-menu': entry.path },
  })
}

function openFolderMenu(event: MouseEvent, folder: CorePlanLibraryFolder): void {
  openContextMenu({
    event,
    items: [
      { id: 'open', label: '打开文件夹', action: () => goToFolder(folder.dir) },
      {
        id: 'new-subfolder',
        label: '在里面新建文件夹',
        action: () => { goToFolder(folder.dir); openDialog('create-folder') },
      },
      { type: 'separator' as const, id: 'sep' },
      {
        id: 'delete-folder',
        label: '删除文件夹',
        destructive: true,
        disabled: !isFolderEmpty(folder),
        action: () => void removeFolder(folder),
      },
    ],
    ownerId: `library-folder:${folder.path}`,
    ariaLabel: `${folder.name} 的操作`,
    panelAttributes: { 'data-library-folder-menu': folder.path },
  })
}

async function removeFolder(folder: CorePlanLibraryFolder): Promise<void> {
  if (!props.projectId) return
  error.value = ''
  try {
    await props.client.deletePlanLibraryFolder(props.projectId, folder.path)
    if (openFolder.value === folder.dir) openFolder.value = folder.parent
    await reload()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}

/* ---- 返回层级 ---- */
function handleBack(): boolean {
  if (mode.value === 'editor') {
    requestCloseEditor()
    return true
  }
  if (mode.value === 'reader') {
    mode.value = 'listing'
    if (readerFrom.value !== 'folder') openFolder.value = ''
    clearSelection()
    return true
  }
  if (openFolder.value) {
    // 逐层退回：先回上一层，最外层再退才是退出资料库。
    openFolder.value = openFolder.value.includes('/')
      ? openFolder.value.slice(0, openFolder.value.lastIndexOf('/'))
      : ''
    return true
  }
  return false
}
function onBackClick(): void {
  if (!handleBack()) emit('back')
}
defineExpose({ handleBack, isEditing: () => mode.value === 'editor' })

/* ---- 顶部条标题随子页变化 ---- */
const heading = computed(() => {
  const root = rootLabel.value
  if (mode.value === 'editor' && selected.value) {
    return { title: `${root} › 编辑 ${truncateTitle(displayTitle(selected.value))}`, subtitle: '' }
  }
  if (mode.value === 'reader' && selected.value) {
    return { title: `${root} › ${truncateTitle(displayTitle(selected.value))}`, subtitle: '' }
  }
  if (openFolder.value) {
    return { title: `${root} › ${folderTrail.value.map(step => step.name).join(' › ')}`, subtitle: '' }
  }
  return { title: root, subtitle: `「${dirName}」文件夹里的方案 — 点开读全文，就绪后开工。` }
})
watch(heading, (value) => emit('heading', { ...value }), { immediate: true })

/* ---- Esc：先关掉最上面那一层，都不在了才退出整版 ---- */
function onKeydown(event: KeyboardEvent): void {
  if (event.key !== 'Escape') return
  if (pendingDiscard.value) { pendingDiscard.value = false; return }
  if (pendingDelete.value) { pendingDelete.value = null; return }
  if (dialog.value) { closeDialog(); return }
  onBackClick()
}

watch(
  () => props.projectId,
  () => {
    mode.value = 'listing'
    openFolder.value = ''
    clearSelection()
    entries.value = []
    folders.value = []
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

<!-- 版面样式（工具栏 / 网格 / 阅读 / 编辑 / 对话框）见 styles/library-surface.css：
     资料库与记忆共用同一套配方，由根元素上的 .library-surface 承载。 -->

