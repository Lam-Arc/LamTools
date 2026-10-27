<!--
  子代理分屏视图：从主线程里点开某个子代理后，占住对话区右侧的一块只读聊天区。
  它只读——没有输入框，不改变子代理；看的是这个子代理自己的过程：它的任务、
  模型的输出、每一次工具调用与结果。

  数据来自实时消息投影解析出的 run（父组件每次消息更新重算），所以子代理运行时
  这里会跟着流式更新，不需要额外轮询。
-->
<template>
  <Teleport defer :to="teleportTo" :disabled="embedded">
    <aside
      ref="paneElement"
      class="sub-agent-pane"
      :class="{ 'sub-agent-pane--resizing': resizing, 'sub-agent-pane--embedded': embedded }"
      data-sub-agent-pane
      :style="paneWidthStyle"
      :aria-label="t('子代理 {0}', { 0: run.name })"
    >
    <!-- 面板与聊天区之间那道缝就是把手：平时无痕，悬停微亮，拖动改面板宽度。
         实现与右侧栏那条把手同一套（拖动方向、限宽、方向键、指针捕获都一致）。 -->
    <div
      v-if="!embedded"
      ref="handleElement"
      class="sub-agent-pane-resize"
      role="separator"
      tabindex="0"
      aria-orientation="vertical"
      :aria-label="t('调整子代理面板宽度')"
      :aria-valuenow="currentWidth()"
      :aria-valuemin="PANE_WIDTH_MIN"
      :aria-valuemax="paneMaxWidth()"
      data-sub-agent-pane-resize
      @pointerdown="onResizePointerdown"
      @pointermove="onResizePointermove"
      @pointerup="onResizePointerup"
      @pointercancel="onResizePointerup"
      @keydown="onResizeKeydown"
    ></div>
    <header class="sub-agent-pane-head">
      <button
        v-if="!embedded"
        type="button"
        class="sub-agent-pane-back"
        :aria-label="t('返回主会话')"
        :title="t('返回主会话')"
        @click="emit('close')"
      >
        <ArrowLeft :size="15" :stroke-width="1.8" aria-hidden="true" />
      </button>
      <strong class="sub-agent-pane-name" :title="run.name">{{ run.name }}</strong>
      <span
        class="sub-agent-pane-status"
        :class="`sub-agent-pane-status--${statusTone}`"
        role="status"
        aria-live="polite"
      >
        <LoaderCircle
          v-if="effectiveStatus === 'running'"
          class="sub-agent-pane-status-icon"
          :size="12"
          :stroke-width="2"
          aria-hidden="true"
        />
        <span v-else class="sub-agent-pane-status-dot" aria-hidden="true" />
        {{ statusLabel }}
      </span>
    </header>

    <div class="sub-agent-pane-meta">
      <span class="sub-agent-pane-meta-item">{{ typeToken }}</span>
      <span class="sub-agent-pane-meta-sep" aria-hidden="true">·</span>
      <span class="sub-agent-pane-meta-item" :title="modelLabel">{{ modelLabel }}</span>
      <span class="sub-agent-pane-meta-item" :title="reasoningLabel">{{ reasoningLabel }}</span>
      <template v-if="elapsedLabel">
        <span class="sub-agent-pane-meta-sep" aria-hidden="true">·</span>
        <span class="sub-agent-pane-meta-item">{{ elapsedLabel }}</span>
      </template>
    </div>

    <div
      ref="scrollElement"
      class="thread sub-agent-pane-scroll"
      tabindex="0"
      :aria-label="t('{0} 的过程', { 0: run.name })"
      @wheel.passive="paneScroll.handleWheel"
      @scroll.passive="paneScroll.handleScroll"
    >
      <button
        v-if="hasEarlierMessages"
        type="button"
        class="sub-agent-pane-earlier"
        data-sub-agent-pane-earlier
        @click="showEarlierMessages"
      >{{ t("显示更早的过程") }}</button>
      <ChatThread
        :messages="paneTimeline"
        :transport="transport"
        :assistant-label="run.name"
        :process-expanded-ids="expandedMessageIds"
        :message-actions="false"
        :sub-agent-rows-inert="true"
        :decisions-disabled="decisionsDisabled"
        @toggle-process="toggleProcess"
        @decision-select="emit('decision-select', $event)"
      >
        <template #empty>
          <span>{{ emptyText }}</span>
        </template>
      </ChatThread>
    </div>

    <footer class="sub-agent-pane-resources" :aria-label="t('子代理资源统计')">
      <span>{{ t("上下文") }} {{ resourceSummary?.contextLabel ?? '— / —' }}</span>
      <span>{{ t("调用") }} {{ resourceValue(t("调用")) }}</span>
      <span>{{ t("缓存命中率") }} {{ resourceValue(t("缓存")) }}</span>
    </footer>
    <Transition name="sub-agent-pane-jump">
      <button
        v-if="!paneScroll.autoFollow.value && run.timeline.length > 0"
        type="button"
        class="sub-agent-pane-jump optical-glass optical-glass--low-trans"
        :aria-label="t('回到子代理最新')"
        :title="t('回到最新')"
        @click="paneScroll.scrollToBottom(true)"
      >
        <ArrowDown :size="15" :stroke-width="1.8" aria-hidden="true" />
      </button>
    </Transition>
    </aside>
  </Teleport>
</template>

<script setup lang="ts">
import { t } from '@/i18n/index.ts'

import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { reconcileCoreSubAgentRun } from '@/agents/subAgentProjection.ts'
import { ArrowDown, ArrowLeft, LoaderCircle } from 'lucide-vue-next'
import type { CoreSubAgentDurableRecord, CoreSubAgentRun } from '@/types.ts'
import type { LamToolsTransport } from '@/transport/index.ts'
import type { CoreDecisionOption } from '@/appServer/pendingDecisions.ts'
import { formatSubAgentElapsed, normalizeSubAgentType, subAgentStatusLabel } from '@/agents/subAgentDisplay.ts'
import { useCoreAutoFollowScroll } from '@/composables/useCoreAutoFollowScroll.ts'
import ChatThread from '@/components/ChatThread.vue'
import { buildCoreResourceSummary } from '@/runtime/resources.ts'

const props = withDefaults(defineProps<{
  embedded?: boolean
  decisionsDisabled?: boolean
  run: CoreSubAgentRun
  transport: LamToolsTransport
  emptyText?: string
  /** 卡片挂在壳层根节点下：外层带玻璃/抽屉时内层的位置推导会失真。 */
  teleportTo?: string
  /** 监督者的持久记录：续跑过的子代理，其运行边界只在这里有（投影看不到）。 */
  durableRecord?: CoreSubAgentDurableRecord | null
  /** 宿主持有的面板宽度（px）：拖过之后由宿主记住，聊天区按它让位。 */
  width?: number | null
  /** 运行时是否发布过"在等成员"这一事实（无事实时不能据此收敛）。 */
  memberWaitKnown?: boolean
  /** 运行时当前报告的仍在运行的成员名字（仅在等成员时非空）。 */
  runningMemberNames?: string[]
  /** 主代理是否正在工作（前台的委派不算挂起等待，不能据此收敛）。 */
  mainRunning?: boolean
  /** 运行时按成员发布的实时状态（名字小写 → 归一化状态）。回合还没结束时也会发，
   *  比监督者记录的下一次轮询更准。 */
  memberStatuses?: Record<string, string>
  memberStatusRecords?: Record<string, CoreSubAgentDurableRecord>
}>(), {
  get emptyText() { return t("这个子代理还没有产生过程记录。") },
  embedded: true,
  teleportTo: '.workspace-shell',
  durableRecord: null,
  width: null,
  memberWaitKnown: false,
  runningMemberNames: () => [],
  mainRunning: false,
  memberStatuses: () => ({}),
})

const resourceSummary = computed(() => buildCoreResourceSummary(props.run.timeline))
function resourceValue(label: string): string {
  return resourceSummary.value?.callItems.find(item => item.label === label)?.value ?? '--'
}

const emit = defineEmits<{
  close: []
  resize: [width: number]
  /** 子代理自己的提问/审批卡被作答：交给宿主用同一条决策通道回传（按 requestId
   *  回到发问的那个子代理），面板本身不直接调 RPC。 */
  'decision-select': [payload: { partId: string; option: CoreDecisionOption; response: string }]
}>()

// ── 面板宽度拖拽：与右侧栏那条把手同一套口径（左拖加宽、限宽、方向键、指针捕获）。──
// 下限保住面板内过程卡片的可读宽度；上限保证聊天区不被挤没（聊天区最小宽 + 右栏 + 缝）。
const PANE_WIDTH_MIN = 320
const PANE_WIDTH_MAX = 720
const MAIN_AREA_MIN_WIDTH = 420
const RIGHT_RAIL_WIDTH = 46
const SPLIT_GAP = 2
const paneElement = ref<HTMLElement | null>(null)
const handleElement = ref<HTMLElement | null>(null)
const measuredWidth = ref(PANE_WIDTH_MIN)
const resizing = ref(false)
let resizeState: { pointerId: number; startX: number; startWidth: number } | null = null

function paneMaxWidth(): number {
  const viewport = typeof window === 'undefined' ? 1280 : window.innerWidth
  const room = viewport - MAIN_AREA_MIN_WIDTH - RIGHT_RAIL_WIDTH - SPLIT_GAP
  return Math.min(PANE_WIDTH_MAX, Math.max(PANE_WIDTH_MIN, Math.round(room)))
}

/** 当前宽度：宿主给的优先，否则取挂载时量到的实际宽度（CSS 的 clamp 默认值）。 */
function currentWidth(): number {
  const own = Number(props.width)
  if (Number.isFinite(own) && own > 0) return Math.round(own)
  return measuredWidth.value
}

const paneWidthStyle = computed(() => (
  props.width ? { '--sub-agent-pane-width': `${Math.round(props.width)}px` } : undefined
))

function measureWidth(): void {
  const width = paneElement.value?.offsetWidth ?? 0
  if (width > 0) measuredWidth.value = Math.round(width)
}

function onResizePointerdown(event: PointerEvent): void {
  if (!event.isPrimary) return
  // 合成/测试事件可能不带 button；真实 pointerdown 主键恒为 0。
  if (event.button !== undefined && event.button !== 0) return
  measureWidth()
  resizeState = { pointerId: event.pointerId, startX: event.clientX, startWidth: currentWidth() }
  resizing.value = true
  const handle = event.currentTarget
  if (handle instanceof HTMLElement && handle.setPointerCapture) {
    try { handle.setPointerCapture(event.pointerId) } catch { /* 合成指针可能不支持捕获 */ }
  }
}

function onResizePointermove(event: PointerEvent): void {
  const state = resizeState
  if (!state || state.pointerId !== event.pointerId) return
  // 面板贴右缘：向左拖 = 加宽。
  const next = state.startWidth + (state.startX - event.clientX)
  scheduleResize(Math.round(Math.min(paneMaxWidth(), Math.max(PANE_WIDTH_MIN, next))))
}

function onResizePointerup(event: PointerEvent): void {
  if (!resizeState || resizeState.pointerId !== event.pointerId) return
  const handle = event.currentTarget
  if (handle instanceof HTMLElement && handle.hasPointerCapture?.(event.pointerId)) {
    handle.releasePointerCapture(event.pointerId)
  }
  resizeState = null
  resizing.value = false
  // 落点必须发出去：最后一帧还没跑完就松手时，宽度不能丢。
  flushPendingResize()
}

// 拖动路径按帧合并：高刷鼠标的 pointermove 可达 120+/s，逐条 emit 会让宿主每条
// 都重写宽度、整屏（主聊天卡与输入栏）跟着重排；合并到 rAF 后一帧最多一次，
// 手感仍是跟手实时。
let pendingResizeWidth: number | null = null
let resizeFrame: number | null = null

function flushPendingResize(): void {
  if (resizeFrame !== null) {
    if (typeof cancelAnimationFrame === 'function') cancelAnimationFrame(resizeFrame)
    resizeFrame = null
  }
  const width = pendingResizeWidth
  pendingResizeWidth = null
  if (width !== null) emit('resize', width)
}

function scheduleResize(width: number): void {
  pendingResizeWidth = width
  if (resizeFrame !== null) return
  if (typeof requestAnimationFrame !== 'function') {
    flushPendingResize()
    return
  }
  resizeFrame = requestAnimationFrame(() => {
    resizeFrame = null
    const next = pendingResizeWidth
    pendingResizeWidth = null
    if (next !== null) emit('resize', next)
  })
}

function onResizeKeydown(event: KeyboardEvent): void {
  // 与鼠标方向一致：向左（箭头左）= 加宽；Shift 步进更大。
  const step = event.shiftKey ? 32 : 12
  let next: number | null = null
  if (event.key === 'ArrowLeft') next = currentWidth() + step
  else if (event.key === 'ArrowRight') next = currentWidth() - step
  if (next === null) return
  event.preventDefault()
  emit('resize', Math.round(Math.min(paneMaxWidth(), Math.max(PANE_WIDTH_MIN, next))))
}

const scrollElement = ref<HTMLElement | null>(null)

function syncMeasuredWidth(): void {
  measureWidth()
}
const paneScroll = useCoreAutoFollowScroll(scrollElement)
/** 子代理内部默认展开：这一屏存在的意义就是看清它在做什么。 */
const collapsedMessageIds = ref<Set<string>>(new Set())

// 分屏只挂载尾部一窗：子代理时间线可以很长（真实会话里单成员上百条过程），
// 整条挂进 DOM 会让每一帧的 patch 与排版量随历史线性增长。窗口按步加宽，
// 更早的过程不丢，只是不默认挂载。
const PANE_TIMELINE_STEP = 30
const visibleCount = ref(PANE_TIMELINE_STEP)
const timelineLength = computed(() => props.run.timeline.length)
const hasEarlierMessages = computed(() => timelineLength.value > visibleCount.value)

function showEarlierMessages(): void {
  visibleCount.value = Math.min(timelineLength.value, visibleCount.value + PANE_TIMELINE_STEP)
}

/**
 * 分屏渲染的时间线：尾部窗口；且只有真正在跑的成员才算"live"。
 * 已收敛的成员即使过程条目还挂着 running（续跑/唤醒后的残留状态），也不能继续走
 * 流式渲染与默认展开——那等于把完成的内容永远留在实时路径上逐帧重投影。
 */
const expandedMessageIds = computed(() => new Set(
  paneTimeline.value
    .filter(message => message.role === 'assistant' && !collapsedMessageIds.value.has(message.id))
    .map(message => message.id),
))

function toggleProcess(messageId: string): void {
  const next = new Set(collapsedMessageIds.value)
  if (next.has(messageId)) next.delete(messageId)
  else next.add(messageId)
  collapsedMessageIds.value = next
}

/** 卡片与分屏共享按子代理生命周期时间戳解析的状态与耗时。
 * 新的子代理启动可以续跑；主代理回合状态不能替代子代理的终态。 */
const effectiveRun = computed(() => {
  const name = String(props.run.name || '').trim().toLowerCase()
  const published = props.memberStatusRecords?.[name] ?? props.memberStatuses?.[name]
  return reconcileCoreSubAgentRun(props.run, published, props.durableRecord)
})
const effectiveStatus = computed(() => effectiveRun.value.status)

const statusLabel = computed(() => subAgentStatusLabel(effectiveStatus.value))

/**
 * 收敛判据：只有真正在跑的成员才算 live。
 * 两路依据：(1) 监督者记录/运行状态已经不是 running；(2) 运行时的成员事实已经把这个
 * 成员排除——在等成员但名单里没有它，或等成员结束、主代理也没在工作的窗口里名单已清空。
 * 第二路让"父条目与子过程都还写着 running"的残留不再挂在实时路径上，也不依赖分屏是否
 * 打开（名单来自快照，不需要监督者记录）。
 */
const isSettled = computed(() => {
  if (effectiveStatus.value !== 'running') return true
  if (!props.memberWaitKnown) return false
  const names = props.runningMemberNames ?? []
  if (names.length > 0) {
    const own = String(props.run.name || '').trim().toLowerCase()
    return !names.some(name => String(name || '').trim().toLowerCase() === own)
  }
  // 名单已清空（drain 结束）：全部成员收敛；但只在主代理确实没在跑时算数——
  // 同一轮里主代理回到前台后的前台委派不是"挂起等待"。
  return !props.mainRunning
})

/** See the timeline-window note above: bounded tail, live only while unsettled. */
const paneTimeline = computed(() => {
  const windowed = props.run.timeline.slice(-visibleCount.value)
  if (!isSettled.value) return windowed
  return windowed.map(message => (
    message.metadata?.live
      ? { ...message, metadata: { ...message.metadata, live: false } }
      : message
  ))
})
const typeToken = computed(() => normalizeSubAgentType(props.run.type || 'execute'))
const modelLabel = computed(() => String(props.run.modelId || props.run.model || '—').trim() || '—')
const reasoningLabel = computed(() => String(props.run.reasoningLevel || '').trim())
const statusTone = computed(() => {
  if (effectiveStatus.value === 'running') return 'running'
  if (effectiveStatus.value === 'pending' || effectiveStatus.value === 'paused') return 'waiting'
  if (effectiveStatus.value === 'error' || effectiveStatus.value === 'interrupted') return 'failed'
  return 'done'
})

/** 运行中每秒推进耗时；结束后停在记录的时长上。 */
const nowTick = ref(Date.now())
let elapsedTimer: ReturnType<typeof setInterval> | null = null

function syncElapsedTimer(): void {
  if (elapsedTimer) {
    clearInterval(elapsedTimer)
    elapsedTimer = null
  }
  if (effectiveStatus.value !== 'running') return
  nowTick.value = Date.now()
  elapsedTimer = setInterval(() => { nowTick.value = Date.now() }, 1000)
}

/** 运行中每秒推进耗时；结束后停在记录的时长上。
 *  有监督者记录时以记录为准（续跑过的子代理，消息部件上看不出运行边界）；
 *  历史快照里的运行可能只有起止时间而没带时长——那就不显示，不要编一个 0ms 出来。 */
const elapsedLabel = computed(() => {
  const run = effectiveRun.value
  const start = Date.parse(run.startedAt || '')
  if (run.status === 'running') {
    return Number.isFinite(start) ? formatSubAgentElapsed(Math.max(0, nowTick.value - start)) : ''
  }
  if (typeof run.elapsedMs === 'number' && Number.isFinite(run.elapsedMs) && run.elapsedMs > 0) {
    return formatSubAgentElapsed(run.elapsedMs)
  }
  const completed = Date.parse(run.completedAt || '')
  return Number.isFinite(start) && Number.isFinite(completed) && completed > start
    ? formatSubAgentElapsed(completed - start) : ''
})

// 换一个子代理 = 全新的一屏：折叠状态、时间线窗口与滚动位置都不该继承上一个。
watch(
  () => props.run.subSessionId || props.run.id,
  async () => {
    collapsedMessageIds.value = new Set()
    visibleCount.value = PANE_TIMELINE_STEP
    paneScroll.reset()
    await paneScroll.scrollToBottom(true)
  },
  { immediate: true },
)

watch(() => effectiveStatus.value, syncElapsedTimer, { immediate: true })

// 过程增长时把视口带到最新——与对话窗同一条通道：只由容器尺寸变化驱动，
// 是否真的滚动仍由 autoFollow（用户是否在读历史）决定。
let resizeObserver: ResizeObserver | null = null
watch(scrollElement, (element) => {
  resizeObserver?.disconnect()
  resizeObserver = null
  if (!element || typeof ResizeObserver === 'undefined') return
  resizeObserver = new ResizeObserver(() => { void paneScroll.scrollToBottom() })
  resizeObserver.observe(element)
  const thread = element.querySelector('.chat-thread')
  if (thread instanceof HTMLElement) resizeObserver.observe(thread)
}, { immediate: true })

onMounted(() => {
  measureWidth()
  window.addEventListener('resize', syncMeasuredWidth)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', syncMeasuredWidth)
  if (resizeFrame !== null && typeof cancelAnimationFrame === 'function') cancelAnimationFrame(resizeFrame)
  resizeFrame = null
  pendingResizeWidth = null
  if (elapsedTimer) clearInterval(elapsedTimer)
  elapsedTimer = null
  resizeObserver?.disconnect()
  resizeObserver = null
})
</script>

<style scoped>
/* 子代理卡：与主聊天卡并排的第二张卡。几何完全由壳层的内缩变量决定——
   主聊天区让出「卡宽 + 留缝」的右内缩（见 workspace-shell.css），这张卡就贴在
   让出来的位置上，两张卡之间露出背景色，像细胞分裂成两半。 */
/* 面板与聊天区之间那道缝就是把手：透明命中条跨在缝上，平时无痕、悬停微亮，
   拖动时整个面板锁光标并禁选中（与右侧栏那条把手同一套配方）。 */
.sub-agent-pane-resize {
  position: absolute;
  top: 0;
  bottom: 0;
  left: -6px;
  width: 10px;
  border-radius: var(--workspace-panel-radius-inner) 0 0 var(--workspace-panel-radius-inner);
  cursor: col-resize;
  touch-action: none;
  z-index: 1;
}
.sub-agent-pane-resize:hover,
.sub-agent-pane-resize:focus-visible {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
}
.sub-agent-pane-resize:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--blue) 75%, transparent);
  outline-offset: -2px;
}
.sub-agent-pane--resizing {
  cursor: col-resize;
  user-select: none;
}

.sub-agent-pane {
  --text: var(--theme-main-text);
  position: fixed;
  top: var(--titlebar-offset, 0px);
  bottom: var(--shell-bottom-inset, 6px);
  right: var(--right-peek, 6px);
  width: var(--sub-agent-pane-width, clamp(340px, 34vw, 620px));
  z-index: var(--z-main-surface);
  display: flex;
  flex-direction: column;
  border: 1px solid var(--theme-main-border);
  border-radius: var(--workspace-panel-radius-inner) var(--workspace-panel-radius-outer)
    var(--workspace-panel-radius-outer) var(--workspace-panel-radius-inner);
  background: var(--theme-main-background);
  color: var(--text);
  overflow: hidden;
  animation: sub-agent-pane-in var(--dur-morph) var(--ease-out);
}
@keyframes sub-agent-pane-in {
  from { opacity: 0; transform: translateX(14px); }
}

.sub-agent-pane-head {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid color-mix(in srgb, var(--text) 10%, transparent);
}

.sub-agent-pane-back {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  padding: 0;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--text) 62%, transparent);
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}
.sub-agent-pane-back:hover {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  color: var(--text);
}
.sub-agent-pane-back:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--blue) 75%, transparent);
  outline-offset: 1px;
}

.sub-agent-pane-name {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  font-size: 13px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sub-agent-pane-status {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: 1px var(--space-2);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  font-size: 11px;
  white-space: nowrap;
}
.sub-agent-pane-status--running { color: var(--text); }
.sub-agent-pane-status--waiting { color: color-mix(in srgb, var(--orange) 70%, var(--text)); }
.sub-agent-pane-status--failed { color: color-mix(in srgb, var(--red) 70%, var(--text)); }
.sub-agent-pane-status--done { color: color-mix(in srgb, var(--text) 70%, transparent); }
.sub-agent-pane-status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}
.sub-agent-pane-status-icon { animation: sub-agent-pane-spin 1.4s linear infinite; }
@keyframes sub-agent-pane-spin { to { transform: rotate(360deg); } }

.sub-agent-pane-meta {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1) var(--space-3) 0;
  overflow: hidden;
  font-size: 12px;
  color: color-mix(in srgb, var(--text) 65%, transparent);
  white-space: nowrap;
}
.sub-agent-pane-meta-item {
  overflow: hidden;
  text-overflow: ellipsis;
}
.sub-agent-pane-meta-sep { flex: 0 0 auto; }


/* 过程正文沿用主线程那一套：容器带上 `thread` 类，
   `.thread` 作用域的规则（过程组标题的网格、思考/工具卡片的排版）才会生效。
   但这些规则里属于「线程容器几何」的部分归分屏卡自己——全出血、composer 底部
   留白、顶部渐隐都在这里收回，其余（网格间距、滚动条、卡片排版）保持与主线程一致。 */
.sub-agent-pane-scroll {
  width: auto;
  margin-inline: 0;
  padding: var(--space-3) var(--space-3) var(--space-4);
  -webkit-mask-image: none;
  mask-image: none;
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  overscroll-behavior: contain;
}
.sub-agent-pane-sentinel { height: 1px; }

/* 时间线窗口的「显示更早」入口：安静一行，位于滚动区顶部，不抢内容。 */
.sub-agent-pane-earlier {
  display: block;
  width: 100%;
  margin: 0 0 var(--space-2);
  padding: var(--space-1) 0;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--text) 58%, transparent);
  font-size: 12px;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}
.sub-agent-pane-earlier:hover {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  color: color-mix(in srgb, var(--text) 78%, transparent);
}
@media (prefers-reduced-motion: reduce) {
  .sub-agent-pane-earlier { transition: none; }
}
.sub-agent-pane-resources {
  flex: 0 0 auto;
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1) var(--space-3);
  padding: var(--space-2) var(--space-3);
  color: color-mix(in srgb, var(--text) 65%, transparent);
  font-size: 11px;
}


.sub-agent-pane-jump {
  --text: var(--theme-main-text);
  --optical-glass-overlay: transparent;
  position: absolute;
  bottom: var(--space-3);
  left: 50%;
  transform: translateX(-50%);
  z-index: var(--z-edge-trigger);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: var(--space-6);
  height: var(--space-6);
  padding: 0;
  overflow: hidden;
  border-radius: 50%;
  color: var(--text);
  cursor: pointer;
}
.sub-agent-pane-jump:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--text) 72%, transparent);
  outline-offset: 2px;
}
.sub-agent-pane-jump-enter-active,
.sub-agent-pane-jump-leave-active {
  transition: opacity var(--dur-fast) var(--ease-out), transform var(--dur-fast) var(--ease-out);
}
.sub-agent-pane-jump-enter-from,
.sub-agent-pane-jump-leave-to {
  opacity: 0;
  transform: translate(-50%, 4px);
}

@media (max-width: 900px) {
  /* 窄窗放不下两张卡：子代理卡铺满整个对话区（主聊天与输入栏由壳层收起）。 */
  .sub-agent-pane {
    left: var(--main-left, 64px);
    right: var(--right-peek, 6px);
    width: auto;
  }
}

@media (prefers-reduced-motion: reduce) {
  .sub-agent-pane { animation: none; }
  .sub-agent-pane-status-icon { animation: none; }
  .sub-agent-pane-jump-enter-active,
  .sub-agent-pane-jump-leave-active { transition: none; }
  .sub-agent-pane-back { transition: none; }
}
/* user:“分屏”+(子代理仅负责内容，尺寸与关闭由通用分屏宿主负责)。 */
.sub-agent-pane.sub-agent-pane--embedded { position: relative; inset: auto; width: 100%; height: 100%; border: 0; border-radius: 0; animation: none; z-index: auto; }
.sub-agent-pane--embedded .sub-agent-pane-head { padding-top: var(--space-3); }
</style>
