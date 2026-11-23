<template>
  <div class="preview-image" :class="{ 'is-annotating': annotating }" data-preview-image :data-annotations="annotations.length">
    <!-- user:“默认大小自适应”+(打开就装进这块容器：大图缩小、小图保持 1:1，和原来浏览器
         自带查看器给人的第一眼一致，不给一个铺满又糊掉的图)。
         user:“把ctrl加滚轮改成滚轮控制”+(舞台负责手势：滚轮直接以光标为锚缩放，
         左键拖动平移，标注模式下左键改成画标注)。 -->
    <div
      ref="stageEl"
      class="preview-image__stage"
      :class="{ 'is-panning': panning, 'is-drawing': Boolean(drawing) }"
      tabindex="-1"
      role="group"
      :aria-label="`图片预览：${name}`"
      @wheel.prevent="onWheel"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="onPointerUp"
      @dblclick="onDoubleClick"
      @keydown="onStageKeydown"
    >
      <img
        v-if="src"
        :key="imgKey"
        ref="imgEl"
        class="preview-image__img"
        :src="src"
        :alt="name"
        :style="imgStyle"
        draggable="false"
        @load="onImageLoad"
        @error="onImageError"
      />
      <!-- 标注画在覆盖画布上：用图片坐标 + 当前视图变换，缩放/拖动后不糊也不偏。 -->
      <canvas ref="marksEl" class="preview-image__marks" aria-hidden="true" />

      <div v-if="!ready && !failure" class="preview-image__status" role="status">
        <span class="preview-image__spinner" aria-hidden="true" />
        <span>正在载入图片…</span>
      </div>
      <p v-if="failure" class="preview-image__error" role="alert">
        <span>{{ failure }}</span>
        <button type="button" @click="reload">重试</button>
      </p>
    </div>

    <textarea
      v-if="draft"
      ref="draftEl"
      v-model="draft.value"
      class="preview-image__draft"
      :style="draftStyle"
      rows="1"
      placeholder="输入文字，回车确认"
      @keydown="onDraftKeydown"
      @blur="onDraftBlur"
    />

    <!-- 底部工具坞：标注工具条在上，缩放条在下，都贴着图片区底部居中。 -->
    <div class="preview-image__dock">
      <div v-if="annotating" class="preview-image__panel" data-preview-annotate-tools>
        <AnnotationToolbar
          v-model:tool="tool"
          v-model:color="pickedColor"
          :can-undo="annotations.length > 0"
          :can-redo="redoStack.length > 0"
          :disabled="!ready"
          @undo="undo"
          @redo="redo"
          @clear="clearAll"
        >
          <template #end>
            <button
              type="button"
              class="preview-image__tool preview-image__tool--exit"
              title="退出标注 · Esc"
              aria-label="退出标注"
              @click="exitAnnotate"
            >
              <X :size="15" :stroke-width="1.9" aria-hidden="true" />
            </button>
          </template>
        </AnnotationToolbar>
      </div>

      <div class="preview-image__panel preview-image__zoom" role="toolbar" aria-label="图片缩放">
        <button type="button" class="preview-image__tool" title="缩小" aria-label="缩小" :disabled="!ready" @click="zoomBy(1 / ZOOM_STEP)">
          <Minus :size="15" :stroke-width="1.9" aria-hidden="true" />
        </button>
        <span class="preview-image__percent" aria-live="polite" data-preview-zoom-percent>{{ percent }}%</span>
        <button type="button" class="preview-image__tool" title="放大" aria-label="放大" :disabled="!ready" @click="zoomBy(ZOOM_STEP)">
          <Plus :size="15" :stroke-width="1.9" aria-hidden="true" />
        </button>
        <span class="preview-image__sep" aria-hidden="true" />
        <button type="button" class="preview-image__text" title="适应窗口 · 按 0" aria-label="适应窗口" :disabled="!ready" @click="fit">适应</button>
        <button type="button" class="preview-image__text" title="实际像素" aria-label="实际像素" :disabled="!ready" @click="actualSize">1:1</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 灯箱里的图片查看器（原生 `<img>`，不再交给浏览器自带的图片文档）。
 *
 * user:“灯箱应该配套缩放UI，支持Ctrl滚轮，提供复制/外部打开键，默认大小自适应，左键可拖动”+
 * user:“把ctrl加滚轮改成滚轮控制”+(滚轮不再需要修饰键，直接以光标为锚缩放)。
 * (自带缩放条与手势；复制/外部打开/引用这类“对这个文件做什么”的动作留在灯箱头部，
 *  这里只负责把图画好、把标注画上去，并对外交出合成好的图)。
 *
 * user:“支持修改标注（可以复用ping的框选那里的标注功能与样式，将这一个功能抽出来共用）”+
 * (工具条与绘制来自 `@/annotation/*`，与 Ping 截图编辑器同一份实现、同一套颜色与比例)。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch, type CSSProperties } from 'vue'
import { Minus, Plus, X } from 'lucide-vue-next'
import AnnotationToolbar from '@/annotation/AnnotationToolbar.vue'
import { drawAnnotation, drawAnnotations } from '@/annotation/draw'
import { renderAnnotatedPng } from '@/annotation/export'
import { annotationColor, createAnnotation, type Annotation, type AnnotationTool } from '@/annotation/model'
import {
  centeredView,
  clampScale,
  clampView,
  fitScale,
  imageToScreen,
  scaleAt,
  screenToImage,
  zoomAtCenter,
  type ImageView,
  type ViewPoint,
  type ViewSize,
} from './imageView'

const props = withDefaults(defineProps<{
  src: string
  /** 文件名：alt 文本与提示都用它。 */
  name?: string
  /** 标注模式开关由宿主（灯箱头部）控制。 */
  annotating?: boolean
  /**
   * 原始字节：合成标注图时用它重新解码。
   *
   * user:“『引用』…已标注…直接加入输入框”+(界面里的图片来自后台地址，和界面不同源；
   * 直接画到画布上会被判成污染源、导出直接失败。所以合成时改用预览通道读到的字节
   * 走 blob 地址解码，等于同源图片)。
   */
  loadOriginal?: (() => Promise<Blob>) | null
  /** 图片解码/加载超时；测试里可以调小。 */
  loadTimeoutMs?: number
}>(), {
  name: '图片',
  annotating: false,
  loadOriginal: null,
  loadTimeoutMs: 20000,
})

const emit = defineEmits<{
  'update:annotating': [value: boolean]
  /** 标注数量变化：灯箱据此决定「复制/引用」要不要提示“已标注”。 */
  'annotations-change': [count: number]
}>()

const ZOOM_STEP = 1.25
/** 指针拖出这么远才算真的画了一条，避免一次误点留下看不见的标注。 */
const MIN_DRAG_SCREEN = 4

const stageEl = ref<HTMLElement | null>(null)
const imgEl = ref<HTMLImageElement | null>(null)
const marksEl = ref<HTMLCanvasElement | null>(null)
const draftEl = ref<HTMLTextAreaElement | null>(null)

const imgKey = ref(0)
const ready = ref(false)
const failure = ref('')
const natural = ref<ViewSize>({ width: 0, height: 0 })
const viewport = ref<ViewSize>({ width: 0, height: 0 })
const view = ref<ImageView>({ scale: 1, x: 0, y: 0 })
/** 自适应状态：还没被手动缩放/平移过，就在窗口变化时重新装一次。 */
const fitMode = ref(true)
const panning = ref(false)
const annotations = ref<Annotation[]>([])
const redoStack = ref<Annotation[]>([])
const tool = ref<AnnotationTool>('arrow')
const pickedColor = ref<string | null>(null)
const drawing = ref<Annotation | null>(null)
const draft = ref<{ x: number; y: number; value: string } | null>(null)
const nextId = ref(1)

let panStart: { clientX: number; clientY: number; x: number; y: number } | null = null
let drawStart: { clientX: number; clientY: number } | null = null
let stageObserver: ResizeObserver | null = null
let loadTimer: ReturnType<typeof setTimeout> | undefined

const percent = computed(() => Math.round(view.value.scale * 100))
const draftStyle = computed(() => {
  const current = draft.value
  if (!current) return {}
  const point = imageToScreen(view.value, current)
  return { left: `${point.x}px`, top: `${point.y}px` }
})
const imgStyle = computed<CSSProperties>(() => ({
  width: `${natural.value.width}px`,
  height: `${natural.value.height}px`,
  transform: `translate(${view.value.x}px, ${view.value.y}px) scale(${view.value.scale})`,
  visibility: ready.value ? 'visible' : 'hidden',
}))

function clearLoadTimer(): void {
  if (loadTimer !== undefined) { clearTimeout(loadTimer); loadTimer = undefined }
}

function armLoadTimer(): void {
  clearLoadTimer()
  if (!Number.isFinite(props.loadTimeoutMs) || props.loadTimeoutMs <= 0) return
  loadTimer = setTimeout(() => {
    loadTimer = undefined
    if (!ready.value) failure.value = '图片在预期时间内没有载入，可能是文件不存在或格式不受支持'
  }, props.loadTimeoutMs)
}

/** 重新计算「装得下」的位置：只有还在自适应状态下，窗口变化才跟着重排。 */
function applyFit(): void {
  const stage = stageEl.value
  if (!stage || !natural.value.width) return
  viewport.value = { width: stage.clientWidth, height: stage.clientHeight }
  view.value = centeredView(natural.value, viewport.value, fitScale(natural.value, viewport.value))
  redraw()
}

function fit(): void {
  fitMode.value = true
  applyFit()
}

function actualSize(): void {
  const stage = stageEl.value
  if (!stage) return
  fitMode.value = false
  viewport.value = { width: stage.clientWidth, height: stage.clientHeight }
  view.value = scaleAt(view.value, natural.value, viewport.value, 1, {
    x: viewport.value.width / 2,
    y: viewport.value.height / 2,
  })
  redraw()
}

function zoomBy(factor: number): void {
  const stage = stageEl.value
  if (!stage) return
  fitMode.value = false
  viewport.value = { width: stage.clientWidth, height: stage.clientHeight }
  view.value = zoomAtCenter(view.value, natural.value, viewport.value, factor)
  redraw()
}

function onWheel(event: WheelEvent): void {
  const stage = stageEl.value
  if (!stage || !ready.value) return
  // user:“把ctrl加滚轮改成滚轮控制”+(滚轮直接缩放，不再需要按住 Ctrl；光标指哪就缩哪)。
  // deltaMode 依设备不同可能是行或页，先归一到像素，触控板的细碎增量仍然跟手。
  const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? 100 : 1
  const rect = stage.getBoundingClientRect()
  const anchor: ViewPoint = { x: event.clientX - rect.left, y: event.clientY - rect.top }
  const factor = Math.exp(-event.deltaY * unit * 0.0018)
  if (!Number.isFinite(factor) || factor <= 0) return
  fitMode.value = false
  viewport.value = { width: stage.clientWidth, height: stage.clientHeight }
  view.value = scaleAt(view.value, natural.value, viewport.value, view.value.scale * factor, anchor)
  redraw()
}

const canPan = computed(() => (
  natural.value.width * view.value.scale > viewport.value.width + 0.5
  || natural.value.height * view.value.scale > viewport.value.height + 0.5
))

function stageRect(): DOMRect | null {
  return stageEl.value?.getBoundingClientRect() ?? null
}

function eventPoint(event: PointerEvent): ViewPoint | null {
  const rect = stageRect()
  if (!rect) return null
  return { x: event.clientX - rect.left, y: event.clientY - rect.top }
}

function onPointerDown(event: PointerEvent): void {
  if (event.button !== 0 || !ready.value) return
  const stage = stageEl.value
  if (!stage) return
  if (props.annotating) {
    const point = eventPoint(event)
    if (!point) return
    const imagePoint = screenToImage(view.value, point)
    if (tool.value === 'text') {
      // user:“文字不可用，点击后无文字框”+(浏览器在 pointerdown 之后会把焦点抢到舞台，
      // 刚出现的文字框立刻 blur 被当成“空文本”提交掉；先挡住这次默认聚焦)。
      event.preventDefault()
      draft.value = { x: imagePoint.x, y: imagePoint.y, value: '' }
      void nextTick(() => draftEl.value?.focus())
      return
    }
    stage.setPointerCapture?.(event.pointerId)
    drawing.value = createAnnotation(nextId.value++, tool.value, imagePoint, annotationColor(tool.value, pickedColor.value))
    drawStart = { clientX: event.clientX, clientY: event.clientY }
    if (tool.value === 'question' || tool.value === 'exclamation') commitDrawing()
    redraw()
    return
  }
  if (!canPan.value) return
  panning.value = true
  panStart = { clientX: event.clientX, clientY: event.clientY, x: view.value.x, y: view.value.y }
  stage.setPointerCapture?.(event.pointerId)
}

function onPointerMove(event: PointerEvent): void {
  const stage = stageEl.value
  if (!stage) return
  if (drawing.value) {
    const point = eventPoint(event)
    if (!point) return
    const imagePoint = screenToImage(view.value, point)
    if (drawing.value.tool === 'arrow') drawing.value.points = [drawing.value.points[0], imagePoint]
    else drawing.value.points = [...drawing.value.points, imagePoint]
    redraw()
    return
  }
  if (panning.value && panStart) {
    view.value = clampView(
      { scale: view.value.scale, x: panStart.x + (event.clientX - panStart.clientX), y: panStart.y + (event.clientY - panStart.clientY) },
      natural.value,
      viewport.value,
    )
    fitMode.value = false
    redraw()
  }
}

function onPointerUp(event: PointerEvent): void {
  if (drawing.value) {
    const start = drawStart
    const distance = start ? Math.hypot(event.clientX - start.clientX, event.clientY - start.clientY) : Infinity
    // 一次误点不应该留下一条看不见的箭头/一个点的涂鸦。
    if (drawing.value.tool === 'arrow' || drawing.value.tool === 'pen') {
      if (distance < MIN_DRAG_SCREEN) { drawing.value = null; redraw(); return }
    }
    commitDrawing()
  }
  if (panning.value) {
    panning.value = false
    panStart = null
  }
}

function commitDrawing(): void {
  const current = drawing.value
  drawing.value = null
  drawStart = null
  if (!current) return
  annotations.value = [...annotations.value, current]
  redoStack.value = []
  emit('annotations-change', annotations.value.length)
  redraw()
}

/**
 * user:“文字不可用，点击后无文字框”+(点击舞台带来的默认聚焦不等于“结束输入”：
 * 焦点落到舞台上就把焦点还给文字框，只有真的点到别处才提交)。
 */
function onDraftBlur(event: FocusEvent): void {
  const next = event.relatedTarget as Node | null
  const stage = stageEl.value
  if (draft.value && next && stage && (next === stage || stage.contains(next))) {
    void nextTick(() => draftEl.value?.focus())
    return
  }
  commitText()
}

function commitText(): void {
  const current = draft.value
  const value = current?.value.trim()
  draft.value = null
  if (!current || !value) return
  annotations.value = [...annotations.value, {
    id: nextId.value++,
    tool: 'text',
    points: [{ x: current.x, y: current.y }],
    text: value,
    color: annotationColor('text', pickedColor.value),
  }]
  redoStack.value = []
  emit('annotations-change', annotations.value.length)
  redraw()
}

function onDraftKeydown(event: KeyboardEvent): void {
  // 文字输入里的 Esc 只取消这段文字，不许顺手把整个灯箱关掉。
  if (event.key === 'Escape') { event.stopPropagation(); draft.value = null; return }
  if (event.key === 'Enter') { event.preventDefault(); commitText() }
}

function undo(): void {
  const last = annotations.value[annotations.value.length - 1]
  if (!last) return
  annotations.value = annotations.value.slice(0, -1)
  redoStack.value = [...redoStack.value, last]
  emit('annotations-change', annotations.value.length)
  redraw()
}

function redo(): void {
  const last = redoStack.value[redoStack.value.length - 1]
  if (!last) return
  redoStack.value = redoStack.value.slice(0, -1)
  annotations.value = [...annotations.value, last]
  emit('annotations-change', annotations.value.length)
  redraw()
}

function clearAll(): void {
  annotations.value = []
  redoStack.value = []
  emit('annotations-change', 0)
  redraw()
}

function exitAnnotate(): void {
  draft.value = null
  drawing.value = null
  emit('update:annotating', false)
}

function onDoubleClick(): void {
  if (props.annotating || !ready.value) return
  // 双击在「装得下」和「实际像素」之间来回切，和常见查看器一致。
  if (fitMode.value) actualSize()
  else fit()
}

function onStageKeydown(event: KeyboardEvent): void {
  if (event.key === '+' || event.key === '=') { event.preventDefault(); zoomBy(ZOOM_STEP); return }
  if (event.key === '-' || event.key === '_') { event.preventDefault(); zoomBy(1 / ZOOM_STEP); return }
  if (event.key === '0') { event.preventDefault(); fit(); return }
  if (event.key === 'Escape' && props.annotating) { event.stopPropagation(); exitAnnotate() }
}

/** 画布尺寸跟着舞台走；绘制坐标系用「图片像素」，由变换矩阵负责缩放。 */
function redraw(): void {
  const canvas = marksEl.value
  const stage = stageEl.value
  if (!canvas || !stage) return
  const width = stage.clientWidth
  const height = stage.clientHeight
  if (!width || !height) return
  const ratio = window.devicePixelRatio || 1
  canvas.width = Math.max(1, Math.round(width * ratio))
  canvas.height = Math.max(1, Math.round(height * ratio))
  canvas.style.width = `${width}px`
  canvas.style.height = `${height}px`
  const context = canvas.getContext('2d')
  if (!context) return
  context.setTransform(1, 0, 0, 1, 0, 0)
  context.clearRect(0, 0, canvas.width, canvas.height)
  if (!annotations.value.length && !drawing.value) return
  context.setTransform(
    ratio * view.value.scale, 0, 0, ratio * view.value.scale,
    ratio * view.value.x, ratio * view.value.y,
  )
  drawAnnotations(context, annotations.value, natural.value.width)
  if (drawing.value) drawAnnotation(context, drawing.value, natural.value.width)
}

function onImageLoad(): void {
  clearLoadTimer()
  const image = imgEl.value
  if (!image) return
  natural.value = { width: image.naturalWidth, height: image.naturalHeight }
  ready.value = true
  failure.value = ''
  fitMode.value = true
  void nextTick(() => {
    applyFit()
    observeStage()
  })
}

function onImageError(): void {
  clearLoadTimer()
  ready.value = false
  failure.value = '图片解码失败，原文件可能格式不受支持或内容已损坏'
}

function reload(): void {
  failure.value = ''
  ready.value = false
  natural.value = { width: 0, height: 0 }
  imgKey.value += 1
  armLoadTimer()
}

function observeStage(): void {
  const stage = stageEl.value
  if (!stage || typeof ResizeObserver === 'undefined') return
  stageObserver?.disconnect()
  stageObserver = new ResizeObserver(() => {
    viewport.value = { width: stage.clientWidth, height: stage.clientHeight }
    if (fitMode.value) applyFit()
    else view.value = clampView(view.value, natural.value, viewport.value)
    redraw()
  })
  stageObserver.observe(stage)
}

function focusStage(): void {
  stageEl.value?.focus()
}

/** 有没有标注：没有就交出原图，有就交出合成图（灯箱据此决定复制/引用哪一份）。 */
function hasAnnotations(): boolean {
  return annotations.value.length > 0
}

/** 合成一张带标注的 PNG（图片原始像素）。 */
async function exportBlob(): Promise<Blob> {
  const width = natural.value.width
  const height = natural.value.height
  if (!width) throw new Error('图片还没有载入')
  const load = props.loadOriginal
  if (!load) {
    const element = imgEl.value
    if (!element) throw new Error('图片还没有载入')
    return renderAnnotatedPng({ image: element, width, height, annotations: annotations.value })
  }
  const blob = await load()
  const url = URL.createObjectURL(blob)
  try {
    const image = new Image()
    image.src = url
    await image.decode().catch(() => undefined)
    if (!image.naturalWidth || !image.naturalHeight) throw new Error('图片无法解码，不能合成标注图')
    return await renderAnnotatedPng({ image, width, height, annotations: annotations.value })
  } finally {
    URL.revokeObjectURL(url)
  }
}

watch(() => props.src, () => {
  annotations.value = []
  redoStack.value = []
  draft.value = null
  drawing.value = null
  emit('annotations-change', 0)
  reload()
}, { immediate: true })

watch(() => props.annotating, () => {
  // 进入标注时把焦点放到舞台上，Esc 先退出标注；
  // 退出时也放回舞台：工具条一卸载，焦点会掉到 body，「Esc 关灯箱」就失效了。
  void nextTick(focusStage)
  if (!props.annotating) { draft.value = null; drawing.value = null }
})

watch(view, redraw, { deep: true })

onMounted(() => {
  armLoadTimer()
  observeStage()
  redraw()
})

onBeforeUnmount(() => {
  clearLoadTimer()
  stageObserver?.disconnect()
  stageObserver = null
})

defineExpose({ hasAnnotations, exportBlob, fit, zoomBy, reload, focusStage })
</script>

<style scoped>
.preview-image {
  position: relative;
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  background: var(--theme-main-sunken-background);
  overflow: hidden;
}

.preview-image__stage {
  position: relative;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
  outline: none;
  cursor: grab;
  touch-action: none;
}

.preview-image__stage.is-panning {
  cursor: grabbing;
}

.preview-image__stage.is-drawing {
  cursor: crosshair;
}

.preview-image__img {
  position: absolute;
  top: 0;
  left: 0;
  max-width: none;
  user-select: none;
  -webkit-user-drag: none;
  transform-origin: 0 0;
  will-change: transform;
}

.preview-image__marks {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.preview-image__status {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  color: color-mix(in srgb, var(--theme-main-text) 62%, transparent);
  font-size: 12px;
  pointer-events: none;
}

.preview-image__spinner {
  width: 14px;
  height: 14px;
  border: 2px solid color-mix(in srgb, var(--theme-main-text) 24%, transparent);
  border-top-color: color-mix(in srgb, var(--theme-main-text) 68%, transparent);
  border-radius: 50%;
  animation: preview-image-spin 900ms linear infinite;
}

@keyframes preview-image-spin {
  to { transform: rotate(360deg); }
}

.preview-image__error {
  position: absolute;
  inset: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-4);
  color: color-mix(in srgb, var(--theme-main-text) 78%, transparent);
  font-size: 12px;
  text-align: center;
}

.preview-image__error button {
  height: 26px;
  border: 0;
  border-radius: 999px;
  padding: 0 var(--space-3);
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), transparent);
  color: var(--theme-main-text);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

/* 文字块输入框贴着点击位置，样式与 Ping 截图编辑器一致。 */
.preview-image__draft {
  position: absolute;
  z-index: 3;
  min-width: 160px;
  max-width: 320px;
  margin: 0;
  padding: 4px 8px;
  border: 1px solid rgba(238, 243, 251, 0.28);
  border-radius: 8px;
  background: rgba(8, 10, 14, 0.85);
  color: #f4f7ff;
  font: inherit;
  font-size: 13px;
  line-height: 1.4;
  resize: none;
  outline: none;
  box-shadow: 0 10px 24px rgba(0, 0, 0, 0.35);
}

.preview-image__draft::placeholder {
  color: rgba(238, 243, 251, 0.45);
}

.preview-image__dock {
  position: absolute;
  left: 50%;
  bottom: var(--space-3);
  z-index: 2;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  transform: translateX(-50%);
  pointer-events: none;
}

.preview-image__panel {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 4px;
  border: 1px solid color-mix(in srgb, var(--theme-main-text) 12%, transparent);
  border-radius: 999px;
  background: color-mix(in srgb, var(--theme-main-background) 92%, transparent);
  -webkit-backdrop-filter: blur(14px) saturate(1.1);
  backdrop-filter: blur(14px) saturate(1.1);
  box-shadow: var(--shadow-sm);
  pointer-events: auto;
  /* 共用工具条换皮：Ping 用截图窗口的深色玻璃，灯箱跟会话主题走。 */
  --annotation-fg: color-mix(in srgb, var(--theme-main-text) 62%, transparent);
  --annotation-fg-strong: var(--theme-main-text);
  --annotation-hover: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), transparent);
  --annotation-active: color-mix(in srgb, var(--theme-main-text) var(--alpha-active), transparent);
  --annotation-divider: color-mix(in srgb, var(--theme-main-text) 14%, transparent);
  --annotation-menu-bg: color-mix(in srgb, var(--theme-main-background) 96%, transparent);
  --annotation-menu-border: color-mix(in srgb, var(--theme-main-text) 14%, transparent);
  --annotation-swatch-active-ring: var(--theme-main-background);
}

.preview-image__tool {
  flex: none;
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text) 66%, transparent);
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}

.preview-image__tool:hover:enabled {
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), transparent);
  color: var(--theme-main-text);
}

.preview-image__tool:disabled {
  opacity: 0.45;
  cursor: default;
}

.preview-image__tool--exit {
  margin-left: 2px;
}

.preview-image__percent {
  min-width: 42px;
  text-align: center;
  color: color-mix(in srgb, var(--theme-main-text) 70%, transparent);
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
}

.preview-image__sep {
  width: 1px;
  height: 16px;
  margin: 0 4px;
  background: color-mix(in srgb, var(--theme-main-text) 16%, transparent);
}

.preview-image__text {
  flex: none;
  height: 28px;
  padding: 0 var(--space-2);
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text) 66%, transparent);
  font: inherit;
  font-size: 11.5px;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}

.preview-image__text:hover:enabled {
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), transparent);
  color: var(--theme-main-text);
}

.preview-image__text:disabled {
  opacity: 0.45;
  cursor: default;
}

@media (prefers-reduced-motion: reduce) {
  .preview-image__spinner { animation-duration: 0ms; }
  .preview-image__tool,
  .preview-image__text { transition-duration: 0ms; }
}
</style>
