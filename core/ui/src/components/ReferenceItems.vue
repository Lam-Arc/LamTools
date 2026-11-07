<template>
  <div v-if="!previewOnly" v-bind="$attrs" class="reference-items" :class="{ 'reference-items--icons': compact }" :aria-label="compact ? '消息附件' : '本轮成果'">
    <button v-for="item in visibleItems" :key="item.id" type="button" class="reference-item" :class="{ 'reference-item--link': item.link, 'reference-item--failed': errors[item.id] }" :title="[item.name, resolvedPaths[item.id] || item.path, errors[item.id]].filter(Boolean).join('\n')" :aria-label="[item.name, errors[item.id]].filter(Boolean).join('：')" @click="preview(item)" @contextmenu.stop="item.path && !item.path.startsWith('data:') ? actions.menu($event, resolvedPaths[item.id] || item.path) : $event.preventDefault()">
      <img v-if="thumbnails[item.id] && !errors[item.id]" :src="thumbnails[item.id]" alt="" @error="errors[item.id] = '图片解码失败'">
      <component :is="item.link ? Link2 : BookOpen" v-else-if="item.link || item.memory" :size="compact ? 18 : 16" :stroke-width="1.6" />
      <FileTypeBadge v-else :name="item.name" :failed="Boolean(errors[item.id])" :size="compact ? 20 : 18" />
      <span v-if="!compact" class="reference-item-name">{{ item.name }}</span>
      <span v-if="errors[item.id]" class="reference-item-error" aria-hidden="true">!</span>
    </button>
    <button
      v-if="showToggle"
      type="button"
      class="reference-item reference-item--more"
      data-reference-toggle
      :aria-expanded="expanded"
      :title="hiddenErrorCount ? t('部分文件不存在') : undefined"
      @click="expanded = !expanded"
    >
      <span class="reference-item-name">{{ expanded ? t('收起') : t('展开其余 {0} 项', { 0: items.length - COLLAPSED_LIMIT }) }}</span>
      <span v-if="hiddenErrorCount" class="reference-item-error" aria-hidden="true">!</span>
    </button>
  </div>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { BookOpen, Link2 } from 'lucide-vue-next'
import FileTypeBadge from '@/components/FileTypeBadge.vue'
import { t } from '@/i18n/index.ts'
import { useReferenceActions } from '@/helpers/referenceActions'
import { useOptionalSplitWorkspace } from '@/split/useSplitWorkspace'
import { openFileInSplit } from '@/split/openFile'
import { normalizeWebLink } from '@/helpers/webLinks'
import type { CoreAttachment, ToolArtifact } from '@/types'
import type { LamToolsTransport, TransportHttpResponse } from '@/transport'

defineOptions({ inheritAttrs: false })
const props = withDefaults(defineProps<{ attachments?: CoreAttachment[]; artifacts?: ToolArtifact[]; transport: LamToolsTransport; projectId?: string | null; workRoot?: string | null; compact?: boolean; previewOnly?: boolean }>(), { attachments: () => [], artifacts: () => [] })
const actions = useReferenceActions(props.transport, () => props.workRoot || '')
const splitWorkspace = useOptionalSplitWorkspace()
type Item = { id: string; name: string; path: string; kind: string; mime: string; attachment?: string; artifactId?: string; link: boolean; memory: boolean; inline?: string }
const items = computed<Item[]>(() => [
  ...props.attachments.map(a => ({ id: a.id, name: a.filename, path: a.path || '', kind: a.preview_type, mime: a.mime_type, attachment: a.id.startsWith('path:') ? undefined : a.id, link: false, memory: false })),
  ...props.artifacts.map((a, index) => {
    const raw = a as ToolArtifact & { artifact_id?: string; name?: string; path?: string; mime_type?: string }
    const metadata = raw.metadata || {}, path = String(raw.path || raw.uri || metadata.path || '')
    return { artifactId: raw.artifact_id, inline: typeof metadata.image_data_url === 'string' && metadata.image_data_url.startsWith('data:image') ? metadata.image_data_url : undefined, id: raw.artifact_id || path || `legacy-${index}`, name: raw.name || String(metadata.name || path.split('/').pop() || '文件'), path, kind: raw.kind, mime: raw.mime_type || String(metadata.mime_type || ''), link: Boolean(normalizeWebLink(path)), memory: raw.kind === 'memory' }
  }),
])
const resolvedPaths = reactive<Record<string, string>>({})
const errors = reactive<Record<string, string>>({}), thumbnails = reactive<Record<string, string>>({})
// user:“底下跟的那一堆成果文件默认折叠一下，正常显示 6 个，多余 6 个的就折叠进去”+
// (本轮成果/附件列表默认只显示前 6 项，其余收进“展开其余 N 项”按钮；新的一批成果
// 到达时重新折叠，避免上一轮展开状态串到下一轮)。
const COLLAPSED_LIMIT = 6
const expanded = ref(false)
const visibleItems = computed(() => (
  props.compact || expanded.value ? items.value : items.value.slice(0, COLLAPSED_LIMIT)
))
const showToggle = computed(() => !props.compact && items.value.length > COLLAPSED_LIMIT)
const hiddenErrorCount = computed(() => (
  showToggle.value && !expanded.value
    ? items.value.slice(COLLAPSED_LIMIT).filter(item => Boolean(errors[item.id])).length
    : 0
))
watch(
  () => items.value.map(item => item.id).join('\u0000'),
  () => { expanded.value = false },
)
const owned = new Set<string>()
let generation = 0
function binaryPath(item: Item) {
  if (item.attachment) return `/attachments/${encodeURIComponent(item.attachment)}/download`
  if (item.artifactId && props.projectId) return `/projects/${encodeURIComponent(props.projectId)}/artifacts/${encodeURIComponent(item.artifactId)}/file?path=${encodeURIComponent(item.path)}`
  const query = new URLSearchParams({ path: item.path, ...(props.workRoot ? { work_root: props.workRoot } : {}) })
  return `/files/read-reference?${query}`
}
async function bytes(item: Item) {
  let response = await props.transport.request<TransportHttpResponse>({ kind: 'http', method: 'GET', path: binaryPath(item) })
  // user:“引用的地址可能不对”+(旧投影 ID 不当作真实资料库 ID；文件预览和正文共用核实后的路径)。
  if (response.status === 404 && item.artifactId && item.path) return actions.read(item.path)
  if (response.status < 200 || response.status >= 300) {
    let detail = response.status === 404 ? '原文件不存在' : '文件无法读取'
    try { detail = JSON.parse(new TextDecoder().decode(response.body)).detail || detail } catch { /* Keep the existing fallback for non-JSON failures. */ }
    throw new Error(detail)
  }
  return response
}
function blobUrl(response: TransportHttpResponse, mime: string) {
  const url = URL.createObjectURL(new Blob([Uint8Array.from(response.body)], { type: response.headers['content-type'] || mime }))
  owned.add(url); return url
}
// user:“点击文件优先在分屏中预览”+(分屏工作区可用时，点击文件先在分屏里按类型打开：
// 图片、音视频、PDF、Office、Markdown 用预览器，其他文本用编辑器)。
// user:“Markdown 还是弹中间的浮层”+(记忆/方案类 Markdown 也带真实路径，同样进分屏，不再单独弹浮层)。
function previewInSplit(item: Item): boolean {
  if (!splitWorkspace || !item.path || item.link || item.inline) return false
  try {
    const actual = resolvedPaths[item.id] || actions.absolute(item.path)
    return Boolean(openFileInSplit(splitWorkspace, actual, { workRoot: props.workRoot || '' }))
  } catch {
    return false
  }
}
// user:“气泡下方不要用行，用小图标可以吗”+(输入附件仅占一排小图标，具体错误通过悬浮与预览说明)。
watch(() => items.value.map(i => i.id + '\0' + i.path + '\0' + i.kind).join('\n'), async () => {
  const current = items.value
  const run = ++generation
  if (props.previewOnly) return
  // user:“图片引用应在会话保存、恢复、重新加载后保持有效”+(每次条目变化都重新判定一次，
  // 上一轮的偶发失败不再钉死某个条目的错误态)。
  for (const item of current) delete errors[item.id]
  for (const item of current) {
    if (!item.attachment && item.path && !item.link && !item.memory && !item.inline) {
      try {
        const actual = await actions.resolve(item.path)
        if (run !== generation) return
        item.path = actual; resolvedPaths[item.id] = actual
        delete errors[item.id]
      } catch (error) {
        if (run === generation) errors[item.id] = error instanceof Error ? error.message : '原文件不存在'
        if (!item.artifactId) continue
      }
    }
    if (item.attachment) {
      try {
        const response = await props.transport.request<TransportHttpResponse>({ kind: 'http', method: 'GET', path: `/attachments/${encodeURIComponent(item.attachment)}/preview` })
        if (run !== generation) return
        if (response.status !== 200) throw new Error(response.status === 404 ? '附件记录不存在' : '文件无法读取')
        const meta = JSON.parse(new TextDecoder().decode(response.body))
        item.path = meta.path || item.path
        resolvedPaths[item.id] = item.path
        if (meta.error_code) throw new Error(({ file_missing: '原文件不存在', file_unreadable: '文件无法读取', image_decode_failed: '图片解码失败', image_format_unsupported: '图片格式暂不支持预览' } as Record<string, string>)[meta.error_code] || '暂时无法预览')
      } catch (error) { errors[item.id] = error instanceof Error ? error.message : '文件无法读取'; continue }
    }
    if (item.inline) { thumbnails[item.id] = item.inline; continue }
    if (item.kind !== 'image' || thumbnails[item.id]) continue
    try { const response = await bytes(item); if (run === generation) thumbnails[item.id] = blobUrl(response, item.mime) }
    catch (error) { if (run === generation) errors[item.id] = error instanceof Error ? error.message : '文件无法读取' }
  }
}, { immediate: true })
async function preview(item: Item) {
  item.path = resolvedPaths[item.id] || item.path
  if (item.link) { await actions.open(item.path); return }
  if (previewInSplit(item)) return
  // 点击可能早于后台路径核实完成：先补一次核实，再决定是否进分屏。
  if (item.attachment && !resolvedPaths[item.id] && props.transport) {
    try {
      const response = await props.transport.request<TransportHttpResponse>({ kind: 'http', method: 'GET', path: `/attachments/${encodeURIComponent(item.attachment)}/preview` })
      if (response.status === 200) {
        const meta = JSON.parse(new TextDecoder().decode(response.body))
        if (typeof meta.path === 'string' && meta.path) { item.path = meta.path; resolvedPaths[item.id] = meta.path }
      }
    } catch { /* The default-app fallback below reports the failure. */ }
  } else if (!item.attachment && item.path && !item.inline && !resolvedPaths[item.id]) {
    try {
      const actual = await actions.resolve(item.path)
      item.path = actual; resolvedPaths[item.id] = actual
    } catch { /* The default-app fallback below reports the failure. */ }
  }
  if (previewInSplit(item)) return
  // user:“没有浮窗预览这一说，砍掉”+(分屏不可用或预览开关关闭时，直接交给系统默认应用，
  // 不再弹出居中预览浮层；复制/打开文件夹仍走右键菜单)。
  if (item.path) await actions.open(item.path)
}
onBeforeUnmount(() => { ++generation; for (const url of owned) URL.revokeObjectURL(url) })
defineExpose({ previewPath(path: string) {
  const item = items.value.find(item => actions.absolute(item.path) === actions.absolute(path))
  if (item) void preview(item)
  else void actions.open(path)
} })
</script>
<style scoped>
.reference-items { --text: var(--theme-main-text); display: flex; flex-wrap: wrap; gap: var(--space-2); margin-top: var(--space-2); }
.reference-items--icons { justify-content: flex-end; gap: var(--space-1); }
.reference-item { position: relative; display: inline-flex; align-items: center; gap: var(--space-1); max-width: 100%; border: 0; border-radius: var(--radius-sm); padding: var(--space-1) var(--space-2); color: color-mix(in srgb,var(--text) 75%,transparent); background: color-mix(in srgb,var(--text) 4%,transparent); cursor: pointer; font: inherit; font-size: 12px; }
.reference-item:hover { background: color-mix(in srgb,var(--text) var(--alpha-hover),transparent); }
.reference-item:active { background: color-mix(in srgb,var(--text) var(--alpha-active),transparent); }
.reference-item { color: var(--blue); }
.reference-item span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.reference-item-name { min-width: 0; }
/* user:“底下跟的那一堆成果文件默认折叠一下……多余 6 个的就折叠进去”+(
   “展开其余 N 项/收起”与普通条目同排，虚线边界表明它是操作而不是文件)。 */
.reference-item--more { color: color-mix(in srgb, var(--text) 65%, transparent); background: transparent; border: 1px dashed color-mix(in srgb, var(--text) 18%, transparent); }
.reference-item--more:hover { color: var(--text); background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent); }
.reference-item img { width: 20px; height: 20px; object-fit: cover; border-radius: var(--radius-sm); }
.reference-items--icons .reference-item { width: 32px; height: 32px; justify-content: center; padding: var(--space-1); }
.reference-items--icons .reference-item img { width: 24px; height: 24px; }
.reference-item-error { position: absolute; right: 0; top: 0; color: var(--red); font-weight: 700; }
</style>
