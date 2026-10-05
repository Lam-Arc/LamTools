<template>
  <div
    v-if="outline.length"
    ref="rootEl"
    class="chat-outline-navigator"
    role="group"
    aria-label="用户指令导航"
    :aria-describedby="statusId"
    tabindex="0"
    data-chat-outline-navigator
    @focusin="handleFocusIn"
    @focusout="handleFocusOut"
    @keydown="handleKeydown"
  >
    <canvas
      ref="canvasEl"
      class="chat-outline-navigator__canvas"
      aria-hidden="true"
      @pointermove="handlePointerMove"
      @pointerleave="handlePointerLeave"
      @click="handleCanvasClick"
    />

    <button
      v-if="previewItem"
      ref="previewEl"
      type="button"
      class="chat-outline-navigator__preview optical-glass optical-glass--low-trans"
      :style="previewStyle"
      data-chat-outline-preview
      @pointerenter="handlePreviewEnter"
      @pointerleave="handlePreviewLeave"
      @click.stop="selectIndex(previewIndex)"
    >
      <span class="chat-outline-navigator__preview-label">
        第 {{ previewIndex + 1 }} 条用户指令
      </span>
      <span class="chat-outline-navigator__preview-prompt">
        {{ previewItem.prompt || '（空指令）' }}
      </span>
      <span v-if="previewItem.response_excerpt" class="chat-outline-navigator__preview-response">
        {{ previewItem.response_excerpt }}
      </span>
    </button>

    <span :id="statusId" class="chat-outline-navigator__status" role="status" aria-live="polite">
      {{ statusText }}
    </span>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import type { CoreMessage } from '../types'
import {
  CHAT_OUTLINE_ACTIVATION_RATIO,
  compactOutlineMarkerPositions,
  loadedUserMessageSignature,
  nearestMountedOutlineIndex,
  nearestOutlineIndex,
  normalizeChatOutlinePayload,
  outlineIndexFromScrollProgress,
  outlineMarkerStyle,
  resolveOutlineSelectedIndex,
  type MountedOutlineMessagePosition,
  type ChatOutlineItem,
} from './chatOutlineNavigator'

export type ChatOutlineRequestRpc = (
  method: string,
  params?: Record<string, unknown>,
  timeoutMs?: number,
) => Promise<Record<string, unknown>>

const props = defineProps<{
  sessionId: string | null
  messages: readonly CoreMessage[]
  requestRpc: ChatOutlineRequestRpc
  scrollContainer: HTMLElement | null
}>()

const emit = defineEmits<{
  select: [messageId: string]
}>()

const rootEl = ref<HTMLElement | null>(null)
const canvasEl = ref<HTMLCanvasElement | null>(null)
const previewEl = ref<HTMLElement | null>(null)
const outline = shallowRef<ChatOutlineItem[]>([])
const currentIndex = ref(-1)
const keyboardIndex = ref(-1)
const hoverIndex = ref(-1)
const focused = ref(false)
const statusId = `chat-outline-status-${Math.random().toString(36).slice(2, 9)}`

interface NavigatorLayout {
  positions: number[]
  activationY: number
  activeIndex: number
  rootWidth: number
  rootHeight: number
  trackTop: number
  trackHeight: number
}

const layout = shallowRef<NavigatorLayout>({
  positions: [],
  activationY: 0,
  activeIndex: -1,
  rootWidth: 0,
  rootHeight: 0,
  trackTop: 0,
  trackHeight: 0,
})

let refreshGeneration = 0
let framePending = false
let frameId: number | null = null
let resizeObserver: ResizeObserver | null = null
let hoverLeaveTimer: ReturnType<typeof setTimeout> | null = null
let pointerOverPreview = false

const loadedSignature = computed(() => loadedUserMessageSignature(props.messages))
const selectedIndex = computed(() => resolveOutlineSelectedIndex(
  hoverIndex.value,
  keyboardIndex.value,
  focused.value,
))
const previewIndex = computed(() => {
  if (hoverIndex.value >= 0) return hoverIndex.value
  if (focused.value && keyboardIndex.value >= 0) return keyboardIndex.value
  return -1
})
const previewItem = computed(() => (
  previewIndex.value >= 0 ? outline.value[previewIndex.value] || null : null
))
const statusText = computed(() => {
  const index = selectedIndex.value
  return index >= 0 && outline.value.length
    ? `第 ${index + 1} 条用户指令，共 ${outline.value.length} 条`
    : ''
})
const previewStyle = computed(() => {
  const index = previewIndex.value
  const y = index >= 0 ? layout.value.positions[index] : undefined
  if (y === undefined) return undefined
  const margin = readCssPixels('--space-3', 12)
  const measuredHalfHeight = (previewEl.value?.getBoundingClientRect().height || 0) / 2
  const conservativeHalfHeight = readCssPixels('--space-6', 32) * 3
  const halfHeight = Math.max(
    margin,
    Math.min(layout.value.rootHeight / 2, measuredHalfHeight || conservativeHalfHeight),
  )
  const minY = halfHeight + margin
  const maxY = Math.max(minY, layout.value.rootHeight - halfHeight - margin)
  const boundedY = Math.max(minY, Math.min(maxY, y))
  return { top: `${boundedY}px` }
})

async function refreshOutline(sessionId: string | null, signature: string): Promise<void> {
  const generation = ++refreshGeneration
  outline.value = []
  currentIndex.value = -1
  keyboardIndex.value = -1
  hoverIndex.value = -1
  if (!sessionId) {
    updateScroll()
    return
  }

  try {
    const response = await props.requestRpc('thread.outline', { thread_id: sessionId })
    if (
      generation !== refreshGeneration
      || props.sessionId !== sessionId
      || loadedSignature.value !== signature
    ) return
    outline.value = normalizeChatOutlinePayload(response)
    await nextTick()
    updateScroll()
  } catch {
    // The outline is an optional affordance. A disconnected or older server
    // must not disturb the transcript or surface a second error toast.
  }
}

watch(
  [() => props.sessionId, loadedSignature],
  ([sessionId, signature]) => {
    void refreshOutline(typeof sessionId === 'string' ? sessionId : null, String(signature || ''))
  },
  { immediate: true, flush: 'post' },
)

watch(outline, () => {
  if (keyboardIndex.value >= outline.value.length) keyboardIndex.value = -1
  if (hoverIndex.value >= outline.value.length) hoverIndex.value = -1
  updateScroll()
}, { flush: 'post' })

function readCssPixels(name: string, fallback: number): number {
  const root = rootEl.value
  if (!root || typeof getComputedStyle !== 'function') return fallback
  const parsed = Number.parseFloat(getComputedStyle(root).getPropertyValue(name))
  return Number.isFinite(parsed) ? parsed : fallback
}

function buildLayout(): NavigatorLayout | null {
  const root = rootEl.value
  const thread = props.scrollContainer
  if (!root || !thread || outline.value.length === 0) return null

  const rootRect = root.getBoundingClientRect()
  const threadRect = thread.getBoundingClientRect()
  const rootWidth = rootRect.width || root.clientWidth || readCssPixels('--space-6', 32)
  const rootHeight = rootRect.height || root.clientHeight || threadRect.height
  const trackTop = threadRect.top - rootRect.top
  const trackHeight = threadRect.height || rootHeight
  const activationY = threadRect.top + trackHeight * CHAT_OUTLINE_ACTIVATION_RATIO
  const loadedElements = new Map<string, HTMLElement>()
  thread.querySelectorAll<HTMLElement>('[data-message-id]').forEach((element) => {
    const id = element.dataset.messageId
    if (id && !loadedElements.has(id)) loadedElements.set(id, element)
  })

  // Marker positions are deliberately independent from card heights. The
  // rail is a stable index scale; only the active-item calculation reads
  // mounted message geometry below.
  const positions = compactOutlineMarkerPositions(
    outline.value.length,
    trackTop,
    trackHeight,
    readCssPixels('--space-2', 8),
  )
  const mounted: MountedOutlineMessagePosition[] = []
  outline.value.forEach((item, index) => {
    const element = loadedElements.get(item.message_id)
    if (element) {
      const rect = element.getBoundingClientRect()
      if (rect.height > 0) mounted.push({ index, centerY: rect.top + rect.height * 0.5 })
    }
  })
  const mountedActiveIndex = nearestMountedOutlineIndex(mounted, activationY)
  const activeIndex = mountedActiveIndex >= 0
    ? mountedActiveIndex
    : outlineIndexFromScrollProgress(
      thread.scrollTop,
      thread.scrollHeight,
      thread.clientHeight,
      outline.value.length,
    )
  return { positions, activationY, rootWidth, rootHeight, trackTop, trackHeight, activeIndex }
}

function drawNavigator(): void {
  framePending = false
  frameId = null
  const nextLayout = buildLayout()
  if (!nextLayout) return
  layout.value = nextLayout
  currentIndex.value = nextLayout.activeIndex
  if (focused.value && keyboardIndex.value < 0) keyboardIndex.value = currentIndex.value

  const canvas = canvasEl.value
  const root = rootEl.value
  if (!canvas || !root) return
  let context: CanvasRenderingContext2D | null = null
  try {
    context = canvas.getContext('2d')
  } catch {
    context = null
  }
  if (!context) return

  const pixelRatio = Math.max(
    1,
    Math.min(2, typeof window !== 'undefined' ? window.devicePixelRatio || 1 : 1),
  )
  const width = Math.max(1, Math.round(nextLayout.rootWidth))
  const height = Math.max(1, Math.round(nextLayout.rootHeight))
  if (canvas.width !== width * pixelRatio || canvas.height !== height * pixelRatio) {
    canvas.width = width * pixelRatio
    canvas.height = height * pixelRatio
  }
  context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0)
  context.clearRect(0, 0, width, height)
  const color = getComputedStyle(root).color || 'currentcolor'
  const markerUnit = Math.max(1, Math.min(readCssPixels('--space-1', 4), width / 4))
  context.lineCap = 'round'
  context.strokeStyle = color

  const active = selectedIndex.value
  nextLayout.positions.forEach((position, index) => {
    const style = outlineMarkerStyle(index, active, markerUnit)
    context.globalAlpha = style.opacity
    context.lineWidth = Math.max(1, markerUnit * 0.75)
    context.beginPath()
    context.moveTo(markerUnit, position)
    context.lineTo(Math.min(width - markerUnit, markerUnit + style.length), position)
    context.stroke()
  })
  context.globalAlpha = 1
}

function updateScroll(): void {
  if (framePending) return
  framePending = true
  if (typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function') {
    frameId = window.requestAnimationFrame(drawNavigator)
  } else {
    frameId = null
    drawNavigator()
  }
}

function pointerIndex(event: PointerEvent | MouseEvent): number {
  const canvas = canvasEl.value
  if (!canvas || layout.value.positions.length === 0) return -1
  const rect = canvas.getBoundingClientRect()
  const targetY = event.clientY - rect.top
  const index = nearestOutlineIndex(layout.value.positions, targetY)
  if (index < 0) return -1
  const distance = Math.abs(layout.value.positions[index] - targetY)
  const hitRadius = Math.max(readCssPixels('--space-2', 8), Math.min(readCssPixels('--space-4', 16), layout.value.rootWidth))
  return distance <= hitRadius ? index : -1
}

function clearHoverTimer(): void {
  if (hoverLeaveTimer !== null) {
    clearTimeout(hoverLeaveTimer)
    hoverLeaveTimer = null
  }
}

function handlePointerMove(event: PointerEvent): void {
  clearHoverTimer()
  const nextIndex = pointerIndex(event)
  if (hoverIndex.value === nextIndex) return
  hoverIndex.value = nextIndex
  updateScroll()
}

function handlePointerLeave(): void {
  clearHoverTimer()
  hoverLeaveTimer = setTimeout(() => {
    hoverLeaveTimer = null
    if (!pointerOverPreview && hoverIndex.value >= 0) {
      hoverIndex.value = -1
      updateScroll()
    }
  }, 80)
}

function handleCanvasClick(event: MouseEvent): void {
  const index = pointerIndex(event)
  if (index >= 0) selectIndex(index)
}

function handlePreviewEnter(): void {
  pointerOverPreview = true
  clearHoverTimer()
}

function handlePreviewLeave(): void {
  pointerOverPreview = false
  hoverIndex.value = -1
  updateScroll()
}

function selectIndex(index: number): void {
  const item = outline.value[index]
  if (!item) return
  if (rootEl.value && !rootEl.value.contains(document.activeElement)) {
    rootEl.value.focus({ preventScroll: true })
  }
  keyboardIndex.value = index
  emit('select', item.message_id)
}

function handleFocusIn(): void {
  focused.value = true
  if (keyboardIndex.value < 0) keyboardIndex.value = currentIndex.value >= 0 ? currentIndex.value : 0
}

function handleFocusOut(event: FocusEvent): void {
  const nextTarget = event.relatedTarget
  if (nextTarget instanceof Node && rootEl.value?.contains(nextTarget)) return
  focused.value = false
  keyboardIndex.value = -1
}

function handleKeydown(event: KeyboardEvent): void {
  if (!outline.value.length) return
  const index = keyboardIndex.value >= 0 ? keyboardIndex.value : Math.max(0, currentIndex.value)
  let nextIndex = index
  if (event.key === 'ArrowDown' || event.key === 'ArrowRight') nextIndex = Math.min(outline.value.length - 1, index + 1)
  else if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') nextIndex = Math.max(0, index - 1)
  else if (event.key === 'Home') nextIndex = 0
  else if (event.key === 'End') nextIndex = outline.value.length - 1
  else if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    selectIndex(index)
    return
  } else return

  event.preventDefault()
  keyboardIndex.value = nextIndex
  updateScroll()
}

function observeLayoutTargets(): void {
  resizeObserver?.disconnect()
  resizeObserver = null
  if (typeof ResizeObserver === 'undefined') return
  resizeObserver = new ResizeObserver(() => updateScroll())
  if (rootEl.value) resizeObserver.observe(rootEl.value)
  if (props.scrollContainer) resizeObserver.observe(props.scrollContainer)
}

watch(
  [rootEl, () => props.scrollContainer],
  () => {
    observeLayoutTargets()
    updateScroll()
  },
  { flush: 'post' },
)

onMounted(() => {
  window.addEventListener('resize', updateScroll, { passive: true })
  observeLayoutTargets()
  updateScroll()
})

onUnmounted(() => {
  window.removeEventListener('resize', updateScroll)
  if (frameId !== null && typeof window.cancelAnimationFrame === 'function') {
    window.cancelAnimationFrame(frameId)
  }
  frameId = null
  resizeObserver?.disconnect()
  resizeObserver = null
  clearHoverTimer()
  framePending = false
})

defineExpose({ updateScroll, refreshOutline })
</script>

<style>
.chat-outline-navigator {
  --text: var(--theme-main-text);
  position: absolute;
  inset: 0 auto 0 var(--space-4);
  width: var(--space-6);
  min-height: 0;
  color: color-mix(in srgb, var(--text) 65%, transparent);
  pointer-events: none;
  z-index: var(--z-edge-trigger);
}

.chat-outline-navigator__canvas {
  position: absolute;
  inset: 0;
  display: block;
  width: 100%;
  height: 100%;
  pointer-events: auto;
  cursor: pointer;
  touch-action: manipulation;
}

.chat-outline-navigator__preview {
  position: absolute;
  left: calc(100% + var(--space-2));
  display: grid;
  gap: var(--space-1);
  width: min(24rem, calc(100vw - var(--space-6) - var(--space-6) - var(--space-6)));
  max-height: 12rem;
  box-sizing: border-box;
  padding: var(--space-3);
  border-radius: var(--radius);
  color: var(--text);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transform: translateY(-50%);
  transition: filter var(--dur-base) var(--ease-out), transform var(--dur-base) var(--ease-out);
  pointer-events: auto;
}

.chat-outline-navigator__preview:hover,
.chat-outline-navigator__preview:focus-visible {
  filter: brightness(1.015);
}

.chat-outline-navigator__preview:active {
  transform: translateY(-50%) scale(.98);
}

.chat-outline-navigator__preview:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--text) 72%, transparent);
  outline-offset: 2px;
}

.chat-outline-navigator__preview-label {
  color: color-mix(in srgb, var(--text) 56%, transparent);
  font-size: 11px;
  line-height: 1.3;
}

.chat-outline-navigator__preview-prompt,
.chat-outline-navigator__preview-response {
  overflow: hidden;
  text-overflow: ellipsis;
  word-break: break-word;
  white-space: normal;
}

.chat-outline-navigator__preview-prompt {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 4;
  color: var(--text);
  font-size: 13px;
  font-weight: 650;
  line-height: 1.45;
}

.chat-outline-navigator__preview-response {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  color: color-mix(in srgb, var(--text) 65%, transparent);
  font-size: 12px;
  line-height: 1.4;
}

.chat-outline-navigator__status {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  clip-path: inset(50%);
  white-space: nowrap;
}

@media (prefers-reduced-motion: reduce) {
  .chat-outline-navigator__preview,
  .chat-outline-navigator__preview:hover,
  .chat-outline-navigator__preview:focus-visible,
  .chat-outline-navigator__preview:active {
    transition: none;
    transform: translateY(-50%);
  }
}

@media (max-width: 640px) {
  .chat-outline-navigator {
    display: none;
  }
}
</style>
