<script setup lang="ts">
/**
 * 截图编辑：在独立的截图窗口里框选、标注、说明并发送。
 *
 * user:“重新设计与实现 Ping 的框选工具”+(截图窗口只显示一张静态截图，
 * 框选、标注、撤销、Esc 取消、发送全部在这个窗口内完成；它不再依赖 Ping
 * 覆盖层，也不受覆盖层鼠标穿透/不可激活的影响。)
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { AlertCircle, Check, Eraser, HelpCircle, Palette, Redo2, SquareDashed, Type, Undo2, X } from 'lucide-vue-next'
import type { CapturedFrame } from '../bridge.ts'
import {
  cropFor,
  displayRectFor,
  frameToClient,
  normalizeRegion,
  pointToFrame,
  selectionMeta,
  type CaptureDisplayRect,
} from '../capture/geometry.ts'

type Tool = 'region' | 'question' | 'exclamation' | 'arrow' | 'text' | 'pen'

interface Annotation {
  id: number
  tool: Exclude<Tool, 'region'>
  points: { x: number; y: number }[]
  text?: string
  color: string
}

export interface CaptureSelectionMeta {
  x: number
  y: number
  width: number
  height: number
  scale: number
}

const props = defineProps<{
  frame: CapturedFrame
  busy: boolean
  error: string
}>()

const emit = defineEmits<{
  cancel: []
  send: [payload: { blob: Blob; text: string; meta: CaptureSelectionMeta }]
}>()

const canvas = ref<HTMLCanvasElement | null>(null)
const region = ref<{ x1: number; y1: number; x2: number; y2: number } | null>(null)
const tool = ref<Tool>('region')
const annotations = ref<Annotation[]>([])
const redoStack = ref<Annotation[]>([])
const capsule = ref('')
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
const INPUT_SIDE_GUTTER = 32

const colors: Record<string, string> = {
  question: '#6AA8FF',
  exclamation: '#FF9F5A',
  text: '#F4F7FF',
  arrow: '#FF6F91',
  pen: '#7ED6A5',
}

/** user:“给一些常见的颜色…这些颜色用圆形”+(常用标注色板：点击后新画的标注用它。) */
const palette = [
  '#FF6F91', '#FF9F5A', '#FFD166', '#7ED6A5',
  '#6AA8FF', '#C7A6FF', '#F4F7FF', '#111318',
]
const activeColor = ref<string | null>(null)
const colorMenuOpen = ref(false)

function strokeColor(toolName: Tool): string {
  return activeColor.value || colors[toolName] || '#ffffff'
}

function chooseColor(color: string): void {
  activeColor.value = color
  colorMenuOpen.value = false
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
    clientX,
    clientY,
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
  const available = Math.max(280, window.innerWidth - 48)
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
  for (const annotation of annotations.value) drawAnnotation(context, annotation)
  if (drawing.value?.current) drawAnnotation(context, drawing.value.current)
}

function drawAnnotation(context: CanvasRenderingContext2D, annotation: Annotation): void {
  const size = Math.max(22, Math.min(64, props.frame.width * 0.03))
  context.save()
  context.strokeStyle = annotation.color
  context.fillStyle = annotation.color
  context.lineWidth = Math.max(3, size * 0.12)
  context.lineCap = 'round'
  context.lineJoin = 'round'
  if (annotation.tool === 'question' || annotation.tool === 'exclamation') {
    const point = annotation.points[0]
    if (point) {
      context.beginPath()
      context.arc(point.x, point.y, size * 0.7, 0, Math.PI * 2)
      context.stroke()
      context.font = `${Math.round(size)}px system-ui, sans-serif`
      context.textAlign = 'center'
      context.textBaseline = 'middle'
      context.fillText(annotation.tool === 'question' ? '?' : '!', point.x, point.y)
    }
  } else if (annotation.tool === 'arrow') {
    const [start, end] = annotation.points
    if (start && end) {
      context.beginPath()
      context.moveTo(start.x, start.y)
      context.lineTo(end.x, end.y)
      context.stroke()
      const angle = Math.atan2(end.y - start.y, end.x - start.x)
      const head = size * 0.6
      context.beginPath()
      context.moveTo(end.x, end.y)
      context.lineTo(end.x - head * Math.cos(angle - 0.4), end.y - head * Math.sin(angle - 0.4))
      context.lineTo(end.x - head * Math.cos(angle + 0.4), end.y - head * Math.sin(angle + 0.4))
      context.closePath()
      context.fill()
    }
  } else if (annotation.tool === 'text') {
    const point = annotation.points[0]
    if (point) {
      context.font = `${Math.round(size * 0.62)}px system-ui, sans-serif`
      context.textAlign = 'left'
      context.textBaseline = 'top'
      const text = annotation.text || '文字'
      const metrics = context.measureText(text)
      context.fillStyle = 'rgba(8, 10, 14, 0.72)'
      context.fillRect(point.x - 4, point.y - 4, metrics.width + 10, size * 0.9)
      context.fillStyle = annotation.color
      context.fillText(text, point.x, point.y)
    }
  } else {
    context.beginPath()
    annotation.points.forEach((point, index) => {
      if (index === 0) context.moveTo(point.x, point.y)
      else context.lineTo(point.x, point.y)
    })
    context.stroke()
  }
  context.restore()
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

async function send(): Promise<void> {
  if (props.busy) return
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
  for (const annotation of annotations.value) drawAnnotation(context, annotation)
  context.restore()
  const blob = await new Promise<Blob | null>(resolve => output.toBlob(resolve, 'image/png'))
  if (!blob) return
  emit('send', {
    blob,
    text: capsule.value.trim(),
    meta: selectionMeta(props.frame, selected),
  })
}

function onResize(): void {
  viewport.value = { width: window.innerWidth, height: window.innerHeight }
  draw()
  syncInputWidth()
}

watch(() => props.frame, () => {
  region.value = null
  annotations.value = []
  redoStack.value = []
  void nextTick(draw)
})

onMounted(() => {
  window.addEventListener('resize', onResize)
  void nextTick(() => {
    draw()
    syncInputWidth()
    if (toolsBar.value) {
      toolsObserver = new ResizeObserver(syncInputWidth)
      toolsObserver.observe(toolsBar.value)
    }
  })
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  toolsObserver?.disconnect()
  toolsObserver = null
})
</script>

<template>
  <div class="capture" role="dialog" aria-label="截图框选">
    <div class="capture__stage" @pointermove="onPointerMove">
      <canvas
        ref="canvas"
        class="capture__canvas"
        @pointerdown="onPointerDown"
        @pointerup="onPointerUp"
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
        <button type="button" class="capture__tool" :class="{ 'is-active': tool === 'arrow' }"
          title="箭头" aria-label="箭头" @click="tool = 'arrow'">
          <svg class="capture__arrow-icon" viewBox="0 0 16 16" aria-hidden="true">
            <path d="M3.2 12.8 L11.1 4.9" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" />
            <path d="M7.5 3.2 L12.8 3.2 L12.8 8.5 Z" fill="currentColor" />
          </svg>
        </button>
        <button type="button" class="capture__tool" :class="{ 'is-active': tool === 'question' }"
          title="问号" aria-label="问号" @click="tool = 'question'">
          <HelpCircle :size="15" :stroke-width="1.8" aria-hidden="true" />
        </button>
        <button type="button" class="capture__tool" :class="{ 'is-active': tool === 'exclamation' }"
          title="叹号" aria-label="叹号" @click="tool = 'exclamation'">
          <AlertCircle :size="15" :stroke-width="1.8" aria-hidden="true" />
        </button>
        <button type="button" class="capture__tool" :class="{ 'is-active': tool === 'text' }"
          title="文字块" aria-label="文字块" @click="tool = 'text'">
          <Type :size="15" :stroke-width="1.8" aria-hidden="true" />
        </button>

        <div
          class="capture__palette-wrap"
          @pointerenter="colorMenuOpen = true"
          @pointerleave="colorMenuOpen = false"
        >
          <button type="button" class="capture__tool" :class="{ 'is-active': colorMenuOpen }"
            title="颜色" aria-label="颜色" @click="colorMenuOpen = !colorMenuOpen">
            <Palette :size="15" :stroke-width="1.8" aria-hidden="true" />
            <span class="capture__color-dot" :style="{ background: activeColor || colors[tool] }" />
          </button>
          <div v-if="colorMenuOpen" class="capture__palette">
            <button
              v-for="color in palette"
              :key="color"
              type="button"
              class="capture__swatch"
              :class="{ 'is-active': activeColor === color }"
              :style="{ '--swatch': color }"
              :title="color"
              :aria-label="color"
              @click="chooseColor(color)"
            />
          </div>
        </div>

        <span class="capture__divider" aria-hidden="true" />
        <button type="button" class="capture__tool" title="撤销" aria-label="撤销" @click="undo">
          <Undo2 :size="15" :stroke-width="1.8" aria-hidden="true" />
        </button>
        <button type="button" class="capture__tool" title="重做" aria-label="重做" @click="redo">
          <Redo2 :size="15" :stroke-width="1.8" aria-hidden="true" />
        </button>
        <button type="button" class="capture__tool" title="清空" aria-label="清空" @click="clearAll">
          <Eraser :size="15" :stroke-width="1.8" aria-hidden="true" />
        </button>
        <button type="button" class="capture__tool capture__tool--cancel" title="取消" aria-label="取消" @click="emit('cancel')">
          <X :size="15" :stroke-width="1.9" aria-hidden="true" />
        </button>
      </div>

      <div class="capture__input" :style="inputWidth ? { width: `${inputWidth}px` } : undefined">
        <input v-model="capsule" type="text" placeholder="说明你想让我看什么（可留空）" @keydown.enter.prevent="send">
        <button
          class="capture__send"
          type="button"
          :disabled="busy"
          :title="busy ? '发送中' : '发送'"
          :aria-label="busy ? '发送中' : '发送'"
          @click="send"
        >
          <Check :size="16" :stroke-width="2.4" aria-hidden="true" />
        </button>
      </div>
    </div>

    <div v-if="error" class="capture__error">{{ error }}</div>
    <div v-if="!hasSelection" class="capture__note">未框选时发送整屏</div>
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

.capture__arrow-icon {
  display: block;
  width: 16px;
  height: 16px;
}

.capture__divider {
  flex: none;
  width: 1px;
  height: 16px;
  margin: 0 4px;
  background: rgba(238, 243, 251, 0.16);
}

.capture__palette-wrap {
  position: relative;
  display: flex;
}

.capture__color-dot {
  position: absolute;
  right: 4px;
  bottom: 4px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.35);
  pointer-events: none;
}

.capture__palette {
  position: absolute;
  left: 50%;
  bottom: calc(100% + 10px);
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border: 1px solid rgba(238, 243, 251, 0.14);
  border-radius: 999px;
  background: rgba(20, 23, 28, 0.94);
  -webkit-backdrop-filter: blur(16px) saturate(1.15);
  backdrop-filter: blur(16px) saturate(1.15);
  box-shadow: 0 14px 34px rgba(0, 0, 0, 0.32);
  white-space: nowrap;
}

.capture__palette::after {
  content: '';
  position: absolute;
  top: 100%;
  right: 0;
  left: 0;
  height: 12px;
}

.capture__swatch {
  flex: none;
  width: 18px;
  height: 18px;
  padding: 0;
  border: 1px solid rgba(255, 255, 255, 0.26);
  border-radius: 50%;
  background: var(--swatch);
  cursor: pointer;
  transition: transform 120ms ease-out;
}

.capture__swatch:hover {
  transform: scale(1.14);
}

.capture__swatch.is-active {
  box-shadow: 0 0 0 2px #14171c, 0 0 0 3.5px var(--swatch);
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
