<template>
  <div
    v-if="outline.length"
    ref="rootEl"
    class="chat-outline-navigator"
    :class="{ 'chat-outline-navigator--catalog-open': catalogOpen }"
    :style="{
      top: `${layout.railTop}px`,
      height: `${layout.railHeight}px`,
      '--outline-controls-top': `${layout.controlsTop}px`,
      '--outline-controls-bottom': `${layout.controlsBottom}px`,
      '--outline-catalog-bottom': `${layout.catalogBottom}px`,
      '--outline-catalog-max-height': `${layout.catalogMaxHeight}px`,
      '--outline-marker-inset': `${layout.markerUnit}px`,
      '--outline-marker-width': `${layout.markerUnit * 3}px`,
      '--outline-marker-stroke': `${Math.max(1, layout.markerUnit * 0.75)}px`,
    }"
    role="group"
    :aria-label="t('用户指令导航')"
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

    <!-- user:“紧贴标记组的上下边缘”+(上翻箭头贴在第一条用户消息标记上方) -->
    <div
      ref="topControlsEl"
      class="chat-outline-navigator__controls chat-outline-navigator__controls--top"
      data-chat-outline-pager
    >
      <button
        v-if="canPageUp"
        type="button"
        class="chat-outline-navigator__pager-button"
        :aria-label="t('上一页用户消息')"
        data-chat-outline-page-up
        @click="shiftPage(-1)"
      >
        <ChevronUp class="chat-outline-navigator__arrow-icon" aria-hidden="true" />
      </button>
    </div>

    <!-- user:“那个目录键放在下箭头的下方在下方放 1/几这种数字”+(最后一条标记下方依次是：下翻箭头、目录键、页码) -->
    <div
      ref="controlsEl"
      class="chat-outline-navigator__controls chat-outline-navigator__controls--bottom"
      data-chat-outline-pager
    >
      <button
        v-if="canPageDown"
        type="button"
        class="chat-outline-navigator__pager-button"
        :aria-label="t('下一页用户消息')"
        data-chat-outline-page-down
        @click="shiftPage(1)"
      >
        <ChevronDown class="chat-outline-navigator__arrow-icon" aria-hidden="true" />
      </button>
      <!-- user:“目录那个按钮 把它换成图标 别用文字”+(目录入口只显示列表图标，文字仅保留在无障碍名称里) -->
      <button
        ref="catalogToggleEl"
        type="button"
        class="chat-outline-navigator__catalog-toggle"
        :aria-expanded="catalogOpen"
        :aria-label="catalogOpen ? t('收起目录') : t('展开目录')"
        :title="catalogOpen ? t('收起目录') : t('展开目录')"
        data-chat-outline-catalog-toggle
        @click="toggleCatalog"
      >
        <List class="chat-outline-navigator__arrow-icon" aria-hidden="true" />
      </button>
      <span
        class="chat-outline-navigator__page-indicator"
        :aria-label="t('第 {0} 页，共 {1} 页', { 0: pageNumber, 1: pageTotal })"
        data-chat-outline-page-indicator
      >{{ pageNumber }}/{{ pageTotal }}</span>
    </div>

    <!-- user:“支持时间排序、关键词搜索和类型筛选”+(目录卡片按关键词/类型筛选，可切换时间正序倒序，点击条目跳转) -->
    <div
      v-if="catalogOpen"
      ref="catalogEl"
      class="chat-outline-navigator__catalog optical-glass optical-glass--low-trans"
      role="dialog"
      :aria-label="t('用户指令目录')"
      :aria-describedby="statusId"
      data-chat-outline-catalog
    >
      <div class="chat-outline-navigator__catalog-head">
        <span class="chat-outline-navigator__catalog-title">{{ t("目录") }}</span>
        <span class="chat-outline-navigator__catalog-count" data-chat-outline-catalog-count>
          {{ catalogEntries.length }}/{{ outline.length }}
        </span>
      </div>

      <div class="chat-outline-navigator__catalog-controls">
        <input
          ref="catalogSearchEl"
          class="chat-outline-navigator__catalog-search"
          type="search"
          :value="catalogQuery"
          :placeholder="t('搜索用户消息')"
          :aria-label="t('搜索用户消息')"
          data-chat-outline-catalog-search
          data-chat-outline-catalog-control
          @input="handleCatalogSearchInput"
        >
        <div
          class="chat-outline-navigator__catalog-filters"
          role="group"
          :aria-label="t('消息类型筛选')"
          data-chat-outline-catalog-control
        >
          <button
            v-for="option in catalogKindOptions"
            :key="option.value"
            type="button"
            class="chat-outline-navigator__catalog-chip"
            :class="{ 'is-active': catalogKind === option.value }"
            :aria-pressed="catalogKind === option.value"
            :data-chat-outline-catalog-kind="option.value"
            @click="catalogKind = option.value"
          >{{ option.label }}</button>
        </div>
        <button
          type="button"
          class="chat-outline-navigator__catalog-sort"
          :aria-label="t('切换时间排序方向')"
          data-chat-outline-catalog-control
          data-chat-outline-catalog-sort
          @click="toggleCatalogSort"
        >{{ catalogSort === 'asc' ? t("时间：旧→新") : t("时间：新→旧") }}</button>
      </div>

      <ul class="chat-outline-navigator__catalog-list" data-chat-outline-catalog-list>
        <li v-for="entry in catalogEntries" :key="entry.item.message_id">
          <button
            type="button"
            class="chat-outline-navigator__catalog-item"
            :class="{
              'is-active': entry.index === selectedGlobalIndex,
              'is-guide': entry.isGuide,
            }"
            :data-chat-outline-catalog-item="entry.item.message_id"
            :data-chat-outline-catalog-kind-value="entry.isGuide ? 'guide' : 'normal'"
            @click="jumpToCatalogEntry(entry.index)"
          >
            <span class="chat-outline-navigator__catalog-item-meta">
              <span class="chat-outline-navigator__catalog-item-index">#{{ entry.index + 1 }}</span>
              <span
                v-if="entry.isGuide"
                class="chat-outline-navigator__catalog-item-badge"
              >{{ t("引导") }}</span>
              <span
                v-if="formatOutlineTimestamp(entry.item.timestamp)"
                class="chat-outline-navigator__catalog-item-time"
              >{{ formatOutlineTimestamp(entry.item.timestamp) }}</span>
            </span>
            <span class="chat-outline-navigator__catalog-item-prompt">
              {{ entry.item.prompt || t("（空指令）") }}
            </span>
          </button>
        </li>
        <li
          v-if="!catalogEntries.length"
          class="chat-outline-navigator__catalog-empty"
          data-chat-outline-catalog-empty
        >{{ t("没有匹配的用户消息") }}</li>
      </ul>
    </div>

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
        {{ t("第") }}{{ previewIndex + 1 }}{{ t("条用户指令") }}
        <span
          v-if="previewIsGuide"
          class="chat-outline-navigator__preview-badge"
        >{{ t("引导") }}</span>
      </span>
      <span class="chat-outline-navigator__preview-prompt">
        {{ previewItem.prompt || t("（空指令）") }}
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
import { t } from '@/i18n/index.ts'

import { ChevronDown, ChevronUp, List } from 'lucide-vue-next'
import { computed, nextTick, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import type { CoreMessage } from '@/types.ts'
import {
  CHAT_OUTLINE_ACTIVATION_RATIO,
  CHAT_OUTLINE_PAGE_SIZE,
  bracketOutlineControls,
  buildOutlineCatalog,
  clampOutlinePage,
  compactOutlineMarkerPositions,
  filterOutlineCatalog,
  formatOutlineTimestamp,
  isGuideOutlineItem,
  loadedUserMessageSignature,
  nearestMountedOutlineIndex,
  nearestOutlineIndex,
  normalizeChatOutlinePayload,
  outlineIndexFromScrollProgress,
  outlineCatalogBounds,
  outlineMarkerHitRadius,
  outlineMarkerStyle,
  outlinePageCount,
  resolveOutlineSelectedIndex,
  sortOutlineCatalog,
  type ChatOutlineKind,
  type ChatOutlineSortDirection,
  type MountedOutlineMessagePosition,
  type ChatOutlineItem,
} from '@/components/chatOutlineNavigator.ts'

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
const controlsEl = ref<HTMLElement | null>(null)
const topControlsEl = ref<HTMLElement | null>(null)
const catalogEl = ref<HTMLElement | null>(null)
const catalogSearchEl = ref<HTMLInputElement | null>(null)
const catalogToggleEl = ref<HTMLButtonElement | null>(null)
const outline = shallowRef<ChatOutlineItem[]>([])
const currentIndex = ref(-1)
// user:“按原始顺序记录用户消息”+(hover/键盘索引一直用全局原始序号，翻页只在渲染时切片)
const keyboardIndex = ref(-1)
const hoverIndex = ref(-1)
const focused = ref(false)
// user:“上下竖向 > 分页，每页 20 条”+(当前页号，每页固定 20 条，越界一律夹回合法范围)
const pageIndex = ref(0)
const catalogOpen = ref(false)
const catalogQuery = ref('')
const catalogKind = ref<ChatOutlineKind>('all')
const catalogSort = ref<ChatOutlineSortDirection>('asc')
const statusId = `chat-outline-status-${Math.random().toString(36).slice(2, 9)}`

interface NavigatorLayout {
  positions: number[]
  activationY: number
  activeIndex: number
  rootWidth: number
  rootHeight: number
  trackTop: number
  trackHeight: number
  pageStart: number
  controlsTop: number
  controlsBottom: number
  catalogBottom: number
  catalogMaxHeight: number
  markerUnit: number
  railTop: number
  railHeight: number
}

const layout = shallowRef<NavigatorLayout>({
  positions: [],
  activationY: 0,
  activeIndex: -1,
  rootWidth: 0,
  rootHeight: 0,
  trackTop: 0,
  trackHeight: 0,
  pageStart: 0,
  controlsTop: 0,
  controlsBottom: 0,
  catalogBottom: 0,
  catalogMaxHeight: 0,
  markerUnit: 4,
  railTop: 0,
  railHeight: 0,
})

let refreshGeneration = 0
let framePending = false
let frameId: number | null = null
let resizeObserver: ResizeObserver | null = null
let hoverLeaveTimer: ReturnType<typeof setTimeout> | null = null
let pointerOverPreview = false
/** Last scroll-derived index the rail already paged to (manual paging wins). */
let followedActiveIndex = -1

const loadedSignature = computed(() => loadedUserMessageSignature(props.messages))
const pageTotal = computed(() => outlinePageCount(outline.value.length))
const pageNumber = computed(() => Math.min(pageTotal.value, pageIndex.value + 1))
const pageStart = computed(() => (
  clampOutlinePage(pageIndex.value, outline.value.length) * CHAT_OUTLINE_PAGE_SIZE
))
const canPageUp = computed(() => pageIndex.value > 0)
const canPageDown = computed(() => pageIndex.value + 1 < pageTotal.value)
// user:“区分引导消息与普通消息”+(目录卡片提供 全部/引导/普通 三种筛选)
const catalogKindOptions = computed<Array<{ value: ChatOutlineKind; label: string }>>(() => [
  { value: 'all', label: t('全部') },
  { value: 'guide', label: t('引导') },
  { value: 'normal', label: t('普通') },
])

const selectedGlobalIndex = computed(() => resolveOutlineSelectedIndex(
  hoverIndex.value,
  keyboardIndex.value,
  focused.value,
))
const selectedPageIndex = computed(() => {
  const index = selectedGlobalIndex.value - pageStart.value
  return index >= 0 && index < CHAT_OUTLINE_PAGE_SIZE ? index : -1
})
const previewIndex = computed(() => {
  if (hoverIndex.value >= 0) return hoverIndex.value
  if (focused.value && keyboardIndex.value >= 0) return keyboardIndex.value
  return -1
})
const previewItem = computed(() => (
  previewIndex.value >= 0 ? outline.value[previewIndex.value] || null : null
))
const previewIsGuide = computed(() => isGuideOutlineItem(previewItem.value))
const statusText = computed(() => {
  const index = selectedGlobalIndex.value
  return index >= 0 && outline.value.length
    ? t("第 {0} 条用户指令，共 {1} 条", { 0: index + 1, 1: outline.value.length })
    : ''
})
const catalogEntries = computed(() => sortOutlineCatalog(
  filterOutlineCatalog(
    buildOutlineCatalog(outline.value),
    catalogQuery.value,
    catalogKind.value,
  ),
  catalogSort.value,
))
const previewStyle = computed(() => {
  const index = previewIndex.value
  const localIndex = index - pageStart.value
  const y = localIndex >= 0 ? layout.value.positions[localIndex] : undefined
  if (y === undefined) return undefined
  const margin = readCssPixels('--space-3', 12)
  const measuredHalfHeight = (previewEl.value?.getBoundingClientRect().height || 0) / 2
  const conservativeHalfHeight = readCssPixels('--space-6', 32) * 3
  const halfHeight = Math.max(
    margin,
    Math.min(layout.value.rootHeight / 2, measuredHalfHeight || conservativeHalfHeight),
  )
  const minY = halfHeight + margin
  // 预览卡也不越过消息区底边，避免被输入栏盖住。
  const visibleBottom = layout.value.trackTop + layout.value.trackHeight
  const maxY = Math.max(minY, visibleBottom - halfHeight - margin)
  const boundedY = Math.max(minY, Math.min(maxY, y))
  return { top: `${boundedY}px` }
})

async function refreshOutline(sessionId: string | null, signature: string): Promise<void> {
  const generation = ++refreshGeneration
  outline.value = []
  currentIndex.value = -1
  keyboardIndex.value = -1
  hoverIndex.value = -1
  pageIndex.value = 0
  followedActiveIndex = -1
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
  const clampedPage = clampOutlinePage(pageIndex.value, outline.value.length)
  if (clampedPage !== pageIndex.value) pageIndex.value = clampedPage
  if (keyboardIndex.value >= outline.value.length) keyboardIndex.value = -1
  if (hoverIndex.value >= outline.value.length) hoverIndex.value = -1
  updateScroll()
}, { flush: 'post' })

watch(pageIndex, () => updateScroll(), { flush: 'post' })

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
  // Same unit the canvas uses for every bar, so the pager arrows can share the
  // bars' horizontal start, width and stroke weight.
  const markerUnit = Math.max(1, Math.min(readCssPixels('--space-1', 4), rootWidth / 4))
  const trackTop = threadRect.top - rootRect.top
  const trackHeight = threadRect.height || rootHeight
  const activationY = threadRect.top + trackHeight * CHAT_OUTLINE_ACTIVATION_RATIO
  const loadedElements = new Map<string, HTMLElement>()
  thread.querySelectorAll<HTMLElement>('[data-message-id]').forEach((element) => {
    const id = element.dataset.messageId
    if (id && !loadedElements.has(id)) loadedElements.set(id, element)
  })

  // Pager arrows sit above and below the marker group, so markers are laid
  // out only inside the remaining space and one page shows at most 20 of them.
  const topControlsHeight = topControlsEl.value?.getBoundingClientRect().height || 0
  const bottomControlsHeight = controlsEl.value?.getBoundingClientRect().height || 0
  const edgeGap = readCssPixels('--space-2', 8)
  const start = pageStart.value
  const pageLength = Math.max(0, Math.min(
    CHAT_OUTLINE_PAGE_SIZE,
    outline.value.length - start,
  ))
  // Marker positions are deliberately independent from card heights. The
  // rail is a stable index scale; only the active-item calculation reads
  // mounted message geometry below.
  const markerTop = trackTop + topControlsHeight + edgeGap
  const markerHeight = Math.max(
    0,
    trackHeight - topControlsHeight - bottomControlsHeight - edgeGap * 2,
  )
  const positions = compactOutlineMarkerPositions(
    pageLength,
    markerTop,
    markerHeight,
    edgeGap,
  )
  // user:“紧贴标记组的上下边缘”+(箭头与底部控件跟随标记组首尾，而不是钉在整条栏的两端)
  const controls = bracketOutlineControls(
    positions,
    edgeGap,
    topControlsHeight,
    bottomControlsHeight,
    rootHeight,
  )
  // user:“点击目录按钮出的那个卡片它现在被输入框给遮挡了”+(卡片底边跟着下翻控件组走，
  // 始终留在消息区内，不再沉到输入栏下面被盖住)
  const stackBottomLocal = controls.bottom + bottomControlsHeight
  const catalogBounds = outlineCatalogBounds(rootHeight, stackBottomLocal, edgeGap)
  // 导航条收窄后卡片仍按整个消息区的高度伸展，而不是被导航条自身的小盒子压矮。
  const catalogAvailableHeight = Math.max(
    0,
    stackBottomLocal + rootRect.top - threadRect.top - edgeGap,
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
  // user:“把导航栏大小收缩到响应式大小 根据需要”+(导航条盒子只包住标记组和上下控件，
  // 不再占满整个消息区高度；悬停/点击判定也跟着盒子一起收窄)
  const offsetParent = root.offsetParent
  const containerRect = offsetParent instanceof HTMLElement
    ? offsetParent.getBoundingClientRect()
    : rootRect
  const firstMarker = positions.length ? Math.min(...positions) : trackTop + trackHeight / 2
  const lastMarker = positions.length ? Math.max(...positions) : firstMarker
  const railTopViewport = firstMarker + rootRect.top - edgeGap - topControlsHeight
  const railBottomViewport = lastMarker + rootRect.top + edgeGap + bottomControlsHeight
  const railTop = Math.max(0, Math.round(railTopViewport - containerRect.top))
  const railHeight = Math.max(0, Math.round(railBottomViewport - railTopViewport))
  return {
    positions,
    activationY,
    rootWidth,
    rootHeight,
    trackTop,
    trackHeight,
    activeIndex,
    pageStart: start,
    controlsTop: controls.top,
    controlsBottom: controls.bottom,
    catalogBottom: catalogBounds.bottom,
    catalogMaxHeight: catalogAvailableHeight,
    markerUnit,
    railTop,
    railHeight,
  }
}

function drawNavigator(): void {
  framePending = false
  frameId = null
  const nextLayout = buildLayout()
  if (!nextLayout) return
  layout.value = nextLayout
  currentIndex.value = nextLayout.activeIndex

  // Follow the transcript across page boundaries, otherwise the rail would
  // highlight a marker that is not part of the page being drawn. Only a change
  // of the scroll-derived index triggers the follow, so manually paged views
  // are not snapped back on the next redraw.
  if (nextLayout.activeIndex >= 0 && nextLayout.activeIndex !== followedActiveIndex) {
    followedActiveIndex = nextLayout.activeIndex
    const activePage = Math.floor(nextLayout.activeIndex / CHAT_OUTLINE_PAGE_SIZE)
    if (activePage !== pageIndex.value && activePage < outlinePageCount(outline.value.length)) {
      pageIndex.value = activePage
      updateScroll()
      return
    }
  }
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
  const markerUnit = nextLayout.markerUnit
  context.lineCap = 'round'
  context.strokeStyle = color

  const active = selectedPageIndex.value
  nextLayout.positions.forEach((position, index) => {
    const style = outlineMarkerStyle(index, active, markerUnit)
    // Guide instructions keep the same scale but stay visually lighter so a
    // page of markers still tells the two message kinds apart.
    const guide = isGuideOutlineItem(outline.value[nextLayout.pageStart + index])
    const scale = guide ? 0.62 : 1
    context.globalAlpha = guide ? style.opacity * 0.78 : style.opacity
    context.lineWidth = Math.max(1, markerUnit * (guide ? 0.55 : 0.75))
    context.beginPath()
    context.moveTo(markerUnit, position)
    context.lineTo(Math.min(width - markerUnit, markerUnit + style.length * scale), position)
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
  return distance <= outlineMarkerHitRadius(layout.value.positions) ? index : -1
}

function clearHoverTimer(): void {
  if (hoverLeaveTimer !== null) {
    clearTimeout(hoverLeaveTimer)
    hoverLeaveTimer = null
  }
}

function handlePointerMove(event: PointerEvent): void {
  clearHoverTimer()
  const localIndex = pointerIndex(event)
  const nextIndex = localIndex >= 0 ? layout.value.pageStart + localIndex : -1
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
  const localIndex = pointerIndex(event)
  if (localIndex >= 0) selectIndex(layout.value.pageStart + localIndex)
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

function shiftPage(delta: number): void {
  const nextPage = clampOutlinePage(pageIndex.value + delta, outline.value.length)
  if (nextPage === pageIndex.value) return
  pageIndex.value = nextPage
  hoverIndex.value = -1
  updateScroll()
}

function selectIndex(index: number, options: { focusRoot?: boolean } = {}): void {
  const item = outline.value[index]
  if (!item) return
  if (options.focusRoot !== false && rootEl.value && !rootEl.value.contains(document.activeElement)) {
    rootEl.value.focus({ preventScroll: true })
  }
  keyboardIndex.value = index
  const page = Math.floor(index / CHAT_OUTLINE_PAGE_SIZE)
  if (page !== pageIndex.value && page < outlinePageCount(outline.value.length)) {
    pageIndex.value = page
  }
  emit('select', item.message_id)
}

function toggleCatalog(): void {
  if (catalogOpen.value) {
    closeCatalog()
    return
  }
  catalogOpen.value = true
  // The catalog is its own focus context: drop the rail selection so the
  // preview card does not hover over the list while browsing it.
  focused.value = false
  clearHoverTimer()
  hoverIndex.value = -1
  void nextTick(() => catalogSearchEl.value?.focus())
}

function closeCatalog(): void {
  if (!catalogOpen.value) return
  catalogOpen.value = false
  catalogToggleEl.value?.focus()
}

function toggleCatalogSort(): void {
  catalogSort.value = catalogSort.value === 'asc' ? 'desc' : 'asc'
}

function handleCatalogSearchInput(event: Event): void {
  const target = event.target
  catalogQuery.value = target instanceof HTMLInputElement ? target.value : ''
}

function jumpToCatalogEntry(index: number): void {
  catalogOpen.value = false
  selectIndex(index, { focusRoot: false })
}

function isRailControlTarget(target: EventTarget | null): boolean {
  return target instanceof HTMLElement
    && Boolean(target.closest('button, input, textarea, select, a, [contenteditable="true"]'))
}

function handleDocumentPointerDown(event: PointerEvent): void {
  const target = event.target
  if (!(target instanceof Node)) return
  if (catalogEl.value?.contains(target)) return
  if (catalogToggleEl.value?.contains(target)) return
  closeCatalog()
}

watch(catalogOpen, (open) => {
  if (typeof document === 'undefined') return
  if (open) document.addEventListener('pointerdown', handleDocumentPointerDown, true)
  else document.removeEventListener('pointerdown', handleDocumentPointerDown, true)
})

function handleFocusIn(event: FocusEvent): void {
  const target = event.target
  if (target instanceof HTMLElement && target.closest(
    '[data-chat-outline-catalog], [data-chat-outline-pager], [data-chat-outline-catalog-toggle]',
  )) return
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
  if (event.key === 'Escape' && catalogOpen.value) {
    event.preventDefault()
    closeCatalog()
    return
  }
  // Buttons and the search field inside the rail keep their own key handling.
  if (isRailControlTarget(event.target)) return
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
  } else if (event.key === 'PageDown') {
    event.preventDefault()
    shiftPage(1)
    return
  } else if (event.key === 'PageUp') {
    event.preventDefault()
    shiftPage(-1)
    return
  } else return

  event.preventDefault()
  keyboardIndex.value = nextIndex
  const page = Math.floor(nextIndex / CHAT_OUTLINE_PAGE_SIZE)
  if (page !== pageIndex.value) pageIndex.value = page
  updateScroll()
}

function observeLayoutTargets(): void {
  resizeObserver?.disconnect()
  resizeObserver = null
  if (typeof ResizeObserver === 'undefined') return
  resizeObserver = new ResizeObserver(() => updateScroll())
  if (rootEl.value) resizeObserver.observe(rootEl.value)
  if (props.scrollContainer) resizeObserver.observe(props.scrollContainer)
  if (controlsEl.value) resizeObserver.observe(controlsEl.value)
  if (topControlsEl.value) resizeObserver.observe(topControlsEl.value)
}

watch(
  [rootEl, () => props.scrollContainer, controlsEl, topControlsEl],
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
  if (typeof document !== 'undefined') {
    document.removeEventListener('pointerdown', handleDocumentPointerDown, true)
  }
  clearHoverTimer()
  framePending = false
})

defineExpose({ updateScroll, refreshOutline })
</script>

<style>
.chat-outline-navigator {
  --text: var(--theme-main-text);
  position: absolute;
  left: var(--space-4);
  /* user:“把导航栏大小收缩到响应式大小 根据需要”+(整条栏收窄到控件所需宽度，高度由脚本按内容算) */
  width: var(--space-5);
  min-height: 0;
  color: color-mix(in srgb, var(--text) 72%, transparent);
  pointer-events: none;
  /* user:“不是按钮有背景，是有一个大的竖条胶囊”+(整条导航栏本身去掉边框和胶囊底色，
     只保留透明的悬浮条与标记；淡灰圆底只留在翻页键上) */
  border: 0;
  border-radius: 0;
  background: none;
  box-shadow: none;
  z-index: var(--z-edge-trigger);
}

/* 目录卡片比侧栏自身的浮层优先级更高：打开时整条左栏提到弹层层级，
   否则会压到输入栏下面。 */
.chat-outline-navigator--catalog-open {
  z-index: var(--z-popover);
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

/* user:“那个目录键，还有不要一直显示，等 hover 到导航条那块之后再显示出来”
   +(翻页键、目录键、页码默认隐藏，指针进入导航条或键盘聚焦后再淡入) */
.chat-outline-navigator__controls {
  position: absolute;
  right: 0;
  left: 0;
  display: grid;
  justify-items: start;
  padding-left: var(--outline-marker-inset, var(--space-1));
  gap: var(--space-1);
  opacity: 0;
  pointer-events: none;
  transition: opacity var(--dur-fast) var(--ease-out);
}

.chat-outline-navigator:hover > .chat-outline-navigator__controls,
.chat-outline-navigator:focus-within > .chat-outline-navigator__controls,
.chat-outline-navigator--catalog-open > .chat-outline-navigator__controls {
  opacity: 1;
  pointer-events: auto;
}

/* user:“紧贴标记组的上下边缘”+(上箭头的顶边由脚本按第一条标记的位置算出来) */
.chat-outline-navigator__controls--top {
  top: var(--outline-controls-top, var(--space-2));
}

/* user:“紧贴标记组的上下边缘”+(下箭头、目录键、页码这一组从最后一条标记下方开始) */
.chat-outline-navigator__controls--bottom {
  top: var(--outline-controls-bottom, var(--space-2));
  bottom: auto;
}

.chat-outline-navigator__pager-button {
  display: flex;
  align-items: center;
  justify-content: center;
  width: var(--space-5);
  height: var(--space-5);
  padding: 0;
  /* user:“玻璃样式 你是不是把边框给忘掉了？”+(淡灰圆底保留一圈随明暗变化的细边，像玻璃控件) */
  border: 1px solid color-mix(in srgb, var(--text) 18%, transparent);
  /* user:“它本身不是一种类似淡灰色吗？你把它的那种给整明显一点就行了，但注意明暗”
     +(翻页键常驻淡灰圆底：浅色主题取深字色的低比例=淡灰，深色主题取浅字色的低比例=淡亮灰；
       不用阴影，只靠这层底色) */
  border-radius: 999px;
  background: color-mix(in srgb, var(--text) 10%, transparent);
  /* 圆底和标记条共用同一条中心线：圆比 12px 标记宽时向两侧对称让出。 */
  margin-left: calc((var(--outline-marker-width, 12px) - var(--space-5)) / 2);
  color: inherit;
  font: inherit;
  box-shadow: none;
  cursor: pointer;
  transition: background-color var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}

.chat-outline-navigator__pager-button:hover:not(:disabled),
.chat-outline-navigator__pager-button:active:not(:disabled) {
  background: color-mix(in srgb, var(--text) 16%, transparent);
  color: var(--text);
}

.chat-outline-navigator__pager-button:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--text) 72%, transparent);
  outline-offset: 1px;
}

.chat-outline-navigator__pager-button:disabled {
  opacity: .32;
  cursor: default;
}

/* user:“两个箭头，不要直接用文字的那个符号”“在杠变宽的时候，箭头同步变宽”+(箭头改用图标，
   尺寸/线宽和标记条共用同一套单位，杆变粗时箭头一起变粗) */
.chat-outline-navigator__arrow-icon {
  display: block;
  flex: none;
  width: var(--outline-marker-width, 12px);
  height: var(--outline-marker-width, 12px);
  stroke-width: var(--outline-marker-stroke, 3);
}

.chat-outline-navigator__page-indicator {
  color: color-mix(in srgb, var(--text) 65%, transparent);
  font-size: 9px;
  font-variant-numeric: tabular-nums;
  letter-spacing: .02em;
  line-height: 1.2;
  white-space: nowrap;
}

/* user:“目录怎么还有那么大的一个边框和胶囊背景呢”+(选择器提高一级，任何旧样式表都盖不掉；
   盒子收到图标大小，边框/背景彻底没有) */
.chat-outline-navigator .chat-outline-navigator__controls .chat-outline-navigator__catalog-toggle {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  width: var(--outline-marker-width, 12px);
  height: var(--outline-marker-width, 12px);
  padding: 0;
  border: 0;
  border-radius: 0;
  background: none;
  box-shadow: none;
  /* user:“箭头和目录都和横轴一个颜色，选中时变色”+(目录图标沿用标记条的颜色，展开时提亮) */
  color: inherit;
  line-height: 1;
  cursor: pointer;
  transition: color var(--dur-fast) var(--ease-out);
}

.chat-outline-navigator .chat-outline-navigator__controls .chat-outline-navigator__catalog-toggle:hover,
.chat-outline-navigator .chat-outline-navigator__controls .chat-outline-navigator__catalog-toggle[aria-expanded="true"] {
  background: none;
  color: var(--text);
}

.chat-outline-navigator .chat-outline-navigator__controls .chat-outline-navigator__catalog-toggle:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--text) 72%, transparent);
  outline-offset: 1px;
}

.chat-outline-navigator__catalog {
  position: absolute;
  /* user:“点击目录按钮出的那个卡片它现在被输入框给遮挡了”+(底边贴住下翻控件组，
     高度按上方可用空间收缩，卡片不会再伸进输入栏区域) */
  bottom: var(--outline-catalog-bottom, var(--space-2));
  left: calc(100% + var(--space-2));
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
  gap: var(--space-2);
  width: min(21rem, calc(100vw - var(--space-6) - var(--space-6) - var(--space-6)));
  max-height: min(60vh, 30rem, var(--outline-catalog-max-height, 30rem));
  box-sizing: border-box;
  padding: var(--space-3);
  border-radius: var(--radius);
  color: var(--text);
  font: inherit;
  text-align: left;
  pointer-events: auto;
}

.chat-outline-navigator__catalog-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-2);
}

/* user:“目录的文字太细了，把它加粗一下”+(目录卡片里的标题、条目和筛选文字统一加粗一档) */
.chat-outline-navigator__catalog-title {
  font-size: 13px;
  font-weight: 700;
  line-height: 1.3;
}

.chat-outline-navigator__catalog-count {
  color: color-mix(in srgb, var(--text) 56%, transparent);
  font-size: 11px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.chat-outline-navigator__catalog-controls {
  display: grid;
  gap: var(--space-1);
}

.chat-outline-navigator__catalog-search {
  width: 100%;
  box-sizing: border-box;
  padding: var(--space-1) var(--space-2);
  border: 1px solid color-mix(in srgb, var(--text) 20%, transparent);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--text) 6%, transparent);
  color: var(--text);
  font: inherit;
  font-size: 12px;
  font-weight: 500;
  line-height: 1.4;
}

.chat-outline-navigator__catalog-search:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--text) 55%, transparent);
  outline-offset: 1px;
}

.chat-outline-navigator__catalog-filters {
  display: flex;
  gap: var(--space-1);
}

.chat-outline-navigator__catalog-chip,
.chat-outline-navigator__catalog-sort {
  padding: 2px var(--space-2);
  border: 1px solid color-mix(in srgb, var(--text) 18%, transparent);
  border-radius: var(--radius);
  background: transparent;
  color: color-mix(in srgb, var(--text) 68%, transparent);
  font: inherit;
  font-size: 11px;
  font-weight: 600;
  line-height: 1.5;
  cursor: pointer;
  transition: background-color var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}

.chat-outline-navigator__catalog-chip:hover,
.chat-outline-navigator__catalog-sort:hover {
  background: color-mix(in srgb, var(--text) 10%, transparent);
  color: var(--text);
}

.chat-outline-navigator__catalog-chip.is-active {
  border-color: color-mix(in srgb, var(--text) 34%, transparent);
  background: color-mix(in srgb, var(--text) 16%, transparent);
  color: var(--text);
}

.chat-outline-navigator__catalog-chip:focus-visible,
.chat-outline-navigator__catalog-sort:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--text) 55%, transparent);
  outline-offset: 1px;
}

.chat-outline-navigator__catalog-sort {
  justify-self: start;
}

.chat-outline-navigator__catalog-list {
  display: grid;
  gap: 2px;
  min-height: 0;
  margin: 0;
  padding: 0 var(--space-1) 0 0;
  overflow-y: auto;
  list-style: none;
  overscroll-behavior: contain;
}

.chat-outline-navigator__catalog-item {
  display: grid;
  gap: 2px;
  width: 100%;
  box-sizing: border-box;
  padding: var(--space-1) var(--space-2);
  border: 0;
  border-radius: var(--radius);
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: background-color var(--dur-fast) var(--ease-out);
}

.chat-outline-navigator__catalog-item:hover {
  background: color-mix(in srgb, var(--text) 10%, transparent);
  color: var(--text);
}

.chat-outline-navigator__catalog-item.is-active {
  background: color-mix(in srgb, var(--text) 15%, transparent);
  color: var(--text);
}

.chat-outline-navigator__catalog-item.is-guide {
  border-left: 2px solid color-mix(in srgb, var(--text) 30%, transparent);
}

.chat-outline-navigator__catalog-item:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--text) 55%, transparent);
  outline-offset: 1px;
}

.chat-outline-navigator__catalog-item-meta {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  color: color-mix(in srgb, var(--text) 56%, transparent);
  font-size: 10px;
  font-weight: 600;
  line-height: 1.3;
}

.chat-outline-navigator__catalog-item-index {
  font-variant-numeric: tabular-nums;
}

.chat-outline-navigator__catalog-item-badge {
  padding: 0 4px;
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--text) 14%, transparent);
  color: color-mix(in srgb, var(--text) 78%, transparent);
  font-weight: 600;
}

.chat-outline-navigator__catalog-item-time {
  margin-left: auto;
  font-variant-numeric: tabular-nums;
}

.chat-outline-navigator__catalog-item-prompt {
  display: -webkit-box;
  overflow: hidden;
  color: var(--text);
  font-size: 12px;
  font-weight: 600;
  line-height: 1.4;
  word-break: break-word;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.chat-outline-navigator__catalog-empty {
  padding: var(--space-2);
  color: color-mix(in srgb, var(--text) 55%, transparent);
  font-size: 11px;
  font-weight: 500;
  text-align: center;
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

.chat-outline-navigator__preview-badge {
  margin-left: var(--space-1);
  padding: 0 4px;
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--text) 14%, transparent);
  color: color-mix(in srgb, var(--text) 78%, transparent);
  font-size: 10px;
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
