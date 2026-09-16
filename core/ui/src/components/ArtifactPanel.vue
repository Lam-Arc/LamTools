<template>
  <section class="artifact-panel" data-artifact-library aria-label="项目成果库">
    <header class="artifact-panel-head">
      <div class="artifact-panel-title">
        <strong>成果库</strong>
        <span class="artifact-panel-count">{{ visibleArtifacts.length }} / {{ roleArtifacts.length }}</span>
      </div>
      <div class="artifact-actions">
        <button
          v-if="!cleanupMode"
          class="text-btn danger"
          type="button"
          title="勾选后从成果库移除"
          @click="enterCleanup"
        >移除</button>
        <template v-else>
          <button
            class="text-btn danger"
            type="button"
            :disabled="!selected.length"
            @click="removeSelected"
          >从成果库移除 ({{ selected.length }})</button>
          <button class="text-btn" type="button" @click="exitCleanup">取消</button>
        </template>
        <button class="text-btn" type="button" title="刷新成果库" aria-label="刷新成果库" @click="fetchArtifacts">
          <RefreshCw :size="14" :stroke-width="1.8" aria-hidden="true" />
        </button>
      </div>
    </header>

    <div class="artifact-search-row">
      <Search :size="14" :stroke-width="1.8" aria-hidden="true" />
      <input
        v-model="searchText"
        class="artifact-search"
        type="search"
        placeholder="搜索名称、路径或来源…"
        aria-label="搜索成果库"
      />
      <button
        v-if="searchText"
        type="button"
        class="artifact-search-clear"
        aria-label="清除搜索"
        @click="searchText = ''"
      >×</button>
    </div>

    <div class="artifact-filters" aria-label="成果筛选">
      <UiSelect
        :model-value="roleFilter"
        :options="roleOptions"
        aria-label="按角色筛选"
        @update:model-value="roleFilter = $event"
      />
      <UiSelect
        :model-value="kindFilter"
        :options="kindOptions"
        aria-label="按类型筛选"
        @update:model-value="kindFilter = $event"
      />
      <UiSelect
        :model-value="statusFilter"
        :options="statusOptions"
        aria-label="按状态筛选"
        @update:model-value="statusFilter = $event"
      />
      <button
        class="artifact-removed-toggle"
        :class="{ active: showRemoved }"
        type="button"
        :aria-pressed="showRemoved"
        @click="showRemoved = !showRemoved"
      >{{ showRemoved ? '隐藏已移除' : '显示已移除' }}</button>
    </div>

    <p class="artifact-panel-hint">仅展示输入、处理中间产物与可交付成果。移除只改变成果库状态，不删除文件。</p>
    <p v-if="error" class="artifact-error" role="alert">{{ error }}</p>

    <div v-if="loading" class="artifact-state" data-state="loading" role="status" aria-live="polite">
      <LoaderCircle class="artifact-state-spinner" :size="15" :stroke-width="1.8" aria-hidden="true" />
      <span>正在加载成果库…</span>
    </div>
    <div v-else-if="!projectId" class="artifact-state" data-state="empty">
      选择项目后查看成果库。
    </div>
    <div v-else-if="!visibleArtifacts.length" class="artifact-state" data-state="empty">
      {{ showRemoved ? '暂无已移除的成果。' : '暂无符合筛选条件的成果。' }}
    </div>

    <ul v-else class="artifact-list" aria-label="成果列表">
      <li
        v-for="item in visibleArtifacts"
        :key="item.artifact_id"
        class="artifact-item"
        :class="{
          'artifact-item--selected': selectedArtifact?.artifact_id === item.artifact_id,
          'artifact-item--deleted': item.deleted,
          'artifact-item--missing': item.missing,
        }"
        :data-artifact-id="item.artifact_id"
        :data-role="item.role"
        :data-status="artifactStatus(item)"
        @contextmenu="onArtifactContextMenu($event, item)"
      >
        <button
          class="artifact-item-main"
          type="button"
          :aria-label="`${item.deleted ? '已移除' : '打开'} ${item.name}`"
          @click="openArtifactInStage(item)"
        >
          <span class="artifact-kind" :title="kindLabel(item.kind)">
            <component :is="kindIcon(item.kind, item.name)" :size="14" :stroke-width="1.8" aria-hidden="true" />
          </span>
          <span class="artifact-item-copy">
            <span class="artifact-name" :title="item.path || item.uri || item.name">{{ item.name }}</span>
            <span class="artifact-item-meta">
              {{ roleLabel(item.role) }} · {{ kindLabel(item.kind, item.name) }} · {{ revisionCount(item) }} 个版本
            </span>
          </span>
          <span class="artifact-status" :data-status="artifactStatus(item)">{{ statusLabel(item) }}</span>
        </button>

        <div class="artifact-item-actions">
          <label v-if="cleanupMode" class="artifact-check" @click.stop>
            <input
              type="checkbox"
              :checked="selectedSet.has(item.artifact_id)"
              :aria-label="`选择 ${item.name}`"
              @change="toggleSelected(item.artifact_id)"
            />
          </label>
          <button
            type="button"
            class="artifact-icon-button"
            :aria-expanded="selectedArtifact?.artifact_id === item.artifact_id"
            :aria-label="`${selectedArtifact?.artifact_id === item.artifact_id ? '收起' : '查看'} ${item.name} 详情`"
            title="详情"
            @click.stop="toggleDetails(item)"
          >
            <Info :size="14" :stroke-width="1.8" aria-hidden="true" />
          </button>
          <button
            type="button"
            class="artifact-icon-button"
            :aria-expanded="historyArtifactId === item.artifact_id"
            :aria-label="`查看 ${item.name} 的版本历史`"
            title="版本历史"
            @click.stop="toggleHistory(item)"
          >
            <History :size="14" :stroke-width="1.8" aria-hidden="true" />
          </button>
          <button
            v-if="item.deleted"
            type="button"
            class="artifact-icon-button artifact-icon-button--restore"
            :aria-label="`恢复 ${item.name}`"
            title="恢复到成果库"
            @click.stop="restoreArtifact(item)"
          >
            <RotateCcw :size="14" :stroke-width="1.8" aria-hidden="true" />
          </button>
          <button
            v-else
            type="button"
            class="artifact-icon-button artifact-icon-button--danger"
            :aria-label="`从成果库移除 ${item.name}`"
            title="从成果库移除"
            @click.stop="removeArtifact(item)"
          >
            <Trash2 :size="14" :stroke-width="1.8" aria-hidden="true" />
          </button>
        </div>
      </li>
    </ul>

    <section v-if="selectedArtifact" class="artifact-detail" :aria-label="`${selectedArtifact.name} 详情`">
      <header class="artifact-detail-head">
        <div>
          <strong>{{ selectedArtifact.name }}</strong>
          <span>{{ provenanceLabel(selectedArtifact) }}</span>
        </div>
        <button type="button" class="artifact-open-button" @click="openArtifactInStage(selectedArtifact)">
          <ExternalLink :size="13" :stroke-width="1.8" aria-hidden="true" />
          打开视窗
        </button>
      </header>
      <dl class="artifact-meta">
        <dt>角色</dt><dd>{{ roleLabel(selectedArtifact.role) }}</dd>
        <dt>类型</dt><dd>{{ kindLabel(selectedArtifact.kind, selectedArtifact.name) }}</dd>
        <dt>状态</dt><dd>{{ statusLabel(selectedArtifact) }}</dd>
        <dt>来源</dt><dd>{{ provenanceLabel(selectedArtifact) }}</dd>
        <dt>版本</dt><dd>{{ revisionCount(selectedArtifact) }} 个版本</dd>
        <template v-if="selectedArtifact.thread_id || selectedArtifact.turn_id || selectedArtifact.item_id">
          <dt>运行链路</dt>
          <dd>{{ [selectedArtifact.thread_id, selectedArtifact.turn_id, selectedArtifact.item_id].filter(Boolean).join(' · ') }}</dd>
        </template>
        <template v-if="selectedArtifact.path || selectedArtifact.uri">
          <dt>路径</dt><dd :title="selectedArtifact.path || selectedArtifact.uri">{{ selectedArtifact.path || selectedArtifact.uri }}</dd>
        </template>
      </dl>
    </section>

    <section v-if="historyArtifactId" class="artifact-history" aria-label="版本历史">
      <header class="artifact-history-head">
        <strong>版本历史</strong>
        <button type="button" class="artifact-icon-button" aria-label="关闭版本历史" @click="historyArtifactId = ''">×</button>
      </header>
      <div v-if="historyLoading" class="artifact-history-state" role="status">正在加载版本…</div>
      <div v-else-if="historyError" class="artifact-history-state artifact-history-state--error" role="alert">{{ historyError }}</div>
      <div v-else-if="!historyRows.length" class="artifact-history-state">暂无版本记录。</div>
      <ol v-else class="artifact-revision-list">
        <li v-for="revision in historyRows" :key="revisionKey(revision)" class="artifact-revision">
          <div class="artifact-revision-copy">
            <strong>{{ revisionLabel(revision) }}</strong>
            <span>{{ formatTime(revision.created_at || revision.updated_at || '') }} · {{ revisionStatusLabel(revision) }}</span>
          </div>
          <div class="artifact-revision-actions">
            <button type="button" class="artifact-revision-open" @click="openArtifactInStage(historyArtifact!, revision)">打开</button>
            <button
              v-if="!isLatestRevision(historyArtifact!, revision)"
              type="button"
              class="artifact-revision-restore"
              @click="restoreRevision(historyArtifact!, revision)"
            >恢复</button>
            <span v-else class="artifact-revision-latest">当前</span>
          </div>
        </li>
      </ol>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  Copy,
  ExternalLink,
  File,
  FileCode2,
  FileSpreadsheet,
  FileText,
  Film,
  History,
  Image as ImageIcon,
  Info,
  LoaderCircle,
  Music,
  Package,
  Presentation,
  RefreshCw,
  RotateCcw,
  Search,
  Trash2,
  type LucideIcon,
} from 'lucide-vue-next'
import type { ArtifactRevision, ArtifactRole, ProjectArtifact } from '../types'
import type { LamToolsTransport } from '../transport'
import { copyText } from '../helpers/clipboard'
import { isNativeContextTarget, openContextMenu } from './context-menu/context-menu'
import UiSelect from './UiSelect.vue'

const props = withDefaults(defineProps<{
  projectId: string | null
  transport?: LamToolsTransport
  requestRpc: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>
  /** Last workbench event; artifact-bearing events trigger a quiet refresh. */
  artifactSignal?: unknown
  /** Optional host callback that owns StagePane tabs and preview bytes. */
  openArtifact?: (artifact: ProjectArtifact, revision?: ArtifactRevision) => void | Promise<void>
}>(), {
  transport: undefined,
  openArtifact: undefined,
})

const emit = defineEmits<{
  'open-artifact': [artifact: ProjectArtifact, revision?: ArtifactRevision]
}>()

const ROLE_VALUES: ArtifactRole[] = ['input', 'intermediate', 'deliverable']
const artifacts = ref<ProjectArtifact[]>([])
const loading = ref(false)
const error = ref('')
const searchText = ref('')
const roleFilter = ref('all')
const kindFilter = ref('all')
const statusFilter = ref('all')
const showRemoved = ref(false)
const cleanupMode = ref(false)
const selectedSet = ref<Set<string>>(new Set())
const selectedArtifact = ref<ProjectArtifact | null>(null)
const historyArtifactId = ref('')
const historyLoading = ref(false)
const historyError = ref('')
const historyRowsById = ref<Record<string, ArtifactRevision[]>>({})
let fetchRevision = 0

const roleOptions = [
  { value: 'all', label: '全部角色' },
  { value: 'input', label: '输入' },
  { value: 'intermediate', label: '中间产物' },
  { value: 'deliverable', label: '可交付' },
]
const kindOptions = computed(() => [
  { value: 'all', label: '全部类型' },
  ...Array.from(new Set(artifacts.value.map(item => item.kind).filter(Boolean))).sort().map(kind => ({
    value: kind,
    label: kindLabel(kind),
  })),
])
const statusOptions = [
  { value: 'all', label: '全部状态' },
  { value: 'ready', label: '就绪' },
  { value: 'running', label: '处理中' },
  { value: 'completed', label: '已完成' },
  { value: 'failed', label: '失败' },
  { value: 'missing', label: '文件缺失' },
  { value: 'deleted', label: '已移除' },
]

const roleArtifacts = computed(() => artifacts.value.filter(item => ROLE_VALUES.includes(item.role as ArtifactRole)))
const visibleArtifacts = computed(() => {
  const query = searchText.value.trim().toLocaleLowerCase()
  return roleArtifacts.value.filter(item => {
    if (showRemoved.value ? !item.deleted : item.deleted) return false
    if (roleFilter.value !== 'all' && item.role !== roleFilter.value) return false
    if (kindFilter.value !== 'all' && item.kind !== kindFilter.value) return false
    if (statusFilter.value !== 'all' && artifactStatus(item) !== statusFilter.value) return false
    if (!query) return true
    const searchable = [
      item.name,
      item.path,
      item.uri,
      item.kind,
      item.role,
      item.source,
      provenanceLabel(item),
    ].filter(Boolean).join(' ').toLocaleLowerCase()
    return searchable.includes(query)
  })
})
const selected = computed(() => Array.from(selectedSet.value))
const historyArtifact = computed(() => artifacts.value.find(item => item.artifact_id === historyArtifactId.value) || null)
const historyRows = computed(() => historyArtifact.value ? (
  historyRowsById.value[historyArtifact.value.artifact_id]
    || historyArtifact.value.revisions
    || []
) : [])

const KIND_ICONS: Record<string, LucideIcon> = {
  image: ImageIcon,
  video: Film,
  audio: Music,
  pdf: FileText,
  document: File,
  code: FileCode2,
  spreadsheet: FileSpreadsheet,
  presentation: Presentation,
  file: Package,
  file_change: FileText,
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value : value == null ? '' : String(value)
}

function roleFor(raw: Record<string, unknown>): ArtifactRole {
  const explicit = stringValue(raw.role || asRecord(raw.metadata)?.role)
  if (ROLE_VALUES.includes(explicit as ArtifactRole)) return explicit as ArtifactRole
  const source = stringValue(raw.source || asRecord(raw.metadata)?.source).toLowerCase()
  if (source === 'user_upload' || source === 'user' || source === 'input') return 'input'
  if (source === 'agent_generated' || source === 'agent' || source === 'generated') return 'deliverable'
  if (stringValue(raw.kind) === 'file_change') return 'deliverable'
  return ''
}

function normalizeArtifact(value: unknown): ProjectArtifact | null {
  const raw = asRecord(value)
  if (!raw) return null
  const metadata = asRecord(raw.metadata) || {}
  const artifactId = stringValue(raw.artifact_id || raw.id)
  if (!artifactId) return null
  const path = stringValue(raw.path || raw.uri || metadata.path)
  const deleted = raw.deleted === true
  const availability = stringValue(raw.availability || metadata.availability).toLowerCase()
  // Artifact V2 uses metadata_only when the durable manifest exists but no
  // content blob could be captured. Surface that as the panel's missing-file
  // state so it cannot appear deceptively ready/openable.
  const missing = raw.missing === true || availability === 'missing' || availability === 'metadata_only'
  const role = roleFor(raw)
  if (!ROLE_VALUES.includes(role as ArtifactRole)) return null
  const revisions = Array.isArray(raw.revisions)
    ? raw.revisions.flatMap(item => asRecord(item) ? [item as ArtifactRevision] : [])
    : undefined
  const revisionCount = Number(raw.revision_count ?? metadata.revision_count ?? revisions?.length ?? 1)
  return {
    ...raw,
    artifact_id: artifactId,
    name: stringValue(raw.name || metadata.name || path.split(/[\\/]/).pop() || artifactId),
    kind: stringValue(raw.kind || metadata.kind || 'file'),
    mime_type: stringValue(raw.mime_type || metadata.mime_type),
    path,
    uri: stringValue(raw.uri),
    role,
    status: stringValue(raw.status || metadata.status) || undefined,
    source: stringValue(raw.source || metadata.source),
    provenance: raw.provenance ?? metadata.provenance,
    availability: availability || undefined,
    created_at: stringValue(raw.created_at || metadata.created_at),
    updated_at: stringValue(raw.updated_at || metadata.updated_at),
    latest_revision_id: stringValue(raw.latest_revision_id || metadata.latest_revision_id),
    revision_count: Number.isFinite(revisionCount) && revisionCount > 0 ? revisionCount : 1,
    ...(revisions ? { revisions } : {}),
    thread_id: stringValue(raw.thread_id || metadata.thread_id),
    turn_id: stringValue(raw.turn_id || metadata.turn_id),
    item_id: stringValue(raw.item_id || metadata.item_id),
    missing,
    deleted,
  }
}

function extractArtifactRows(result: Record<string, unknown>): unknown[] {
  if (Array.isArray(result.artifacts)) return result.artifacts
  if (Array.isArray(result.items)) return result.items
  const data = asRecord(result.data)
  if (data && Array.isArray(data.artifacts)) return data.artifacts
  return []
}

function extractRevisionRows(result: Record<string, unknown>): ArtifactRevision[] {
  const artifact = asRecord(result.artifact)
  const values = Array.isArray(result.revisions)
    ? result.revisions
    : Array.isArray(result.history)
      ? result.history
      : artifact && Array.isArray(artifact.revisions)
        ? artifact.revisions
        : []
  return values.flatMap(value => asRecord(value) ? [value as ArtifactRevision] : [])
}

function inferredKind(kind: string, name = ''): string {
  if (!['file', 'document', 'file_change'].includes(kind)) return kind
  const ext = name.split('.').pop()?.toLowerCase() || ''
  if (['xlsx', 'xls', 'ods', 'csv', 'tsv'].includes(ext)) return 'spreadsheet'
  if (['pptx', 'ppt', 'odp'].includes(ext)) return 'presentation'
  if (['ts', 'tsx', 'js', 'jsx', 'vue', 'py', 'rs', 'go', 'java', 'c', 'cpp', 'h', 'hpp', 'cs', 'rb', 'php', 'sh', 'ps1', 'sql', 'html', 'css', 'scss', 'json', 'jsonc', 'yaml', 'yml', 'toml', 'xml'].includes(ext)) return 'code'
  return kind
}

function kindIcon(kind: string, name = ''): LucideIcon {
  return KIND_ICONS[inferredKind(kind, name)] || File
}

function kindLabel(kind: string, name = ''): string {
  const resolved = inferredKind(kind, name)
  return ({ image: '图片', video: '视频', audio: '音频', pdf: 'PDF', document: '文档', code: '代码', spreadsheet: '表格', presentation: '演示文稿', file: '文件', file_change: '文件改动' } as Record<string, string>)[resolved] || resolved || '文件'
}

function roleLabel(role?: string): string {
  return ({ input: '输入', intermediate: '中间产物', deliverable: '可交付' } as Record<string, string>)[role || ''] || '成果'
}

function artifactStatus(item: ProjectArtifact): string {
  if (item.deleted) return 'deleted'
  if (item.missing) return 'missing'
  const value = stringValue(item.status).toLowerCase()
  if (value === 'in_progress') return 'running'
  return value || 'ready'
}

function statusLabel(item: ProjectArtifact): string {
  return ({ ready: '就绪', running: '处理中', completed: '已完成', failed: '失败', missing: '文件缺失', deleted: '已移除' } as Record<string, string>)[artifactStatus(item)] || artifactStatus(item)
}

function revisionCount(item: ProjectArtifact): number {
  const count = Number(item.revision_count || item.revisions?.length || 1)
  return Number.isFinite(count) && count > 0 ? count : 1
}

function provenanceLabel(item: ProjectArtifact): string {
  const provenance = asRecord(item.provenance)
  if (provenance) {
    const label = stringValue(provenance.label || provenance.name || provenance.source)
    if (label) return label
  }
  if (item.source === 'user_upload' || item.source === 'user') return '用户上传'
  if (item.source === 'agent_generated' || item.source === 'agent') return 'Agent 生成'
  return item.source || '工作区'
}

function formatTime(value: string): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function revisionKey(revision: ArtifactRevision): string {
  return stringValue(revision.revision_id || revision.id || revision.revision || JSON.stringify(revision))
}

function revisionLabel(revision: ArtifactRevision): string {
  const number = Number(revision.ordinal ?? revision.revision)
  if (Number.isFinite(number) && number > 0) return `版本 ${number}`
  return stringValue(revision.revision_id || revision.id).slice(0, 12) || '版本'
}

function revisionStatusLabel(revision: ArtifactRevision): string {
  if (revision.deleted) return '已移除'
  if (revision.missing) return '文件缺失'
  return ({ failed: '失败', running: '处理中', completed: '已完成', ready: '就绪' } as Record<string, string>)[stringValue(revision.status)] || '已保存'
}

function isLatestRevision(item: ProjectArtifact, revision: ArtifactRevision): boolean {
  const latest = stringValue(item.latest_revision_id)
  if (latest) return latest === stringValue(revision.revision_id || revision.id)
  const number = Number(revision.ordinal ?? revision.revision)
  const rows = historyRowsById.value[item.artifact_id] || item.revisions || []
  const max = Math.max(...rows.map(row => Number(row.ordinal ?? row.revision)).filter(Number.isFinite), 0)
  return Number.isFinite(number) && number > 0 ? number === max : revision === rows[rows.length - 1]
}

function toggleSelected(id: string): void {
  const next = new Set(selectedSet.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selectedSet.value = next
}

function enterCleanup(): void {
  cleanupMode.value = true
  selectedSet.value = new Set()
}

function exitCleanup(): void {
  cleanupMode.value = false
  selectedSet.value = new Set()
}

function toggleDetails(item: ProjectArtifact): void {
  selectedArtifact.value = selectedArtifact.value?.artifact_id === item.artifact_id ? null : item
}

function openArtifactInStage(item: ProjectArtifact, revision?: ArtifactRevision): void {
  selectedArtifact.value = item
  emit('open-artifact', item, revision)
  void props.openArtifact?.(item, revision)
}

function onArtifactContextMenu(event: MouseEvent, item: ProjectArtifact): void {
  if (isNativeContextTarget(event.target)) return
  openContextMenu({
    event,
    items: [
      { id: 'open', label: '打开视窗', icon: ExternalLink, action: () => openArtifactInStage(item) },
      { id: 'history', label: '版本历史', icon: History, action: () => toggleHistory(item) },
      { type: 'separator', id: 'artifact-path-separator' },
      { id: 'copy-path', label: '复制路径', icon: Copy, action: () => copyText(item.path || item.uri || '').catch(() => undefined) },
      { type: 'separator', id: 'artifact-danger-separator' },
      item.deleted
        ? { id: 'restore', label: '恢复到成果库', icon: RotateCcw, action: () => restoreArtifact(item) }
        : { id: 'remove', label: '从成果库移除', icon: Trash2, destructive: true, action: () => removeArtifact(item) },
    ],
    ownerId: `artifact:${item.artifact_id}`,
    ariaLabel: `${item.name} 成果操作`,
    panelAttributes: { 'data-artifact-menu': item.artifact_id },
  })
}

async function removeArtifact(item: ProjectArtifact): Promise<void> {
  if (!props.projectId) return
  if (!window.confirm(`确定将「${item.name}」从成果库移除？文件不会被删除。`)) return
  await mutateArtifact('artifact.delete', [item.artifact_id])
}

async function removeSelected(): Promise<void> {
  if (!selected.value.length || !props.projectId) return
  if (!window.confirm(`确定将选中的 ${selected.value.length} 项从成果库移除？文件不会被删除。`)) return
  await mutateArtifact('artifact.delete', selected.value)
  selectedArtifact.value = null
  exitCleanup()
}

async function restoreArtifact(item: ProjectArtifact): Promise<void> {
  if (!props.projectId) return
  error.value = ''
  try {
    await props.requestRpc('artifact.restore', {
      project_id: props.projectId,
      artifact_ids: [item.artifact_id],
    })
    await fetchArtifacts()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}

async function mutateArtifact(method: string, ids: string[]): Promise<void> {
  error.value = ''
  try {
    await props.requestRpc(method, { project_id: props.projectId, artifact_ids: ids })
    await fetchArtifacts()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}

async function loadHistory(item: ProjectArtifact): Promise<void> {
  historyError.value = ''
  if (!props.projectId) return
  historyLoading.value = true
  try {
    const result = await props.requestRpc('artifact.revisions', {
      project_id: props.projectId,
      artifact_id: item.artifact_id,
    })
    historyRowsById.value = {
      ...historyRowsById.value,
      [item.artifact_id]: extractRevisionRows(result),
    }
  } catch (cause) {
    historyError.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    historyLoading.value = false
  }
}

async function toggleHistory(item: ProjectArtifact): Promise<void> {
  if (historyArtifactId.value === item.artifact_id) {
    historyArtifactId.value = ''
    return
  }
  historyArtifactId.value = item.artifact_id
  if (item.revisions?.length || historyRowsById.value[item.artifact_id]) return
  await loadHistory(item)
}

async function restoreRevision(item: ProjectArtifact, revision: ArtifactRevision): Promise<void> {
  if (!props.projectId) return
  const revisionId = stringValue(revision.revision_id || revision.id)
  if (!revisionId) return
  error.value = ''
  try {
    await props.requestRpc('artifact.revision.restore', {
      project_id: props.projectId,
      artifact_id: item.artifact_id,
      revision_id: revisionId,
    })
    await fetchArtifacts()
    const nextHistory = { ...historyRowsById.value }
    delete nextHistory[item.artifact_id]
    historyRowsById.value = nextHistory
    if (historyArtifactId.value === item.artifact_id) {
      await loadHistory(item)
    } else {
      await toggleHistory(item)
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}

function isArtifactSignal(value: unknown): boolean {
  const signal = asRecord(value)
  if (!signal) return false
  const method = stringValue(signal.method || signal.event_type || signal.type).toLowerCase()
  const payload = asRecord(signal.payload) || signal
  return method.includes('artifact')
    || Boolean(payload.artifact_id || payload.artifactId)
    || Array.isArray(payload.artifacts)
    || stringValue(payload.kind).toLowerCase() === 'artifact.changed'
}

async function fetchArtifacts(): Promise<void> {
  const projectId = props.projectId
  const revision = ++fetchRevision
  if (!projectId) {
    artifacts.value = []
    return
  }
  loading.value = true
  error.value = ''
  try {
    const result = await props.requestRpc('artifact.list', { project_id: projectId, include_deleted: true })
    if (revision !== fetchRevision) return
    artifacts.value = extractArtifactRows(result)
      .flatMap(value => {
        const normalized = normalizeArtifact(value)
        return normalized ? [normalized] : []
      })
    if (selectedArtifact.value) {
      selectedArtifact.value = artifacts.value.find(item => item.artifact_id === selectedArtifact.value?.artifact_id) || null
    }
  } catch (cause) {
    if (revision === fetchRevision) error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    if (revision === fetchRevision) loading.value = false
  }
}

watch(() => props.projectId, () => {
  selectedArtifact.value = null
  historyArtifactId.value = ''
  historyRowsById.value = {}
  exitCleanup()
  void fetchArtifacts()
})

watch(() => props.artifactSignal, signal => {
  if (isArtifactSignal(signal)) void fetchArtifacts()
}, { deep: true })

onMounted(() => { void fetchArtifacts() })
</script>

<style scoped>
.artifact-panel { --text: var(--theme-backdrop-text); display: flex; flex-direction: column; min-height: 0; color: var(--text); }
.artifact-panel-head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); padding: var(--space-1) 0 var(--space-2); }
.artifact-panel-title { display: flex; align-items: baseline; gap: var(--space-1); min-width: 0; }
.artifact-panel-title strong { font-size: 13px; font-weight: 760; }
.artifact-panel-count { color: color-mix(in srgb, var(--text) 52%, transparent); font-size: 10px; }
.artifact-actions { display: flex; align-items: center; gap: var(--space-1); }
.text-btn { display: inline-flex; align-items: center; justify-content: center; min-height: 28px; border: 0; border-radius: var(--radius-sm); padding: 0 var(--space-1); background: transparent; color: color-mix(in srgb, var(--text) 64%, transparent); font-size: 11px; }
.text-btn:hover:not(:disabled) { background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent); color: var(--text); }
.text-btn:active:not(:disabled) { background: color-mix(in srgb, var(--text) var(--alpha-active), transparent); }
.text-btn.danger { color: color-mix(in srgb, var(--red) 80%, var(--text) 20%); }
.text-btn:disabled { opacity: .45; }
.artifact-search-row { display: flex; align-items: center; gap: var(--space-1); min-height: 32px; border: 1px solid color-mix(in srgb, var(--theme-composer-text) 12%, transparent); border-radius: var(--radius-sm); padding: 0 var(--space-2); background: color-mix(in srgb, var(--theme-composer-background) 70%, transparent); color: color-mix(in srgb, var(--theme-composer-text) 52%, transparent); }
.artifact-search { min-width: 0; flex: 1 1 auto; border: 0; outline: 0; background: transparent; color: var(--theme-composer-text); caret-color: var(--theme-composer-text); font: inherit; font-size: 11px; }
.artifact-search::placeholder { color: color-mix(in srgb, var(--theme-composer-text) 45%, transparent); }
.artifact-search-clear { border: 0; border-radius: var(--radius-sm); background: transparent; color: inherit; font-size: 15px; line-height: 1; }
.artifact-filters { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--space-1); padding: var(--space-2) 0 var(--space-1); }
.artifact-filters :deep(.ui-select-trigger) { min-height: 28px; padding-inline: var(--space-1); font-size: 10px; }
.artifact-removed-toggle { grid-column: 1 / -1; justify-self: start; min-height: 26px; border: 0; border-radius: var(--radius-sm); padding: 0 var(--space-1); background: transparent; color: color-mix(in srgb, var(--text) 55%, transparent); font-size: 10px; }
.artifact-removed-toggle:hover { background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent); color: var(--text); }
.artifact-removed-toggle.active { color: var(--orange); }
.artifact-panel-hint { margin: 0 0 var(--space-2); color: color-mix(in srgb, var(--text) 46%, transparent); font-size: 10px; line-height: 1.45; }
.artifact-error { margin: 0 0 var(--space-2); border: 1px solid color-mix(in srgb, var(--red) 22%, transparent); border-radius: var(--radius-sm); padding: var(--space-1) var(--space-2); background: color-mix(in srgb, var(--red) 10%, var(--theme-backdrop-background)); color: color-mix(in srgb, var(--red) 80%, var(--text) 20%); font-size: 11px; }
.artifact-state { display: flex; align-items: center; justify-content: center; gap: var(--space-1); min-height: 88px; padding: var(--space-3); color: color-mix(in srgb, var(--text) 52%, transparent); font-size: 11px; line-height: 1.5; text-align: center; }
.artifact-state-spinner { animation: artifact-spin .9s linear infinite; color: var(--blue); }
@keyframes artifact-spin { to { transform: rotate(360deg); } }
.artifact-list { display: grid; gap: var(--space-1); min-height: 0; max-height: 42vh; overflow: auto; margin: 0; padding: 0; list-style: none; }
.artifact-item { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: var(--space-1); min-width: 0; border: 1px solid color-mix(in srgb, var(--text) 10%, transparent); border-radius: var(--radius-sm); padding: var(--space-1); background: var(--theme-backdrop-background); }
.artifact-item:hover { border-color: color-mix(in srgb, var(--text) var(--alpha-hover), transparent); background: color-mix(in srgb, var(--text) var(--alpha-hover), var(--theme-backdrop-background)); }
.artifact-item--selected { border-color: color-mix(in srgb, var(--text) 28%, transparent); background: color-mix(in srgb, var(--text) var(--alpha-active), var(--theme-backdrop-background)); }
.artifact-item--deleted { opacity: .68; }
.artifact-item--missing .artifact-name { text-decoration: line-through; text-decoration-color: color-mix(in srgb, var(--red) 70%, transparent); }
.artifact-item-main { display: flex; align-items: center; gap: var(--space-2); min-width: 0; border: 0; border-radius: var(--radius-sm); padding: var(--space-1); background: transparent; color: inherit; text-align: left; }
.artifact-item-main:focus-visible, .artifact-icon-button:focus-visible, .artifact-open-button:focus-visible, .artifact-revision-open:focus-visible, .artifact-revision-restore:focus-visible { outline: 2px solid color-mix(in srgb, var(--blue) 75%, transparent); outline-offset: 1px; }
.artifact-kind { display: inline-flex; flex: 0 0 auto; color: color-mix(in srgb, var(--text) 66%, transparent); }
.artifact-item-copy { display: grid; min-width: 0; gap: 2px; }
.artifact-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; font-weight: 700; }
.artifact-item-meta { min-width: 0; overflow: hidden; color: color-mix(in srgb, var(--text) 48%, transparent); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.artifact-status { flex: 0 0 auto; border-radius: 999px; padding: 1px var(--space-1); color: color-mix(in srgb, var(--text) 58%, transparent); font-size: 9px; }
.artifact-status[data-status="running"] { color: var(--orange); }
.artifact-status[data-status="failed"], .artifact-status[data-status="missing"] { color: var(--red); }
.artifact-status[data-status="completed"] { color: var(--green); }
.artifact-status[data-status="deleted"] { color: color-mix(in srgb, var(--red) 68%, var(--text) 32%); }
.artifact-item-actions { display: inline-flex; align-items: center; gap: 2px; }
.artifact-icon-button { display: inline-flex; align-items: center; justify-content: center; min-width: 26px; min-height: 26px; border: 0; border-radius: var(--radius-sm); padding: 0; background: transparent; color: color-mix(in srgb, var(--text) 52%, transparent); }
.artifact-icon-button:hover { background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent); color: var(--text); }
.artifact-icon-button:active { background: color-mix(in srgb, var(--text) var(--alpha-active), transparent); }
.artifact-icon-button--danger:hover { color: var(--red); }
.artifact-icon-button--restore:hover { color: var(--green); }
.artifact-check { display: inline-flex; align-items: center; justify-content: center; min-width: 26px; min-height: 26px; }
.artifact-check input { width: 14px; height: 14px; margin: 0; accent-color: var(--green); }
.artifact-detail, .artifact-history { margin-top: var(--space-2); border-top: 1px solid color-mix(in srgb, var(--text) 12%, transparent); padding-top: var(--space-2); }
.artifact-detail-head, .artifact-history-head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); }
.artifact-detail-head > div { display: grid; min-width: 0; gap: 2px; }
.artifact-detail-head strong, .artifact-history-head strong { overflow: hidden; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.artifact-detail-head span { color: color-mix(in srgb, var(--text) 48%, transparent); font-size: 10px; }
.artifact-open-button { display: inline-flex; align-items: center; gap: var(--space-1); flex: 0 0 auto; min-height: 28px; border: 1px solid color-mix(in srgb, var(--text) 14%, transparent); border-radius: var(--radius-sm); padding: 0 var(--space-2); background: transparent; color: color-mix(in srgb, var(--text) 72%, transparent); font-size: 10px; }
.artifact-open-button:hover { background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent); color: var(--text); }
.artifact-meta { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 3px var(--space-2); margin: var(--space-2) 0 0; color: color-mix(in srgb, var(--text) 68%, transparent); font-size: 10px; }
.artifact-meta dt { color: color-mix(in srgb, var(--text) 45%, transparent); }
.artifact-meta dd { min-width: 0; overflow: hidden; margin: 0; text-overflow: ellipsis; white-space: nowrap; }
.artifact-history-head { margin-bottom: var(--space-1); }
.artifact-history-state { padding: var(--space-2) 0; color: color-mix(in srgb, var(--text) 52%, transparent); font-size: 10px; }
.artifact-history-state--error { color: var(--red); }
.artifact-revision-list { display: grid; gap: var(--space-1); margin: 0; padding: 0; list-style: none; }
.artifact-revision { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); border-radius: var(--radius-sm); padding: var(--space-1); background: color-mix(in srgb, var(--text) 5%, var(--theme-backdrop-background)); }
.artifact-revision-copy { display: grid; min-width: 0; gap: 2px; }
.artifact-revision-copy strong { font-size: 10px; }
.artifact-revision-copy span { color: color-mix(in srgb, var(--text) 46%, transparent); font-size: 9px; }
.artifact-revision-actions { display: inline-flex; align-items: center; gap: var(--space-1); flex: 0 0 auto; }
.artifact-revision-open, .artifact-revision-restore { min-height: 24px; border: 0; border-radius: var(--radius-sm); padding: 0 var(--space-1); background: transparent; color: var(--blue); font-size: 10px; }
.artifact-revision-open:hover, .artifact-revision-restore:hover { background: color-mix(in srgb, var(--blue) var(--alpha-hover), transparent); }
.artifact-revision-restore { color: var(--green); }
.artifact-revision-latest { color: color-mix(in srgb, var(--text) 45%, transparent); font-size: 9px; }
@media (max-width: 640px) {
  .artifact-filters { grid-template-columns: 1fr 1fr; }
  .artifact-filters :deep(.ui-select-trigger) { min-height: 34px; }
  .artifact-removed-toggle { grid-column: 1 / -1; min-height: 34px; }
  .artifact-icon-button, .artifact-check { min-width: 34px; min-height: 34px; }
}
@media (prefers-reduced-motion: reduce) { .artifact-state-spinner { animation: none; } }
</style>
