<script setup lang="ts">
/**
 * 截图编辑：在独立的截图窗口里框选、标注、说明并发送。
 *
 * user:“重新设计与实现 Ping 的框选工具”+(截图窗口只显示一张静态截图，
 * 框选、标注、撤销、Esc 取消、发送全部在这个窗口内完成；它不再依赖 Ping
 * 覆盖层，也不受覆盖层鼠标穿透/不可激活的影响。)
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
// user:“支持修改标注（可以复用ping的框选那里的标注功能与样式，将这一个功能抽出来共用）”+
// (工具种类、默认色、色板与绘制都来自 `@/annotation/*`：灯箱里的图片查看器与这里
//  共用同一份实现，改一处两边同时生效；本组件只保留 Ping 特有的框选与取字。)
import AnnotationToolbar from '@/annotation/AnnotationToolbar.vue'
import { drawAnnotation } from '@/annotation/draw'
import { annotationColor, type Annotation, type AnnotationTool } from '@/annotation/model'
import { Check, ScanText, SquareDashed, X } from 'lucide-vue-next'
import type { CapturedFrame, OcrLine } from '../bridge.ts'
import { ocrImage } from '../bridge.ts'
import { t } from '@/i18n/index.ts'
import UiSelect from '@/components/UiSelect.vue'
import type { Translator } from '../translate/client.ts'
import {
  DEFAULT_SOURCE,
  DEFAULT_TARGET,
  SOURCE_LANGUAGES,
  TARGET_LANGUAGES,
  type TranslateLanguage,
} from '../translate/request.ts'
import {
  cropFor,
  displayRectFor,
  frameToClient,
  normalizeRegion,
  pointToFrame,
  selectionMeta,
  type CaptureDisplayRect,
  type CaptureRegion,
} from '../capture/geometry.ts'

/** `region` 是 Ping 的框选，不属于标注；其余工具来自共用模型。 */
type Tool = 'region' | AnnotationTool

export interface CaptureSelectionMeta {
  x: number
  y: number
  width: number
  height: number
  scale: number
}

const props = defineProps<{
  frame: CapturedFrame
  /** user:“确保视觉、功能和交互不退化”+(工作台沙盒嵌入页面，不覆盖其他设置)。 */
  sandbox?: boolean
  busy: boolean
  /** 标注层圈选带过来的区域，截图内像素；有值时打开就框好。 */
  presetRegion?: CaptureRegion | null
  error: string
  /**
   * user:“用现有模型直调通道（core/src/lamtools_core/direct/executor.py）…不要接第三方翻译 API”+
   * (翻译通道由宿主注入：截图窗口接直调，展厅/沙盒没有通道时按钮如实说明不可用，
   *  而不是假装能翻。)
   */
  translate?: Translator
  /** user:“实时预览、交互测试”+(展厅使用本地取字示例，实际截图使用宿主识别)。 */
  recognizeText?: typeof ocrImage
}>()

const emit = defineEmits<{
  cancel: []
  send: [payload: { blob: Blob; text: string; meta: CaptureSelectionMeta }]
}>()

const root = ref<HTMLElement | null>(null)
const canvas = ref<HTMLCanvasElement | null>(null)
const region = ref<{ x1: number; y1: number; x2: number; y2: number } | null>(null)
const tool = ref<Tool>('region')
/** 共用工具条只认标注工具；框选模式下不让任何工具高亮。 */
const annotationTool = computed<AnnotationTool>(() => (tool.value === 'region' ? 'arrow' : tool.value))
const annotations = ref<Annotation[]>([])
const redoStack = ref<Annotation[]>([])
const capsule = ref('')
const encoding = ref(false)
let disposed = false
const drawing = ref<{ current: Annotation | null } | null>(null)
const nextId = ref(1)
const viewport = ref({ width: window.innerWidth, height: window.innerHeight })
const textDraft = ref<{ x: number; y: number; value: string; editing: boolean } | null>(null)
const textInput = ref<HTMLInputElement | null>(null)
// user:“上面那个宽度自适应，没让你把底下的输入栏也给缩短啊，那个输入栏的长度
// 必须要长于上面的那个空间栏，并左右额外加 32px”+
// (工具条按图标内容自适应；输入栏跟着工具条走，左右各多 32px，不按文字长度收缩。)
const toolsBar = ref<HTMLElement | null>(null)
const inputWidth = ref(0)
let toolsObserver: ResizeObserver | null = null
let viewportObserver: ResizeObserver | null = null
const INPUT_SIDE_GUTTER = 32

const activeColor = ref<string | null>(null)

/** 当前工具该用的颜色（框选模式下仍按箭头色显示，避免调色板变空）。 */
function strokeColor(toolName: Tool): string {
  return annotationColor(toolName === 'region' ? 'arrow' : toolName, activeColor.value)
}

const hasSelection = computed(() => Boolean(normalizedRegion()))

/** 文字块输入框跟着点击位置走（窗口 css 坐标）。 */
const textDraftStyle = computed(() => {
  const draft = textDraft.value
  if (!draft) return {}
  const point = toScreen(draft.x, draft.y)
  return { left: `${point.left}px`, top: `${point.top}px` }
})

function displayRect(): CaptureDisplayRect {
  return displayRectFor(
    props.frame.width,
    props.frame.height,
    viewport.value.width,
    viewport.value.height,
  )
}

function toImage(clientX: number, clientY: number): { x: number; y: number } {
  return pointToFrame(
    clientX - (props.sandbox ? root.value?.getBoundingClientRect().left ?? 0 : 0),
    clientY - (props.sandbox ? root.value?.getBoundingClientRect().top ?? 0 : 0),
    props.frame.width,
    props.frame.height,
    displayRect(),
  )
}

function toScreen(x: number, y: number): { left: number; top: number } {
  return frameToClient(x, y, displayRect())
}

function syncInputWidth(): void {
  const element = toolsBar.value
  if (!element) return
  const available = Math.max(280, viewport.value.width - 48)
  const wanted = Math.ceil(element.getBoundingClientRect().width) + INPUT_SIDE_GUTTER * 2
  inputWidth.value = Math.min(available, Math.max(280, wanted))
}

function draw(): void {
  const element = canvas.value
  if (!element) return
  const rect = displayRect()
  element.width = props.frame.width
  element.height = props.frame.height
  element.style.width = `${rect.width}px`
  element.style.height = `${rect.height}px`
  element.style.left = `${rect.offsetX}px`
  element.style.top = `${rect.offsetY}px`
  const context = element.getContext('2d')
  if (!context) return
  context.putImageData(
    new ImageData(new Uint8ClampedArray(props.frame.data), props.frame.width, props.frame.height),
    0,
    0,
  )
  const selected = normalizedRegion()
  if (selected) {
    context.save()
    context.fillStyle = 'rgba(6, 8, 12, 0.5)'
    context.beginPath()
    context.rect(0, 0, props.frame.width, props.frame.height)
    context.rect(selected.x, selected.y, selected.width, selected.height)
    context.fill('evenodd')
    context.restore()
    context.strokeStyle = 'rgba(126, 180, 255, 0.95)'
    context.lineWidth = Math.max(2, 2 / rect.scale)
    context.strokeRect(selected.x, selected.y, selected.width, selected.height)
  }
  for (const annotation of annotations.value) drawAnnotation(context, annotation, props.frame.width)
  if (drawing.value?.current) drawAnnotation(context, drawing.value.current, props.frame.width)
}

function normalizedRegion(): ReturnType<typeof normalizeRegion> {
  return normalizeRegion(region.value)
}

function onPointerDown(event: PointerEvent): void {
  if (props.busy) return
  const point = toImage(event.clientX, event.clientY)
  if (tool.value === 'region') {
    region.value = { x1: point.x, y1: point.y, x2: point.x, y2: point.y }
    drawing.value = { current: null }
    ;(event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId)
    return
  }
  if (tool.value === 'text') {
    textDraft.value = { x: point.x, y: point.y, value: '', editing: true }
    void nextTick(() => textInput.value?.focus())
    return
  }
  const current: Annotation = {
    id: nextId.value++,
    tool: tool.value,
    points: [point],
    color: strokeColor(tool.value),
  }
  if (tool.value === 'pen' || tool.value === 'arrow') {
    drawing.value = { current }
    // user:“确保视觉、功能和交互不退化”+(拖到画布外松开也能结束标注，不留下跟随鼠标的残影)。
    ;(event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId)
  } else {
    annotations.value = [...annotations.value, current]
    redoStack.value = []
    draw()
  }
}

function onPointerMove(event: PointerEvent): void {
  const state = drawing.value
  if (!state) return
  const point = toImage(event.clientX, event.clientY)
  if (state.current) {
    if (state.current.tool === 'arrow') state.current.points = [state.current.points[0], point]
    else state.current.points = [...state.current.points, point]
  } else if (region.value) {
    region.value = { ...region.value, x2: point.x, y2: point.y }
  }
  draw()
}

function onPointerUp(): void {
  const state = drawing.value
  drawing.value = null
  if (state?.current) {
    annotations.value = [...annotations.value, state.current]
    redoStack.value = []
  }
  draw()
}

// user:“确保视觉、功能和交互不退化”+(系统取消指针时丢弃未完成的拖拽)。
function onPointerCancel(): void {
  if (drawing.value && !drawing.value.current) region.value = null
  drawing.value = null
  draw()
}

function commitText(): void {
  const draft = textDraft.value
  const value = draft?.value.trim()
  if (draft && value) {
    annotations.value = [...annotations.value, {
      id: nextId.value++,
      tool: 'text',
      points: [{ x: draft.x, y: draft.y }],
      text: value,
      color: strokeColor('text'),
    }]
    redoStack.value = []
    draw()
  }
  textDraft.value = null
}

function onTextKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    event.stopPropagation()
    textDraft.value = null
    return
  }
  if (event.key === 'Enter') {
    event.preventDefault()
    commitText()
  }
}

function undo(): void {
  const last = annotations.value[annotations.value.length - 1]
  if (!last) return
  annotations.value = annotations.value.slice(0, -1)
  redoStack.value = [...redoStack.value, last]
  draw()
}

function redo(): void {
  const last = redoStack.value[redoStack.value.length - 1]
  if (!last) return
  redoStack.value = redoStack.value.slice(0, -1)
  annotations.value = [...annotations.value, last]
  draw()
}

function clearAll(): void {
  annotations.value = []
  redoStack.value = []
  region.value = null
  draw()
}

// ---------------------------------------------------------------------------
// 截图取字（Windows 自带的识别引擎，离线）
// ---------------------------------------------------------------------------

const ocrVisible = ref(false)
const ocrBusy = ref(false)
const ocrText = ref('')
const ocrError = ref('')
const ocrMeta = ref<{ lines: number; language: string } | null>(null)
const copied = ref(false)
/** 这一轮取字的逐行结果：译文要按行对回 bounds，所以行本身要留着。 */
const ocrLines = ref<OcrLine[]>([])
// user:“语言对默认「自动 → 简体中文」，至少支持中/英切换”+(源语言可以选「自动检测」，
// 目标语言只给具体语言；改语言不用关面板，翻译键就在同一行)。
const translateSource = ref<TranslateLanguage>(DEFAULT_SOURCE)
const translateTarget = ref<TranslateLanguage>(DEFAULT_TARGET)
// user:“统一与去重”+(语言对沿用统一下拉，保留自动检测仅用于原文)。
const sourceLanguageOptions = computed(() => SOURCE_LANGUAGES.map(option => ({ ...option, label: t(option.label) })))
const targetLanguageOptions = computed(() => TARGET_LANGUAGES.map(option => ({ ...option, label: t(option.label) })))

function selectSourceLanguage(value: string): void {
  const option = SOURCE_LANGUAGES.find(item => item.value === value)
  if (option) translateSource.value = option.value
}

function selectTargetLanguage(value: string): void {
  const option = TARGET_LANGUAGES.find(item => item.value === value)
  if (option) translateTarget.value = option.value
}

const translateBusy = ref(false)
const translateError = ref('')
const translateText = ref('')
const translateModel = ref('')
const translateCopied = ref(false)
/**
 * user:“按行叠加显示（用 lines[].bounds 画回屏幕）如果成本可控就做”+
 * (译文按行拆好后，这里已经和原文行、bounds 一一对上；叠回屏幕要走 desktop_overlay，
 *  那是 Python 工具层的能力，截图窗口这边没有可复用的画布命令，所以这一批只把数据备好，
 *  不在界面上假装已经叠上去了——详见汇报里的「未做部分」。)
 */
const translatedLines = ref<{ text: string; source: string; bounds: [number, number, number, number] }[]>([])

/**
 * 取字只用截图的原始像素：标注不要混进去，否则识别结果里会多出我们自己画上去的字。
 *
 * user:“区域：支持整图与矩形裁剪（复用现有裁剪）”+(有框选就只认框里那块，没框选就整张图)。
 */
function selectionToDataUrl(): string {
  const selected = cropFor(normalizedRegion(), props.frame.width, props.frame.height)
  const width = Math.max(1, Math.round(selected.width))
  const height = Math.max(1, Math.round(selected.height))
  const source = document.createElement('canvas')
  source.width = props.frame.width
  source.height = props.frame.height
  const sourceContext = source.getContext('2d')
  if (!sourceContext) throw new Error('读不到截图像素，无法取字')
  sourceContext.putImageData(
    new ImageData(new Uint8ClampedArray(props.frame.data), props.frame.width, props.frame.height),
    0,
    0,
  )
  const output = document.createElement('canvas')
  output.width = width
  output.height = height
  const context = output.getContext('2d')
  if (!context) throw new Error('读不到截图像素，无法取字')
  context.drawImage(source, selected.x, selected.y, width, height, 0, 0, width, height)
  return output.toDataURL('image/png')
}

// user:“把「截图/选中区域 → 提取文字」做通”+(识别交给桌面端 Windows.Media.Ocr，界面只负责传图和显示)。
async function extractText(): Promise<void> {
  if (ocrBusy.value || props.busy) return
  ocrVisible.value = true
  ocrBusy.value = true
  ocrText.value = ''
  ocrError.value = ''
  ocrMeta.value = null
  ocrLines.value = []
  resetTranslation()
  try {
    const result = await (props.recognizeText ?? ocrImage)(selectionToDataUrl())
    ocrText.value = result.text.replace(/\s+$/, '')
    ocrMeta.value = { lines: result.lines.length, language: result.language }
    // user:“按行叠加显示（用 lines[].bounds 画回屏幕）”+(每次取字都把行位置留下来)。
    ocrLines.value = result.lines
    if (!ocrText.value) {
      // 识别为空不等于出错：说清为什么，并给可操作的下一步。
      ocrError.value = '这块区域里没有识别到文字。可以缩小框选只框文字，或者把窗口放大再截一次。'
    }
  } catch (cause) {
    ocrError.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    ocrBusy.value = false
  }
}

function closeOcrPanel(): void {
  ocrVisible.value = false
  ocrText.value = ''
  ocrError.value = ''
  ocrMeta.value = null
  copied.value = false
  resetTranslation()
}

// user:“结果可复制、可直接送进会话”+(复制走系统剪贴板；被系统挡住时退到手动全选，不静默失败)。
async function copyOcrText(): Promise<void> {
  const text = ocrText.value
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    copied.value = true
    window.setTimeout(() => { copied.value = false }, 1600)
  } catch {
    ocrError.value = '复制没成功：点一下下面这段文字全选，按 Ctrl+C 复制'
  }
}

function useOcrText(): void {
  const text = ocrText.value.trim()
  if (!text) return
  capsule.value = capsule.value.trim() ? `${capsule.value.trim()}\n${text}` : text
  closeOcrPanel()
}

function resetTranslation(): void {
  translateBusy.value = false
  translateError.value = ''
  translateText.value = ''
  translateModel.value = ''
  translatedLines.value = []
  translateCopied.value = false
}

/** 原行与译行按序号对齐：行数对不上就不硬凑，界面会说「逐行对照暂时不可用」。 */
function pairTranslatedLines(
  lines: OcrLine[],
  translated: string,
): { text: string; source: string; bounds: [number, number, number, number] }[] {
  const parts = translated.split(/\r?\n/).map(part => part.trim()).filter(part => part.length > 0)
  if (parts.length !== lines.length) return []
  return lines.map((line, index) => ({ text: parts[index], source: line.text, bounds: line.bounds }))
}

/**
 * user:“在 OCR 结果面板加「翻译」…失败给可读原因（无可用模型、语言不支持、无文字）”+
 * (每一条退路都在面板里说一句人话：没接通道、没文字、语言对不成立、没有文本模型、
 *  模型报错，都不静默失败；失败保留原文，不把已经识别到的字弄丢)。
 */
async function translateOcr(): Promise<void> {
  if (translateBusy.value || ocrBusy.value) return
  const run = props.translate
  if (!run) {
    translateError.value = t('翻译需要在桌面应用里运行。')
    return
  }
  translateBusy.value = true
  translateError.value = ''
  translateCopied.value = false
  try {
    const outcome = await run({
      text: ocrText.value,
      source: translateSource.value,
      target: translateTarget.value,
    })
    translateText.value = outcome.text
    translateModel.value = outcome.model
    translatedLines.value = pairTranslatedLines(ocrLines.value, outcome.text)
  } catch (cause) {
    translateText.value = ''
    translateModel.value = ''
    translatedLines.value = []
    translateError.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    translateBusy.value = false
  }
}

// user:“结果可复制、可直接送进会话”+(译文同样可复制、可直接填进说明栏)。
async function copyTranslatedText(): Promise<void> {
  const text = translateText.value.trim()
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    translateCopied.value = true
    window.setTimeout(() => { translateCopied.value = false }, 1600)
  } catch {
    translateError.value = t('复制没成功：点一下下面这段译文全选，按 Ctrl+C 复制')
  }
}

function useTranslation(): void {
  const text = translateText.value.trim()
  if (!text) return
  capsule.value = capsule.value.trim() ? `${capsule.value.trim()}\n${text}` : text
  closeOcrPanel()
}

/** 取字面板开着时，第一次 Esc 只关面板，不顺手把整个截图窗口关掉。 */
function onEditorKeydown(event: KeyboardEvent): void {
  if (event.key !== 'Escape' || !ocrVisible.value) return
  // user:“确保视觉、功能和交互不退化”+(先关下拉，再关取字面板，再退出截图)。
  const target = event.target
  if (target instanceof Element && target.closest('.ui-select-menu, .ui-select-trigger[aria-expanded="true"]')) return
  event.preventDefault()
  event.stopPropagation()
  closeOcrPanel()
}

async function send(): Promise<void> {
  // user:“确保视觉、功能和交互不退化”+(截图编码期间禁止重复发送，关闭后不再派发结果)。
  if (props.busy || encoding.value) return
  encoding.value = true
  try {
  const selected = cropFor(normalizedRegion(), props.frame.width, props.frame.height)
  const output = document.createElement('canvas')
  output.width = Math.round(selected.width)
  output.height = Math.round(selected.height)
  const context = output.getContext('2d')
  if (!context) return
  const source = document.createElement('canvas')
  source.width = props.frame.width
  source.height = props.frame.height
  const sourceContext = source.getContext('2d')
  if (!sourceContext) return
  sourceContext.putImageData(
    new ImageData(new Uint8ClampedArray(props.frame.data), props.frame.width, props.frame.height),
    0,
    0,
  )
  context.drawImage(
    source,
    selected.x, selected.y, selected.width, selected.height,
    0, 0, selected.width, selected.height,
  )
  // 标注按选区裁剪后叠加，保持和屏幕上看到的一致。
  context.save()
  context.translate(-selected.x, -selected.y)
  for (const annotation of annotations.value) drawAnnotation(context, annotation, props.frame.width)
  context.restore()
  const blob = await new Promise<Blob | null>(resolve => output.toBlob(resolve, 'image/png'))
  if (!blob || disposed) return
  emit('send', {
    blob,
    text: capsule.value.trim(),
    meta: selectionMeta(props.frame, selected),
  })
  } finally {
    encoding.value = false
  }
}

function onResize(): void {
  const bounds = props.sandbox ? root.value?.getBoundingClientRect() : null
  viewport.value = { width: bounds?.width || window.innerWidth, height: bounds?.height || window.innerHeight }
  draw()
  syncInputWidth()
}

watch(() => props.frame, () => {
  region.value = props.presetRegion ?? null
  annotations.value = []
  redoStack.value = []
  void nextTick(draw)
})

onMounted(() => {
  window.addEventListener('resize', onResize)
  window.addEventListener('keydown', onEditorKeydown, true)
  // 标注层圈选进来时 frame 已经有值，watch 不会触发首次初始化，这里补一次。
  if (props.presetRegion) region.value = props.presetRegion
  void nextTick(() => {
    onResize()
    if (props.sandbox && root.value) {
      viewportObserver = new ResizeObserver(onResize)
      viewportObserver.observe(root.value)
    }
    if (toolsBar.value) {
      toolsObserver = new ResizeObserver(syncInputWidth)
      toolsObserver.observe(toolsBar.value)
    }
  })
})

onBeforeUnmount(() => {
  disposed = true
  window.removeEventListener('resize', onResize)
  window.removeEventListener('keydown', onEditorKeydown, true)
  toolsObserver?.disconnect()
  toolsObserver = null
  viewportObserver?.disconnect()
  viewportObserver = null
})
</script>

<template>
  <div ref="root" class="capture" :class="{ 'capture--sandbox': sandbox }" role="dialog" aria-label="截图框选">
    <div class="capture__stage" @pointermove="onPointerMove">
      <canvas
        ref="canvas"
        class="capture__canvas"
        @pointerdown="onPointerDown"
        @pointerup="onPointerUp"
        @pointercancel="onPointerCancel"
      />
    </div>

    <div v-if="!hasSelection" class="capture__hint">拖拽框选区域 · Esc 取消</div>

    <textarea
      v-if="textDraft"
      ref="textInput"
      v-model="textDraft.value"
      class="capture__text-draft"
      :style="textDraftStyle"
      rows="1"
      placeholder="输入文字，回车确认"
      @keydown="onTextKeydown"
      @blur="commitText"
    />

    <!-- 底部工具坞：上方工具栏胶囊 + 下方输入胶囊，紧贴在一起。 -->
    <div class="capture__dock">
      <div ref="toolsBar" class="capture__tools">
        <button type="button" class="capture__tool" :class="{ 'is-active': tool === 'region' }"
          title="框选" aria-label="框选" @click="tool = 'region'">
          <SquareDashed :size="15" :stroke-width="1.8" aria-hidden="true" />
        </button>
        <AnnotationToolbar
          :tool="annotationTool"
          :color="activeColor"
          :active="tool !== 'region'"
          :can-undo="annotations.length > 0"
          :can-redo="redoStack.length > 0"
          :disabled="busy"
          @update:tool="tool = $event"
          @update:color="activeColor = $event"
          @undo="undo"
          @redo="redo"
          @clear="clearAll"
        >
          <template #extra>
            <span class="capture__divider" aria-hidden="true" />
            <button type="button" class="capture__tool" :class="{ 'is-active': ocrVisible }"
              :disabled="busy || ocrBusy" title="提取文字" aria-label="提取文字" @click="extractText">
              <ScanText :size="15" :stroke-width="1.8" aria-hidden="true" />
            </button>
          </template>
          <template #end>
            <button type="button" class="capture__tool capture__tool--cancel" title="取消" aria-label="取消" @click="emit('cancel')">
              <X :size="15" :stroke-width="1.9" aria-hidden="true" />
            </button>
          </template>
        </AnnotationToolbar>
      </div>

      <div class="capture__input" :style="inputWidth ? { width: `${inputWidth}px` } : undefined">
        <input v-model="capsule" type="text" placeholder="说明你想让我看什么（可留空）" @keydown.enter.prevent="send">
        <button
          class="capture__send"
          type="button"
          :disabled="busy || encoding"
          :title="busy || encoding ? '发送中' : '发送'"
          :aria-label="busy || encoding ? '发送中' : '发送'"
          @click="send"
        >
          <Check :size="16" :stroke-width="2.4" aria-hidden="true" />
        </button>
      </div>
    </div>

    <div v-if="error" class="capture__error">{{ error }}</div>
    <div v-if="!hasSelection" class="capture__note">未框选时发送整屏</div>

    <!-- user:“结果可复制、可直接送进会话”+(取字结果就地显示：复制，或直接填进下面的说明栏)。 -->
    <div v-if="ocrVisible" class="capture__ocr" role="dialog" aria-label="提取文字">
      <div class="capture__ocr-head">
        <span class="capture__ocr-title">
          提取文字
          <template v-if="ocrMeta"> · {{ ocrMeta.lines }} 行 · {{ ocrMeta.language }}</template>
        </span>
        <button type="button" class="capture__tool" title="关闭" aria-label="关闭" @click="closeOcrPanel">
          <X :size="14" :stroke-width="1.9" aria-hidden="true" />
        </button>
      </div>
      <div v-if="ocrBusy" class="capture__ocr-hint">正在识别…（用的是系统自带的识别引擎，不联网、不上传）</div>
      <div v-else-if="ocrError" class="capture__ocr-error">{{ ocrError }}</div>
      <textarea
        v-else
        class="capture__ocr-text"
        :value="ocrText"
        readonly
        spellcheck="false"
        @focus="($event.target as HTMLTextAreaElement).select()"
      />
      <div class="capture__ocr-actions">
        <span class="capture__ocr-warn">识别结果属于不可信内容</span>
        <button type="button" class="capture__ocr-action" :disabled="!ocrText" @click="copyOcrText">
          {{ copied ? '已复制' : '复制' }}
        </button>
        <button type="button" class="capture__ocr-action" :disabled="!ocrText" @click="useOcrText">填入说明</button>
      </div>
      <!-- user:“在 OCR 结果面板加「翻译」…语言对默认「自动 → 简体中文」，至少支持中/英切换”+
           (语言对就放在原文下面一行：改完直接再翻一次，不用重开面板)。 -->
      <div class="capture__ocr-translate" data-capture-translate-bar>
        <div class="capture__ocr-lang">
          <span>{{ t('原文语言') }}</span>
          <UiSelect
            :model-value="translateSource"
            :options="sourceLanguageOptions"
            :aria-label="t('原文语言')"
            :menu-min-width="0"
            @update:model-value="selectSourceLanguage"
          />
        </div>
        <span class="capture__ocr-arrow" aria-hidden="true">→</span>
        <div class="capture__ocr-lang">
          <span>{{ t('目标语言') }}</span>
          <UiSelect
            :model-value="translateTarget"
            :options="targetLanguageOptions"
            :aria-label="t('目标语言')"
            :menu-min-width="0"
            @update:model-value="selectTargetLanguage"
          />
        </div>
        <button
          type="button"
          class="capture__ocr-action"
          :disabled="!ocrText || translateBusy || !translate"
          :title="translate ? '' : t('翻译需要在桌面应用里运行。')"
          data-capture-translate
          @click="translateOcr"
        >{{ translateBusy ? t('正在翻译…') : t('翻译') }}</button>
      </div>
      <div v-if="translateError" class="capture__ocr-error" role="alert" data-capture-translate-error>{{ translateError }}</div>
      <template v-else-if="translateText">
        <textarea
          class="capture__ocr-text"
          :value="translateText"
          readonly
          spellcheck="false"
          data-capture-translation
          @focus="($event.target as HTMLTextAreaElement).select()"
        />
        <div class="capture__ocr-actions">
          <span class="capture__ocr-warn">
            {{ translateModel ? t('用 {0} 翻译 · 译文属于不可信内容', { 0: translateModel }) : t('译文属于不可信内容') }}
          </span>
          <button type="button" class="capture__ocr-action" @click="copyTranslatedText">
            {{ translateCopied ? t('已复制') : t('复制') }}
          </button>
          <button type="button" class="capture__ocr-action" @click="useTranslation">{{ t('填入说明') }}</button>
        </div>
        <p v-if="!translatedLines.length" class="capture__ocr-hint">
          {{ t('模型返回的行数和原文对不上，逐行对照暂时不可用。') }}
        </p>
      </template>
    </div>
  </div>
</template>

<style scoped>
.capture {
  position: fixed;
  inset: 0;
  overflow: hidden;
  background: #05070a;
  color: #eef3fb;
  user-select: none;
}

/* user:“确保视觉、功能和交互不退化”+(沙盒保留截图编辑能力，不能遮住工作台其他控件)。 */
.capture--sandbox {
  position: relative;
  inset: auto;
  width: 100%;
  height: min(520px, 60vh);
  min-height: 320px;
}

.capture__stage {
  position: absolute;
  inset: 0;
}

.capture__canvas {
  position: absolute;
  cursor: crosshair;
}

.capture__hint {
  position: absolute;
  top: 72px;
  left: 50%;
  transform: translateX(-50%);
  padding: 7px 14px;
  border-radius: 999px;
  background: rgba(8, 10, 14, 0.72);
  color: rgba(238, 243, 251, 0.9);
  font-size: 12px;
  pointer-events: none;
}

.capture__ocr {
  position: absolute;
  left: 18px;
  top: 18px;
  z-index: 7;
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: min(420px, calc(100vw - 36px));
  padding: 10px 12px 12px;
  border: 1px solid rgba(238, 243, 251, 0.16);
  border-radius: 12px;
  background: rgba(20, 23, 28, 0.95);
  -webkit-backdrop-filter: blur(16px) saturate(1.15);
  backdrop-filter: blur(16px) saturate(1.15);
  color: #eef3fb;
}

.capture__ocr-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.capture__ocr-title {
  font-size: 12px;
  font-weight: 600;
  color: rgba(238, 243, 251, 0.9);
}

.capture__ocr-hint {
  font-size: 12px;
  color: rgba(238, 243, 251, 0.7);
}

.capture__ocr-error {
  font-size: 12px;
  line-height: 1.5;
  color: #ffb4b4;
}

.capture__ocr-text {
  width: 100%;
  min-height: 88px;
  max-height: 40vh;
  padding: 8px 10px;
  border: 1px solid rgba(238, 243, 251, 0.14);
  border-radius: 8px;
  background: rgba(8, 10, 14, 0.72);
  color: #eef3fb;
  font: inherit;
  font-size: 12px;
  line-height: 1.6;
  resize: vertical;
  outline: none;
}

.capture__ocr-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.capture__ocr-translate {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.capture__ocr-lang {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: rgba(238, 243, 251, 0.7);
}

.capture__ocr-lang :deep(.ui-select-trigger) {
  min-height: var(--interaction-height-sm);
  font-size: inherit;
}

.capture__ocr-arrow {
  font-size: 11px;
  color: rgba(238, 243, 251, 0.45);
}

.capture__ocr-warn {
  flex: 1;
  font-size: 11px;
  color: rgba(238, 243, 251, 0.45);
}

.capture__ocr-action {
  padding: 5px 12px;
  border: 1px solid rgba(238, 243, 251, 0.16);
  border-radius: 999px;
  background: transparent;
  color: #eef3fb;
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.capture__ocr-action:hover:not(:disabled) {
  background: rgba(238, 243, 251, 0.12);
}

.capture__ocr-action:disabled {
  opacity: 0.4;
  cursor: default;
}

.capture__note {
  position: absolute;
  right: 18px;
  bottom: 18px;
  color: rgba(238, 243, 251, 0.45);
  font-size: 11px;
  pointer-events: none;
}

.capture__text-draft {
  position: absolute;
  z-index: 5;
  width: 220px;
  padding: 6px 9px;
  border: 1px solid rgba(126, 180, 255, 0.6);
  border-radius: 8px;
  background: rgba(8, 10, 14, 0.9);
  color: #eef3fb;
  font: inherit;
  font-size: 13px;
  outline: none;
  resize: none;
}

/* 底部工具坞：上方工具栏胶囊（上圆角/下直角）+ 下方输入胶囊，紧贴在一起。 */
.capture__dock {
  position: absolute;
  left: 50%;
  bottom: 24px;
  transform: translateX(-50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  width: auto;
  max-width: calc(100vw - 48px);
  z-index: 6;
}

.capture__tools {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 5px 8px;
  border: 1px solid rgba(238, 243, 251, 0.14);
  border-bottom: 0;
  border-radius: 16px 16px 0 0;
  background: rgba(20, 23, 28, 0.92);
  -webkit-backdrop-filter: blur(16px) saturate(1.15);
  backdrop-filter: blur(16px) saturate(1.15);
}

.capture__tool {
  position: relative;
  flex: none;
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: rgba(238, 243, 251, 0.62);
  cursor: pointer;
}

.capture__tool:hover {
  background: rgba(238, 243, 251, 0.1);
  color: #eef3fb;
}

.capture__tool.is-active {
  background: rgba(238, 243, 251, 0.16);
  color: #eef3fb;
}

.capture__tool--cancel {
  margin-left: 2px;
}

/* 调色板与色块已随工具条抽到 `@/annotation/AnnotationToolbar.vue`，
   这里只留 Ping 自己的分隔线。 */
.capture__divider {
  flex: none;
  width: 1px;
  height: 16px;
  margin: 0 4px;
  background: rgba(238, 243, 251, 0.16);
}

.capture__input {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: -1px;
  max-width: 100%;
  padding: 6px 6px 6px 16px;
  border: 1px solid rgba(238, 243, 251, 0.14);
  border-radius: 999px;
  background: rgba(20, 23, 28, 0.96);
  -webkit-backdrop-filter: blur(16px) saturate(1.15);
  backdrop-filter: blur(16px) saturate(1.15);
  box-shadow: 0 16px 36px rgba(0, 0, 0, 0.34);
}

.capture__input input {
  flex: 1;
  min-width: 0;
  height: 30px;
  padding: 0;
  border: 0;
  background: transparent;
  color: #eef3fb;
  font: inherit;
  font-size: 13px;
  outline: none;
}

.capture__input input::placeholder {
  color: rgba(238, 243, 251, 0.42);
}

.capture__send {
  flex: none;
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: rgba(238, 243, 251, 0.9);
  color: #14171c;
  cursor: pointer;
}

.capture__send:disabled {
  opacity: 0.5;
  cursor: default;
}

.capture__error {
  position: absolute;
  left: 50%;
  bottom: 150px;
  transform: translateX(-50%);
  max-width: min(560px, 80vw);
  padding: 8px 14px;
  border-radius: 10px;
  background: rgba(80, 16, 22, 0.9);
  color: #ffd7d7;
  font-size: 12px;
  z-index: 7;
}
</style>
