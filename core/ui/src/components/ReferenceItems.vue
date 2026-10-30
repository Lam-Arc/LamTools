<template>
  <div v-if="!previewOnly" v-bind="$attrs" class="reference-items" :class="{ 'reference-items--icons': compact }" :aria-label="compact ? '消息附件' : '本轮成果'">
    <button v-for="item in items" :key="item.id" type="button" class="reference-item" :class="{ 'reference-item--link': item.link, 'reference-item--failed': errors[item.id] }" :title="[item.name, resolvedPaths[item.id] || item.path, errors[item.id]].filter(Boolean).join('\n')" :aria-label="[item.name, errors[item.id]].filter(Boolean).join('：')" @click="preview(item)" @contextmenu.stop="item.path && !item.path.startsWith('data:') ? actions.menu($event, resolvedPaths[item.id] || item.path) : $event.preventDefault()">
      <img v-if="thumbnails[item.id] && !errors[item.id]" :src="thumbnails[item.id]" alt="" @error="errors[item.id] = '图片解码失败'">
      <component :is="item.link ? Link2 : item.memory ? BookOpen : kindIcon(item.kind, item.name)" v-else :size="compact ? 18 : 15" :stroke-width="1.6" />
      <span v-if="!compact">{{ item.link ? item.name : '@' + item.name }}</span>
      <span v-if="errors[item.id]" class="reference-item-error" aria-hidden="true">!</span>
    </button>
  </div>
  <Teleport to="body">
    <div v-if="selected" class="reference-preview-overlay" @click.self="close" @keydown.esc="close">
      <section ref="dialog" class="reference-preview" role="dialog" aria-modal="true" :aria-label="selected.name" tabindex="-1" @keydown="onPreviewKeydown">
        <header>
          <span :title="selected.path">{{ selected.name }}</span>
          <span v-if="selected.kind === 'image' && previewUrl" class="reference-preview-zoom" role="group" aria-label="调整预览大小">
            <button type="button" aria-label="缩小预览" title="缩小" @click="zoomBy(-25)">−</button>
            <span class="reference-preview-zoom-value" aria-live="polite">{{ previewZoom }}%</span>
            <button type="button" aria-label="放大预览" title="放大" @click="zoomBy(25)">+</button>
            <button type="button" aria-label="适应预览大小" title="适应窗口" @click="fitPreview">适应</button>
          </span>
          <button type="button" @click="actions.menu($event, selected.path)">操作</button>
          <button type="button" aria-label="关闭预览" @click="close">×</button>
        </header>
        <p v-if="loading" role="status">正在读取…</p>
        <p v-else-if="previewError" role="alert">{{ previewError }}</p>
        <div v-else-if="selected.kind === 'image' && previewUrl" class="reference-preview-stage">
          <img
            :src="previewUrl"
            :alt="selected.name"
            :style="{ width: `${previewZoom}%` }"
            @error="previewError = '图片解码失败，原文件可能格式不受支持或内容已损坏'"
          >
        </div>
        <pre v-else-if="previewText !== null">{{ previewText }}</pre>
        <button v-else type="button" @click="actions.open(selected.path)">使用默认应用打开</button>
      </section>
    </div>
  </Teleport>
</template>
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { BookOpen, Link2 } from 'lucide-vue-next'
import { kindIcon } from '@/artifacts/model'
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
const selected = ref<Item | null>(null), dialog = ref<HTMLElement>(), loading = ref(false), previewError = ref(''), previewText = ref<string | null>(null), previewUrl = ref('')
const owned = new Set<string>()
let generation = 0, previewGeneration = 0, previousFocus: HTMLElement | null = null
// user:“图片按比例展示，支持调整预览大小”+(图片宽度按百分比缩放、高度自适应保持比例，
// 用户可用按钮或 +/- 键调整预览大小，0 键回到适应窗口)。
const previewZoom = ref(100)
const PREVIEW_ZOOM_STEP = 25
const PREVIEW_ZOOM_MIN = 25
const PREVIEW_ZOOM_MAX = 400
function zoomBy(delta: number) {
  previewZoom.value = Math.min(PREVIEW_ZOOM_MAX, Math.max(PREVIEW_ZOOM_MIN, previewZoom.value + delta))
}
function fitPreview() {
  previewZoom.value = 100
}
function onPreviewKeydown(event: KeyboardEvent) {
  if (event.key === '+' || event.key === '=') { event.preventDefault(); zoomBy(PREVIEW_ZOOM_STEP) }
  else if (event.key === '-' || event.key === '_') { event.preventDefault(); zoomBy(-PREVIEW_ZOOM_STEP) }
  else if (event.key === '0') { event.preventDefault(); fitPreview() }
}
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
// 图片、音视频、PDF、Office 用预览器，文本用编辑器；分屏用不了才回落到弹窗预览)。
function previewInSplit(item: Item): boolean {
  if (!splitWorkspace || !item.path || item.link || item.memory) return false
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
  previousFocus = document.activeElement as HTMLElement
  selected.value = item; loading.value = true; previewError.value = errors[item.id] || ''; previewText.value = null; previewUrl.value = ''; previewZoom.value = 100
  const run = ++previewGeneration
  await nextTick(); dialog.value?.focus()
  try {
    previewError.value = ''
    delete errors[item.id]
    if (!item.attachment && item.path && !item.memory && !item.inline) {
      const actual = await actions.resolve(item.path)
      if (run !== previewGeneration) return
      item.path = actual; resolvedPaths[item.id] = actual
    }
    if (item.kind === 'image' && item.inline) previewUrl.value = item.inline
    else if (item.kind === 'image') { const response = await bytes(item); if (run === previewGeneration) previewUrl.value = blobUrl(response, item.mime) }
    else if (/^(?:text\/|application\/(?:json|xml))/.test(item.mime) || /\.(md|txt|log|jsonc?|ya?ml|csv|py|rs|ts|js)$/i.test(item.name)) {
      const response = await bytes(item); if (run === previewGeneration) previewText.value = new TextDecoder().decode(response.body.slice(0, 200000))
    }
  } catch (error) { if (run === previewGeneration) previewError.value = error instanceof Error ? error.message : '预览失败' }
  finally { if (run === previewGeneration) loading.value = false }
}
function close() {
  ++previewGeneration; selected.value = null
  if (owned.delete(previewUrl.value)) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = ''; previousFocus?.focus()
}
onBeforeUnmount(() => { ++generation; ++previewGeneration; for (const url of owned) URL.revokeObjectURL(url) })
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
.reference-item img { width: 20px; height: 20px; object-fit: cover; border-radius: var(--radius-sm); }
.reference-items--icons .reference-item { width: 32px; height: 32px; justify-content: center; padding: var(--space-1); }
.reference-items--icons .reference-item img { width: 24px; height: 24px; }
.reference-item-error { position: absolute; right: 0; top: 0; color: var(--red); font-weight: 700; }
.reference-preview-overlay { position: fixed; inset: 0; z-index: var(--z-modal); background: color-mix(in srgb,var(--theme-backdrop-text) 20%,transparent); display: grid; place-items: center; padding: var(--space-4); }
/* user:“图片预览默认放大”+(预览面板默认就按更大尺寸打开，图片不再挤在小窗里)。 */
.reference-preview { display: flex; flex-direction: column; width: min(1280px,94vw); max-height: 90vh; padding: var(--space-3); gap: var(--space-2); border-radius: var(--radius); background: var(--theme-main-background); color: var(--theme-main-text); box-shadow: var(--shadow-lg); overflow: auto; }
.reference-preview header { display: flex; gap: var(--space-2); align-items: center; }
.reference-preview header span { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.reference-preview button { border: 0; border-radius: var(--radius-sm); padding: var(--space-1) var(--space-2); background: var(--theme-control-background); color: var(--theme-control-text); }
.reference-preview-zoom { display: flex; flex: 0 0 auto; align-items: center; gap: var(--space-1); }
.reference-preview-zoom-value { flex: 0 0 auto; min-width: 42px; color: color-mix(in srgb,var(--theme-main-text) 70%,transparent); font-size: 12px; text-align: center; }
.reference-preview-stage { display: block; flex: 1 1 auto; min-height: 0; max-height: 78vh; overflow: auto; }
/* user:“图片按比例展示，支持调整预览大小”+(宽度由缩放比例决定，高度自动，保持原始比例)。 */
.reference-preview-stage img { display: block; max-width: none; min-height: 0; height: auto; margin: 0 auto; object-fit: contain; }
.reference-preview pre { white-space: pre-wrap; overflow-wrap: anywhere; font: 13px/1.6 var(--font-mono); }
</style>
