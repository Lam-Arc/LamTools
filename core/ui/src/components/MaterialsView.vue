<template>
  <section
    class="materials-view"
    data-materials-view
    :aria-busy="loading"
    :style="{ '--library-zoom': String(zoom) }"
    @wheel="onZoomWheel"
  >
    <!-- ── 大标题 + 右侧一整条工具 ── -->
    <header class="materials-head">
      <h1 class="materials-title">资料库</h1>
      <div class="materials-tools">
        <button class="icon-button" type="button" :aria-label="sortLabel" :title="sortLabel" data-materials-sort @click="toggleSort">
          <ArrowDownWideNarrow :size="16" :stroke-width="1.8" aria-hidden="true" />
        </button>
        <div class="library-view-toggle" role="group" aria-label="视图切换" data-materials-view-toggle>
          <button type="button" :class="{ active: view === 'grid' }" :aria-pressed="view === 'grid'" aria-label="网格视图" title="网格视图" @click="view = 'grid'">
            <LayoutGrid :size="14" :stroke-width="1.8" aria-hidden="true" />
          </button>
          <button type="button" :class="{ active: view === 'list' }" :aria-pressed="view === 'list'" aria-label="列表视图" title="列表视图" @click="view = 'list'">
            <List :size="14" :stroke-width="1.8" aria-hidden="true" />
          </button>
        </div>
        <div class="library-search materials-search">
          <Search :size="14" :stroke-width="1.8" aria-hidden="true" />
          <input v-model="query" type="search" placeholder="搜索资料库" aria-label="搜索资料库" data-materials-search />
        </div>
        <button class="library-button library-button--primary materials-new" type="button" :disabled="!projectId || uploading" data-materials-new @click="uploadHere">
          <Plus :size="14" :stroke-width="1.8" aria-hidden="true" />
          {{ uploading ? '上传中…' : '新建' }}
        </button>
      </div>
    </header>

    <!-- ── 一句实话：有多少、占多大。没有配额体系，所以不做"已满/升级"。 ── -->
    <p class="materials-usage" data-materials-usage>
      {{ statsLine }}
    </p>

    <!-- 打开失败这类动作错误：就近提示，不顶掉整面墙。 -->
    <p v-if="actionError" class="full-area-note full-area-note--error" role="alert" data-materials-action-error>
      {{ actionError }}<button class="library-link" type="button" @click="actionError = ''">知道了</button>
    </p>

    <!-- ── 药丸筛选页签 ── -->
    <div class="filter-tabs" role="group" aria-label="筛选资料" data-materials-tabs>
      <button
        v-for="tab in TABS"
        :key="tab.id"
        type="button"
        :class="{ active: activeTab === tab.id }"
        :aria-pressed="activeTab === tab.id"
        :data-materials-tab="tab.id"
        @click="selectTab(tab.id)"
      >{{ tab.label }}</button>
    </div>

    <!-- ── 文件夹里：面包屑 + 这一层的内容 ── -->
    <nav v-if="openFolder" class="library-crumb materials-crumb" data-materials-crumb aria-label="位置">
      <button type="button" class="crumb-link" @click="goToFolder('')">资料库</button>
      <template v-for="(step, index) in folderTrail" :key="step.dir">
        <span class="crumb-sep" aria-hidden="true">›</span>
        <button
          type="button"
          class="crumb-link"
          :class="{ 'crumb-link--current': index === folderTrail.length - 1 }"
          :data-materials-crumb-step="step.dir"
          @click="goToFolder(step.dir)"
        >{{ step.name }}</button>
      </template>
    </nav>

    <!-- 层内：这一层下面的子层，一条可点的入口；数字同样是子层的直属文件数 -->
    <nav
      v-if="openFolder && activeTab === 'folders' && childFolders.length"
      class="folder-chips"
      data-materials-subfolders
      aria-label="子层"
    >
      <button
        v-for="folder in childFolders"
        :key="folder.path"
        type="button"
        class="folder-chip"
        :data-materials-subfolder="folder.path"
        @click="goToFolder(folder.path)"
      >
        <Folder :size="13" :stroke-width="1.7" aria-hidden="true" />
        <span class="folder-chip-name">{{ folder.name }}</span>
        <span class="folder-chip-count">{{ folder.count }}</span>
      </button>
    </nav>

    <p v-if="!projectId" class="full-area-note">先在左侧选择一个项目 — 资料库跟随项目。</p>
    <p v-else-if="loading && !items.length" class="full-area-note" role="status">正在读取资料库…</p>
    <p v-else-if="error" class="full-area-note full-area-note--error" role="alert">
      {{ error }}<button class="library-link" type="button" @click="reload">重试</button>
    </p>

    <template v-else>
      <!-- 文件夹页签：这一层有哪些归档 -->
      <div v-if="activeTab === 'folders' && !openFolder && childFolders.length" class="folder-grid" role="list" data-materials-folders>
        <article
          v-for="folder in childFolders"
          :key="folder.path"
          class="folder-card"
          role="listitem"
          tabindex="0"
          :aria-label="`打开文件夹 ${folder.name}`"
          :data-materials-folder="folder.path"
          @click="goToFolder(folder.path)"
          @keydown.enter.prevent="goToFolder(folder.path)"
        >
          <span class="folder-card-icon" aria-hidden="true"><Folder :size="18" :stroke-width="1.6" /></span>
          <span class="folder-card-name">{{ folder.name }}</span>
          <span class="folder-card-count">{{ folder.count }} 个文件</span>
        </article>
      </div>
      <p v-else-if="activeTab === 'folders' && !childFolders.length && !openFolder" class="full-area-note tab-empty" data-materials-folders-empty>
        还没有归档 — 在文件卡片的菜单里「归到文件夹」就会出现在这里。
      </p>

      <!-- 空态 -->
      <div v-else-if="!visible.length" class="full-area-empty" data-materials-empty>
        <span class="full-area-empty-icon" aria-hidden="true"><Folder :size="18" :stroke-width="1.8" /></span>
        <h2 class="full-area-empty-title">{{ openFolder ? '这一层还没有文件' : '资料库还是空的' }}</h2>
        <p class="full-area-empty-hint">助手产出的文件会自动出现在这里；你也可以直接上传文件进来。</p>
        <button class="library-button library-button--primary" type="button" data-materials-empty-upload @click="uploadHere">上传文件</button>
      </div>

      <!-- 卡片墙（网格 = 多列瀑布流，贴近参考图里的错落；列表 = 行式） -->
      <div v-else-if="view === 'grid'" class="materials-grid" role="list">
        <article
          v-for="item in visible"
          :key="item.artifact_id"
          class="material-card"
          :class="{ 'material-card--selected': selectedSet.has(item.artifact_id) }"
          role="listitem"
          tabindex="0"
          :aria-label="`打开 ${item.name}`"
          :data-material="item.artifact_id"
          @click="open(item)"
          @keydown.enter.prevent="open(item)"
          @contextmenu="openMenu($event, item)"
        >
          <div class="material-thumb" :data-kind="inferredKind(item.kind, item.name)">
            <img v-if="thumbs.get(item.artifact_id)" :src="thumbs.get(item.artifact_id)" :alt="item.name" loading="lazy" />
            <component v-else :is="kindIcon(item.kind, item.name)" :size="30" :stroke-width="1.5" aria-hidden="true" />
            <span class="library-status material-status" :data-artifact-status="artifactStatus(item)">{{ statusLabel(item) }}</span>
            <button
              class="material-check"
              type="button"
              :aria-label="selectedSet.has(item.artifact_id) ? `取消选择 ${item.name}` : `选择 ${item.name}`"
              :aria-pressed="selectedSet.has(item.artifact_id)"
              :data-material-check="item.artifact_id"
              @click.stop="toggleSelected(item.artifact_id)"
            ><Check v-if="selectedSet.has(item.artifact_id)" :size="12" :stroke-width="2.4" aria-hidden="true" /></button>
          </div>
          <button class="card-menu-btn" type="button" :aria-label="`${item.name} 的操作`" @click.stop="openMenu($event, item)">
            <MoreHorizontal :size="15" :stroke-width="1.8" aria-hidden="true" />
          </button>
          <h4 class="material-name" :title="displayPath(item) || item.name">{{ item.name }}</h4>
          <p class="material-meta">
            <button
              v-if="item.favorite"
              class="material-star"
              type="button"
              aria-label="取消收藏"
              data-material-star
              @click.stop="setFavorite(item, false)"
            ><Star :size="12" :stroke-width="1.8" aria-hidden="true" /></button>
            <span>修改于 {{ shortDate(item.updated_at) }}</span>
          </p>
        </article>
      </div>

      <ul v-else class="library-items" role="list">
        <li v-for="item in visible" :key="item.artifact_id">
          <div
            class="library-row"
            role="button"
            tabindex="0"
            :data-material="item.artifact_id"
            @click="open(item)"
            @keydown.enter.prevent="open(item)"
            @contextmenu="openMenu($event, item)"
          >
            <div class="library-item-top">
              <span class="library-item-title">{{ item.name }}</span>
              <Star v-if="item.favorite" :size="12" :stroke-width="1.8" aria-label="已收藏" class="plan-card-star" />
              <span class="library-status" :data-artifact-status="artifactStatus(item)">{{ statusLabel(item) }}</span>
            </div>
            <div class="library-item-bottom">
              <span class="library-item-summary">{{ kindLabel(item.kind, item.name) }} · {{ roleLabel(item.role) }}</span>
              <span class="library-item-time">修改于 {{ shortDate(item.updated_at) }}</span>
            </div>
            <button class="card-menu-btn" type="button" :aria-label="`${item.name} 的操作`" @click.stop="openMenu($event, item)">
              <MoreHorizontal :size="15" :stroke-width="1.8" aria-hidden="true" />
            </button>
          </div>
        </li>
      </ul>

      <!-- 选中若干件时的批量动作 -->
      <div v-if="selectedSet.size" class="materials-selection" data-materials-selection>
        <span>已选 {{ selectedSet.size }} 项</span>
        <button class="library-button" type="button" @click="clearSelection">取消</button>
        <button class="library-button" type="button" data-materials-favorite-selected @click="favoriteSelected(true)">收藏</button>
        <button class="library-button" type="button" @click="favoriteSelected(false)">取消收藏</button>
        <button class="library-button library-button--danger" type="button" data-materials-remove-selected @click="pendingRemove = selectedItems">移除</button>
      </div>
    </template>

    <!-- ── 移除确认：只改资料库状态，不删文件（沿用成果库既有语义） ── -->
    <Transition name="library-dialog">
      <div v-if="pendingRemove" class="dialog-dimmer" @click.self="pendingRemove = null">
        <div class="dialog-card" role="dialog" aria-modal="true" aria-label="确认移除" data-materials-confirm>
          <div class="dialog-body">
            <h3 class="dialog-title">从资料库移除</h3>
            <p class="dialog-text">
              将移除此处的 {{ pendingRemove.length }} 项；文件本身不会被删除。
            </p>
          </div>
          <div class="dialog-actions">
            <button class="library-button" type="button" @click="pendingRemove = null">取消</button>
            <button class="library-button library-button--danger" type="button" data-materials-confirm-remove @click="confirmRemove">移除</button>
          </div>
        </div>
      </div>
    </Transition>

    <CoreConfirmDialog
      :open="Boolean(pendingFolderName)"
      title="归到文件夹"
      input
      :input-value="folderNameDraft"
      input-placeholder="文件夹名"
      @cancel="pendingFolderName = null"
      @update:input-value="folderNameDraft = $event"
      @confirm="confirmFolderName"
    />
  </section>
</template>

<script setup lang="ts">
/**
 * MaterialsView — 资料库的「资料」分区：项目里进出的文件（用户 / 中间产物 / 产物）。
 *
 * 版式对标 ChatGPT 的资料库：大标题 + 右侧一整条工具、药丸筛选页签、卡片墙
 * （真实缩略图或类型图标、文件名、修改时间、⋯ 菜单、悬停勾选）、一句占用实话。
 * 取数与推导全部来自 artifacts/model.ts 与右栏成果库同一份判断，不另立一套。
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  ArrowDownWideNarrow,
  Check,
  Folder,
  LayoutGrid,
  List,
  MoreHorizontal,
  Plus,
  Search,
  Star,
} from 'lucide-vue-next'
import type { ProjectArtifact } from '../types'
import CoreConfirmDialog from './CoreConfirmDialog.vue'
import type { LamToolsTransport } from '../transport'
import { copyText } from '../helpers/clipboard'
import { useLibraryZoom } from '../composables/useLibraryZoom'
import { openContextMenu, type ContextMenuEntry } from './context-menu'
import {
  absoluteArtifactPath,
  artifactHttpPath,
  artifactStatus,
  extractArtifactRows,
  folderName,
  folderOf,
  folderParent,
  inferredKind,
  isArtifactSignal,
  isThumbnailable,
  kindIcon,
  kindLabel,
  mediaGroup,
  normalizeArtifact,
  roleLabel,
  statusLabel,
} from '../artifacts/model'

const props = defineProps<{
  projectId?: string | null
  transport?: LamToolsTransport
  requestRpc: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>
  /** 项目工作根：把 workspace:// 引用展开成磁盘上的绝对路径再给人看。 */
  workRoot?: string | null
  /** 最近一次工作台事件；成果相关的事件会触发一次安静刷新。 */
  artifactSignal?: unknown
  /** 上传文件到当前这一层（宿主负责选文件与传字节）。 */
  uploadFiles?: (folder: string) => Promise<void>
}>()

const TABS = [
  { id: 'all', label: '全部' },
  { id: 'image', label: '图片' },
  { id: 'document', label: '文档' },
  { id: 'spreadsheet', label: '表格' },
  { id: 'media', label: '音视频' },
  { id: 'favorite', label: '收藏' },
  { id: 'folders', label: '文件夹' },
] as const
type TabId = (typeof TABS)[number]['id']

const items = ref<ProjectArtifact[]>([])
const loading = ref(false)
const error = ref('')
const stats = ref<{ count: number; bytes: number }>({ count: 0, bytes: 0 })
const query = ref('')
const activeTab = ref<TabId>('all')
const view = ref<'grid' | 'list'>('grid')
const sort = ref<'updated' | 'name'>('updated')
const openFolder = ref('')
const selectedSet = ref<Set<string>>(new Set())
const pendingRemove = ref<ProjectArtifact[] | null>(null)
const uploading = ref(false)
const thumbs = ref<Map<string, string>>(new Map())
const actionError = ref('')
let fetchRevision = 0

/* ---- 卡片墙缩放：Ctrl+滚轮增减，资料与方案共用一档 ---- */
const { zoom, onZoomWheel } = useLibraryZoom()

const sortLabel = computed(() => (sort.value === 'updated' ? '按修改时间（新到旧）' : '按名称'))

function toggleSort(): void {
  sort.value = sort.value === 'updated' ? 'name' : 'updated'
}

/* ---- 取数 ---- */
async function reload(): Promise<void> {
  const projectId = props.projectId
  if (!projectId) {
    items.value = []
    stats.value = { count: 0, bytes: 0 }
    return
  }
  const revision = ++fetchRevision
  loading.value = true
  error.value = ''
  try {
    const [listed, counted] = await Promise.all([
      props.requestRpc('artifact.list', { project_id: projectId, include_deleted: false }),
      props.requestRpc('artifact.stats', { project_id: projectId }).catch(() => ({ count: 0, bytes: 0 })),
    ])
    if (revision !== fetchRevision) return
    items.value = extractArtifactRows(listed)
      .map(normalizeArtifact)
      .filter((item): item is ProjectArtifact => item !== null)
    const total = counted as { count?: number; bytes?: number }
    stats.value = { count: Number(total.count || 0), bytes: Number(total.bytes || 0) }
    if (openFolder.value && !folderExists(openFolder.value)) openFolder.value = ''
    void loadThumbs()
  } catch (cause) {
    if (revision !== fetchRevision) return
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    if (revision === fetchRevision) loading.value = false
  }
}

/* ---- 缩略图：只在有实体字节的图片上取一次，卸载时全部释放 ---- */
async function loadThumbs(): Promise<void> {
  const projectId = props.projectId
  const transport = props.transport
  if (!projectId || !transport) return
  for (const item of items.value) {
    if (!isThumbnailable(item) || thumbs.value.has(item.artifact_id)) continue
    const path = artifactHttpPath(projectId, item)
    if (!path) continue
    try {
      const response = await transport.request<{ status: number; headers: Record<string, string>; body: Uint8Array }>({
        kind: 'http', method: 'GET', path,
      })
      if (response.status < 200 || response.status >= 300) continue
      const url = URL.createObjectURL(new Blob([Uint8Array.from(response.body)], {
        type: response.headers['content-type'] || item.mime_type || 'application/octet-stream',
      }))
      const next = new Map(thumbs.value)
      next.set(item.artifact_id, url)
      thumbs.value = next
    } catch {
      // 取不到缩略图就退回类型图标，不让它挡住整面墙。
    }
  }
}

function releaseThumbs(): void {
  for (const url of thumbs.value.values()) URL.revokeObjectURL(url)
  thumbs.value = new Map()
}

onMounted(() => { void reload() })
onUnmounted(() => { releaseThumbs() })

watch(() => props.projectId, () => {
  openFolder.value = ''
  activeTab.value = 'all'
  selectedSet.value = new Set()
  releaseThumbs()
  void reload()
})

watch(() => props.artifactSignal, (signal) => {
  if (isArtifactSignal(signal)) void reload()
}, { deep: true })

/* ---- 筛选与排序 ---- */
const folders = computed(() => {
  const names = new Set<string>()
  for (const item of items.value) {
    const folder = folderOf(item)
    if (!folder) continue
    for (let index = 1; index <= folder.split('/').length; index += 1) {
      names.add(folder.split('/').slice(0, index).join('/'))
    }
  }
  return [...names].sort((left, right) => left.localeCompare(right))
})

const childFolders = computed(() => folders.value
  .filter(path => folderParent(path) === openFolder.value)
  .map(path => ({
    path,
    name: folderName(path),
    // Count only this layer's own files, exactly like the listing behind the
    // card: nested entries belong to the child layer's own card, and folding
    // them in here promises more files than opening the folder can show.
    count: items.value.filter(item => folderOf(item) === path).length,
  })))

const folderTrail = computed(() => {
  const parts = openFolder.value ? openFolder.value.split('/') : []
  return parts.map((name, index) => ({ name, dir: parts.slice(0, index + 1).join('/') }))
})

function folderExists(path: string): boolean {
  return folders.value.includes(path)
}

const visible = computed(() => {
  const keyword = query.value.trim().toLocaleLowerCase()
  const level = openFolder.value
  let list = items.value.filter(item => {
    if (item.deleted) return false
    const folder = folderOf(item)
    if (level) {
      // 在文件夹里看这一层：直属文件，不穿透到更深的层。
      if (folder !== level) return false
    } else if (activeTab.value === 'folders') {
      if (!folder) return false
    }
    return true
  })
  if (activeTab.value === 'favorite') list = list.filter(item => item.favorite)
  else if (activeTab.value !== 'all' && activeTab.value !== 'folders') {
    list = list.filter(item => mediaGroup(item) === activeTab.value)
  }
  if (keyword) {
    list = list.filter(item => [item.name, item.path, item.uri, kindLabel(item.kind, item.name), roleLabel(item.role)]
      .filter(Boolean).join(' ').toLocaleLowerCase().includes(keyword))
  }
  return [...list].sort((left, right) => {
    if (sort.value === 'name') return left.name.localeCompare(right.name)
    return String(right.updated_at || '').localeCompare(String(left.updated_at || ''))
  })
})

const statsLine = computed(() => {
  const count = stats.value.count
  const label = `${count} 个文件 · ${formatBytes(stats.value.bytes)}`
  return count ? label : '资料库还是空的'
})

function formatBytes(bytes: number): string {
  if (!bytes || bytes < 0) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
}

function shortDate(value?: string): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const pad = (n: number): string => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

/* ---- 导航与动作 ---- */
function selectTab(tab: TabId): void {
  activeTab.value = tab
  if (tab !== 'folders') openFolder.value = ''
}

function goToFolder(dir: string): void {
  openFolder.value = dir
  activeTab.value = 'folders'
}

function open(item: ProjectArtifact): void {
  void openWithSystem(item)
}

/** 引用给人看的形态：workspace:// 展开成磁盘绝对路径，其余原样。 */
function displayPath(item: ProjectArtifact): string {
  return absoluteArtifactPath(item, props.workRoot)
}

/**
 * 打开文件 = 交给系统默认应用。工作区文件走成果打开通道（文件不在了会明确报错），
 * 上传原件走附件打开通道；两处失败都落在视图的错误行上，不再是无声的失败。
 */
async function openWithSystem(item: ProjectArtifact): Promise<void> {
  actionError.value = ''
  const reference = item.path || item.uri || ''
  try {
    if (reference.startsWith('attachment://')) {
      const attachmentId = reference.slice('attachment://'.length)
      const response = await props.transport?.request<{ status: number; body: Uint8Array }>({
        kind: 'http', method: 'POST', path: `/attachments/${encodeURIComponent(attachmentId)}/open`,
      })
      if (response && (response.status < 200 || response.status >= 300)) {
        throw new Error(new TextDecoder().decode(Uint8Array.from(response.body)) || `HTTP ${response.status}`)
      }
    } else {
      await props.requestRpc('artifact.open', {
        project_id: props.projectId,
        artifact_id: item.artifact_id,
        path: reference,
      })
    }
  } catch (cause) {
    actionError.value = cause instanceof Error ? cause.message : String(cause)
  }
}

function toggleSelected(id: string): void {
  const next = new Set(selectedSet.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selectedSet.value = next
}

function clearSelection(): void {
  selectedSet.value = new Set()
}

const selectedItems = computed(() => items.value.filter(item => selectedSet.value.has(item.artifact_id)))

async function patch(item: ProjectArtifact, method: string, params: Record<string, unknown>): Promise<void> {
  error.value = ''
  try {
    const result = await props.requestRpc(method, { project_id: props.projectId, artifact_id: item.artifact_id, ...params })
    const fresh = normalizeArtifact((result as { artifact?: unknown }).artifact)
    if (fresh) items.value = items.value.map(entry => entry.artifact_id === fresh.artifact_id ? fresh : entry)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}

async function setFavorite(item: ProjectArtifact, favorite: boolean): Promise<void> {
  await patch(item, 'artifact.favorite', { favorite })
}

async function favoriteSelected(favorite: boolean): Promise<void> {
  for (const item of selectedItems.value) {
    if (item.favorite === favorite) continue
    await patch(item, 'artifact.favorite', { favorite })
  }
  clearSelection()
}

/** 新建归档文件夹：应用内输入胶囊替代系统输入框。 */
const pendingFolderName = ref<ProjectArtifact | null>(null)
const folderNameDraft = ref('')

async function confirmFolderName(): Promise<void> {
  const item = pendingFolderName.value
  pendingFolderName.value = null
  const cleaned = folderNameDraft.value.trim().replace(/^\/+|\/+$/g, '')
  if (item && cleaned) await moveToFolder(item, cleaned)
}

async function moveToFolder(item: ProjectArtifact, folder: string): Promise<void> {
  await patch(item, 'artifact.folder', { folder })
}

async function confirmRemove(): Promise<void> {
  const victims = pendingRemove.value || []
  pendingRemove.value = null
  if (!victims.length) return
  error.value = ''
  try {
    await props.requestRpc('artifact.delete', {
      project_id: props.projectId,
      artifact_ids: victims.map(item => item.artifact_id),
    })
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
    return
  }
  clearSelection()
  await reload()
}

async function uploadHere(): Promise<void> {
  if (!props.uploadFiles || uploading.value) return
  uploading.value = true
  error.value = ''
  try {
    await props.uploadFiles(openFolder.value)
    await reload()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    uploading.value = false
  }
}

function openMenu(event: MouseEvent, item: ProjectArtifact): void {
  const children: ContextMenuEntry[] = [
    { id: 'folder-root', label: '不归档', disabled: !folderOf(item), action: () => void moveToFolder(item, '') },
    ...folders.value.map(folder => ({
      id: `folder-${folder}`,
      label: `　`.repeat(folder.split('/').length - 1) + folderName(folder),
      disabled: folderOf(item) === folder,
      action: () => void moveToFolder(item, folder),
    })),
    {
      id: 'folder-new',
      label: '新建文件夹…',
      action: () => {
        folderNameDraft.value = ''
        pendingFolderName.value = item
      },
    },
  ]
  openContextMenu({
    event,
    items: [
      { id: 'open', label: '打开', action: () => void openWithSystem(item) },
      {
        id: 'favorite',
        label: item.favorite ? '取消收藏' : '添加到收藏',
        action: () => void setFavorite(item, !item.favorite),
      },
      { id: 'folder', type: 'submenu', label: '归到文件夹', children },
      { type: 'separator' as const, id: 'sep-copy' },
      { id: 'copy', label: '复制路径', action: () => void copyText(displayPath(item)) },
      { type: 'separator' as const, id: 'sep-danger' },
      { id: 'remove', label: '从资料库移除', destructive: true, action: () => { pendingRemove.value = [item] } },
    ],
    ownerId: `material:${item.artifact_id}`,
    ariaLabel: `${item.name} 的操作`,
    panelAttributes: { 'data-materials-menu': item.artifact_id },
  })
}
</script>
