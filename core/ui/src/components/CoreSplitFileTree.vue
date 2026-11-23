<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { ChevronDown, ChevronRight, File, Folder, FolderOpen, RefreshCw, Search, X } from 'lucide-vue-next'
import { openContextMenu, type ContextMenuEntry } from '@/components/context-menu/index.ts'
import SendToDeviceMenu from '@/components/SendToDeviceMenu.vue'
import { t } from '@/i18n/index.ts'
import { splitNative, type SplitFileEntry } from '@/split/native'
import type { LamToolsTransport } from '@/transport'
import '@/styles/split-workspace.css'
// user:“给现有 search_files 能力一个可见入口”+
// (入口选在文件树里：它就是「文件」这块屏，检索结果直接落在同一棵树的位置上，
// 点开走的是和文件树完全相同的打开通道——预览/编辑器/插件页面，不需要第二套。
// 全局按内容检索仍是单工作区、有扫描预算，所以结果区会明说「扫了多少、是否扫完」。)
const props = defineProps<{
  root: string
  listFiles?: (root: string, path: string) => Promise<SplitFileEntry[]>
  /** 检索走后台的 HTTP 通道；没有通道时这个入口退化成不显示。 */
  transport?: LamToolsTransport
}>()
const emit = defineEmits<{ open: [path: string] }>()
const entries = ref<Record<string, SplitFileEntry[]>>({}), expanded = ref(new Set<string>()), error = ref(''), loading = ref(new Set<string>())
const failedPath = ref('')
let generation = 0
async function load(path: string) {
  const root = props.root, run = generation
  if (!root) { failedPath.value = ''; error.value = '先选择一个项目，再浏览文件'; return }
  if (loading.value.has(path)) return
  loading.value.add(path); error.value = ''; failedPath.value = ''
  try { const result = props.listFiles ? await props.listFiles(root, path) : await splitNative<SplitFileEntry[]>('split_file_list', { root, path }); if (run === generation) entries.value[path] = result }
  catch (e) { if (run === generation) { error.value = String(e); failedPath.value = path } } finally { if (run === generation) loading.value.delete(path) }
}
async function toggle(entry: SplitFileEntry) {
  if (!entry.directory) { emit('open', entry.path); return }
  if (expanded.value.has(entry.path)) expanded.value.delete(entry.path)
  else { expanded.value.add(entry.path); if (!entries.value[entry.path]) await load(entry.path) }
}
const rows = computed(() => {
  const result: { entry: SplitFileEntry; depth: number }[] = []
  const walk = (path: string, depth: number) => { if (depth > 30) return; for (const entry of entries.value[path] || []) { result.push({ entry, depth }); if (entry.directory && expanded.value.has(entry.path)) walk(entry.path, depth + 1) } }
  walk(props.root, 0); return result
})
const tree = ref<HTMLElement | null>(null), focusedPath = ref('')
/**
 * user:“文件树、资料库、预览器里对文件加「发送到设备」”+
 * (文件树这一份入口：右键任意一行给出「打开／发送到设备」；目录没有「发送」这一项，
 *  因为发出去的是文件本身。能不能发、为什么不能发交给 SendToDeviceMenu 里的
 *  sendEligibility 统一判定，这里不写第二套规则。)
 */
const sendTarget = ref<{ path: string; name: string } | null>(null)
const sendStyle = ref<Record<string, string>>({})
const sendNotice = ref('')

function openRowMenu(event: MouseEvent, entry: SplitFileEntry): void {
  const items: ContextMenuEntry[] = [
    { label: t('打开'), action: () => void toggle(entry) },
  ]
  if (!entry.directory) {
    items.push(
      { type: 'separator' },
      { label: t('发送到设备'), action: () => openSendToDevice(entry, event) },
    )
  }
  openContextMenu({ event, items, ariaLabel: t('{0} 的操作', { 0: entry.name }) })
}

/** 清单贴着右键处出现，但不许跑出窗口（与资料库那一份同样的避让规则）。 */
function openSendToDevice(entry: SplitFileEntry, event: MouseEvent): void {
  sendTarget.value = { path: entry.path, name: entry.name }
  const width = 300
  const height = 260
  const left = Math.min(Math.max(8, event.clientX), Math.max(8, window.innerWidth - width - 8))
  const top = Math.min(Math.max(8, event.clientY), Math.max(8, window.innerHeight - height - 8))
  sendStyle.value = { left: `${left}px`, top: `${top}px` }
  sendNotice.value = ''
}

/** 发送真的开始了：给一句本地反馈，进度在「设备连接」的传输面板里看。 */
function onSent(payload: { name: string }): void {
  sendTarget.value = null
  sendNotice.value = t('已开始发送：{0}', { 0: payload.name })
}
const activePath = computed(() => rows.value.some(row => row.entry.path === focusedPath.value) ? focusedPath.value : rows.value[0]?.entry.path)
function focusRow(index: number) {
  const row = rows.value[index]
  if (!row) return
  focusedPath.value = row.entry.path
  void nextTick(() => tree.value?.querySelectorAll<HTMLButtonElement>('[role="treeitem"]')[index]?.focus())
}
// user:“确保视觉、功能和交互不退化”+(文件树支持方向键展开、收起与逐项浏览)。
async function onTreeKeydown(event: KeyboardEvent, index: number) {
  const row = rows.value[index]
  if (!row) return
  if (event.key === 'ArrowDown') { event.preventDefault(); focusRow(Math.min(rows.value.length - 1, index + 1)) }
  else if (event.key === 'ArrowUp') { event.preventDefault(); focusRow(Math.max(0, index - 1)) }
  else if (event.key === 'Home') { event.preventDefault(); focusRow(0) }
  else if (event.key === 'End') { event.preventDefault(); focusRow(rows.value.length - 1) }
  else if (event.key === 'ArrowRight') {
    event.preventDefault()
    if (!row.entry.directory) return
    if (!expanded.value.has(row.entry.path)) await toggle(row.entry)
    else if (rows.value[index + 1]?.depth === row.depth + 1) focusRow(index + 1)
  } else if (event.key === 'ArrowLeft') {
    event.preventDefault()
    if (row.entry.directory && expanded.value.has(row.entry.path)) { expanded.value.delete(row.entry.path); return }
    for (let i = index - 1; i >= 0; i--) if (rows.value[i].depth < row.depth) { focusRow(i); break }
  }
}
/* ---- 检索：结果落在同一棵树上，打开走同一条通道 ---- */
interface SearchHit { path: string; line: number | null; text: string }
interface SearchReport { matches: SearchHit[]; match_count: number; scanned_entries: number; scan_exhausted: boolean; truncated: boolean }
const query = ref('')
/** 文件名 or 内容；内容模式命中的是「文件:行号」这种位置。 */
const mode = ref<'name' | 'content'>('name')
const searching = ref(false)
const searchError = ref('')
const report = ref<SearchReport | null>(null)
let searchRevision = 0

const searchActive = computed(() => Boolean(report.value || searching.value))
const hasChannel = computed(() => Boolean(props.transport))

function resetSearch() {
  searchRevision++
  query.value = ''
  report.value = null
  searchError.value = ''
  searching.value = false
}

/** 结果里的相对路径换成可打开的绝对路径（文件树里的条目本来就是绝对路径）。 */
function absoluteFor(relative: string): string {
  const root = props.root.replace(/[\\/]+$/, '')
  const clean = relative.replace(/^[\\/]+/, '')
  return root ? `${root}/${clean}` : clean
}

async function runSearch() {
  const keyword = query.value.trim()
  if (!keyword) { report.value = null; searchError.value = ''; return }
  if (!props.transport || !props.root) { searchError.value = '检索需要在桌面应用中、并已选择项目'; return }
  const run = ++searchRevision
  searching.value = true; searchError.value = ''
  try {
    const params = new URLSearchParams({
      query: keyword,
      mode: mode.value,
      path: '.',
      limit: '50',
      work_root: props.root,
    })
    const response = await props.transport.request<{ status: number; body: Uint8Array }>({
      kind: 'http', method: 'GET', path: `/files/search?${params.toString()}`,
    })
    if (run !== searchRevision) return
    if (response.status < 200 || response.status >= 300) {
      let detail = '检索失败'
      try {
        const payload = JSON.parse(new TextDecoder().decode(response.body))
        if (typeof payload.detail === 'string') detail = payload.detail
      } catch { /* 非 JSON 失败保留可读的兜底文案。 */ }
      throw new Error(detail)
    }
    report.value = JSON.parse(new TextDecoder().decode(response.body)) as SearchReport
  } catch (cause) {
    if (run === searchRevision) { searchError.value = cause instanceof Error ? cause.message : '检索失败'; report.value = null }
  } finally {
    if (run === searchRevision) searching.value = false
  }
}

/** 结果说明必须说清「扫全了没有」：预算耗尽时结果可能不全。 */
const searchSummary = computed(() => {
  const current = report.value
  if (!current) return ''
  const total = current.match_count || current.matches.length
  const parts = [`${total} 处结果`]
  parts.push(`扫描了 ${current.scanned_entries} 个条目`)
  if (current.scan_exhausted) parts.push('扫描预算已用完，结果可能不全')
  else if (current.truncated) parts.push('结果过多，只显示前 50 条')
  return parts.join(' · ')
})

/**
 * 打开命中项：走的是文件树完全相同的 open 通道（预览器/编辑器/插件页面由下游决定）。
 *
 * user:“打开即走上面的统一预览链路；文本走编辑器”+
 * (内容检索的行号只作为结果里的定位线索显示，不另开「跳到第 N 行」的通道——
 * 那需要编辑器侧支持，属于后续批次；现在假装支持会比不跳更糟。)
 */
function openHit(hit: SearchHit) {
  emit('open', absoluteFor(hit.path))
}

// user:“确保视觉、功能和交互不退化”+
// (切换项目后重新加载，旧项目的迟到结果不能覆盖新界面。注册放在检索状态之后：
// immediate 回调会重置检索，提前注册会读到还没初始化的变量。)
watch(() => props.root, root => {
  generation++
  entries.value = {}
  expanded.value = new Set()
  loading.value = new Set()
  focusedPath.value = ''
  error.value = ''
  failedPath.value = ''
  resetSearch()
  void load(root)
}, { immediate: true })
onBeforeUnmount(() => { generation++ })
</script>
<template>
  <div class="split-file-tree">
    <div class="split-content-toolbar">
      <span class="split-path" :title="root">{{ root.split(/[\\/]/).filter(Boolean).pop() || '项目文件' }}</span>
      <button class="split-icon-button" type="button" aria-label="刷新文件树" title="刷新" @click="load(root)"><RefreshCw :size="14" /></button>
    </div>
    <!-- user:“给现有 search_files 能力一个可见入口”+(检索就放在文件树顶部：它检索的正是这棵树)。 -->
    <div v-if="hasChannel" class="split-file-search" role="search">
      <Search :size="13" aria-hidden="true" />
      <input
        v-model="query"
        type="search"
        :placeholder="mode === 'content' ? '在文件内容中检索…' : '按文件名检索…'"
        :aria-label="mode === 'content' ? '按内容检索文件' : '按文件名检索文件'"
        data-split-file-search-input
        @keydown.enter.prevent="runSearch"
        @keydown.esc.prevent="resetSearch"
      />
      <button
        class="split-text-button"
        type="button"
        :aria-pressed="mode === 'content'"
        :title="mode === 'content' ? '当前按内容检索，切换为按文件名' : '当前按文件名检索，切换为按内容'"
        data-split-file-search-mode
        @click="mode = mode === 'content' ? 'name' : 'content'; if (query.trim()) runSearch()"
      >{{ mode === 'content' ? '内容' : '文件名' }}</button>
      <button v-if="searchActive" class="split-icon-button" type="button" aria-label="清除检索" title="清除检索" data-split-file-search-clear @click="resetSearch"><X :size="13" /></button>
    </div>
    <p v-if="searchError" class="split-content-error" role="alert">{{ searchError }}</p>
    <p v-else-if="searching" class="split-content-notice" role="status">正在检索…</p>
    <!-- 结果区：命中数、扫了多少、有没有扫完，都明说。 -->
    <template v-else-if="searchActive">
      <p class="split-content-notice" data-split-file-search-summary>{{ searchSummary }}</p>
      <div class="split-file-rows" role="list" aria-label="检索结果">
        <button
          v-for="hit in report?.matches || []"
          :key="`${hit.path}:${hit.line ?? 0}`"
          type="button"
          role="listitem"
          :title="hit.line ? `${absoluteFor(hit.path)}:${hit.line}` : absoluteFor(hit.path)"
          :data-split-file-hit="hit.path"
          @click="openHit(hit)"
        >
          <File :size="13" aria-hidden="true" />
          <span>{{ hit.path }}<template v-if="hit.line">:{{ hit.line }}</template></span>
          <small v-if="hit.text" class="split-file-hit-text">{{ hit.text }}</small>
        </button>
        <p v-if="report && !report.matches.length" class="split-content-notice">没有找到匹配的文件</p>
      </div>
    </template>
    <template v-else>
      <p v-if="error" class="split-content-error" role="alert">{{ error }} <button v-if="failedPath" type="button" class="split-text-button" @click="load(failedPath)">重试</button></p>
      <div ref="tree" class="split-file-rows" role="tree" aria-label="项目文件">
        <button v-for="({entry, depth}, index) in rows" :key="entry.path" type="button" role="treeitem" :tabindex="activePath === entry.path ? 0 : -1" :aria-level="depth + 1" :aria-expanded="entry.directory ? expanded.has(entry.path) : undefined" :style="{ paddingLeft: `${12 + depth * 16}px` }" :title="entry.path" @focus="focusedPath = entry.path" @keydown="onTreeKeydown($event, index)" @contextmenu.prevent="openRowMenu($event, entry)" @click="toggle(entry)">
          <component :is="entry.directory ? expanded.has(entry.path) ? ChevronDown : ChevronRight : File" :size="13" aria-hidden="true" />
          <component v-if="entry.directory" :is="expanded.has(entry.path) ? FolderOpen : Folder" :size="14" aria-hidden="true" /><span>{{ entry.name }}</span>
        </button>
        <p v-if="!rows.length && !error" class="split-content-notice">{{ loading.size ? '正在读取目录…' : '文件夹为空' }}</p>
      </div>
    </template>
    <!-- user:“发送到设备”+(清单贴在右键处；选中即开始传输，点空白收起)。 -->
    <div v-if="sendTarget" class="split-file-send-layer" data-split-file-send @click="sendTarget = null">
      <SendToDeviceMenu
        class="split-file-send-menu"
        :style="sendStyle"
        :path="sendTarget.path"
        :name="sendTarget.name"
        @sent="onSent"
        @close="sendTarget = null"
      />
    </div>
    <p v-if="sendNotice" class="split-content-notice" role="status" data-split-file-send-notice>
      {{ sendNotice }}<button class="split-text-button" type="button" @click="sendNotice = ''">{{ t('知道了') }}</button>
    </p>
  </div>
</template>

<style scoped>
/* user:“发送到设备”+(清单盖在文件树之上、贴住右键位置；点空白处收起)。 */
.split-file-send-layer {
  position: fixed;
  inset: 0;
  z-index: 70;
}

.split-file-send-menu {
  position: fixed;
}
</style>
