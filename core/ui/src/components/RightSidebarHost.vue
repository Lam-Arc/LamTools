<template>
  <section
    class="right-sidebar-host"
    :aria-label="t('右侧工具栏')"
    data-right-sidebar-host
  >
    <!-- 卡片挂在页面最外层：嵌在同样带玻璃的抽屉里时，内层的模糊采样不到
         窗外真实内容（backdrop root 被抽屉截断），会退化成只剩灰底。 -->
    <Teleport to="body">
      <div
        v-if="activeModule"
        :key="activeModule.id"
        class="right-sidebar-card optical-glass optical-glass--low-trans"
        data-right-sidebar-card
        :style="railSpanStyle"
        @mouseenter="onCardEnter"
        @mouseleave="onCardLeave"
      >
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
      :aria-label="t('右侧工具')"
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
import { t } from '../i18n/index'

import { computed, onBeforeUnmount, onMounted, ref, watch, type Component } from 'vue'
import { Bot, BookOpen, Gauge, Globe, ListChecks, ListTodo } from 'lucide-vue-next'
import RightSidebarChecklist from './RightSidebarChecklist.vue'
import RightSidebarWebSearch from './RightSidebarWebSearch.vue'
import RightSidebarRag from './RightSidebarRag.vue'
import RightSidebarProcesses from './RightSidebarProcesses.vue'
import CoreResourceStats from './CoreResourceStats.vue'
import CoreSubAgentPanel from './CoreSubAgentPanel.vue'
import { reconcileCoreSubAgentRun, selectCoreSubAgentRuns } from '../agents/subAgentProjection'
import { subAgentRunIdentity } from '../agents/subAgentDisplay'
import { buildCurrentTurnChecklistGroups } from '../runtime/checklist'
import type {
  RightSidebarPluginContribution,
  RightSidebarRpc,
} from '../right-sidebar/types'
import type { CoreMessage, CoreSubAgentRun, CoreSubAgentDurableRecord } from '../types'
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
  memberStatuses?: Record<string, string>
  memberStatusRecords?: Record<string, CoreSubAgentDurableRecord>
  subAgentDurableRecords?: Record<string, CoreSubAgentDurableRecord>
  contextWindow?: number | null
  processSignal?: unknown
  activePluginId?: string | null
  activeModeId?: string | null
  pluginContributions?: RightSidebarPluginContribution[]
  /** 已删除（后端删掉监督者记录）的子代理身份：列表不再为它们占位。 */
  hiddenSubAgentIdentities?: readonly string[]
}>()

const emit = defineEmits<{
  /** 悬停卡是否正占用右侧栏区域（浮出中或指针在卡上）。壳层据此决定收不收竖栏。 */
  'hover-change': [occupied: boolean]
  /** 面板里点了某个子代理：交给壳层打开右侧子代理分屏。 */
  'open-sub-agent': [run: CoreSubAgentRun]
  /** 面板里删除了某个已结束的子代理：那一次调用由壳层发，列表不直接发 RPC。 */
  'delete-sub-agent': [run: CoreSubAgentRun]
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

const subAgentRuns = computed(() => {
  const hidden = props.hiddenSubAgentIdentities ?? []
  const runs = selectCoreSubAgentRuns(props.messages ?? []).map(run => {
    const name = run.name.trim().toLowerCase()
    return reconcileCoreSubAgentRun(run, props.memberStatusRecords?.[name] ?? props.memberStatuses?.[name],
      props.subAgentDurableRecords?.[name])
  })
  if (hidden.length === 0) return runs
  const dismissed = new Set(hidden)
  return runs.filter(run => !dismissed.has(subAgentRunIdentity(run)))
})
const checklistGroups = computed(() => buildCurrentTurnChecklistGroups(props.messages ?? []))

function openSubAgent(subSessionId: string): void {
  const run = subAgentRuns.value.find(item => item.subSessionId === subSessionId)
  if (!run) return
  // 右栏点开 = 打开右侧子代理分屏（与主线程里点委派工具条同一条路）。
  emit('open-sub-agent', run)
}

function deleteSubAgent(run: CoreSubAgentRun): void {
  emit('delete-sub-agent', run)
}

const railModules = computed<RailModule[]>(() => [
  {
    id: 'checklist',
    title: 'Checklist',
    icon: ListChecks,
    component: RightSidebarChecklist,
    // 步骤组与运行组合同样按消息全量扫描；用 getter 让它们在卡真正挂载时才求值，
    // 竖栏图标列表每帧读 railModules 不会再带着这些扫描一起跑。
    get componentProps() {
      return { stepGroups: checklistGroups.value }
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
    // 隐藏时不应重跑子代理投影：getter 只在卡片可见（v-bind 展开时）求值，
    // 关闭状态下的每帧全量 selectCoreSubAgentRuns 因此消失。
    get componentProps() {
      return {
        runs: subAgentRuns.value,
        activeSubAgentId: '',
        loading: false,
        errorText: '',
        onOpen: openSubAgent,
        onDelete: deleteSubAgent,
      }
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
  /* 竖直居中收在窗口标题栏与底部内缩之间：无论窗口多矮、内容多长，卡片都不
     越过顶部标题区（原先 top: 0 居中时，矮窗口会把卡片顶进标题区）。 */
  top: var(--titlebar-offset, 0px);
  bottom: var(--shell-bottom-inset, 6px);
  right: calc(var(--right-rail-width, 46px) + var(--space-2));
  margin-block: auto;
  height: fit-content;
  /* 宽度上限给主区（含它的标题带）留出最小可读宽度：窗口再窄也不会横跨过去。 */
  width: min(285px, calc(100vw - var(--right-rail-width, 46px) - var(--space-2) - var(--right-card-main-min, 240px)));
  max-height: min(505px, calc(100dvh - var(--titlebar-offset, 0px) - var(--shell-bottom-inset, 6px) - var(--right-card-vertical-gap, 24px)));
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
