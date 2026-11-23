<script setup lang="ts">
/**
 * 浮层外壳（V2-C1）。
 *
 * user:“浮层：拖动/缩放跟手（setFloatRect 每次变更即写、每帧最多一次、矩形不变不写，
 * 松手补最后一帧）、点击置顶、关闭=收起（内容不销毁，可唤回）、Alt+` 循环焦点、
 * Esc 回主区、pin/unpin 接 ops.pinFloat/unpinArea 并显示预览条（预览=落地结果）”+
 * (跟手的关键只有三条：变更立刻排队、每帧只下发一次、值没变就一个字节都不写；
 *  松手时补最后一帧，避免“松手才跟上”的旧病。
 *  浮层拖动**不算**重排手势——交互相位用 'floating'，网页因此保持可见、跟着走。)
 */
import { computed, onBeforeUnmount, ref } from 'vue'
import type { SplitTab } from '@/workspace/types'
import type { Rect } from '@/workspace'
// user:“中间消失了”+(浮窗直接使用独立裁切逻辑，避免与工作区互相加载)。
import { buildCutoutClipPath } from '@/workspace/composition'
import type { WorkspaceContentTarget } from './workspaceInjection'
import type { ComponentPublicInstance } from 'vue'

const props = defineProps<{
  tab: SplitTab
  rect: Rect
  cutoutHoles?: Rect[]
  origin?: { x: number; y: number }
  active: boolean
  yieldEnabled: boolean
  /** 落位预览：pin 的落地结果（不是估算），显示在浮层上方。 */
  preview?: Rect | null
}>()

const emit = defineEmits<{
  'content-target': [target: WorkspaceContentTarget | null]
  focus: []
  close: []
  pin: []
  'pin-hover': [active: boolean]
  'toggle-yield': [enabled: boolean]
  'begin-drag': []
  'end-drag': []
  'rect-change': [rect: Rect]
}>()

const MIN_WIDTH = 240
const MIN_HEIGHT = 160

type ResizeCorner = 'nw' | 'ne' | 'sw' | 'se'

const dragging = ref(false)
// user:“优化一下浮层的拖动手感， 浮层的角落应当可以被拖动以更改大小”+
// (拖动/缩放期间直接驱动本地 liveRect 保证 60/120fps 跟手零卡顿，同时通过 rAF 队列同步到控制器，松手时补最后一帧)
const liveRect = ref<Rect | null>(null)
// user:“浮层队列复用”+(V2-C1b：不再内联第二份 rAF 队列，统一用 `useWorkspace.ts::createRectQueue`，
// 语义不变：同一帧最多下发一次、矩形不变不写、松手 flush 补最后一帧)。
import { createRectQueue } from '@/workspace/useWorkspace'
const rectQueue = createRectQueue(value => emit('rect-change', value), { initial: props.rect })

function queue(next: Rect) {
  liveRect.value = next
  rectQueue.schedule(next)
}

function flush() { rectQueue.flush() }

const style = computed(() => {
  const r = liveRect.value ?? props.rect
  return {
    left: `${r.x}px`,
    top: `${r.y}px`,
    width: `${r.width}px`,
    height: `${r.height}px`,
    // user:“网页层级不正确”+(只有上方活网页覆盖的部分让出，浮窗其余区域照常绘制)。
    clipPath: props.cutoutHoles?.length ? buildCutoutClipPath(r, props.cutoutHoles) : undefined,
  }
})

// user:“这个页面这个问题好像 bug 还不少，你去统一查一查，统一修一修”+
// (浮层里的原生浏览器同样需要基于 origin + liveRect 的窗口绝对坐标，否则网页会左偏并脱离浮窗，拖动时也不跟随)
const FLOAT_HEAD_HEIGHT = 36
const BROWSER_BAR_HEIGHT = 36
const FLOAT_BORDER = 1
const floatWindowHostRect = computed<Rect>(() => {
  const r = liveRect.value ?? props.rect
  return {
    x: r.x + (props.origin?.x ?? 0) + FLOAT_BORDER,
    y: r.y + (props.origin?.y ?? 0) + FLOAT_HEAD_HEIGHT,
    width: Math.max(0, r.width - FLOAT_BORDER * 2),
    height: Math.max(0, r.height - FLOAT_HEAD_HEIGHT - FLOAT_BORDER),
  }
})
const floatWindowContentRect = computed<Rect>(() => {
  const r = floatWindowHostRect.value
  const insetTop = props.tab.kind === 'browser' ? BROWSER_BAR_HEIGHT : 0
  return {
    x: r.x,
    y: r.y + insetTop,
    width: r.width,
    height: Math.max(0, r.height - insetTop),
  }
})
function rects() {
  return { contentRect: floatWindowContentRect.value, hostRect: floatWindowHostRect.value }
}
function setContentTarget(element: Element | ComponentPublicInstance | null) {
  emit('content-target', element instanceof HTMLElement ? { element, rects } : null)
}

const previewStyle = computed(() => {
  const rect = props.preview
  if (!rect) return null
  return {
    left: `${rect.x}px`,
    top: `${rect.y}px`,
    width: `${rect.width}px`,
    height: `${rect.height}px`,
  }
})

let start = { x: 0, y: 0, rect: { ...props.rect }, corner: 'se' as ResizeCorner }

function onHeaderDown(event: PointerEvent) {
  if (event.button !== 0) return
  emit('focus')
  dragging.value = true
  start = { x: event.clientX, y: event.clientY, rect: { ...props.rect }, corner: 'se' }
  liveRect.value = { ...props.rect }
  ;(event.currentTarget as HTMLElement | null)?.setPointerCapture?.(event.pointerId)
  emit('begin-drag')
}

function onResizeDown(corner: ResizeCorner, event: PointerEvent) {
  if (event.button !== 0) return
  emit('focus')
  dragging.value = true
  start = { x: event.clientX, y: event.clientY, rect: { ...props.rect }, corner }
  liveRect.value = { ...props.rect }
  ;(event.currentTarget as HTMLElement | null)?.setPointerCapture?.(event.pointerId)
  emit('begin-drag')
}

function onMove(event: PointerEvent) {
  if (!dragging.value) return
  const dx = event.clientX - start.x
  const dy = event.clientY - start.y
  queue({
    x: Math.round(start.rect.x + dx),
    y: Math.round(start.rect.y + dy),
    width: start.rect.width,
    height: start.rect.height,
  })
}

function onResizeMove(event: PointerEvent) {
  if (!dragging.value) return
  const dx = event.clientX - start.x
  const dy = event.clientY - start.y
  const fromLeft = start.corner === 'nw' || start.corner === 'sw'
  const fromTop = start.corner === 'nw' || start.corner === 'ne'
  const width = Math.max(MIN_WIDTH, Math.round(fromLeft ? start.rect.width - dx : start.rect.width + dx))
  const height = Math.max(MIN_HEIGHT, Math.round(fromTop ? start.rect.height - dy : start.rect.height + dy))
  const x = fromLeft ? start.rect.x + (start.rect.width - width) : start.rect.x
  const y = fromTop ? start.rect.y + (start.rect.height - height) : start.rect.y
  queue({ x, y, width, height })
}

function stop() {
  if (!dragging.value) return
  dragging.value = false
  // 松手补最后一帧：拖动期间被合并掉的那一次必须落地。
  flush()
  liveRect.value = null
  emit('end-drag')
}

onBeforeUnmount(() => rectQueue.dispose())
</script>

<template>
  <div
    class="ws2-float"
    :class="{ 'is-active': props.active, 'is-dragging': dragging }"
    :style="style"
    :data-ws2-float="props.tab.id"
    role="dialog"
    :aria-label="props.tab.title"
    @pointerdown="emit('focus')"
  >
    <div
      v-if="previewStyle"
      class="ws2-float__preview"
      :style="previewStyle"
      aria-hidden="true"
    ></div>

    <header
      class="ws2-float__head"
      @pointerdown="onHeaderDown"
      @pointermove="onMove"
      @pointerup="stop"
      @pointercancel="stop"
    >
      <span class="ws2-float__title">{{ props.tab.title }}</span>
      <button
        class="ws2-float__action"
        type="button"
        :aria-pressed="props.yieldEnabled"
        :title="props.yieldEnabled ? '关闭自由让位' : '开启自由让位'"
        @pointerdown.stop
        @click.stop="emit('toggle-yield', !props.yieldEnabled)"
      >让位</button>
      <button
        class="ws2-float__action"
        type="button"
        data-ws2-float-pin
        title="固定到工作区"
        @pointerdown.stop
        @pointerenter="emit('pin-hover', true)"
        @pointerleave="emit('pin-hover', false)"
        @focus="emit('pin-hover', true)"
        @blur="emit('pin-hover', false)"
        @click.stop="emit('pin-hover', false); emit('pin')"
      >固定</button>
      <button class="ws2-float__action" type="button" aria-label="收起" @pointerdown.stop @click.stop="emit('close')">×</button>
    </header>

    <div :ref="setContentTarget" class="ws2-float__body"></div>

    <span
      v-for="corner in (['nw', 'ne', 'sw', 'se'] as const)"
      :key="corner"
      class="ws2-float__grip"
      :class="`ws2-float__grip--${corner}`"
      :data-ws2-float-grip="corner"
      :aria-label="'缩放浮层'"
      @pointerdown.stop="onResizeDown(corner, $event)"
      @pointermove="onResizeMove"
      @pointerup="stop"
      @pointercancel="stop"
    ></span>
  </div>
</template>
