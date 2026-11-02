<script setup lang="ts">
/**
 * 框选标注：圈定屏幕区域，画 ?、!、箭头、文字块、画笔，再用胶囊输入框说明意图。
 *
 * user:“框选工具至少有 ?、!、箭头、文字块、画笔、撤销/重做/清除/取消、胶囊文本输入框”+
 * (标注叠加进提交的图片；发送前可取消，取消不会发出空白截图。)
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { AlertCircle, Check, Eraser, HelpCircle, Palette, Redo2, SquareDashed, Type, Undo2, X } from 'lucide-vue-next'
import type { PingRuntime } from '../ping/usePingRuntime.ts'
import type { PingMarker } from '../ping/usePingRuntime.ts'
import * as bridge from '../bridge.ts'

// user:"ping 环跟桌宠应当是解耦的，它们是两个独立的功能"+
// (框选标注只依赖 Ping 运行时，不引用桌宠运行时与宠物实例。)
const props = defineProps<{ ping: PingRuntime }>()

type Tool = 'region' | 'question' | 'exclamation' | 'arrow' | 'text' | 'pen'

interface Annotation {
  id: number
  tool: Exclude<Tool, 'region'>
  points: { x: number; y: number }[]
  text?: string
  color: string
}

const frame = ref<bridge.CapturedFrame | null>(null)
const canvas = ref<HTMLCanvasElement | null>(null)
const region = ref<{ x1: number; y1: number; x2: number; y2: number } | null>(null)
const tool = ref<Tool>('region')
const annotations = ref<Annotation[]>([])
const redoStack = ref<Annotation[]>([])
const busy = ref(false)
const error = ref('')
const capsule = ref('')
const drawing = ref<{ startX: number; startY: number; current: Annotation | null } | null>(null)
const nextId = ref(1)

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

/** 选过颜色就覆盖工具默认色，没选过沿用工具自带的颜色。 */
function strokeColor(toolName: Tool): string {
  return activeColor.value || colors[toolName] || '#ffffff'
}

function chooseColor(color: string): void {
  activeColor.value = color
  colorMenuOpen.value = false
}

const active = computed(() => Boolean(props.ping.selectionRequest.value))

// user:“有没有esc退出框选？”+(框选期间 Esc 直接取消：清掉选择请求、恢复穿透，
// 不再只能点取消按钮或被卡住。)
function onKeydown(event: KeyboardEvent): void {
  if (event.key !== 'Escape') return
  event.preventDefault()
  void cancel()
}

watch(active, async value => {
  if (value) {
    window.addEventListener('keydown', onKeydown)
    await load()
    return
  }
  window.removeEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  frame.value = null
  if (active.value) void bridge.setPingInputMode('auto').catch(() => undefined)
})

async function load(): Promise<void> {
  error.value = ''
  region.value = null
  annotations.value = []
  redoStack.value = []
  capsule.value = ''
  try {
    const captured = await bridge.captureMonitorUnderCursor()
    frame.value = captured
    // 全屏标注模式：整个 Ping 覆盖层接收鼠标，取消时立刻恢复穿透。
    // 注意必须是 Ping 的输入模式；误设桌宠模式会把全屏桌宠层变成捕获，
    // 整个屏幕都会被它吃掉点击。
    await bridge.setPingInputMode('capture')
    await new Promise(resolve => requestAnimationFrame(resolve))
    draw()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
    await bridge.setPingInputMode('auto')
  }
}

function displayRect(): { scale: number; offsetX: number; offsetY: number; width: number; height: number } {
  const captured = frame.value
  if (!captured) return { scale: 1, offsetX: 0, offsetY: 0, width: 0, height: 0 }
  const scale = Math.min(window.innerWidth / captured.width, window.innerHeight / captured.height)
  const width = captured.width * scale
  const height = captured.height * scale
  return {
    scale,
    offsetX: (window.innerWidth - width) / 2,
    offsetY: (window.innerHeight - height) / 2,
    width,
    height,
  }
}

function toImage(clientX: number, clientY: number): { x: number; y: number } {
  const rect = displayRect()
  return {
    x: Math.min(frame.value!.width, Math.max(0, (clientX - rect.offsetX) / rect.scale)),
    y: Math.min(frame.value!.height, Math.max(0, (clientY - rect.offsetY) / rect.scale)),
  }
}

function draw(): void {
  const captured = frame.value
  const element = canvas.value
  if (!captured || !element) return
  const rect = displayRect()
  element.width = captured.width
  element.height = captured.height
  element.style.width = `${rect.width}px`
  element.style.height = `${rect.height}px`
  element.style.left = `${rect.offsetX}px`
  element.style.top = `${rect.offsetY}px`
  const context = element.getContext('2d')
  if (!context) return
  context.putImageData(
    new ImageData(new Uint8ClampedArray(captured.data), captured.width, captured.height),
    0,
    0,
  )
  const selected = normalizedRegion()
  if (selected) {
    context.save()
    context.fillStyle = 'rgba(6, 8, 12, 0.45)'
    context.beginPath()
    context.rect(0, 0, captured.width, captured.height)
    context.rect(selected.x, selected.y, selected.width, selected.height)
    context.fill('evenodd')
    context.restore()
    context.strokeStyle = 'rgba(126, 180, 255, 0.9)'
    context.lineWidth = Math.max(2, 2 / rect.scale)
    context.strokeRect(selected.x, selected.y, selected.width, selected.height)
  }
  for (const annotation of annotations.value) {
    drawAnnotation(context, annotation)
  }
  if (drawing.value?.current) drawAnnotation(context, drawing.value.current)
}

function drawAnnotation(context: CanvasRenderingContext2D, annotation: Annotation): void {
  const size = Math.max(22, Math.min(64, (frame.value?.width || 800) * 0.03))
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

function normalizedRegion(): { x: number; y: number; width: number; height: number } | null {
  const value = region.value
  if (!value) return null
  const x = Math.min(value.x1, value.x2)
  const y = Math.min(value.y1, value.y2)
  const width = Math.abs(value.x2 - value.x1)
  const height = Math.abs(value.y2 - value.y1)
  if (width < 8 || height < 8) return null
  return { x, y, width, height }
}

function onPointerDown(event: PointerEvent): void {
  if (!frame.value) return
  const point = toImage(event.clientX, event.clientY)
  if (tool.value === 'region') {
    region.value = { x1: point.x, y1: point.y, x2: point.x, y2: point.y }
    drawing.value = { startX: point.x, startY: point.y, current: null }
    ;(event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId)
    return
  }
  if (tool.value === 'text') {
    const text = window.prompt('文字块内容', '')
    if (text) {
      annotations.value = [...annotations.value, { id: nextId.value++, tool: 'text', points: [point], text, color: strokeColor('text') }]
      redoStack.value = []
      draw()
    }
    return
  }
  const current: Annotation = {
    id: nextId.value++,
    tool: tool.value,
    points: [point],
    color: strokeColor(tool.value),
  }
  if (tool.value === 'pen' || tool.value === 'arrow') {
    drawing.value = { startX: point.x, startY: point.y, current }
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

async function cancel(): Promise<void> {
  props.ping.selectionRequest.value = null
  await bridge.setPingInputMode('auto')
  frame.value = null
}

async function send(): Promise<void> {
  const selected = normalizedRegion() || (frame.value ? { x: 0, y: 0, width: frame.value.width, height: frame.value.height } : null)
  const captured = frame.value
  if (!captured || !selected) {
    error.value = '请先圈定要发送的区域'
    return
  }
  busy.value = true
  error.value = ''
  try {
    const output = document.createElement('canvas')
    output.width = Math.round(selected.width)
    output.height = Math.round(selected.height)
    const context = output.getContext('2d')
    if (!context) throw new Error('无法创建导出画布')
    const source = document.createElement('canvas')
    source.width = captured.width
    source.height = captured.height
    const sourceContext = source.getContext('2d')
    if (!sourceContext) throw new Error('无法创建源画布')
    sourceContext.putImageData(
      new ImageData(new Uint8ClampedArray(captured.data), captured.width, captured.height),
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
    if (!blob) throw new Error('标注图编码失败')
    const sector = props.ping.selectionRequest.value?.sector
    const marker: PingMarker | null = sector
      ? {
          x: props.ping.selectionRequest.value!.x,
          y: props.ping.selectionRequest.value!.y,
          kind: 'select',
          label: sector.label,
          color: sector.color,
        }
      : null
    // user:“不要带那么多有的没的”+(没写说明就只发图，不追加长提示词。)
    const prompt = capsule.value.trim()
    await props.ping.submitPingWithBlob(sector || null, prompt, blob, marker, {
      meta: {
        x: captured.x + selected.x,
        y: captured.y + selected.y,
        width: selected.width,
        height: selected.height,
        scale: captured.scale,
      },
    })
    await cancel()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div v-if="active" class="annotator" data-pet-hit role="dialog" aria-label="框选标注" @pointermove="onPointerMove">
    <canvas
      ref="canvas"
      class="annotator__canvas"
      @pointerdown="onPointerDown"
      @pointerup="onPointerUp"
    />

    <!-- user:“上面那个胶囊…下面是一个胶囊的输入栏、一个圆形对号按钮…从左到右分别是：
         框、箭头、问号、叹号、文字块、撤销、重做、清空和取消…全部都用图标表示”+
         (工具栏胶囊上圆角、下直角，紧贴输入胶囊：只有图标，没有文字。)
         user:“再加一个颜色选择调色盘键…Hover 时在上方再出一个胶囊，放这些常见颜色，
         这些颜色用圆形”+(调色盘按钮悬浮时在工具栏上方弹出圆形色板胶囊。) -->
    <div class="annotator__dock" data-pet-hit>
      <div class="annotator__tools" data-pet-hit>
        <button type="button" class="annotator__tool" :class="{ 'is-active': tool === 'region' }"
          title="框选" aria-label="框选" @click="tool = 'region'">
          <SquareDashed :size="15" :stroke-width="1.8" aria-hidden="true" />
        </button>
        <button type="button" class="annotator__tool" :class="{ 'is-active': tool === 'arrow' }"
          title="箭头" aria-label="箭头" @click="tool = 'arrow'">
          <!-- user:“箭头你自己用SVG重画一遍，不要糊弄”+(与画出来的箭头一致：线 + 实心三角头。) -->
          <svg class="annotator__arrow-icon" viewBox="0 0 16 16" aria-hidden="true">
            <path d="M3.2 12.8 L11.1 4.9" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" />
            <path d="M7.5 3.2 L12.8 3.2 L12.8 8.5 Z" fill="currentColor" />
          </svg>
        </button>
        <button type="button" class="annotator__tool" :class="{ 'is-active': tool === 'question' }"
          title="问号" aria-label="问号" @click="tool = 'question'">
          <HelpCircle :size="15" :stroke-width="1.8" aria-hidden="true" />
        </button>
        <button type="button" class="annotator__tool" :class="{ 'is-active': tool === 'exclamation' }"
          title="叹号" aria-label="叹号" @click="tool = 'exclamation'">
          <AlertCircle :size="15" :stroke-width="1.8" aria-hidden="true" />
        </button>
        <button type="button" class="annotator__tool" :class="{ 'is-active': tool === 'text' }"
          title="文字块" aria-label="文字块" @click="tool = 'text'">
          <Type :size="15" :stroke-width="1.8" aria-hidden="true" />
        </button>

        <div
          class="annotator__palette-wrap"
          @pointerenter="colorMenuOpen = true"
          @pointerleave="colorMenuOpen = false"
        >
          <button type="button" class="annotator__tool" :class="{ 'is-active': colorMenuOpen }"
            title="颜色" aria-label="颜色" @click="colorMenuOpen = !colorMenuOpen">
            <Palette :size="15" :stroke-width="1.8" aria-hidden="true" />
            <span class="annotator__color-dot" :style="{ background: activeColor || colors[tool] }" />
          </button>
          <div v-if="colorMenuOpen" class="annotator__palette" data-pet-hit>
            <button
              v-for="color in palette"
              :key="color"
              type="button"
              class="annotator__swatch"
              :class="{ 'is-active': activeColor === color }"
              :style="{ '--swatch': color }"
              :title="color"
              :aria-label="color"
              @click="chooseColor(color)"
            />
          </div>
        </div>

        <span class="annotator__divider" aria-hidden="true" />
        <button type="button" class="annotator__tool" title="撤销" aria-label="撤销" @click="undo">
          <Undo2 :size="15" :stroke-width="1.8" aria-hidden="true" />
        </button>
        <button type="button" class="annotator__tool" title="重做" aria-label="重做" @click="redo">
          <Redo2 :size="15" :stroke-width="1.8" aria-hidden="true" />
        </button>
        <button type="button" class="annotator__tool" title="清空" aria-label="清空" @click="clearAll">
          <Eraser :size="15" :stroke-width="1.8" aria-hidden="true" />
        </button>
        <button type="button" class="annotator__tool annotator__tool--cancel" title="取消" aria-label="取消" @click="cancel">
          <X :size="15" :stroke-width="1.9" aria-hidden="true" />
        </button>
      </div>

      <div class="annotator__input" data-pet-hit>
        <input v-model="capsule" type="text" placeholder="说明你想让我看什么（可留空）" @keydown.enter.prevent="send">
        <button
          class="annotator__send"
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

    <div v-if="error" class="annotator__error">{{ error }}</div>
  </div>
</template>

<style scoped>
.annotator {
  position: absolute;
  inset: 0;
  z-index: 70;
  background: rgba(6, 8, 12, 0.82);
  pointer-events: auto;
}

.annotator__canvas {
  position: absolute;
  cursor: crosshair;
}

/* 底部工具坞：上方工具栏胶囊（上圆角/下直角）+ 下方输入胶囊，紧贴在一起。 */
.annotator__dock {
  position: absolute;
  left: 50%;
  bottom: 24px;
  transform: translateX(-50%);
  display: flex;
  flex-direction: column;
  width: min(620px, calc(100vw - 48px));
  pointer-events: auto;
}

.annotator__tools {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 5px 8px;
  border: 1px solid color-mix(in srgb, var(--theme-main-text, #e9eff9) 14%, transparent);
  border-bottom: 0;
  border-radius: 16px 16px 0 0;
  background: color-mix(in srgb, var(--theme-main-background, #14171c) 92%, transparent);
  -webkit-backdrop-filter: blur(16px) saturate(1.15);
  backdrop-filter: blur(16px) saturate(1.15);
  color: var(--theme-main-text, #e9eff9);
}

.annotator__tool {
  position: relative;
  flex: none;
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: var(--radius-sm, 8px);
  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text, #e9eff9) 62%, transparent);
  cursor: pointer;
}

.annotator__tool:hover {
  background: color-mix(in srgb, var(--theme-main-text, #e9eff9) 10%, transparent);
  color: var(--theme-main-text, #e9eff9);
}

.annotator__tool.is-active {
  background: color-mix(in srgb, var(--theme-main-text, #e9eff9) 16%, transparent);
  color: var(--theme-main-text, #e9eff9);
}

.annotator__tool--cancel {
  margin-left: auto;
}

.annotator__arrow-icon {
  display: block;
  width: 16px;
  height: 16px;
}

.annotator__divider {
  flex: none;
  width: 1px;
  height: 16px;
  margin: 0 4px;
  background: color-mix(in srgb, var(--theme-main-text, #e9eff9) 16%, transparent);
}

/* 调色盘：按钮 + 悬浮时上方的圆形色板胶囊。 */
.annotator__palette-wrap {
  position: relative;
  display: flex;
}

.annotator__color-dot {
  position: absolute;
  right: 4px;
  bottom: 4px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  box-shadow: 0 0 0 1px color-mix(in srgb, #000 35%, transparent);
  pointer-events: none;
}

.annotator__palette {
  position: absolute;
  left: 50%;
  bottom: calc(100% + 10px);
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border: 1px solid color-mix(in srgb, var(--theme-main-text, #e9eff9) 14%, transparent);
  border-radius: 999px;
  background: color-mix(in srgb, var(--theme-main-background, #14171c) 94%, transparent);
  -webkit-backdrop-filter: blur(16px) saturate(1.15);
  backdrop-filter: blur(16px) saturate(1.15);
  box-shadow: 0 14px 34px color-mix(in srgb, #000 32%, transparent);
  white-space: nowrap;
}

/* 悬停从按钮移到色板时中间的空隙也要算在交互范围内，否则菜单会先收起。 */
.annotator__palette::after {
  content: '';
  position: absolute;
  top: 100%;
  right: 0;
  left: 0;
  height: 12px;
}

.annotator__swatch {
  flex: none;
  width: 18px;
  height: 18px;
  padding: 0;
  border: 1px solid color-mix(in srgb, #fff 26%, transparent);
  border-radius: 50%;
  background: var(--swatch);
  cursor: pointer;
  transition: transform var(--dur-fast, 120ms) var(--ease-out, ease-out);
}

.annotator__swatch:hover {
  transform: scale(1.14);
}

.annotator__swatch.is-active {
  box-shadow:
    0 0 0 2px var(--theme-main-background, #14171c),
    0 0 0 3.5px var(--swatch);
}

/* 输入胶囊 + 圆形对号按钮。 */
.annotator__input {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: -1px;
  padding: 6px 6px 6px 16px;
  border: 1px solid color-mix(in srgb, var(--theme-main-text, #e9eff9) 14%, transparent);
  border-radius: 999px;
  background: color-mix(in srgb, var(--theme-main-background, #14171c) 96%, transparent);
  -webkit-backdrop-filter: blur(16px) saturate(1.15);
  backdrop-filter: blur(16px) saturate(1.15);
  box-shadow: 0 16px 36px color-mix(in srgb, #000 34%, transparent);
}

.annotator__input input {
  flex: 1;
  min-width: 0;
  height: 30px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--theme-main-text, #e9eff9);
  font: inherit;
  font-size: 13px;
  outline: none;
}

.annotator__input input::placeholder {
  color: color-mix(in srgb, var(--theme-main-text, #e9eff9) 42%, transparent);
}

.annotator__send {
  flex: none;
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: color-mix(in srgb, var(--theme-main-text, #e9eff9) 90%, transparent);
  color: var(--theme-main-background, #14171c);
  cursor: pointer;
}

.annotator__send:disabled {
  opacity: 0.5;
  cursor: default;
}

.annotator__error {
  position: absolute;
  left: 50%;
  bottom: 160px;
  transform: translateX(-50%);
  color: #ffb4b4;
  font-size: 12px;
}
</style>
