<template>
  <aside
    :id="props.id"
    data-workspace-left-drawer
    class="workspace-drawer drawer-left sidebar-root"
    :class="{ open: props.open, pinned: props.pinned }"
    :inert="!props.open || undefined"
    :aria-hidden="!props.open"
    @mouseleave="emit('mouseleave', $event)"
  >
    <header v-if="props.showSidebarHeader" class="drawer-head sidebar-header">
      <div class="sidebar-title sidebar-label">{{ props.title || '项目' }}</div>
      <button
        class="sidebar-pin-button"
        :class="{ 'is-active': props.pinned }"
        type="button"
        :title="props.pinned ? '取消固定左侧栏' : '固定左侧栏'"
        :aria-label="props.pinned ? '取消固定左侧栏' : '固定左侧栏'"
        :aria-pressed="props.pinned"
        @click="togglePinned"
      >
        <Pin :size="14" :stroke-width="1.8" aria-hidden="true" />
      </button>
      <div
        v-if="$slots['sidebar-header-action'] || props.showDefaultHeaderAction"
        class="sidebar-header-actions"
      >
        <slot name="sidebar-header-action">
          <button
            v-if="props.showDefaultHeaderAction"
            class="icon-btn"
            type="button"
            title="新建"
            aria-label="新建会话"
            @click="emit('new-session')"
          >+</button>
        </slot>
      </div>
    </header>

    <div v-if="$slots.primary" class="sidebar-primary">
      <slot name="primary" />
    </div>

    <div class="sidebar-scroll-shell">
      <div
        :id="`${props.id}-body`"
        ref="sidebarBodyRef"
        class="drawer-body sidebar-body"
        @scroll="syncScrollbar"
      >
        <slot name="sidebar-body">
          <slot>
            <div class="sidebar-empty">No content</div>
          </slot>
        </slot>
      </div>
      <div
        ref="scrollbarTrackRef"
        class="sidebar-scrollbar"
        :class="{ 'is-visible': scrollbar.visible, 'is-dragging': dragging }"
        data-sidebar-scrollbar
        role="scrollbar"
        aria-label="侧栏滚动条"
        aria-orientation="vertical"
        :aria-controls="`${props.id}-body`"
        :aria-valuemin="0"
        :aria-valuemax="100"
        :aria-valuenow="scrollbar.value"
        :aria-hidden="!scrollbar.visible"
        :tabindex="scrollbar.visible ? 0 : -1"
        @pointerdown="handleScrollbarPointerDown"
        @keydown="handleScrollbarKeydown"
      >
        <span
          class="sidebar-scrollbar-thumb"
          data-sidebar-scrollbar-thumb
          :style="{
            height: `${scrollbar.thumbSize}px`,
            transform: `translateY(${scrollbar.thumbOffset}px)`,
          }"
        ></span>
      </div>
    </div>

    <footer v-if="props.showSearchAction || props.showPluginsAction || props.showSettingsAction || $slots['sidebar-footer']" class="drawer-footer">
      <div class="drawer-footer-row">
        <RailAction
          v-if="props.showSearchAction"
          action-id="search"
          label="搜索"
          description="全局搜索：跨项目查找会话、消息与学习资料。"
          @click="emit('search')"
        >
          <Search :size="14" :stroke-width="1.8" />
        </RailAction>
        <RailAction
          v-if="props.showPluginsAction"
          action-id="plugins"
          label="插件"
          description="管理已安装的插件，开关它们带来的界面与工具。"
          @click="emit('plugins')"
        >
          <Puzzle :size="14" :stroke-width="1.8" />
        </RailAction>
        <RailAction
          v-if="props.showSettingsAction"
          action-id="settings"
          label="设置"
          description="模型与供应商、外观主题、工具权限等应用配置。"
          @click="emit('settings')"
        >
          <Settings :size="14" :stroke-width="1.8" />
        </RailAction>
        <slot name="sidebar-footer" />
      </div>
    </footer>
  </aside>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { Pin, Puzzle, Search, Settings } from 'lucide-vue-next'
import RailAction from './RailAction.vue'

const props = withDefaults(
  defineProps<{
    id: string
    open: boolean
    pinned: boolean
    title?: string
    showSidebarHeader?: boolean
    showDefaultHeaderAction?: boolean
    showSearchAction?: boolean
    showPluginsAction?: boolean
    showSettingsAction?: boolean
  }>(),
  {
    title: '',
    showSidebarHeader: true,
    showDefaultHeaderAction: true,
    showSearchAction: true,
    showPluginsAction: true,
    showSettingsAction: true,
  },
)

const emit = defineEmits<{
  close: []
  'toggle-pinned': []
  'new-session': []
  settings: []
  plugins: []
  search: []
  mouseleave: [event: MouseEvent]
}>()
// Keep these host commands available for a future in-drawer close/pin
// control without moving ownership of layout state out of useShellLayout.
function close() {
  emit('close')
}

function togglePinned() {
  emit('toggle-pinned')
}

const sidebarBodyRef = ref<HTMLElement | null>(null)
const scrollbarTrackRef = ref<HTMLElement | null>(null)
const scrollbar = reactive({
  visible: false,
  thumbSize: 0,
  thumbOffset: 0,
  value: 0,
})
const dragging = ref(false)

type ScrollbarDragState = {
  startY: number
  startOffset: number
  maxOffset: number
}

let dragState: ScrollbarDragState | null = null
let measureTimer: ReturnType<typeof setTimeout> | null = null
let resizeObserver: ResizeObserver | null = null
let mutationObserver: MutationObserver | null = null

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max)
}

function resetScrollbar() {
  scrollbar.visible = false
  scrollbar.thumbSize = 0
  scrollbar.thumbOffset = 0
  scrollbar.value = 0
}

function syncScrollbar() {
  const body = sidebarBodyRef.value
  if (!body) return

  const scrollRange = body.scrollHeight - body.clientHeight
  if (scrollRange <= 0) {
    resetScrollbar()
    return
  }

  const track = scrollbarTrackRef.value
  const trackHeight = track?.getBoundingClientRect().height || body.clientHeight
  if (trackHeight <= 0 || body.scrollHeight <= 0) return

  const thumbSize = Math.min(
    trackHeight,
    Math.max(32, Math.round(trackHeight * body.clientHeight / body.scrollHeight)),
  )
  const maxOffset = Math.max(trackHeight - thumbSize, 0)
  const progress = clamp(body.scrollTop / scrollRange, 0, 1)

  scrollbar.visible = true
  scrollbar.thumbSize = thumbSize
  scrollbar.thumbOffset = Math.round(maxOffset * progress)
  scrollbar.value = Math.round(progress * 100)
}

function scheduleScrollbarMeasure() {
  if (measureTimer !== null) clearTimeout(measureTimer)
  measureTimer = setTimeout(() => {
    measureTimer = null
    syncScrollbar()
  }, 0)
}

function setScrollFromThumbOffset(offset: number, maxOffset: number) {
  const body = sidebarBodyRef.value
  if (!body) return

  const scrollRange = Math.max(body.scrollHeight - body.clientHeight, 0)
  if (scrollRange <= 0) return

  const progress = maxOffset > 0 ? clamp(offset / maxOffset, 0, 1) : 0
  body.scrollTop = progress * scrollRange
  syncScrollbar()
}

function handleScrollbarPointerDown(event: PointerEvent) {
  if (!scrollbar.visible || event.button !== 0) return

  const track = scrollbarTrackRef.value
  if (!track) return

  track.focus({ preventScroll: true })
  const rect = track.getBoundingClientRect()
  const maxOffset = Math.max(rect.height - scrollbar.thumbSize, 0)
  const target = event.target
  const onThumb = target instanceof Element && target.closest('[data-sidebar-scrollbar-thumb]')

  if (!onThumb) {
    setScrollFromThumbOffset(
      event.clientY - rect.top - scrollbar.thumbSize / 2,
      maxOffset,
    )
    event.preventDefault()
    return
  }

  dragState = {
    startY: event.clientY,
    startOffset: scrollbar.thumbOffset,
    maxOffset,
  }
  dragging.value = true
  window.addEventListener('pointermove', handleScrollbarPointerMove)
  window.addEventListener('pointerup', stopScrollbarDrag)
  window.addEventListener('pointercancel', stopScrollbarDrag)
  event.preventDefault()
}

function handleScrollbarPointerMove(event: PointerEvent) {
  if (!dragState) return

  setScrollFromThumbOffset(
    dragState.startOffset + event.clientY - dragState.startY,
    dragState.maxOffset,
  )
  event.preventDefault()
}

function stopScrollbarDrag() {
  dragState = null
  dragging.value = false
  window.removeEventListener('pointermove', handleScrollbarPointerMove)
  window.removeEventListener('pointerup', stopScrollbarDrag)
  window.removeEventListener('pointercancel', stopScrollbarDrag)
}

function handleScrollbarKeydown(event: KeyboardEvent) {
  const body = sidebarBodyRef.value
  if (!body || !scrollbar.visible) return

  const maxScrollTop = Math.max(body.scrollHeight - body.clientHeight, 0)
  let nextScrollTop: number | null = null
  switch (event.key) {
    case 'ArrowUp':
      nextScrollTop = body.scrollTop - 32
      break
    case 'ArrowDown':
      nextScrollTop = body.scrollTop + 32
      break
    case 'PageUp':
      nextScrollTop = body.scrollTop - body.clientHeight
      break
    case 'PageDown':
      nextScrollTop = body.scrollTop + body.clientHeight
      break
    case 'Home':
      nextScrollTop = 0
      break
    case 'End':
      nextScrollTop = maxScrollTop
      break
    default:
      return
  }

  body.scrollTop = clamp(nextScrollTop, 0, maxScrollTop)
  syncScrollbar()
  event.preventDefault()
}

onMounted(() => {
  const body = sidebarBodyRef.value
  if (!body) return

  scheduleScrollbarMeasure()

  if (typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(scheduleScrollbarMeasure)
    resizeObserver.observe(body)
  }
  if (typeof MutationObserver !== 'undefined') {
    mutationObserver = new MutationObserver(scheduleScrollbarMeasure)
    mutationObserver.observe(body, {
      attributes: true,
      characterData: true,
      childList: true,
      subtree: true,
    })
  }
})

onBeforeUnmount(() => {
  if (measureTimer !== null) clearTimeout(measureTimer)
  resizeObserver?.disconnect()
  mutationObserver?.disconnect()
  stopScrollbarDrag()
})

defineExpose({ close, togglePinned })
</script>

<style scoped>
.sidebar-label {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--sidebar-font-title);
  font-weight: 600;
  line-height: 24px;
  color: var(--sidebar-text-primary);
  letter-spacing: -0.02em;
}

.sidebar-title {
  font-size: var(--sidebar-font-title);
  font-weight: 600;
  line-height: 24px;
}

.sidebar-header-actions {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
}

.sidebar-pin-button {
  flex: 0 0 auto;
  width: 28px;
  height: 28px;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--sidebar-text-muted);
  opacity: 0.55;
  display: grid;
  place-items: center;
  transition: opacity var(--dur-fast) var(--ease-out), background var(--dur-fast) var(--ease-out);
}

.sidebar-pin-button:hover,
.sidebar-pin-button:focus-visible,
.sidebar-pin-button.is-active {
  opacity: 1;
}

.sidebar-pin-button:hover {
  background: color-mix(in srgb, var(--theme-backdrop-text) var(--alpha-hover), transparent);
}

.sidebar-pin-button svg,
.icon-btn svg {
  width: var(--sidebar-icon-size);
  height: var(--sidebar-icon-size);
}

.sidebar-pin-button:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--blue) 75%, transparent);
  outline-offset: 1px;
}

.icon-btn {
  flex: 0 0 auto;
  width: var(--sidebar-row-height);
  height: var(--sidebar-row-height);
  border-radius: var(--sidebar-row-radius);
  background: color-mix(in srgb, var(--theme-backdrop-text) var(--alpha-hover), transparent);
  color: color-mix(in srgb, var(--theme-backdrop-text) 56%, transparent);
  display: grid;
  place-items: center;
  font-size: var(--sidebar-icon-size);
  font-weight: 400;
}

.icon-btn:hover {
  background: color-mix(in srgb, var(--theme-backdrop-text) var(--alpha-active), transparent);
  color: var(--theme-backdrop-text);
}

@media (prefers-reduced-motion: reduce) {
  .sidebar-pin-button {
    transition: none;
  }
}
</style>
