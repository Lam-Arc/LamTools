<!--
  子代理分屏视图：从主线程里点开某个子代理后，占住对话区右侧的一块只读聊天区。
  它只读——没有输入框，不改变子代理；看的是这个子代理自己的过程：它的任务、
  模型的输出、每一次工具调用与结果。

  数据来自实时消息投影解析出的 run（父组件每次消息更新重算），所以子代理运行时
  这里会跟着流式更新，不需要额外轮询。
-->
<template>
  <Teleport defer :to="teleportTo">
    <aside
      class="sub-agent-pane"
      data-sub-agent-pane
      :aria-label="`子代理 ${run.name}`"
    >
    <header class="sub-agent-pane-head">
      <button
        type="button"
        class="sub-agent-pane-back"
        aria-label="返回主会话"
        title="返回主会话"
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

    <p v-if="taskText" class="sub-agent-pane-task" :title="taskText">{{ taskText }}</p>

    <div
      ref="scrollElement"
      class="thread sub-agent-pane-scroll"
      tabindex="0"
      :aria-label="`${run.name} 的过程`"
      @wheel.passive="paneScroll.handleWheel"
      @scroll.passive="paneScroll.handleScroll"
    >
      <ChatThread
        :messages="run.timeline"
        :transport="transport"
        :assistant-label="run.name"
        :process-expanded-ids="expandedMessageIds"
        :message-actions="false"
        @toggle-process="toggleProcess"
      >
        <template #empty>
          <span>{{ emptyText }}</span>
        </template>
      </ChatThread>
    </div>

    <Transition name="sub-agent-pane-jump">
      <button
        v-if="!paneScroll.autoFollow.value && run.timeline.length > 0"
        type="button"
        class="sub-agent-pane-jump optical-glass optical-glass--low-trans"
        aria-label="回到子代理最新"
        title="回到最新"
        @click="paneScroll.scrollToBottom(true)"
      >
        <ArrowDown :size="15" :stroke-width="1.8" aria-hidden="true" />
      </button>
    </Transition>
    </aside>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ArrowDown, ArrowLeft, LoaderCircle } from 'lucide-vue-next'
import type { CoreSubAgentDurableRecord, CoreSubAgentRun } from '../types'
import type { LamToolsTransport } from '../transport'
import { formatSubAgentElapsed, normalizeSubAgentType, subAgentStatusLabel } from '../agents/subAgentDisplay'
import { useCoreAutoFollowScroll } from '../composables/useCoreAutoFollowScroll'
import ChatThread from './ChatThread.vue'

const props = withDefaults(defineProps<{
  run: CoreSubAgentRun
  transport: LamToolsTransport
  emptyText?: string
  /** 卡片挂在壳层根节点下：外层带玻璃/抽屉时内层的位置推导会失真。 */
  teleportTo?: string
  /** 监督者的持久记录：续跑过的子代理，其运行边界只在这里有（投影看不到）。 */
  durableRecord?: CoreSubAgentDurableRecord | null
}>(), {
  emptyText: '这个子代理还没有产生过程记录。',
  teleportTo: '.workspace-shell',
  durableRecord: null,
})

const emit = defineEmits<{
  close: []
}>()

const scrollElement = ref<HTMLElement | null>(null)
const paneScroll = useCoreAutoFollowScroll(scrollElement)
/** 子代理内部默认展开：这一屏存在的意义就是看清它在做什么。 */
const collapsedMessageIds = ref<Set<string>>(new Set())

const expandedMessageIds = computed(() => new Set(
  props.run.timeline
    .filter(message => message.role === 'assistant' && !collapsedMessageIds.value.has(message.id))
    .map(message => message.id),
))

function toggleProcess(messageId: string): void {
  const next = new Set(collapsedMessageIds.value)
  if (next.has(messageId)) next.delete(messageId)
  else next.add(messageId)
  collapsedMessageIds.value = next
}

/** 投影给出的运行状态只能看到消息部件；续跑过的子代理以监督者记录为准。 */
const effectiveStatus = computed<string>(() => {
  const raw = String(props.durableRecord?.status || '').trim().toLowerCase()
  if (!raw) return props.run.status
  if (raw === 'failed') return 'error'
  if (raw === 'completed') return 'completed'
  return raw
})

const statusLabel = computed(() => subAgentStatusLabel(effectiveStatus.value))
const typeToken = computed(() => normalizeSubAgentType(props.run.type || 'execute'))
const modelLabel = computed(() => String(props.run.modelId || props.run.model || '—').trim() || '—')
const reasoningLabel = computed(() => String(props.run.reasoningLevel || '').trim())
const taskText = computed(() => String(props.run.task || props.durableRecord?.summary || '').trim())

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
  const record = props.durableRecord
  if (record) {
    const recordStatus = String(record.status || '').toLowerCase()
    if (recordStatus === 'running') {
      const start = (record.started_at ?? 0) * 1000
      return start > 0 ? formatSubAgentElapsed(Math.max(0, nowTick.value - start)) : ''
    }
    if (typeof record.elapsed_ms === 'number' && record.elapsed_ms > 0) {
      return formatSubAgentElapsed(record.elapsed_ms)
    }
    return ''
  }
  const recorded = typeof props.run.elapsedMs === 'number' && Number.isFinite(props.run.elapsedMs) && props.run.elapsedMs > 0
    ? props.run.elapsedMs
    : undefined
  const start = Date.parse(String(props.run.startedAt || ''))
  const completed = Date.parse(String(props.run.completedAt || ''))
  if (props.run.status === 'running') {
    return Number.isFinite(start) ? formatSubAgentElapsed(Math.max(0, nowTick.value - start)) : ''
  }
  if (recorded !== undefined) return formatSubAgentElapsed(recorded)
  if (Number.isFinite(start) && Number.isFinite(completed) && completed > start) {
    return formatSubAgentElapsed(completed - start)
  }
  return ''
})

// 换一个子代理 = 全新的一屏：折叠状态与滚动位置都不该继承上一个。
watch(
  () => props.run.subSessionId || props.run.id,
  async () => {
    collapsedMessageIds.value = new Set()
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

onBeforeUnmount(() => {
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

.sub-agent-pane-task {
  flex: 0 0 auto;
  margin: var(--space-1) var(--space-3) 0;
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  color: color-mix(in srgb, var(--text) 72%, transparent);
  font-size: 12px;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  overflow: hidden;
}

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
</style>
