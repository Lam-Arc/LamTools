<script setup lang="ts">
// user:“过程行读取文件且 MIME 属于多媒体时，在过程行标题下方直接挂内联预览区，不需要用户二次点击展开”
// +(读文件结果里的图片/音视频/文档缩略图直接出现在过程行标题下方，用户不必先展开工具卡再看内容。)
// user:“不要自己实现灯箱……ProcessMediaPreview 只需在点击缩略图时 emit('preview', file)”
// +(本组件不画遮罩、不做缩放旋转：点缩略图只抛出事件，由 MessageView 的全局灯箱承接；
//   图片地址也只用调用方传入的 url，Tauri asset protocol 与按需取字节都在外面解析。)
// user:“文件损坏或加载超时（3s）平滑降级成对应格式的文件类型徽章卡片，绝不出现破图图标”
// +(img/video 报错或 3 秒内没加载出来就换成类型徽章，DOM 里连 <img> 都不再保留。)
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import FileTypeBadge from '@/components/FileTypeBadge.vue'
import { fileExtension } from '@/helpers/fileTypeBadge'
import { t } from '@/i18n/index.ts'

interface ProcessMediaFile {
  path: string
  name?: string
  mime?: string
  size?: number
  /** 已格式化好的体积文案（“1.2 MB”），给了就优先用，省得这里再算一遍。 */
  sizeLabel?: string
  width?: number
  height?: number
  /** 可直接渲染的地址；本组件不做任何路径解析，取不到就降级成徽章。 */
  url?: string
  /** 列表轨用的小图，缺省回落到 url。 */
  thumb?: string
  error?: boolean
}

type MediaKind = 'image' | 'video' | 'audio' | 'document' | 'file'
type CellMode = 'image' | 'video' | 'poster' | 'document' | 'audio' | 'fallback'

interface MediaCell {
  index: number
  file: ProcessMediaFile
  kind: MediaKind
  mode: CellMode
  style: Record<string, string>
  /** 末位遮罩上要显示的剩余张数，0 表示不遮。 */
  more: number
}

const props = withDefaults(defineProps<{
  files: ProcessMediaFile[]
  maxVisible?: number
  mediaHeight?: number
}>(), {
  maxVisible: 5,
  mediaHeight: 96,
})

const emit = defineEmits<{ preview: [file: ProcessMediaFile]; select: [file: ProcessMediaFile] }>()

/** 加载超时：到点还没 load 出来就当坏文件处理，避免过程行一直空着一块。 */
const LOAD_TIMEOUT_MS = 3000
const WAVE_BARS = Array.from({ length: 14 }, (_, index) => index)
const IMAGE_EXT = new Set(['jpg', 'jpeg', 'png', 'webp', 'gif', 'svg', 'avif', 'bmp'])
const VIDEO_EXT = new Set(['mp4', 'webm', 'mov', 'm4v', 'mkv'])
const AUDIO_EXT = new Set(['mp3', 'wav', 'ogg', 'flac', 'm4a', 'aac'])

/** 超时或报错的文件下标；坏掉一个不影响同批其它文件。 */
const failedIndexes = ref<number[]>([])
const timers = new Map<number, ReturnType<typeof setTimeout>>()

function kindOf(file: ProcessMediaFile): MediaKind {
  const mime = String(file.mime || '').toLowerCase()
  if (mime.startsWith('image/')) return 'image'
  if (mime.startsWith('video/')) return 'video'
  if (mime.startsWith('audio/')) return 'audio'
  if (mime === 'application/pdf') return 'document'
  const ext = fileExtension(file.name || file.path || '')
  if (IMAGE_EXT.has(ext)) return 'image'
  if (VIDEO_EXT.has(ext)) return 'video'
  if (AUDIO_EXT.has(ext)) return 'audio'
  if (ext === 'pdf') return 'document'
  return 'file'
}

/** 单文件优先原图（画质），多文件轨道优先缩略图（省内存）。 */
function cellSource(file: ProcessMediaFile): string {
  const url = String(file.url || '').trim()
  const thumb = String(file.thumb || '').trim()
  return props.files.length === 1 ? url || thumb : thumb || url
}

function isFailed(index: number): boolean {
  const file = props.files[index]
  if (!file) return true
  return Boolean(file.error) || failedIndexes.value.includes(index)
}

/** 缩略图地址：视频首帧与 PDF 首页都靠它，没给就各回各的占位/徽章。 */
function thumbSource(file: ProcessMediaFile): string {
  return String(file.thumb || '').trim()
}

/**
 * 一格到底画什么。纯函数：cells 计算与超时兜底都用它，避免两处判断走偏。
 * user:“音视频 mp4/webm……首帧缩略图或波形图占位”+(给了首帧图就直接画图，不拉解码器)。
 */
function modeOf(file: ProcessMediaFile, index: number): CellMode {
  const kind = kindOf(file)
  if (kind === 'audio') return 'audio'
  if (isFailed(index)) return 'fallback'
  if (kind === 'image') return cellSource(file) ? 'image' : 'fallback'
  if (kind === 'video') {
    if (thumbSource(file)) return 'poster'
    return cellSource(file) ? 'video' : 'fallback'
  }
  // user:“ProcessMediaPreview 支持 pdf 类型：无缩略图时显示 PDF 徽章卡片而不是空框”
  // +(PDF 只在给了首页缩略图时才画图，否则一律类型徽章卡片，绝不出现空框。)
  if (kind === 'document') return thumbSource(file) ? 'document' : 'fallback'
  return 'fallback'
}

function aspectRatio(file: ProcessMediaFile): number {
  const width = Number(file.width)
  const height = Number(file.height)
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return 0
  return width / height
}

/** user:“宽度按原图比例自适应，最大不超过容器宽度 60%”+(高度锁定，宽度=高度×宽高比，再用 60% 封顶)。 */
function singleCellStyle(file: ProcessMediaFile): Record<string, string> {
  const style: Record<string, string> = {
    height: `${props.mediaHeight}px`,
    maxWidth: '60%',
  }
  const ratio = aspectRatio(file)
  if (ratio > 0) style.width = `${Math.max(24, Math.round(props.mediaHeight * ratio))}px`
  return style
}

function formatBytes(bytes?: number): string {
  const value = Number(bytes)
  if (!Number.isFinite(value) || value <= 0) return ''
  const units = ['B', 'KB', 'MB', 'GB']
  let size = value
  let unit = 0
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024
    unit += 1
  }
  const digits = unit === 0 || size >= 100 ? 0 : 1
  return `${size.toFixed(digits)} ${units[unit]}`
}

/** 右下角角标：分辨率与体积，两样都没有就不画角标。 */
function metaText(file: ProcessMediaFile): string {
  const parts: string[] = []
  const width = Number(file.width)
  const height = Number(file.height)
  if (Number.isFinite(width) && Number.isFinite(height) && width > 0 && height > 0) parts.push(`${width}×${height}`)
  const size = String(file.sizeLabel || '').trim() || formatBytes(file.size)
  if (size) parts.push(size)
  return parts.join(' · ')
}

function displayName(file: ProcessMediaFile): string {
  const name = String(file.name || '').trim()
  if (name) return name
  const tail = String(file.path || '').split(/[\\/]/).pop() || ''
  return tail || t('文件')
}

function barHeight(bar: number): number {
  return 26 + ((bar * 37) % 62)
}

const cells = computed<MediaCell[]>(() => {
  const single = props.files.length === 1
  const limit = Math.max(1, props.maxVisible)
  const shown = single ? props.files : props.files.slice(0, limit)
  const overflow = single ? 0 : Math.max(0, props.files.length - limit)
  return shown.map((file, index) => ({
    index,
    file,
    kind: kindOf(file),
    mode: modeOf(file, index),
    style: single ? singleCellStyle(file) : { width: '72px', height: '72px' },
    more: overflow > 0 && index === shown.length - 1 ? overflow : 0,
  }))
})

function clearTimer(index: number): void {
  const timer = timers.get(index)
  if (!timer) return
  clearTimeout(timer)
  timers.delete(index)
}

function markFailed(index: number): void {
  clearTimer(index)
  if (!failedIndexes.value.includes(index)) failedIndexes.value = [...failedIndexes.value, index]
}

function onLoaded(index: number): void {
  clearTimer(index)
}

function armTimer(index: number): void {
  const file = props.files[index]
  if (!file) return
  const mode = modeOf(file, index)
  // 只有真去取字节的分支才需要超时兜底：音频波形和徽章卡片都不发请求。
  if (mode !== 'image' && mode !== 'video' && mode !== 'poster' && mode !== 'document') return
  clearTimer(index)
  timers.set(index, setTimeout(() => markFailed(index), LOAD_TIMEOUT_MS))
}

// 一批文件换掉（换消息、重试工具）就整体复位：旧的失败下标与定时器不能带到新文件上。
watch(
  () => props.files.map((file) => `${file.path}|${file.url || ''}|${file.thumb || ''}|${file.error ? 1 : 0}`).join('~'),
  () => {
    failedIndexes.value = []
    for (const timer of timers.values()) clearTimeout(timer)
    timers.clear()
    props.files.forEach((_, index) => armTimer(index))
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  for (const timer of timers.values()) clearTimeout(timer)
  timers.clear()
})

/** 能进灯箱的才抛 preview，其余（文档/坏图）抛 select 让调用方决定怎么打开。 */
function onActivate(index: number): void {
  const file = props.files[index]
  if (!file) return
  const mode = modeOf(file, index)
  if (mode === 'image' || mode === 'video' || mode === 'poster') {
    emit('preview', file)
    return
  }
  emit('select', file)
}
</script>

<template>
  <!-- user:“空列表不渲染”+(没有可预览的文件就整块不出现，过程行里不留空位)。 -->
  <div
    v-if="files.length"
    class="process-media"
    :class="files.length > 1 ? 'process-media--track' : 'process-media--single'"
  >
    <button
      v-for="cell in cells"
      :key="`${cell.index}-${cell.file.path}`"
      type="button"
      class="process-media__cell"
      :style="cell.style"
      :title="displayName(cell.file)"
      :data-media-kind="cell.kind"
      @click="onActivate(cell.index)"
    >
      <img
        v-if="cell.mode === 'image'"
        :src="cellSource(cell.file)"
        :alt="displayName(cell.file)"
        loading="lazy"
        @load="onLoaded(cell.index)"
        @error="markFailed(cell.index)"
      />
      <!-- 视频不自动播放：preload=metadata 拿到首帧当缩略图，点了才由灯箱/外部播放器接手。 -->
      <video
        v-else-if="cell.mode === 'video'"
        :src="cellSource(cell.file)"
        preload="metadata"
        muted
        playsinline
        @loadeddata="onLoaded(cell.index)"
        @error="markFailed(cell.index)"
      ></video>
      <!-- user:“音视频……波形图占位”+(音频没有首帧，用静态波形占位，不额外拉解码器)。 -->
      <div v-else-if="cell.mode === 'audio'" class="process-media__wave" aria-hidden="true">
        <span v-for="bar in WAVE_BARS" :key="bar" :style="{ height: `${barHeight(bar)}%` }" />
      </div>
      <!-- user:“音视频 mp4/webm……首帧缩略图”+(调用方给了首帧图就直接铺图，不再拉解码器)。 -->
      <div v-else-if="cell.mode === 'poster'" class="process-media__poster">
        <img
          :src="thumbSource(cell.file)"
          :alt="displayName(cell.file)"
          loading="lazy"
          @load="onLoaded(cell.index)"
          @error="markFailed(cell.index)"
        />
        <span class="process-media__play" aria-hidden="true"><span class="process-media__play-triangle" /></span>
      </div>
      <!-- user:“ProcessMediaPreview 支持 pdf 类型”+(给了首页缩略图就画图并标 PDF；没给走下面的徽章卡片)。 -->
      <div v-else-if="cell.mode === 'document'" class="process-media__poster process-media__poster--document">
        <img
          :src="thumbSource(cell.file)"
          :alt="displayName(cell.file)"
          loading="lazy"
          @load="onLoaded(cell.index)"
          @error="markFailed(cell.index)"
        />
        <span class="process-media__doc-chip">PDF</span>
      </div>
      <!-- 坏文件、超时、无地址、非多媒体：一律类型徽章卡片，绝不出现破图图标。 -->
      <div v-else class="process-media__fallback">
        <FileTypeBadge :name="displayName(cell.file)" :size="18" :failed="isFailed(cell.index)" />
        <span class="process-media__fallback-name">{{ displayName(cell.file) }}</span>
        <span v-if="metaText(cell.file)" class="process-media__fallback-meta">{{ metaText(cell.file) }}</span>
      </div>
      <span v-if="cell.mode !== 'fallback' && metaText(cell.file)" class="process-media__meta">{{ metaText(cell.file) }}</span>
      <!-- user:“超过 5 张时末位显示 +N 遮罩”+(第 maxVisible 张盖上剩余张数，横向轨到此为止)。 -->
      <span
        v-if="cell.more"
        class="process-media__more"
        :aria-label="t('还有 {count} 个文件', { count: cell.more })"
      >+{{ cell.more }}</span>
    </button>
  </div>
</template>

<style src="../../styles/process-media.css"></style>
