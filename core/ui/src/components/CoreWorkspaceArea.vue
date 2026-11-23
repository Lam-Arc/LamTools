<script setup lang="ts">
/**
 * 工作区区域（V2-C1）：一块矩形 + 一条标签轴 + 一个内容槽。
 *
 * user:“按 computeWorkspace 的 areas/contentRect 定位；单区时铺满；两区必须完整左右或上下”+
 * user:“目前库和file处于分屏时没有关闭键”+(分屏共用可关闭的顶部操作条)。
 * (区域只做三件事：把 compute 给的 rect 画成盒子、按 axis 摆标签、把 contentRect 交给内容。
 *  它绝不 `getBoundingClientRect()` —— 矩形唯一来源是引擎，量 DOM 会重新制造“网页跑到别处”。
 *
 * user:“在 CoreWorkspaceArea.vue 里把 contentRect 通过 provide/props 传下去”+
 * (V2-C2 会让 CoreSplitBrowser 直接读它，不再自己量宿主；这里先把值放到 DOM 与 provide 上。)
 */
import { computed } from 'vue'
import { PictureInPicture2, X } from 'lucide-vue-next'
import { t } from '@/i18n'
import type { SplitTab } from '@/workspace/types'
import type { Rect } from '@/workspace'
// user:“中间消失了”+(区域直接使用独立裁切逻辑，避免与工作区互相加载)。
import { buildCutoutClipPath } from '@/workspace/composition'
import CoreWorkspaceTabs from './CoreWorkspaceTabs.vue'
import type { WorkspaceContentTarget } from './workspaceInjection'
import type { ComponentPublicInstance } from 'vue'

const props = defineProps<{
  areaId: string
  axis: 'vertical' | 'horizontal'
  origin?: { x: number; y: number }
  rect: Rect
  contentRect: Rect
  tabs: SplitTab[]
  activeId: string | null
  compact?: boolean
  tabbar: 'full' | 'compact' | 'hidden'
  cutoutHoles?: Rect[]
  windowTopGap?: number
}>()

const emit = defineEmits<{
  'content-target': [target: WorkspaceContentTarget | null]
  select: [surfaceId: string]
  close: [surfaceId: string]
  'close-pane': []
  'tab-pointerdown': [surfaceId: string, event: PointerEvent]
  unpin: []
  add: []
  rename: [surfaceId: string, title: string]
}>()

// user:“网页似乎不对？位置也对不上，看起来层级也不对”+(引擎矩形是相对于 .ws2-root 的局部坐标，
// 注入给原生 WebView2 的矩形必须加上 .ws2-root 在窗口中的 origin 偏移，否则会左偏盖住侧栏并上移盖住地址栏)。
const windowContentRect = computed<Rect>(() => ({
  x: props.contentRect.x + (props.origin?.x ?? 0),
  y: props.contentRect.y + (props.origin?.y ?? 0),
  width: props.contentRect.width,
  height: props.contentRect.height,
}))
const windowHostRect = computed<Rect>(() => ({
  x: props.rect.x + (props.origin?.x ?? 0),
  y: props.rect.y + (props.origin?.y ?? 0),
  width: props.rect.width,
  height: props.rect.height,
}))

function rects() {
  return { contentRect: windowContentRect.value, hostRect: windowHostRect.value }
}
function setContentTarget(element: Element | ComponentPublicInstance | null) {
  emit('content-target', element instanceof HTMLElement ? { element, rects } : null)
}

const boxStyle = computed(() => ({
  left: `${props.rect.x}px`,
  top: `${props.rect.y}px`,
  width: `${props.rect.width}px`,
  height: `${props.rect.height}px`,
  clipPath: props.cutoutHoles?.length ? buildCutoutClipPath(props.rect, props.cutoutHoles) : undefined,
}))

const horizontalTabHeight = computed(() => {
  if (props.axis !== 'horizontal' || !showTabs.value) return 0
  const maxAvailable = Math.max(0, props.contentRect.y - props.rect.y)
  const target = props.tabbar === 'compact' ? 24 : 36
  return Math.min(target, maxAvailable)
})

/** 内容槽：横向轴内容（含浏览器地址栏页眉）紧贴标签栏下方，不留多余页眉缝隙。 */
const contentStyle = computed(() => {
  if (props.axis === 'horizontal') {
    const top = horizontalTabHeight.value
    return {
      left: `${props.contentRect.x - props.rect.x}px`,
      top: `${top}px`,
      width: `${props.contentRect.width}px`,
      height: `${Math.max(0, props.rect.height - top)}px`,
    }
  }
  return {
    left: `${props.contentRect.x - props.rect.x}px`,
    top: `${props.contentRect.y - props.rect.y}px`,
    width: `${props.contentRect.width}px`,
    height: `${props.contentRect.height}px`,
  }
})

/** 标签轴用 rect 与 contentRect 的差来定位：纵向在左、横向在上，宽/高都由引擎决定。 */
const tabsStyle = computed(() => {
  if (props.axis === 'horizontal') {
    // user:“这个才是标签入口”+(横向标签栏贴顶放在主区第一行，不再下移到地址栏下方)
    return {
      left: '0px',
      top: '0px',
      width: '100%',
      height: `${horizontalTabHeight.value}px`,
      '--ws2-tab-gap-to-window-edge': props.windowTopGap === undefined ? undefined : `${props.windowTopGap}px`,
    }
  }
  return {
    left: '0px',
    top: '0px',
    width: `${Math.max(0, props.contentRect.x - props.rect.x)}px`,
    height: '100%',
  }
})

// user:“这里超出区域了，以及为什么 agent 和 browser 页面宽度不一”+(横向浏览器标签栏不显示 agent-main 占位项)
const visibleTabs = computed(() => (
  props.areaId === 'main' && props.axis === 'horizontal'
    ? props.tabs.filter(tab => tab.kind !== 'agent')
    : props.tabs
))
const showTabs = computed(() => props.tabbar !== 'hidden' && (props.areaId !== 'main' || visibleTabs.value.length > 0))
// user:“依旧不可见，你来完成新布局系统的开发工作”+(主区显示 Agent 本体或无激活分屏标签时，标记为透传状态，避免遮挡底层会话内容)
const isAgentMain = computed(() => {
  if (props.areaId !== 'main') return false
  const active = props.tabs.find(tab => tab.id === props.activeId)
  return !active || active.kind === 'agent'
})
const allowAdd = computed(() => props.axis === 'horizontal' && visibleTabs.value.some(tab => tab.kind === 'browser'))
</script>

<template>
  <section
    class="ws2-area"
    :class="{ 'ws2-area--agent-main': isAgentMain }"
    :data-ws2-area="props.areaId"
    :aria-label="`区域 ${props.areaId}`"
    :style="boxStyle"
  >
    <div
      v-if="showTabs"
      class="ws2-area__tabs"
      :class="[
        `ws2-area__tabs--${props.axis}`,
        { 'ws2-area__tabs--with-root': props.areaId === 'main' && props.axis === 'horizontal' },
      ]"
      :style="tabsStyle"
    >
      <CoreWorkspaceTabs
        v-if="visibleTabs.length"
        :area-id="props.areaId"
        :axis="props.axis"
        :tabs="visibleTabs"
        :active-id="props.activeId"
        :compact="props.compact || props.tabbar === 'compact'"
        :allow-add="allowAdd"
        @select="emit('select', $event)"
        @close="emit('close', $event)"
        @tab-pointerdown="(id, event) => emit('tab-pointerdown', id, event)"
        @add="emit('add')"
        @rename="(id, title) => emit('rename', id, title)"
      />
      <div v-if="props.areaId !== 'main'" class="ws2-area__actions">
        <!-- user:“浮起替换为一个图标”+(文字按钮改成浮层图标：与标签抽屉里“转为浮层”同一枚，
             窄分屏里也不再占一整段文字宽)。 -->
        <button
          v-if="props.activeId"
          type="button"
          class="ws2-area__action ws2-area__action--icon"
          data-ws2-area-unpin
          :aria-label="t('转为浮层')"
          :title="t('转为浮层')"
          @click="emit('unpin')"
        >
          <PictureInPicture2 :size="14" aria-hidden="true" />
        </button>
        <button type="button" class="ws2-area__action ws2-area__action--icon" data-ws2-area-close :aria-label="t('关闭分屏')" :title="t('关闭分屏')" @click="emit('close-pane')">
          <X :size="14" aria-hidden="true" />
        </button>
      </div>
    </div>

    <div :ref="setContentTarget" class="ws2-area__content" :style="contentStyle" :data-ws2-content="props.areaId"></div>
  </section>
</template>
