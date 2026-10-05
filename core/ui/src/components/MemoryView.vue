<template>
  <div class="memory-view library-surface full-area-view" :aria-busy="loading">
    <FullAreaActions :to-band="bandActions">
      <!-- 编辑：写完为止，只留保存 / 取消 -->
      <template v-if="mode === 'editor' && selected">
        <button class="library-button" type="button" data-memory-editor-cancel @click="requestCloseEditor">取消</button>
        <button
          class="library-button library-button--primary"
          type="button"
          :disabled="saving || !dirty"
          data-memory-editor-save
          @click="saveEditor"
        >{{ saving ? '保存中…' : '保存' }}</button>
      </template>
      <template v-else-if="mode === 'reader' && selected">
        <button class="library-button" type="button" data-memory-edit @click="openEditor(selected)">编辑</button>
        <button
          class="library-button library-button--danger"
          type="button"
          :data-memory-delete="confirmingDelete ? 'confirm' : 'arm'"
          @click="removeSelected"
          @blur="confirmingDelete = false"
        >{{ confirmingDelete ? '确认删除' : '删除' }}</button>
      </template>
      <template v-else>
        <button class="icon-button" type="button" :disabled="loading" aria-label="刷新" title="刷新" data-memory-refresh @click="reload">
          <RefreshCw :size="14" :stroke-width="1.8" aria-hidden="true" />
        </button>
        <button class="library-button" type="button" :disabled="!canWrite" :title="canWrite ? '' : '先进入一个项目'" data-memory-create-folder @click="openDialog('create-folder')">新建文件夹</button>
        <button class="library-button library-button--primary" type="button" :disabled="!canWrite" :title="canWrite ? '' : '先进入一个项目'" data-memory-create-file @click="openDialog('create-file')">
          <Plus :size="14" :stroke-width="1.8" aria-hidden="true" />
          新建记忆
        </button>
      </template>
    </FullAreaActions>

    <div class="library-mobile-head">
      <button class="library-back" type="button" aria-label="返回" title="返回" @click="onBackClick">
        <ArrowLeft :size="16" :stroke-width="1.8" aria-hidden="true" />
      </button>
      <p v-if="mode !== 'listing' && selected" class="library-crumb" data-memory-crumb>
        {{ rootLabel }}<template v-if="activeProject"><span class="crumb-sep" aria-hidden="true">›</span>{{ activeProject.name }}</template><span class="crumb-sep" aria-hidden="true">›</span>{{ truncateTitle(selectedName) }}
      </p>
      <nav v-else-if="insideProject" class="library-crumb" data-memory-crumb aria-label="位置">
        <button type="button" class="crumb-link" @click="exitProject">{{ rootLabel }}</button>
        <span class="crumb-sep" aria-hidden="true">›</span>
        <button
          type="button"
          class="crumb-link"
          :class="{ 'crumb-link--current': !openFolder }"
          data-memory-crumb-project
          @click="goToFolder('')"
        >{{ activeProjectName }}</button>
        <template v-for="(step, index) in folderTrail" :key="step.dir">
          <span class="crumb-sep" aria-hidden="true">›</span>
          <button
            type="button"
            class="crumb-link"
            :class="{ 'crumb-link--current': index === folderTrail.length - 1 }"
            :data-memory-crumb-step="step.dir"
            @click="goToFolder(step.dir)"
          >{{ step.name }}</button>
        </template>
      </nav>
      <nav v-else-if="openFolder" class="library-crumb" data-memory-crumb aria-label="位置">
        <button type="button" class="crumb-link" @click="goToFolder('')">记忆</button>
        <template v-for="(step, index) in folderTrail" :key="step.dir">
          <span class="crumb-sep" aria-hidden="true">›</span>
          <button
            type="button"
            class="crumb-link"
            :class="{ 'crumb-link--current': index === folderTrail.length - 1 }"
            :data-memory-crumb-step="step.dir"
            @click="goToFolder(step.dir)"
          >{{ step.name }}</button>
        </template>
      </nav>
      <div v-else class="library-head-copy">
        <h1 class="library-title">记忆</h1>
        <p class="library-subtitle">{{ tierSubtitle }}</p>
      </div>
    </div>

    <!-- ── 阅读子页 ── -->
    <section v-if="mode === 'reader' && selected" class="library-reader" aria-label="记忆阅读" data-memory-reader>
      <header class="library-reader-head">
        <h2 class="library-reader-title">{{ selectedName }}</h2>
        <p class="library-reader-meta">
          <span>{{ selected.path }}</span>
          <span v-if="selected.modified">· {{ selected.modified }}</span>
        </p>
      </header>
      <p v-if="contentLoading" class="full-area-note" role="status">正在打开…</p>
      <p v-else-if="contentError" class="full-area-note full-area-note--error" role="alert">{{ contentError }}</p>
      <article v-else-if="selected.path.toLowerCase().endsWith('.md')" class="library-document">
        <MarkdownRenderer :content="content" />
      </article>
      <pre v-else class="library-document memory-plain" data-memory-plain>{{ content }}</pre>
    </section>

    <!-- ── 编辑子页：和资料库同一个编辑器 ── -->
    <section v-else-if="mode === 'editor' && selected" class="library-editor" aria-label="记忆编辑" data-memory-editor>
      <header class="library-editor-head">
        <h2 class="library-editor-title">{{ selectedName }}</h2>
        <p class="library-editor-meta">
          <span :class="dirty ? 'library-editor-state library-editor-state--dirty' : 'library-editor-state'" data-memory-editor-state>
            {{ dirty ? '未保存' : '已保存' }}
          </span>
          <span class="library-editor-path">{{ selected.path }}</span>
        </p>
      </header>
      <p v-if="editorLoading" class="full-area-note" role="status">正在打开…</p>
      <template v-else>
        <DocumentEditor ref="editorInput" id-prefix="memory-editor" :title="selectedName" v-model="draft">
          <template #preview="{ content }">
            <MarkdownRenderer v-if="selected?.path.toLowerCase().endsWith('.md')" :content="content" />
            <pre v-else class="memory-plain">{{ content }}</pre>
          </template>
        </DocumentEditor>
        <p v-if="saveError" class="full-area-note full-area-note--error" role="alert">{{ saveError }}</p>
      </template>
    </section>

    <template v-else>
      <!-- ── 工具栏：搜索 + 视图切换 ── -->
      <div class="library-toolbar" data-memory-toolbar>
        <div class="library-search">
          <Search :size="14" :stroke-width="1.8" aria-hidden="true" />
          <input
            v-model="query"
            type="search"
            :placeholder="atProjectLevel ? '搜索项目' : '搜索记忆'"
            :aria-label="atProjectLevel ? '搜索项目' : '搜索记忆'"
            data-memory-search
          />
        </div>
        <div v-if="!atProjectLevel" class="library-view-toggle" role="group" aria-label="视图切换" data-memory-view-toggle>
          <button type="button" :class="{ active: viewMode === 'grid' }" :aria-pressed="viewMode === 'grid'" aria-label="网格视图" title="网格视图" @click="viewMode = 'grid'"><LayoutGrid :size="14" :stroke-width="1.8" aria-hidden="true" /></button>
          <button type="button" :class="{ active: viewMode === 'list' }" :aria-pressed="viewMode === 'list'" aria-label="列表视图" title="列表视图" @click="viewMode = 'list'"><List :size="14" :stroke-width="1.8" aria-hidden="true" /></button>
        </div>
      </div>

      <!-- ── 两档：项目 / 全局 ── -->
      <div class="filter-tabs" role="group" aria-label="记忆档位" data-memory-tiers>
        <button type="button" :class="{ active: scope === 'project' }" :aria-pressed="scope === 'project'" data-memory-tier="project" @click="setScope('project')">项目记忆</button>
        <button type="button" :class="{ active: scope === 'global' }" :aria-pressed="scope === 'global'" data-memory-tier="global" @click="setScope('global')">全局记忆</button>
      </div>

      <!-- 手机没有 memory RPC：如实说明，不做半截界面。 -->
      <p v-if="viewNote" class="full-area-note" data-memory-note>{{ viewNote }}</p>

      <!-- ── 项目档第一层：先选是哪个项目 ── -->
      <template v-else-if="atProjectLevel">
        <p v-if="projectsLoading && !projects.length" class="full-area-note" role="status">正在读取项目…</p>
        <p v-else-if="projectsError" class="full-area-note full-area-note--error" role="alert" data-memory-project-error>
          {{ projectsError }}<button class="library-link" type="button" @click="reload">重试</button>
        </p>
        <div v-else-if="filteredProjects.length" class="folder-grid" role="list" data-memory-projects>
          <article
            v-for="project in filteredProjects"
            :key="project.id"
            class="folder-card"
            role="listitem"
            tabindex="0"
            :aria-label="`打开 ${project.name} 的项目记忆`"
            :data-memory-project="project.id"
            @click="enterProject(project)"
            @keydown.enter.prevent="enterProject(project)"
          >
            <span class="folder-card-icon" aria-hidden="true">
              <ProjectVisualIcon :icon-key="project.iconKey" :color-key="project.colorKey" :size="18" :icon-size="13" />
            </span>
            <span class="folder-card-name">{{ project.name }}</span>
          </article>
        </div>
        <div v-else class="full-area-empty" data-memory-no-projects>
          <span class="full-area-empty-icon" aria-hidden="true"><Folder :size="18" :stroke-width="1.8" /></span>
          <h2 class="full-area-empty-title">{{ projectsEmptyTitle }}</h2>
          <p class="full-area-empty-hint">{{ projectsEmptyHint }}</p>
        </div>
      </template>

      <template v-else>
        <p v-if="loading && !entries.length" class="full-area-note" role="status">正在读取记忆…</p>
        <p v-else-if="error" class="full-area-note full-area-note--error" role="alert">
          {{ error }}<button class="library-link" type="button" @click="reload">重试</button>
        </p>
        <template v-else>
        <!-- ── 子文件夹 ── -->
        <div v-if="childFolders.length" class="folder-grid" role="list" data-memory-folders>
          <article
            v-for="folder in childFolders"
            :key="folder.path"
            class="folder-card"
            role="listitem"
            tabindex="0"
            :aria-label="`打开文件夹 ${folder.name}`"
            :data-memory-folder="folder.path"
            @click="goToFolder(folder.path)"
            @keydown.enter.prevent="goToFolder(folder.path)"
            @contextmenu="openFolderMenu($event, folder)"
          >
            <span class="folder-card-icon" aria-hidden="true"><Folder :size="18" :stroke-width="1.6" /></span>
            <span class="folder-card-name">{{ folder.name }}</span>
            <span class="folder-card-count">{{ folder.count }} 个条目</span>
            <button class="card-menu-btn" type="button" :aria-label="`${folder.name} 的操作`" @click.stop="openFolderMenu($event, folder)">
              <MoreHorizontal :size="15" :stroke-width="1.8" aria-hidden="true" />
            </button>
          </article>
        </div>

        <!-- ── 空态 ── -->
        <div v-if="!childFolders.length && !listFiles.length" class="full-area-empty" data-memory-empty>
          <span class="full-area-empty-icon" aria-hidden="true"><BookOpen :size="18" :stroke-width="1.8" /></span>
          <h2 class="full-area-empty-title">{{ emptyTitle }}</h2>
          <p class="full-area-empty-hint">{{ emptyHint }}</p>
          <button class="library-button library-button--primary" type="button" data-memory-empty-create @click="openDialog('create-file')">新建记忆</button>
        </div>
        <p v-else-if="!listFiles.length" class="full-area-note tab-empty" data-memory-tab-empty>这个文件夹里还没有记忆文件。</p>

        <!-- ── 条目本体 ── -->
        <template v-if="listFiles.length">
          <div v-if="viewMode === 'grid'" class="plan-grid" role="list">
            <article
              v-for="file in listFiles"
              :key="file.path"
              class="plan-card"
              role="listitem"
              tabindex="0"
              :aria-label="`打开 ${file.name}`"
              :data-memory-entry="file.path"
              @click="openEntry(file)"
              @keydown.enter.prevent="openEntry(file)"
              @contextmenu="openEntryMenu($event, file)"
            >
              <div class="plan-card-preview">
                <p class="plan-card-summary">{{ file.summary || '还没有内容。' }}</p>
                <FileText :size="26" :stroke-width="1.4" aria-hidden="true" class="plan-card-glyph" />
              </div>
              <button class="card-menu-btn" type="button" :aria-label="`${file.name} 的操作`" @click.stop="openEntryMenu($event, file)">
                <MoreHorizontal :size="15" :stroke-width="1.8" aria-hidden="true" />
              </button>
              <h4 class="plan-card-title">{{ file.name }}</h4>
              <div class="plan-card-foot">
                <span class="plan-card-time">{{ file.modified }}</span>
              </div>
            </article>
          </div>

          <ul v-else class="library-items" role="list">
            <li v-for="file in listFiles" :key="file.path">
              <div
                class="library-row"
                role="button"
                tabindex="0"
                :data-memory-entry="file.path"
                @click="openEntry(file)"
                @keydown.enter.prevent="openEntry(file)"
                @contextmenu="openEntryMenu($event, file)"
              >
                <div class="library-item-top">
                  <span class="library-item-title">{{ file.name }}</span>
                </div>
                <div class="library-item-bottom">
                  <span class="library-item-summary">{{ file.summary || '（还没有内容）' }}</span>
                  <span class="library-item-time">{{ file.modified }}</span>
                </div>
                <button class="card-menu-btn" type="button" :aria-label="`${file.name} 的操作`" @click.stop="openEntryMenu($event, file)">
                  <MoreHorizontal :size="15" :stroke-width="1.8" aria-hidden="true" />
                </button>
              </div>
            </li>
          </ul>
        </template>
        </template>
      </template>
    </template>

    <!-- ── 新建 / 重命名对话框 ── -->
    <Transition name="library-dialog">
      <div v-if="dialog" class="dialog-dimmer" @click.self="closeDialog">
        <div class="dialog-card" role="dialog" aria-modal="true" :aria-label="dialogTitle" data-memory-dialog>
          <div class="dialog-body">
            <h3 class="dialog-title">{{ dialogTitle }}</h3>
            <label class="dialog-field">
              <span>{{ dialog.kind === 'create-folder' ? '文件夹名称' : '记忆名称' }}</span>
              <input
                ref="dialogInput"
                v-model="dialog.value"
                type="text"
                :placeholder="dialog.kind === 'create-folder' ? '例如：偏好' : '例如：用户偏好.md'"
                :data-memory-dialog-input="dialog.kind"
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
              data-memory-dialog-submit
              @click="submitDialog"
            >{{ dialog.busy ? '处理中…' : dialog.kind === 'rename' ? '重命名' : '创建' }}</button>
          </div>
        </div>
      </div>
    </Transition>

    <!-- ── 删除确认 ── -->
    <Transition name="library-dialog">
      <div v-if="pendingDelete" class="dialog-dimmer" @click.self="pendingDelete = null">
        <div class="dialog-card" role="dialog" aria-modal="true" aria-label="确认删除" data-memory-confirm>
          <div class="dialog-body">
            <h3 class="dialog-title">{{ pendingDelete.is_dir ? '删除文件夹' : '删除记忆' }}</h3>
            <p class="dialog-text">
              「{{ pendingDelete.name }}」将被删除{{ pendingDelete.is_dir ? '，里面的条目也会一起删掉' : '' }}，且无法恢复。
            </p>
          </div>
          <div class="dialog-actions">
            <button class="library-button" type="button" @click="pendingDelete = null">取消</button>
            <button class="library-button library-button--danger" type="button" data-memory-confirm-delete @click="confirmDelete">删除</button>
          </div>
        </div>
      </div>
    </Transition>

    <!-- ── 放弃未保存修改 ── -->
    <Transition name="library-dialog">
      <div v-if="pendingDiscard" class="dialog-dimmer" @click.self="pendingDiscard = false">
        <div class="dialog-card" role="dialog" aria-modal="true" aria-label="确认放弃修改" data-memory-discard>
          <div class="dialog-body">
            <h3 class="dialog-title">放弃修改</h3>
            <p class="dialog-text">「{{ selectedName }}」还有没保存的内容，离开就会丢掉。</p>
          </div>
          <div class="dialog-actions">
            <button class="library-button" type="button" @click="pendingDiscard = false">继续编辑</button>
            <button class="library-button library-button--danger" type="button" data-memory-discard-confirm @click="discardEditor">放弃修改</button>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
/**
 * MemoryView — the 记忆 as one full-area view, shaped like the 资料库.
 *
 * Memory is two directory tiers of plain files (project `<work_root>/.lam/memory/`,
 * global `<core config>/memory/`), already exposed over RPC as tree / read /
 * write / delete / rename / mkdir. This view is the browser for them: the same
 * toolbar, level-by-level folder walk, reader and editor the library uses —
 * which is why both render the shared `.library-surface` recipe.
 *
 * The project tier puts projects first: its opening level lists every project
 * (from the project client), and a project's files only appear once one is
 * entered — memory belongs to someone before it belongs to a folder. The
 * global tier has no such layer.
 *
 * `INDEX.md` is generated output and is never listed by the backend, so it
 * cannot be opened, edited or deleted from here either.
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
} from 'lucide-vue-next'
import type { CoreDurableRequest } from '../durable/api'
import type { CoreProjectClient } from '../projects/client'
import type { CoreProject } from '../projects/types'
import FullAreaActions from './FullAreaActions.vue'
import DocumentEditor from './DocumentEditor.vue'
import MarkdownRenderer from './MarkdownRenderer.vue'
import ProjectVisualIcon from './ProjectVisualIcon.vue'
import { openContextMenu, type ContextMenuEntry } from './context-menu'

/** One entry the memory RPC reports, path relative to its tier root. */
interface MemoryEntry {
  path: string
  is_dir: boolean
  size: number
  modified: string
  summary: string
}

/** A row the view works with: the entry plus the level it sits in. */
interface MemoryItem extends MemoryEntry {
  name: string
  /** The directory holding this entry ('' = the tier root) — files and folders alike. */
  dir: string
}

const props = defineProps<{
  /** The host's durable RPC bridge (memory.* is served by the backend). */
  requestRpc: CoreDurableRequest
  /** The project list — the project tier's first level is which project. */
  client?: CoreProjectClient | null
  /** Desktop sends actions into the header band; phones render them in place. */
  bandActions?: boolean
  /** Phones have no memory RPC, so the view explains instead of pretending. */
  platform?: string
  /** 顶部条标题的根名：在资料库里这项叫「记忆」。 */
  rootLabel?: string
}>()

const emit = defineEmits<{
  back: []
  /** 顶部条标题跟随内部子页。 */
  heading: [payload: { title: string; subtitle: string }]
}>()

const scope = ref<'project' | 'global'>('project')
const entries = ref<MemoryEntry[]>([])
const loading = ref(false)
const error = ref('')

/** 项目档第一层：项目清单与当前进入的项目。 */
const projects = ref<CoreProject[]>([])
const projectsLoading = ref(false)
const projectsError = ref('')
const activeProject = ref<CoreProject | null>(null)

const mode = ref<'listing' | 'reader' | 'editor'>('listing')
const openFolder = ref('')
const selected = ref<MemoryItem | null>(null)
const content = ref('')
const contentLoading = ref(false)
const contentError = ref('')
const confirmingDelete = ref(false)

const draft = ref('')
const editorBaseline = ref('')
const editorLoading = ref(false)
const saving = ref(false)
const saveError = ref('')
const pendingDiscard = ref(false)
const editorInput = ref<HTMLTextAreaElement | null>(null)
const dirty = computed(() => draft.value !== editorBaseline.value)

const query = ref('')
type ViewMode = 'grid' | 'list'
const VIEW_STORAGE_KEY = 'lamtools.core.memory.view'
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

type DialogKind = 'create-file' | 'create-folder' | 'rename'
const dialog = ref<{ kind: DialogKind; value: string; error: string; busy: boolean; target?: MemoryItem } | null>(null)
const dialogInput = ref<HTMLInputElement | null>(null)
const pendingDelete = ref<MemoryItem | null>(null)

const isMobile = computed(() => props.platform === 'mobile')
/** 项目档还没进入具体项目时，展示的是项目清单这一层。 */
const atProjectLevel = computed(() => scope.value === 'project' && !activeProject.value)
const insideProject = computed(() => scope.value === 'project' && Boolean(activeProject.value))
const activeProjectName = computed(() => activeProject.value?.name ?? '')
const viewNote = computed(() => (isMobile.value
  ? '手机端还没有接入记忆目录：在会话里让助手用记忆工具整理，或连上桌面端在这里浏览。'
  : ''))
const canWrite = computed(() => scope.value === 'global' || Boolean(activeProject.value))
const tierSubtitle = computed(() => {
  if (scope.value === 'global') return '跨项目共享的记忆 — 模型在会话里读它，你在这里整理它。'
  if (activeProject.value) return `只属于「${activeProject.value.name}」的记忆 — 模型在会话里读它，你在这里整理它。`
  return '项目记忆按项目归档 — 先选一个项目，再整理它的记忆。'
})

/** 项目清单层的搜索框过滤的是项目，不是文件。 */
const filteredProjects = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  return projects.value.filter(project => !keyword || project.name.toLowerCase().includes(keyword))
})
const projectsEmptyTitle = computed(() => (query.value.trim() ? '没有匹配的项目' : '还没有项目有记忆'))
const projectsEmptyHint = computed(() => (query.value.trim() ? '换个关键词再试。' : '在会话里让助手写下记忆，它就会出现在这里。'))

function parentOf(path: string): string {
  return path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : ''
}
function nameOf(path: string): string {
  return path.split('/').pop() || path
}

/** 一个条目所在的层：父目录。文件夹和文件用的是同一个键。 */
function locate(path: string): { name: string; dir: string } {
  return { name: nameOf(path), dir: parentOf(path) }
}

const items = computed<MemoryItem[]>(() => entries.value.map(entry => ({
  ...entry,
  ...locate(entry.path),
})))

/** 直接位于当前层的文件夹。 */
const childFolders = computed(() => items.value
  .filter(item => item.is_dir && item.dir === openFolder.value)
  .map(item => ({
    name: item.name,
    path: item.path,
    count: items.value.filter(other => !other.is_dir && other.path.startsWith(`${item.path}/`)).length,
  })))

const listFiles = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  return items.value
    .filter(item => !item.is_dir && item.dir === openFolder.value)
    .filter(item => !keyword
      || item.name.toLowerCase().includes(keyword)
      || item.summary.toLowerCase().includes(keyword))
})

const folderTrail = computed(() => {
  const parts = openFolder.value ? openFolder.value.split('/') : []
  return parts.map((name, index) => ({ name, dir: parts.slice(0, index + 1).join('/') }))
})

const selectedName = computed(() => selected.value?.name ?? '')
const rootLabel = computed(() => props.rootLabel || '记忆')

const emptyTitle = computed(() => (openFolder.value ? '这个文件夹还是空的' : '这片记忆还是空的'))
const emptyHint = computed(() => (openFolder.value
  ? '写点什么，助手下次就会读到它。'
  : '记忆就是普通文件：写在这里的，助手在之后的每个会话里都能读到。'))

function rpcParams(extra: Record<string, unknown> = {}): Record<string, unknown> {
  if (scope.value === 'global') return { scope: 'global', ...extra }
  const workRoot = activeProject.value?.workRoot
  return { scope: 'project', ...(workRoot ? { work_root: workRoot } : {}), ...extra }
}

async function rpc<T>(method: string, extra: Record<string, unknown> = {}): Promise<T> {
  if (scope.value === 'project' && !activeProject.value?.workRoot) {
    throw new Error('先进入一个项目，再操作它的记忆')
  }
  return await props.requestRpc(method, rpcParams(extra)) as T
}

async function loadProjects(): Promise<void> {
  if (isMobile.value) return
  projectsLoading.value = true
  projectsError.value = ''
  try {
    if (!props.client) throw new Error('项目列表不可用，无法进入项目记忆')
    const all = await props.client.list()
    // 只显示真正存有记忆的项目：后端纯探测，不建目录、不生成索引。
    const result = await props.requestRpc('memory.projects', {
      projects: all.map(project => ({ id: project.id, name: project.name, work_root: project.workRoot })),
    }) as { projects?: Array<{ id?: string }> }
    const withMemory = new Set((result.projects || []).map(project => String(project.id)))
    projects.value = all.filter(project => withMemory.has(project.id))
  } catch (cause) {
    projectsError.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    projectsLoading.value = false
  }
}

async function reload(): Promise<void> {
  if (isMobile.value) return
  if (atProjectLevel.value) {
    await loadProjects()
    return
  }
  if (insideProject.value && !activeProject.value?.workRoot) return
  loading.value = true
  error.value = ''
  try {
    const result = await rpc<{ entries?: MemoryEntry[] }>('memory.tree')
    entries.value = result.entries || []
    if (openFolder.value && !items.value.some(item => item.is_dir && item.path === openFolder.value)) {
      openFolder.value = ''
    }
    if (selected.value) {
      const fresh = items.value.find(item => item.path === selected.value?.path)
      if (fresh) selected.value = fresh
      else clearSelection()
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    loading.value = false
  }
}

function setScope(next: 'project' | 'global'): void {
  if (scope.value === next) return
  scope.value = next
  activeProject.value = null
  openFolder.value = ''
  query.value = ''
  mode.value = 'listing'
  clearSelection()
  entries.value = []
  error.value = ''
  projectsError.value = ''
  void reload()
}

/** 项目档第一层 → 第二层：进入某个项目的记忆。 */
function enterProject(project: CoreProject): void {
  if (activeProject.value?.id === project.id) return
  activeProject.value = project
  openFolder.value = ''
  query.value = ''
  mode.value = 'listing'
  clearSelection()
  entries.value = []
  error.value = ''
  void reload()
}

/** 退回项目清单这一层。 */
function exitProject(): void {
  if (!activeProject.value) return
  activeProject.value = null
  openFolder.value = ''
  query.value = ''
  mode.value = 'listing'
  clearSelection()
  entries.value = []
  error.value = ''
  void reload()
}

async function loadContent(): Promise<void> {
  const entry = selected.value
  if (!entry) return
  contentLoading.value = true
  contentError.value = ''
  try {
    const result = await rpc<{ content?: string }>('memory.read', { path: entry.path })
    content.value = result.content ?? ''
  } catch (cause) {
    contentError.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    contentLoading.value = false
  }
}

function openEntry(item: MemoryItem): void {
  confirmingDelete.value = false
  selected.value = item
  content.value = ''
  contentError.value = ''
  mode.value = 'reader'
  void loadContent()
}

async function openEditor(item: MemoryItem): Promise<void> {
  selected.value = item
  content.value = ''
  contentError.value = ''
  saveError.value = ''
  pendingDiscard.value = false
  mode.value = 'editor'
  draft.value = ''
  editorBaseline.value = ''
  editorLoading.value = true
  try {
    const result = await rpc<{ content?: string }>('memory.read', { path: item.path })
    content.value = result.content ?? ''
    draft.value = content.value
    editorBaseline.value = content.value
  } catch (cause) {
    saveError.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    editorLoading.value = false
    void nextTick(() => editorInput.value?.focus())
  }
}

async function saveEditor(): Promise<void> {
  const entry = selected.value
  if (!entry || saving.value || !dirty.value) return
  saving.value = true
  saveError.value = ''
  try {
    await rpc('memory.write', { path: entry.path, content: draft.value })
  } catch (cause) {
    saveError.value = cause instanceof Error ? cause.message : String(cause)
    return
  } finally {
    saving.value = false
  }
  content.value = draft.value
  editorBaseline.value = draft.value
  await reload()
  // 保存后回到阅读页：该看的是结果，而不是刚写完的原文。
  const fresh = items.value.find(item => item.path === entry.path)
  if (fresh) selected.value = fresh
  mode.value = 'reader'
}

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
  if (!entry) return
  if (!confirmingDelete.value) {
    confirmingDelete.value = true
    return
  }
  confirmingDelete.value = false
  await deleteItem(entry)
  clearSelection()
  mode.value = 'listing'
}

async function confirmDelete(): Promise<void> {
  const entry = pendingDelete.value
  pendingDelete.value = null
  if (!entry) return
  await deleteItem(entry)
}

async function deleteItem(entry: MemoryItem): Promise<void> {
  error.value = ''
  try {
    await rpc('memory.delete', { path: entry.path })
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
    return
  }
  if (selected.value?.path === entry.path) clearSelection()
  await reload()
}

const dialogTitle = computed(() => {
  if (!dialog.value) return ''
  if (dialog.value.kind === 'create-folder') return '新建文件夹'
  if (dialog.value.kind === 'rename') return '重命名'
  return '新建记忆'
})

function openDialog(kind: DialogKind, target?: MemoryItem): void {
  dialog.value = {
    kind,
    value: kind === 'rename' ? (target ? target.name : '') : '',
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
  if (!canWrite.value) {
    current.error = '先进入一个项目'
    return
  }
  const name = current.value.trim().replace(/^\/+|\/+$/g, '')
  if (!name || name.includes('/')) {
    current.error = '名称不能包含路径分隔符'
    return
  }
  const path = openFolder.value ? `${openFolder.value}/${name}` : name
  current.busy = true
  current.error = ''
  try {
    if (current.kind === 'create-folder') {
      await rpc('memory.mkdir', { path })
      await reload()
      closeDialog()
      return
    }
    if (current.kind === 'create-file') {
      const filePath = name.toLowerCase().endsWith('.md') ? path : `${path}.md`
      await rpc('memory.write', { path: filePath, content: '' })
      await reload()
      closeDialog()
      const created = items.value.find(item => item.path === filePath)
      if (created) await openEditor(created)
      return
    }
    if (current.kind === 'rename' && current.target) {
      const target = current.target
      const parent = target.dir
      const renamed = parent ? `${parent}/${name}` : name
      if (renamed !== target.path) await rpc('memory.rename', { path: target.path, new_path: renamed })
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

function openEntryMenu(event: MouseEvent, item: MemoryItem): void {
  openContextMenu({
    event,
    items: [
      { id: 'open', label: '打开', action: () => openEntry(item) },
      { id: 'edit', label: '编辑', action: () => void openEditor(item) },
      { type: 'separator' as const, id: 'sep' },
      { id: 'rename', label: '重命名', action: () => openDialog('rename', item) },
      { id: 'delete', label: '删除', destructive: true, action: () => { pendingDelete.value = item } },
    ],
    ownerId: `memory-entry:${item.path}`,
    ariaLabel: `${item.name} 的操作`,
    panelAttributes: { 'data-memory-menu': item.path },
  })
}

function openFolderMenu(event: MouseEvent, folder: { name: string; path: string; count: number }): void {
  openContextMenu({
    event,
    items: [
      { id: 'open', label: '打开文件夹', action: () => goToFolder(folder.path) },
      { id: 'new-file', label: '在里面新建记忆', action: () => { goToFolder(folder.path); openDialog('create-file') } },
      { id: 'new-folder', label: '在里面新建文件夹', action: () => { goToFolder(folder.path); openDialog('create-folder') } },
      { type: 'separator' as const, id: 'sep' },
      { id: 'rename', label: '重命名', action: () => openDialog('rename', folderItem(folder)) },
      {
        id: 'delete',
        label: folder.count > 0 ? '删除文件夹（含里面全部条目）' : '删除文件夹',
        destructive: true,
        action: () => { pendingDelete.value = folderItem(folder) },
      },
    ],
    ownerId: `memory-folder:${folder.path}`,
    ariaLabel: `${folder.name} 的操作`,
    panelAttributes: { 'data-memory-folder-menu': folder.path },
  })
}

function folderItem(folder: { name: string; path: string }): MemoryItem {
  return {
    path: folder.path,
    is_dir: true,
    size: 0,
    modified: '',
    summary: '',
    ...locate(folder.path),
  }
}

function goToFolder(dir: string): void {
  openFolder.value = dir
  query.value = ''
}

function truncateTitle(text: string): string {
  return text.length > 24 ? `${text.slice(0, 24)}…` : text
}

/* ---- 返回层级 ---- */
function handleBack(): boolean {
  if (mode.value === 'editor') {
    requestCloseEditor()
    return true
  }
  if (mode.value === 'reader') {
    mode.value = 'listing'
    clearSelection()
    return true
  }
  if (openFolder.value) {
    openFolder.value = openFolder.value.includes('/')
      ? openFolder.value.slice(0, openFolder.value.lastIndexOf('/'))
      : ''
    return true
  }
  if (insideProject.value) {
    exitProject()
    return true
  }
  return false
}
function onBackClick(): void {
  if (!handleBack()) emit('back')
}
defineExpose({ handleBack, isEditing: () => mode.value === 'editor' })

const heading = computed(() => {
  const root = rootLabel.value
  const project = activeProject.value ? `${activeProject.value.name} › ` : ''
  if (mode.value === 'editor' && selected.value) {
    return { title: `${root} › ${project}编辑 ${truncateTitle(selectedName.value)}`, subtitle: '' }
  }
  if (mode.value === 'reader' && selected.value) {
    return { title: `${root} › ${project}${truncateTitle(selectedName.value)}`, subtitle: '' }
  }
  if (openFolder.value) {
    return { title: `${root} › ${project}${folderTrail.value.map(step => step.name).join(' › ')}`, subtitle: '' }
  }
  if (activeProject.value) {
    return { title: `${root} › ${activeProject.value.name}`, subtitle: tierSubtitle.value }
  }
  return { title: root, subtitle: tierSubtitle.value }
})
watch(heading, (value) => emit('heading', { ...value }), { immediate: true })

function onKeydown(event: KeyboardEvent): void {
  if (event.key !== 'Escape') return
  if (pendingDiscard.value) { pendingDiscard.value = false; return }
  if (pendingDelete.value) { pendingDelete.value = null; return }
  if (dialog.value) { closeDialog(); return }
  onBackClick()
}

onMounted(() => {
  document.addEventListener('keydown', onKeydown)
  void reload()
})

onUnmounted(() => {
  document.removeEventListener('keydown', onKeydown)
})
</script>

<style scoped>
/* 版面样式共用 styles/library-surface.css；这里只放记忆独有的部分。 */
.memory-plain {
  margin: 0;
  padding: var(--space-3);
  border-radius: var(--radius);
  background: var(--theme-main-sunken-background, color-mix(in srgb, var(--text) 6%, transparent));
  font-family: var(--font-mono);
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
</style>
