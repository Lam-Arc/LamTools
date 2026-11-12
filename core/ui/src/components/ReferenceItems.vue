<template>
  <div v-if="!previewOnly" v-bind="$attrs" class="reference-items" :class="{ 'reference-items--icons': compact }" :aria-label="compact ? '消息附件' : '本轮成果'">
    <div v-if="heading" class="reference-items-heading">{{ heading }}</div>
    <template v-for="(item, index) in displayedItems" :key="item.id">
      <span v-if="mediaCount > 0 && index === mediaCount" class="reference-row-break" aria-hidden="true"></span>
      <button type="button" class="reference-item" :class="{ 'reference-item--failed': errors[item.id], 'reference-item--media': Boolean(mediaKind(item)) }" :title="[item.name, resolvedPaths[item.id] || item.path, errors[item.id]].filter(Boolean).join('\n')" :aria-label="[item.name, errors[item.id]].filter(Boolean).join('：')" @click="preview(item)" @contextmenu.stop="item.path && !item.path.startsWith('data:') ? actions.menu($event, resolvedPaths[item.id] || item.path) : $event.preventDefault()">
      <template v-if="mediaKind(item)">
        <!-- user:“图片和视频附件以大缩略显示”+(媒体附件直接给大缩略图，非媒体仍用小图标；
             视频用首帧 + 播放标识，点击进入分屏预览)。 -->
        <img v-if="mediaKind(item) === 'image' && thumbnails[item.id] && !errors[item.id]" class="reference-item-media" :src="thumbnails[item.id]" alt="" @error="errors[item.id] = '图片解码失败'">
        <video v-else-if="mediaKind(item) === 'video' && thumbnails[item.id] && !errors[item.id]" class="reference-item-media" :src="`${thumbnails[item.id]}#t=0.1`" muted playsinline preload="metadata" @loadedmetadata="seekVideoFrame" @error="errors[item.id] = '视频无法读取'"></video>
        <span v-else class="reference-item-media-placeholder"><component :is="mediaKind(item) === 'video' ? Play : ImageIcon" :size="22" :stroke-width="1.7" aria-hidden="true" /></span>
        <span class="reference-item-media-shade" aria-hidden="true" />
        <span class="reference-item-media-badge" aria-hidden="true"><Play v-if="mediaKind(item) === 'video'" :size="12" fill="currentColor" :stroke-width="0" /><ImageIcon v-else :size="12" :stroke-width="2" /></span>
        <span class="reference-item-media-name">{{ item.name }}</span>
      </template>
      <template v-else>
        <img v-if="thumbnails[item.id] && !errors[item.id]" :src="thumbnails[item.id]" alt="" @error="errors[item.id] = '图片解码失败'">
        <component :is="item.link ? Link2 : BookOpen" v-else-if="item.link || item.memory" :size="compact ? 18 : 16" :stroke-width="1.6" />
        <FileTypeBadge v-else :name="item.name" :failed="Boolean(errors[item.id])" :size="compact ? 20 : 22" />
        <span v-if="!compact" class="reference-item-copy">
          <span class="reference-item-name">{{ item.name }}</span>
          <span class="reference-item-type">{{ pillType(item) }}</span>
        </span>
      </template>
      <span v-if="errors[item.id]" class="reference-item-error" aria-hidden="true">!</span>
      </button>
    </template>

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
import { BookOpen, Image as ImageIcon, Link2, Play } from 'lucide-vue-next'
import FileTypeBadge from '@/components/FileTypeBadge.vue'
import { t } from '@/i18n/index.ts'
import { useReferenceActions } from '@/helpers/referenceActions'
import { useOptionalSplitWorkspace } from '@/split/useSplitWorkspace'
import { openFileInSplit } from '@/split/openFile'
import { normalizeWebLink } from '@/helpers/webLinks'
import type { CoreAttachment, ToolArtifact } from '@/types'
import type { LamToolsTransport, TransportHttpResponse } from '@/transport'

defineOptions({ inheritAttrs: false })
const props = withDefaults(defineProps<{ attachments?: CoreAttachment[]; artifacts?: ToolArtifact[]; transport: LamToolsTransport; projectId?: string | null; workRoot?: string | null; compact?: boolean; previewOnly?: boolean; heading?: string }>(), { attachments: () => [], artifacts: () => [], heading: '' })
const actions = useReferenceActions(props.transport, () => props.workRoot || '')
const splitWorkspace = useOptionalSplitWorkspace()
type Item = { id: string; name: string; path: string; kind: string; mime: string; attachment?: string; artifactId?: string; link: boolean; memory: boolean; inline?: string }
const items = computed<Item[]>(() => [
  ...props.attachments.map(a => ({ id: a.id, name: a.filename, path: a.path || '', kind: a.preview_type, mime: a.mime_type, attachment: a.id.startsWith('path:') ? undefined : a.id, link: false, memory: false })),
  ...props.artifacts.map((a, index) => {
    const raw = a as ToolArtifact & { artifact_id?: string; name?: string; path?: string; mime_type?: string }
    const metadata = raw.metadata || {}
    const rawPath = String(raw.path || raw.uri || metadata.path || '')
    // 工作区 URI 只是内部标记；显示、解析与分屏预览统一用去掉前缀的相对路径。
    const path = rawPath.startsWith('workspace://') ? rawPath.slice('workspace://'.length) : rawPath
    // user:“把附件预览给做好”+(后端把大图换成了引用条目时，metadata 里的旧 data URL
    // 已经作废；这里也不能再拿它当缩略图，必须按需取字节)。
    const referenceOnly = String(raw.availability || '').trim().toLowerCase() === 'reference'
    return { artifactId: raw.artifact_id, inline: !referenceOnly && typeof metadata.image_data_url === 'string' && metadata.image_data_url.startsWith('data:image') ? metadata.image_data_url : undefined, id: raw.artifact_id || path || `legacy-${index}`, name: raw.name || String(metadata.name || path.split('/').pop() || '文件'), path, kind: raw.kind, mime: raw.mime_type || String(metadata.mime_type || ''), link: Boolean(normalizeWebLink(path)), memory: raw.kind === 'memory' }
  }),
])
const resolvedPaths = reactive<Record<string, string>>({})
const errors = reactive<Record<string, string>>({}), thumbnails = reactive<Record<string, string>>({})
const IMAGE_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'ico', 'svg', 'avif', 'tif', 'tiff'])
const VIDEO_EXTENSIONS = new Set(['mp4', 'webm', 'mov', 'm4v', 'ogv', 'mkv', 'avi'])

// user:“图片和视频附件以大缩略显示”+(按附件/产物的 MIME 与扩展名识别媒体；
// 文档与其它二进制继续走小图标，避免整排都被撑成大卡片)。
function mediaKind(item: Item): 'image' | 'video' | null {
  if (item.link || item.memory) return null
  const ext = item.name.split('.').pop()?.toLowerCase() || ''
  if (item.kind === 'image' || item.mime.startsWith('image/') || IMAGE_EXTENSIONS.has(ext)) return 'image'
  if (item.kind === 'video' || item.mime.startsWith('video/') || VIDEO_EXTENSIONS.has(ext)) return 'video'
  return null
}

/** 已经是最终定位（绝对路径或受管产物目录）就不再走引用解析。 */
function isDirectPath(path: string): boolean {
  return /^[A-Za-z]:[\\/]/.test(path) || path.startsWith('/') || path.startsWith('.lam/')
}

/** 类别标签：成果登记处的中号胶囊显示在文件名下方。 */
function pillType(item: Item): string {
  if (item.link) return '链接'
  if (item.memory) return '记忆'
  const ext = item.name.split('.').pop()?.toLowerCase() || ''
  if (ext && ext !== item.name.toLowerCase()) return ext.toUpperCase()
  return String(item.kind || '文件').toUpperCase()
}

/** 视频缩略图用首帧：加载元数据后跳到 0.1 秒，避免只显示黑底。 */
function seekVideoFrame(event: Event): void {
  const video = event.target
  if (!(video instanceof HTMLVideoElement)) return
  try { video.currentTime = 0.1 } catch { /* Some codecs reject early seeks; the frame stays as-is. */ }
}
// user:“底下跟的那一堆成果文件默认折叠一下，正常显示 6 个，多余 6 个的就折叠进去”+
// (本轮成果/附件列表默认只显示前 6 项，其余收进“展开其余 N 项”按钮；新的一批成果
// 到达时重新折叠，避免上一轮展开状态串到下一轮)。
const COLLAPSED_LIMIT = 6
const expanded = ref(false)
const visibleItems = computed(() => (
  props.compact || expanded.value ? items.value : items.value.slice(0, COLLAPSED_LIMIT)
))
// user:“图片和视频附件以大缩略显示”+(媒体卡片排在前面，文档图标紧跟其后，
// 避免大小卡片混排导致换行参差；翻页/折叠仍按原始条目顺序判定)。
const displayedItems = computed(() => {
  const items = visibleItems.value
  if (!props.compact) return items
  const media = items.filter(item => Boolean(mediaKind(item)))
  const files = items.filter(item => !mediaKind(item))
  return media.length ? [...media, ...files] : items
})
const mediaCount = computed(() => (
  props.compact ? displayedItems.value.filter(item => Boolean(mediaKind(item))).length : 0
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
  // Pending uploads and inline data have no readable file yet; opening them in
  // the split preview would only show an unreadable editor.
  if (/^(pending:|data:|blob:)/i.test(item.path)) return false
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
    if (!item.attachment && item.path && !item.link && !item.memory && !item.inline && !isDirectPath(item.path)) {
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
    if (!mediaKind(item) || thumbnails[item.id]) continue
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
  } else if (!item.attachment && item.path && !item.inline && !resolvedPaths[item.id] && !isDirectPath(item.path)) {
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
.reference-items-heading {
  flex: 0 0 100%;
  margin-bottom: calc(-1 * var(--space-1));
  color: color-mix(in srgb, var(--text) 56%, transparent);
  font-size: 11px;
  line-height: 1.35;
}
.reference-item { position: relative; display: inline-flex; align-items: center; gap: var(--space-1); max-width: 100%; border: 0; border-radius: var(--radius-sm); padding: var(--space-1) var(--space-2); color: var(--blue); background: color-mix(in srgb,var(--text) 4%,transparent); cursor: pointer; font: inherit; font-size: 12px; }
.reference-item:hover { background: color-mix(in srgb,var(--text) var(--alpha-hover),transparent); }
.reference-item:active { background: color-mix(in srgb,var(--text) var(--alpha-active),transparent); }
.reference-item span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.reference-item-name { min-width: 0; }
/* user:“底下跟的那一堆成果文件默认折叠一下……多余 6 个的就折叠进去”+(
   “展开其余 N 项/收起”与普通条目同排，虚线边界表明它是操作而不是文件)。 */
.reference-item--more { color: color-mix(in srgb, var(--text) 65%, transparent); background: transparent; border: 1px dashed color-mix(in srgb, var(--text) 18%, transparent); }
.reference-item--more:hover { color: var(--text); background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent); }
.reference-item img:not(.reference-item-media) { width: 20px; height: 20px; object-fit: cover; border-radius: var(--radius-sm); }
.reference-items--icons .reference-item { width: 32px; height: 32px; justify-content: center; padding: var(--space-1); }
.reference-items--icons .reference-item img:not(.reference-item-media) { width: 24px; height: 24px; }
/* user:“图片和视频附件以大缩略显示”+(媒体卡片固定 108×108，裁切铺满；
   非媒体继续用 32px 小图标，整排仍按气泡右对齐)。 */
.reference-items--icons { justify-content: flex-end; align-items: flex-end; gap: var(--space-2); }
.reference-row-break { flex: 0 0 100%; height: 0; }
/* user:“成果登记处登记胶囊”+(本轮产出改用中号胶囊：类型图标 + 文件名 + 类型标签，
   与输入区的文档胶囊同一套视觉；媒体仍用大卡片)。 */
.reference-items:not(.reference-items--icons) { align-items: flex-end; gap: var(--space-2); }
.reference-items:not(.reference-items--icons) .reference-item:not(.reference-item--media):not(.reference-item--more) {
  height: 34px;
  gap: var(--space-2);
  border: 1px solid color-mix(in srgb, var(--text) 12%, transparent);
  border-radius: 999px;
  padding: 0 var(--space-3) 0 5px;
  background: color-mix(in srgb, var(--text) 5%, transparent);
  color: var(--text);
}
.reference-items:not(.reference-items--icons) .reference-item:not(.reference-item--media):not(.reference-item--more):hover {
  border-color: color-mix(in srgb, var(--text) 22%, transparent);
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
}
.reference-item-copy {
  display: grid;
  min-width: 0;
  gap: 0;
  text-align: left;
}
.reference-item-copy .reference-item-name { font-size: 12px; font-weight: 680; line-height: 1.25; }
.reference-item-copy .reference-item-type {
  color: color-mix(in srgb, var(--text) 58%, transparent);
  font-size: 9px;
  font-weight: 650;
  letter-spacing: .05em;
  line-height: 1.15;
}
.reference-item--media,
.reference-items--icons .reference-item--media {
  position: relative;
  display: block;
  width: 108px;
  height: 108px;
  padding: 0;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--text) 14%, transparent);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--text) 6%, transparent);
  cursor: pointer;
}
.reference-item--media:hover { border-color: color-mix(in srgb, var(--text) 26%, transparent); }
.reference-item--media .reference-item-media {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  border-radius: 0;
  background: color-mix(in srgb, var(--text) 8%, transparent);
}
.reference-item-media-placeholder {
  display: grid;
  width: 100%;
  height: 100%;
  place-items: center;
  color: color-mix(in srgb, var(--text) 62%, transparent);
}
.reference-item-media-shade {
  position: absolute;
  inset: auto 0 0;
  height: 46%;
  background: linear-gradient(to top, color-mix(in srgb, #000 62%, transparent), transparent);
  pointer-events: none;
}
.reference-item-media-name {
  position: absolute;
  right: var(--space-2);
  bottom: var(--space-1);
  left: var(--space-2);
  overflow: hidden;
  color: #fff;
  font-size: 11px;
  font-weight: 650;
  line-height: 1.3;
  text-overflow: ellipsis;
  text-shadow: 0 1px 2px color-mix(in srgb, #000 55%, transparent);
  white-space: nowrap;
}
.reference-item-media-badge {
  position: absolute;
  top: var(--space-1);
  left: var(--space-1);
  display: grid;
  width: 20px;
  height: 20px;
  place-items: center;
  border-radius: 50%;
  background: color-mix(in srgb, #000 48%, transparent);
  color: #fff;
}
.reference-item--media .reference-item-error { right: 4px; top: 4px; font-size: 13px; }
.reference-item-error { position: absolute; right: 0; top: 0; color: var(--red); font-weight: 700; }
</style>
