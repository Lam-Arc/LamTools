<template>
  <section
    class="right-sidebar-host"
    aria-label="右侧工具栏"
    data-right-sidebar-host
  >
    <!-- 卡片挂在页面最外层：嵌在同样带玻璃的抽屉里时，内层的模糊采样不到
         窗外真实内容（backdrop root 被抽屉截断），会退化成只剩灰底。 -->
    <Teleport to="body">
      <div
        v-if="activeModule"
        :key="activeModule.id"
        class="right-sidebar-card optical-glass optical-glass--low-trans"
        :class="{ 'right-sidebar-card--resizing': cardResizing }"
        data-right-sidebar-card
        :style="[railSpanStyle, cardWidthStyle]"
        @mouseenter="onCardEnter"
        @mouseleave="onCardLeave"
      >
        <div
          class="right-sidebar-card-resize"
          role="separator"
          tabindex="0"
          aria-orientation="vertical"
          aria-label="调整右侧栏宽度"
          :aria-valuenow="cardWidth"
          :aria-valuemin="CARD_WIDTH_MIN"
          :aria-valuemax="cardMaxWidth()"
          data-right-sidebar-resize
          @pointerdown="onCardResizePointerdown"
          @pointermove="onCardResizePointermove"
          @pointerup="onCardResizePointerup"
          @pointercancel="onCardResizePointerup"
          @keydown="onCardResizeKeydown"
        ></div>
        <div class="right-sidebar-card-body">
          <component
            :is="activeModule.component"
            v-bind="activeModule.componentProps"
          />
        </div>
      </div>
      <!-- 搭桥层与卡片同级：玻璃面 overflow: hidden，挂在卡片里会被裁掉。 -->
      <span
        v-if="activeModule"
        class="right-sidebar-card-bridge"
        data-right-sidebar-bridge
        aria-hidden="true"
        :style="railSpanStyle"
        @mouseenter="onCardEnter"
        @mouseleave="onCardLeave"
      ></span>
    </Teleport>

    <nav
      ref="railRef"
      class="right-sidebar-rail"
      aria-label="右侧工具"
      @mouseenter="onRailEnter"
      @mouseleave="onRailLeave"
    >
      <button
        v-for="module in railModules"
        :key="module.id"
        class="right-sidebar-rail-btn"
        :class="{ active: activeModule?.id === module.id }"
        type="button"
        :aria-label="module.title"
        :title="module.title"
        :data-right-rail-module="module.id"
        @mouseenter="revealModule(module.id)"
        @focus="revealModule(module.id)"
        @blur="scheduleHide"
      >
        <component :is="module.icon" :size="16" :stroke-width="1.8" aria-hidden="true" />
      </button>
    </nav>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch, type Component } from 'vue'
import { Bot, BookOpen, Gauge, Globe, ListChecks, ListTodo } from 'lucide-vue-next'
import RightSidebarChecklist from './RightSidebarChecklist.vue'
import RightSidebarWebSearch from './RightSidebarWebSearch.vue'
import RightSidebarRag from './RightSidebarRag.vue'
import RightSidebarProcesses from './RightSidebarProcesses.vue'
import CoreResourceStats from './CoreResourceStats.vue'
import CoreSubAgentPanel from './CoreSubAgentPanel.vue'
import { selectCoreSubAgentRuns } from '../agents/subAgentProjection'
import { buildCurrentTurnChecklistGroups } from '../runtime/checklist'
import type {
  RightSidebarPluginContribution,
  RightSidebarRpc,
} from '../right-sidebar/types'
import type { CoreMessage, CoreSubAgentRun } from '../types'
import type { LamToolsTransport } from '../transport'

// 竖栏悬停出卡：图标竖栏常驻贴边，指针进入竖栏（图标或图标之间的空白）即在其
// 左侧浮出对应模块的高透玻璃卡；指针移进卡片保持显示，两侧都离开才收起。
// 壳层传入的绑定按 props 声明承接，避免回落成根元素上的 DOM 属性。
const props = defineProps<{
  projectId?: string | null
  workRoot?: string | null
  sessionId?: string | null
  requestRpc?: RightSidebarRpc
  transport?: LamToolsTransport
  messages?: CoreMessage[]
  contextWindow?: number | null
  processSignal?: unknown
  activePluginId?: string | null
  activeModeId?: string | null
  pluginContributions?: RightSidebarPluginContribution[]
}>()

const emit = defineEmits<{
  /** 悬停卡是否正占用右侧栏区域（浮出中或指针在卡上）。壳层据此决定收不收竖栏。 */
  'hover-change': [occupied: boolean]
  /** 面板里点了某个子代理：交给壳层打开右侧子代理分屏。 */
  'open-sub-agent': [run: CoreSubAgentRun]
}>()

interface RailModule {
  id: string
  title: string
  icon: Component
  component: Component
  componentProps: Record<string, unknown>
}

const hoverModuleId = ref<string | null>(null)
/** 指针在竖栏列内（含图标之间的空白），不要求正好落在某个图标上。 */
const railHover = ref(false)
const cardHover = ref(false)
/** 卡片是否出卡。与悬停分开：指针离开后还要留一小段宽限，卡片才算收起。 */
const cardVisible = ref(false)

// 指针从图标移到卡片上，要跨过竖栏与卡片之间的缝隙，途中两侧都不在指针下。
// 这段路程不该算“离开”，因此两侧都离开后先等一小段宽限；期间重新进入竖栏
// 或卡片就取消收起。键盘焦点离开图标走的是同一套逻辑。
const HIDE_GRACE_MS = 160
let hideTimer: ReturnType<typeof setTimeout> | null = null

function cancelHide(): void {
  if (hideTimer === null) return
  clearTimeout(hideTimer)
  hideTimer = null
}

function scheduleHide(): void {
  // 拖宽卡片期间指针可能滑出卡片与竖栏，收起计时一律不发。
  if (cardResizing.value) return
  cancelHide()
  hideTimer = setTimeout(() => {
    hideTimer = null
    if (railHover.value || cardHover.value) return
    cardVisible.value = false
  }, HIDE_GRACE_MS)
}

function revealModule(id: string): void {
  cancelHide()
  hoverModuleId.value = id
  cardVisible.value = true
}

// ── 卡宽拖拽：卡片左缘就是主界面与右栏之间的分界线，横向拖动即调卡宽。──
// 下限保住卡内内容可读（统计网格与子代理行在更窄处换行破碎），上限防止
// 一张卡盖满主界面；宽度只在本组件存活期内有效，是否记住上次宽度另行决策。
const CARD_WIDTH_DEFAULT = 285
const CARD_WIDTH_MIN = 240
const CARD_WIDTH_MAX = 480
const cardWidth = ref(CARD_WIDTH_DEFAULT)
const cardResizing = ref(false)
let cardResizeState: { pointerId: number; startX: number; startWidth: number } | null = null

const cardWidthStyle = computed(() => ({ width: `${cardWidth.value}px` }))

function cardMaxWidth(): number {
  const viewport = typeof window === 'undefined' ? 1024 : window.innerWidth
  return Math.min(CARD_WIDTH_MAX, Math.max(CARD_WIDTH_MIN, Math.round(viewport * 0.6)))
}

function onCardResizePointerdown(event: PointerEvent): void {
  if (!event.isPrimary) return
  // 合成/测试事件可能不带 button；真实 pointerdown 主键恒为 0。
  if (event.button !== undefined && event.button !== 0) return
  cardResizeState = { pointerId: event.pointerId, startX: event.clientX, startWidth: cardWidth.value }
  cardResizing.value = true
  cancelHide()
  // 捕获到拖拽柄上：指针滑出卡片拖动仍连续，松手前的收起判定也全部失效。
  const handle = event.currentTarget
  if (handle instanceof HTMLElement && handle.setPointerCapture) {
    try { handle.setPointerCapture(event.pointerId) } catch { /* 合成指针可能不支持捕获 */ }
  }
}

function onCardResizePointermove(event: PointerEvent): void {
  const state = cardResizeState
  if (!state || state.pointerId !== event.pointerId) return
  // 卡片贴右缘：向左拖 = 加宽。
  const next = state.startWidth + (state.startX - event.clientX)
  cardWidth.value = Math.round(Math.min(cardMaxWidth(), Math.max(CARD_WIDTH_MIN, next)))
}

function onCardResizePointerup(event: PointerEvent): void {
  if (!cardResizeState || cardResizeState.pointerId !== event.pointerId) return
  const handle = event.currentTarget
  if (handle instanceof HTMLElement && handle.hasPointerCapture?.(event.pointerId)) {
    handle.releasePointerCapture(event.pointerId)
  }
  cardResizeState = null
  cardResizing.value = false
}

function onCardResizeKeydown(event: KeyboardEvent): void {
  // 与鼠标方向一致：向左（箭头左）= 加宽；Shift 步进更大。
  const step = event.shiftKey ? 32 : 12
  let next: number | null = null
  if (event.key === 'ArrowLeft') next = cardWidth.value + step
  else if (event.key === 'ArrowRight') next = cardWidth.value - step
  if (next === null) return
  event.preventDefault()
  cardWidth.value = Math.round(Math.min(cardMaxWidth(), Math.max(CARD_WIDTH_MIN, next)))
}

function onRailEnter(): void {
  railHover.value = true
  cancelHide()
}

function onRailLeave(): void {
  railHover.value = false
  scheduleHide()
}

function onCardEnter(): void {
  cardHover.value = true
  cancelHide()
}

function onCardLeave(): void {
  cardHover.value = false
  scheduleHide()
}

// 竖栏与卡片都在窗口内竖直居中：卡片与搭桥层至少和竖栏一样高，竖栏的每个图标
// 都正好落在这段高度里，从任意图标水平移向卡片都不会从上下沿外侧擦过去。
const railRef = ref<HTMLElement | null>(null)
const railHeight = ref(0)
let railObserver: ResizeObserver | null = null

const railSpanStyle = computed<Record<string, string> | undefined>(() => (
  railHeight.value > 0 ? { minHeight: `${railHeight.value}px` } : undefined
))

onMounted(() => {
  if (typeof ResizeObserver === 'undefined' || !railRef.value) return
  // 只用回调带来的尺寸，不在观察回调里读 offsetHeight 触发同步重排。
  railObserver = new ResizeObserver((entries) => {
    const entry = entries[0]
    const height = entry?.borderBoxSize?.[0]?.blockSize ?? entry?.contentRect.height ?? 0
    if (height > 0) railHeight.value = Math.round(height)
  })
  railObserver.observe(railRef.value)
})

onBeforeUnmount(() => {
  railObserver?.disconnect()
  railObserver = null
  cancelHide()
})

watch(cardVisible, (visible) => emit('hover-change', visible))

const subAgentRuns = computed(() => selectCoreSubAgentRuns(props.messages ?? []))
const checklistGroups = computed(() => buildCurrentTurnChecklistGroups(props.messages ?? []))

function openSubAgent(subSessionId: string): void {
  const run = subAgentRuns.value.find(item => item.subSessionId === subSessionId)
  if (!run) return
  // 右栏点开 = 打开右侧子代理分屏（与主线程里点委派工具条同一条路）。
  emit('open-sub-agent', run)
}

const railModules = computed<RailModule[]>(() => [
  {
    id: 'checklist',
    title: 'Checklist',
    icon: ListChecks,
    component: RightSidebarChecklist,
    componentProps: {
      stepGroups: checklistGroups.value,
    },
  },
  {
    id: 'resources',
    title: 'Resources',
    icon: Gauge,
    component: CoreResourceStats,
    componentProps: {
      messages: props.messages,
      contextWindow: props.contextWindow,
    },
  },
  {
    id: 'sub-agents',
    title: 'Sub Agents',
    icon: Bot,
    component: CoreSubAgentPanel,
    componentProps: {
      runs: subAgentRuns.value,
      activeSubAgentId: '',
      loading: false,
      errorText: '',
      onOpen: openSubAgent,
    },
  },
  {
    id: 'web-search',
    title: 'Web Search',
    icon: Globe,
    component: RightSidebarWebSearch,
    componentProps: {
      requestRpc: props.requestRpc,
      projectId: props.projectId,
      workRoot: props.workRoot,
      widgetEntry: null,
    },
  },
  {
    id: 'processes',
    title: 'Background Processes',
    icon: ListTodo,
    component: RightSidebarProcesses,
    componentProps: {
      requestRpc: props.requestRpc,
      sessionId: props.sessionId,
      processSignal: props.processSignal,
    },
  },
  {
    id: 'rag',
    title: 'RAG',
    icon: BookOpen,
    component: RightSidebarRag,
    componentProps: {
      requestRpc: props.requestRpc,
      projectId: props.projectId,
      workRoot: props.workRoot,
      widgetEntry: null,
    },
  },
])

const activeModule = computed<RailModule | null>(() => (
  cardVisible.value
    ? railModules.value.find(module => module.id === hoverModuleId.value) ?? null
    : null
))
</script>

<style scoped>
.right-sidebar-host { --host-text: var(--theme-backdrop-text); position: relative; display: flex; flex-direction: row; justify-content: flex-end; min-width: 0; color: var(--host-text); }

/* 图标竖栏：贴右缘的一列图标，高度只包住图标本身（外层抽屉负责窗口内竖直居中）。 */
.right-sidebar-rail {
  flex: 0 0 auto;
  width: var(--right-rail-width, 46px);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-2) 0;
}
.right-sidebar-rail-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: 0;
  border-radius: var(--radius);
  background: transparent;
  color: color-mix(in srgb, var(--host-text) 62%, transparent);
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}
.right-sidebar-rail-btn:hover { background: color-mix(in srgb, var(--host-text) var(--alpha-hover), transparent); color: var(--host-text); }
.right-sidebar-rail-btn.active { background: color-mix(in srgb, var(--host-text) var(--alpha-active), transparent); color: var(--host-text); }
.right-sidebar-rail-btn:focus-visible { outline: 2px solid color-mix(in srgb, var(--blue) 75%, transparent); outline-offset: 1px; }

/* 悬浮卡：贴窗口右缘、竖栏左侧 8px、窗口内竖直居中；低透玻璃 + 大圆角。
   卡片挂在 body 上（见模板），所以用 fixed 定位；居中用 top/bottom + margin auto，
   不上 transform（transform 会另开 backdrop root，模糊同样会失效）。 */
.right-sidebar-card {
  position: fixed;
  top: 0;
  bottom: 0;
  right: calc(var(--right-rail-width, 46px) + var(--space-2));
  margin-block: auto;
  height: fit-content;
  width: 285px;
  max-height: 505px;
  z-index: var(--z-popover);
  display: flex;
  flex-direction: column;
  border-radius: var(--radius-lg);
  --text: var(--theme-backdrop-text);
  color: var(--text);
  --optical-glass-surface: var(--theme-backdrop-solid);
  pointer-events: auto;
  animation: right-card-in var(--dur-fast) var(--ease-out);
}
@keyframes right-card-in {
  from { opacity: 0; }
}
/* 卡片右缘与竖栏之间留有一条缝隙，指针横穿时会有那么一瞬两侧都不在指针下。
   在缝隙上铺一层不可见的搭桥层（右端压住卡片边缘、左端压进竖栏内缘，不覆盖任何
   图标按钮），指针横穿或停在缝里都仍算悬停在卡片区，卡片不会中途消失。
   它是与卡片同级的一层：玻璃面 overflow: hidden，挂在卡片内部会被裁掉。 */
/* 卡片左缘拖拽柄：主界面与右栏的分界。透明命中条贴玻璃内缘，悬停轻微增亮
   提示可拖；不引入描线（玻璃禁令）。拖动中整个卡片锁光标并禁选中。 */
.right-sidebar-card-resize {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 0;
  width: 7px;
  border-radius: var(--radius-lg) 0 0 var(--radius-lg);
  cursor: col-resize;
  touch-action: none;
}
.right-sidebar-card-resize:hover,
.right-sidebar-card-resize:focus-visible {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
}
.right-sidebar-card--resizing {
  cursor: col-resize;
  user-select: none;
}
.right-sidebar-card-bridge {
  position: fixed;
  top: 0;
  bottom: 0;
  right: calc(var(--right-rail-width, 46px) - 2px);
  margin-block: auto;
  height: fit-content;
  width: calc(var(--space-2) + 4px);
  z-index: var(--z-popover);
}
.right-sidebar-card-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding: var(--space-2) var(--space-3) var(--space-3);
}
/* 右侧栏不出模块名标题：面板内部同名 h3 一并隐藏。 */
.right-sidebar-card-body :deep(.runtime-widget-head h3) {
  display: none;
}

@media (prefers-reduced-motion: reduce) {
  .right-sidebar-card { animation: none; }
  .right-sidebar-rail-btn { transition: none; }
}
</style>
