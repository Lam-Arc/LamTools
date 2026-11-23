<template>
  <div
    ref="shellElement"
    class="workspace-shell" data-ui-id="shell.root"
    :class="[
      shellClass,
      composerShellClass,
      {
        'workspace-shell--compact-chrome': compactChrome,
        'workspace-shell--empty-session': emptySession,
        'workspace-shell--full-bleed': mainContentFullBleed,
        'workspace-shell--workflow': workflowMode,
        'workspace-shell--workflow-interaction-active': workflowMode && workflowInteractionActive,
        'workspace-shell--workflow-composer-has-value': workflowMode && workflowComposerHasValue,
        'workspace-shell--workflow-composer-stop': workflowMode && composerActionMode === 'stop',
      },
    ]"
    :data-workflow-composer-state="workflowMode ? composerActionMode : undefined"
    :data-workflow-composer-has-value="workflowMode ? String(workflowComposerHasValue) : undefined"
    :style="{ ...shellStyle, ...composerLayoutStyle }"
    @pointerdown="onSwipePointerDown"
    @pointermove="onSwipePointerMove"
    @pointerup="onSwipePointerUp"
    @pointercancel="onSwipePointerCancel"
    @selectstart="onSwipeSelectStart"
    @focusin="onShellFocusIn"
    @focusout="onShellFocusOut"
    @pointerover="onWorkflowInteractionPointerOver"
    @pointerout="onWorkflowInteractionPointerOut"
    @input.capture="onShellInput"
  >
    <!-- Notifications are owned by the shared toast service. -->
    <CoreToastHost />

    <button
      v-if="isNarrowViewport && (leftOpen || rightOpen)"
      class="mobile-drawer-backdrop"
      type="button"
      :aria-label="t('关闭面板')"
      @click="closeDrawers"
    ></button>

    <!-- Phones have no hover edge: one visible control opens the drawer, and it leaves
         as soon as the drawer is open. -->
    <button
      v-if="showDrawerToggle && isNarrowViewport && !leftOpen"
      class="mobile-drawer-toggle"
      type="button"
      data-mobile-drawer-toggle
      :aria-label="t('打开左侧栏')"
      :title="t('打开左侧栏')"
      @click="openLeftDrawer"
    >
      <PanelLeft :size="18" :stroke-width="1.8" aria-hidden="true" />
    </button>

    <!-- user:“左侧窄竖栏位置再分配…其余项做成左侧栏，与右侧栏保持样式同套系”+
         (左栏常驻：容器占住 --rail-width 这一列，内部只放应用导航；
          项目侧栏仍由按钮控制，唤出热区挪到左栏右缘)。 -->
    <div
      class="workspace-left-rail"
      data-app-rail-shell
      :inert="rightDrawerModal || undefined"
      @mouseleave="onLeftSurfaceLeave"
    >
      <div
        class="edge edge-left"
        role="button"
        tabindex="0"
        :aria-label="t(compactChrome ? '主导航' : '打开左侧栏')"
        @mouseenter="!compactChrome && !leftPinned && !collapseLeftSidebar && openLeftDrawer()"
        @focus="!compactChrome && !leftPinned && !collapseLeftSidebar && openLeftDrawer()"
        @keydown.enter.prevent="!compactChrome && !collapseLeftSidebar && openLeftDrawer()"
        @keydown.space.prevent="!compactChrome && !collapseLeftSidebar && openLeftDrawer()"
      ></div>
      <div class="workspace-left-rail-content">
        <slot name="app-rail" />
        <PluginSystemContributions v-if="props.pluginRpc" :request-rpc="props.pluginRpc" region="appRail" />
      </div>
    </div>
    <!-- user:“左侧窄竖栏位置再分配”+(项目侧栏的唤出入口挪到左栏右缘的窄热区：
         指针贴上去就展开，和旧版“贴左边缘展开”的手感一致)。 -->
    <div
      v-if="compactChrome && !collapseLeftSidebar && !leftDrawerShown"
      class="workspace-rail-seam"
      data-app-rail-seam
      aria-hidden="true"
      @mouseenter="openLeftDrawer"
    ></div>
    <div
      v-if="$slots['root-entry']"
      class="core-root-bento-anchor"
      data-ws2-root-anchor
    >
      <!-- user:“手动缩回后也应该有打开方式”+(左上角同一按钮明确显示打开和收起状态)。 -->
      <button
        v-if="compactChrome && !collapseLeftSidebar && !requireLeftSidebar"
        class="btn btn--ghost project-sidebar-toggle"
        type="button"
        data-project-sidebar-toggle
        :aria-controls="leftDrawerId"
        :aria-expanded="leftDrawerShown"
        :aria-label="projectSidebarToggleLabel"
        :title="projectSidebarToggleLabel"
        @click="toggleLeftDrawer"
      >
        <PanelLeft :size="16" :stroke-width="1.8" aria-hidden="true" />
      </button>
      <slot name="root-entry" />
    </div>
    <div
      v-if="showRightPanel"
      class="edge edge-right"
      role="button"
      tabindex="0"
      :aria-label="t('打开右侧面板')"
      @mouseenter="openRightDrawer"
      @focus="openRightDrawer"
      @keydown.enter.prevent="openRightDrawer"
      @keydown.space.prevent="openRightDrawer"
    ></div>

    <!-- ===== Left Drawer ===== -->
    <LeftSidebarShell
      :id="leftDrawerId"
      :open="leftDrawerShown"
      :pinned="leftPinned"
      :title="sidebarTitle"
      :show-sidebar-header="showSidebarHeader"
      :show-default-header-action="showSidebarHeaderAction"
      :show-search-action="showSidebarSearchAction"
      :show-plugins-action="showSidebarPluginsAction"
      :show-settings-action="showSidebarSettingsAction"
      @close="closeDrawers"
      @toggle-pinned="onSidebarTogglePinned"
      @mouseleave="onLeftSurfaceLeave"
      @new-session="$emit('new-session')"
      @settings="$emit('settings')"
      @plugins="$emit('plugins')"
      @search="$emit('search')"
    >
      <template v-if="$slots['sidebar-header-action']" #sidebar-header-action>
        <slot name="sidebar-header-action" />
      </template>
      <template v-if="$slots.primary" #primary>
        <slot name="primary" />
      </template>
      <template #sidebar-body>
        <slot v-if="$slots['sidebar-body'] && !isRegionReplaced('left')" name="sidebar-body" />
        <PluginSystemContributions
          v-if="props.pluginRpc"
          :request-rpc="props.pluginRpc"
          region="left"
          replacer-only
        />
      </template>
      <template #sidebar-footer>
        <slot v-if="$slots['sidebar-footer']" name="sidebar-footer" />
        <LeftPluginDock v-if="props.pluginRpc" :request-rpc="props.pluginRpc" />
      </template>
    </LeftSidebarShell>

    <!-- user:“会话栏与主区之间不应再有「两张卡片之间的空隙」…A. 让两者共用一个外层背景，
         缝隙处只留选中行高度的内凹圆角过渡（其余高度上是同色连续面，看不出接缝）”+
         (这一层只是把那条 3px 的缝填成两侧同色：它不吃指针、不参与布局，
          上下两端贴着标题栏与底边，于是整条缝消失；选中行的高亮再由 .session-fusion 跨过去)。 -->
    <div class="session-seam" data-session-seam aria-hidden="true"></div>
    <!-- user:“当前选中的会话与右侧内容区形成连续轮廓…连接处上下用内凹圆角过渡”+
         (连接处必须画在聊天卡之上，所以这一层在壳上：几何由会话栏量出来写进变量，这里只负责画。
          装饰可被主题关掉/换掉：见 --session-fusion-plate-display 等令牌)。 -->
    <div class="session-fusion" data-session-fusion-plate aria-hidden="true"></div>

    <!-- user:“让左侧栏和主内容区中间的边界可以被拖动”+(会话栏与聊天卡之间那条缝
         就是宽度把手：拖动改宽度、双击回默认档，键盘左右键逐档微调)。 -->
    <div
      v-if="sidebarResizable"
      class="sidebar-resize-handle"
      data-sidebar-resize-handle
      role="separator"
      aria-orientation="vertical"
      :aria-label="t('拖动调整左侧栏宽度')"
      :aria-valuemin="LEFT_DRAWER_WIDTH_MIN"
      :aria-valuemax="LEFT_DRAWER_WIDTH_MAX"
      :aria-valuenow="sidebarResizeValue"
      tabindex="0"
      @pointerdown="startSidebarResize"
      @keydown="onSidebarResizeKeydown"
      @dblclick="resetLeftWidth"
    ></div>

    <!-- ===== Main Area ===== -->
    <main
      class="workspace-main" data-region="main" data-ui-id="shell.main"
      :class="{
        'workspace-main--no-composer': hideComposer,
        'workspace-main--no-header': hideMainHeader,
      }"
      :inert="rightDrawerModal || undefined"
    >
      <div class="workspace-runtime-overlay">
        <slot name="runtime-overlay" />
      </div>
      <slot name="main-header" />
      <PluginSystemContributions
        v-if="props.pluginRpc"
        :request-rpc="props.pluginRpc"
        region="titlebar"
      />
      <!-- user:“replace 换主区”+有接管者时默认内容让位（保持挂载，隐藏即可）。 -->
      <div v-show="!isRegionReplaced('main')" class="workspace-main-default">
        <slot name="main-content">
        <section class="thread">
          <slot name="thread-content" />
        </section>
      </slot>
      </div>
      <PluginSystemContributions
        v-if="props.pluginRpc"
        :request-rpc="props.pluginRpc"
        region="main"
      />
    </main>

    <!-- user:“层级应为红>绿>黄”+(标签页抽屉放在主区之外，绘制和命中均在工作区浮窗上方)。 -->
    <div v-if="$slots['workspace-overlays']" class="workspace-chrome-overlays">
      <slot name="workspace-overlays" />
    </div>
    <slot name="window-controls" />

    <!-- ===== Floating Composer ===== -->
    <ComposerBar
      v-if="!hideComposer"
      :class="[
        composerRootClass,
        {
          'composer-root--empty-session': emptySession,
          'composer-root--workflow': workflowMode,
          'composer-root--workflow-has-value': workflowMode && workflowComposerHasValue,
          'composer-root--workflow-stop': workflowMode && composerActionMode === 'stop',
        },
      ]"
      :data-workflow-composer="workflowMode ? 'true' : undefined"
      :data-workflow-composer-state="workflowMode ? composerActionMode : undefined"
      :data-workflow-composer-has-value="workflowMode ? String(workflowComposerHasValue) : undefined"
      :inert="rightDrawerModal || undefined"
      :variant="composerCompact ? 'compact' : 'floating'"
      :placeholder="defaultUiText(composerPlaceholder, '输入内容...')"
      :disabled="composerDisabled"
      :action-mode="composerActionMode"
      :send-label="composerSendLabel"
      :stop-label="composerStopLabel"
      :send-title="defaultUiText(composerSendTitle, '发送')"
      :stop-title="defaultUiText(composerStopTitle, '停止运行')"
      @submit="onComposerSubmit"
      @drop="onComposerDrop"
    >
      <template #popover>
        <slot name="composer-popover" />
      </template>
      <template #queue-panel>
        <slot v-if="!workflowMode" name="composer-queue-panel" />
      </template>
      <template #preamble>
        <slot v-if="!workflowMode" name="composer-preamble" />
      </template>
      <template #status>
        <slot v-if="!workflowMode" name="composer-status" />
      </template>
      <template #attachments>
        <slot v-if="!workflowMode" name="composer-attachments" />
      </template>
      <template #textarea>
        <slot name="composer-textarea">
          <textarea
            :placeholder="defaultUiText(composerPlaceholder, '输入内容...')"
            :aria-label="defaultUiText(composerPlaceholder, '输入内容...')"
            :disabled="composerDisabled"
            rows="1"
            @keydown.enter.exact="onComposerEnter"
          ></textarea>
        </slot>
      </template>
      <template #tools>
        <slot name="composer-tools" />
      </template>
      <template #action>
        <slot name="composer-action">
          <CoreSendStopButton
            :action-mode="composerActionMode"
            :disabled="composerActionMode === 'send' && composerSendDisabled"
            :send-label="composerSendLabel"
            :stop-label="composerStopLabel"
            :send-title="defaultUiText(composerSendTitle, '发送')"
            :stop-title="defaultUiText(composerStopTitle, '停止运行')"
            :hold-enabled="composerHoldEnabled"
            @terminate="emit('composer-terminate')"
          />
        </slot>
      </template>
      <template v-if="$slots['composer-extras']" #extras>
        <slot name="composer-extras" />
        <PluginSystemContributions
          v-if="props.pluginRpc"
          :request-rpc="props.pluginRpc"
          region="composerSide"
        />
      </template>
    </ComposerBar>

    <!-- ===== Right Drawer ===== -->
    <aside
      v-if="showRightPanel"
      :id="rightDrawerId"
      ref="rightDrawerRef"
      data-workspace-right-drawer data-region="right" data-ui-id="shell.right-drawer"
      class="workspace-drawer drawer-right optical-glass"
      :class="{ open: rightDrawerShown, pinned: rightPinned, 'drawer-retracting': rightRetracting }"
      @mouseleave="onRightDrawerLeave"
    >
      <header v-if="showRightPanelHeader" class="drawer-head">
        <strong>{{ defaultUiText(rightPanelTitle, '运行状态') }}</strong>
      </header>
      <div class="drawer-body right-body">
        <slot v-if="!isRegionReplaced('right')" name="right-panel" />
        <PluginSystemContributions
          v-if="props.pluginRpc"
          :request-rpc="props.pluginRpc"
          region="right"
          replacer-only
        />
      </div>
    </aside>

    <!-- ===== Modal slot ===== -->
    <slot name="modals" />
  </div>
</template>

<script setup lang="ts">
import { defaultUiText } from '@/i18n/index.ts'

import PluginSystemContributions from '@/components/PluginSystemContributions.vue'
import LeftPluginDock from '@/components/LeftPluginDock.vue'
import { isRegionReplaced } from '@/plugins/contributions.ts'

import { t } from '@/i18n/index.ts'

/**
 * WorkspaceShell — three-card workspace layout
 *
 * Backdrop layer (backdrop), main card (main), composer bar (composer),
 * plus left sidebar and right info panel.
 *
 * Uses useShellLayout for all drawer/pin/theme/density state.
 * Product provides slots for actual content.
 */
import { gsap } from 'gsap'
import { computed, nextTick, onMounted, onUnmounted, ref, toRef, useId, watch } from 'vue'
import { PanelLeft } from 'lucide-vue-next'
import { useComposerLayout } from '@/composables/useComposerLayout.ts'
import {
  LEFT_DRAWER_WIDTH_MAX,
  LEFT_DRAWER_WIDTH_MIN,
  LEFT_DRAWER_WIDTH_STEP,
  useShellLayout,
} from '@/composables/useShellLayout.ts'
import type { ThemeData } from '@/composables/useShellLayout.ts'
import ComposerBar from '@/components/ComposerBar.vue'
import CoreSendStopButton from '@/components/CoreSendStopButton.vue'
import CoreToastHost from '@/components/CoreToastHost.vue'
import LeftSidebarShell from '@/components/LeftSidebarShell.vue'
import { useComposerColumn } from '@/composables/useComposerColumn'

const props = withDefaults(
  defineProps<{
    compactChrome?: boolean
    requireLeftSidebar?: boolean
    productName: string
    pluginRpc?: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>
    sidebarTitle?: string
    showSidebarHeader?: boolean
    showSidebarHeaderAction?: boolean
    showSidebarSearchAction?: boolean
    showSidebarPluginsAction?: boolean
    showSidebarSettingsAction?: boolean
    /** Runtime platform（desktop / mobile）：窄窗的移动端语义只对 mobile 生效。 */
    platform?: string
    /** 输入栏是否收起成单行胶囊（由宿主按“没字、没附件、没在跑、没聚焦”决定）。 */
    composerCompact?: boolean
    storageKey?: string
    density?: 'compact' | 'standard' | 'loose'
    contentWidth?: number
    /** Let a plugin own the full central surface; headers and overlays remain stacked above it. */
    mainContentFullBleed?: boolean
    /** Enables Workflow-specific Composer density and canvas affordances. */
    workflowMode?: boolean
    /** Host-owned text state so programmatic composer updates count as active use. */
    composerHasValue?: boolean
    theme?: ThemeData
    rightPanelTitle?: string
    /** Set false when the right-panel slot owns its own modular header. */
    showRightPanelHeader?: boolean
    composerPlaceholder?: string
    composerDisabled?: boolean
    composerSendDisabled?: boolean
    composerActionMode?: 'send' | 'stop' | 'resume'
    composerSendLabel?: string
    composerStopLabel?: string
    composerSendTitle?: string
    composerStopTitle?: string
    composerHoldEnabled?: boolean
    showRightPanel?: boolean
    hideComposer?: boolean
    /** 整界面切走：为真时会话栏整列退场（最左竖栏仍常驻）。 */
    collapseLeftSidebar?: boolean
    /**
     * 主卡不渲染标题条（设置 / 插件的页名与分区都在会话栏里）：
     * 顶部那条留给标题条的高度随之收回，内容独占整页。
     */
    hideMainHeader?: boolean
    /** Set false while a full-area view or split owns the surface. */
    showDrawerToggle?: boolean
    /** Host-controlled layout state for a Core session with no messages yet. */
    emptySession?: boolean
    /** Stable host session identity used to retain working-state placement. */
    composerSessionKey?: string | null
    /** False while the host is still loading the selected session history. */
    composerSessionReady?: boolean
    /**
     * 右侧栏的悬停卡正浮在抽屉之外（区域被卡片占用）：指针从竖栏移向卡片时会
     * 先离开抽屉本体，此时不能按“离开竖栏”收起它。
     */
    rightPanelHold?: boolean
  }>(),
  {
    storageKey: 'lamtools.ui',
    sidebarTitle: '',
    showSidebarHeader: true,
    showSidebarHeaderAction: true,
    showSidebarSearchAction: true,
    showSidebarPluginsAction: true,
    showSidebarSettingsAction: true,
    density: 'standard',
    contentWidth: 780,
    mainContentFullBleed: false,
    workflowMode: false,
    composerHasValue: false,
    rightPanelTitle: '运行状态',
    showRightPanelHeader: true,
    composerPlaceholder: '输入内容...',
    composerDisabled: false,
    composerSendDisabled: false,
    composerActionMode: 'send',
    composerSendLabel: 'send',
    composerStopLabel: 'stop',
    composerSendTitle: '发送',
    composerStopTitle: '停止运行',
    composerHoldEnabled: true,
    showRightPanel: true,
    hideMainHeader: false,
    showDrawerToggle: true,
    emptySession: false,
    composerSessionKey: null,
    composerSessionReady: true,
    rightPanelHold: false,
  },
)

const emit = defineEmits<{
  'new-session': []
  'update:left-open': [value: boolean]
  'update:left-pinned': [value: boolean]
  'update:right-pinned': [value: boolean]
  settings: []
  plugins: []
  search: []
  'composer-submit': [],
  'composer-terminate': []
  'composer-drop': [event: DragEvent]
}>()

// IME guard for the fallback textarea: composition-confirm Enter must not
// submit the message (audit 19 S3). Enter only sends — with nothing typed it
// must not reach the host, whose submit handler treats an empty composer as
// the stop action.
function onComposerEnter(event: KeyboardEvent) {
  if (event.isComposing) return
  event.preventDefault()
  const value = (event.target as HTMLTextAreaElement | null)?.value || ''
  if (!value.trim()) return
  emit('composer-submit')
}

const drawerId = useId()
const leftDrawerId = `${drawerId}-left-drawer`
const rightDrawerId = `${drawerId}-right-drawer`

const {
  leftOpen,
  leftDrawerShown,
  rightOpen,
  leftPinned,
  rightPinned,
  rightRetracting,
  isNarrowViewport,
  shellClass,
  shellStyle,
  rightDrawerModal,
  rightDrawerShown,
  density: shellDensity,
  contentWidth: shellContentWidth,
  theme: shellTheme,
  toggleLeftPinned,
  toggleRightPinned,
  onLeftDrawerLeave,
  onRightDrawerLeave: closeRightDrawer,
  openLeftDrawer,
  toggleLeftDrawer,
  openRightDrawer,
  closeDrawers,
  setSidebarCollapsed,
  leftWidth,
  setLeftWidth,
  resetLeftWidth,
} = useShellLayout({
  platform: props.platform,
  compactChrome: props.compactChrome,
  requiresLeftDrawer: () => Boolean(props.requireLeftSidebar),
  storageKey: props.storageKey,
  density: props.density,
  contentWidth: props.contentWidth,
  theme: props.theme,
  showRightPanel: props.showRightPanel,
})

const projectSidebarToggleLabel = computed(() => t(leftDrawerShown.value ? '收起项目侧栏' : '打开项目侧栏'))

watch(
  () => props.collapseLeftSidebar,
  (collapsed) => setSidebarCollapsed(Boolean(collapsed)),
  { immediate: true },
)

function onLeftSurfaceLeave(event: MouseEvent): void {
  const next = event.relatedTarget
  if (next instanceof Element && next.closest('.workspace-left-rail, .drawer-left')) return
  onLeftDrawerLeave()
}

const rightDrawerRef = ref<HTMLElement | null>(null)

/**
 * 右侧的悬停卡浮在抽屉之外。指针从竖栏移向卡片时会先离开抽屉本体，但卡片还没
 * 接管（rightPanelHold 仍是假），按“离开即收起”会把竖栏从指针下抽走。因此：
 * 卡片还在浮出时不算离开；卡片收起后再确认指针没有回到竖栏，才收起抽屉。
 */
function onRightDrawerLeave(): void {
  if (rightPinned.value || props.rightPanelHold) return
  closeRightDrawer()
}

watch(
  () => props.rightPanelHold,
  (hold) => {
    if (hold || rightPinned.value) return
    if (rightDrawerRef.value?.matches(':hover')) return
    closeRightDrawer()
  },
)

const shellElement = ref<HTMLElement | null>(null)
// user:“输入栏必须限制在主内容列内…若主列几何变量缺失，就回退到主区容器 getBoundingClientRect()”+
// (把主区的实测矩形写成 --composer-measured-left/width，CSS 优先读它们；分屏/主内容=浏览器/聚焦全屏都覆盖)。
useComposerColumn(shellElement)

/* user:“让左侧栏和主内容区中间的边界可以被拖动”+
   (分界线把手贴在会话栏右缘：拖动改宽度，松手落盘，双击回默认档。
    拖拽期间在 body 上挂类，越过聊天区也不会把别人的文字选中)。 */
const SIDEBAR_RESIZE_BODY_CLASS = 'sidebar-is-resizing'
// 只给固定住的会话栏拖宽度：未固定时它是悬停浮出的，指针一离开就收回，拖不稳。
const sidebarResizable = computed(
  () => leftOpen.value && leftPinned.value && !props.collapseLeftSidebar && !isNarrowViewport.value,
)
const sidebarResizeValue = computed(() => leftWidth.value ?? undefined)

type SidebarResizeState = { pointerId: number; startX: number; startWidth: number }
let sidebarResize: SidebarResizeState | null = null

function currentSidebarWidth(): number {
  const drawer = shellElement.value?.querySelector<HTMLElement>('.drawer-left')
  // 首帧或测试环境量不到布局时，回落到已保存的宽度，拖动仍从同一个数开始。
  return Math.round(drawer?.getBoundingClientRect().width || leftWidth.value || 0)
}

function startSidebarResize(event: PointerEvent): void {
  if (event.button !== 0) return
  const startWidth = currentSidebarWidth()
  if (startWidth <= 0) return
  // 先把当前宽度定成用户值：拖动途中窗口跨断点换档，不能把宽度拽回去。
  setLeftWidth(startWidth)
  sidebarResize = { pointerId: event.pointerId, startX: event.clientX, startWidth }
  document.body.classList.add(SIDEBAR_RESIZE_BODY_CLASS)
  window.addEventListener('pointermove', onSidebarResizeMove)
  window.addEventListener('pointerup', endSidebarResize)
  window.addEventListener('pointercancel', endSidebarResize)
  event.preventDefault()
}

function onSidebarResizeMove(event: PointerEvent): void {
  if (!sidebarResize || event.pointerId !== sidebarResize.pointerId) return
  setLeftWidth(sidebarResize.startWidth + (event.clientX - sidebarResize.startX))
  event.preventDefault()
}

function endSidebarResize(): void {
  sidebarResize = null
  document.body.classList.remove(SIDEBAR_RESIZE_BODY_CLASS)
  window.removeEventListener('pointermove', onSidebarResizeMove)
  window.removeEventListener('pointerup', endSidebarResize)
  window.removeEventListener('pointercancel', endSidebarResize)
}

function onSidebarResizeKeydown(event: KeyboardEvent): void {
  const step = event.shiftKey ? LEFT_DRAWER_WIDTH_STEP * 4 : LEFT_DRAWER_WIDTH_STEP
  if (event.key === 'ArrowLeft') setLeftWidth(currentSidebarWidth() - step)
  else if (event.key === 'ArrowRight') setLeftWidth(currentSidebarWidth() + step)
  else if (event.key === 'Home') setLeftWidth(LEFT_DRAWER_WIDTH_MIN)
  else if (event.key === 'End') setLeftWidth(LEFT_DRAWER_WIDTH_MAX)
  else return
  event.preventDefault()
}

// 视窗已归档：composer 布局的视口参数恒为关闭。
const composerLayout = useComposerLayout({
  root: shellElement,
  emptySession: toRef(props, 'emptySession'),
  viewportOpen: ref(false),
  sessionKey: toRef(props, 'composerSessionKey'),
  sessionReady: toRef(props, 'composerSessionReady'),
})
const composerShellClass = composerLayout.shellClass
const composerRootClass = composerLayout.rootClass
const composerLayoutStyle = composerLayout.style
const workflowComposerObservedValue = ref(false)
const workflowInteractionActive = ref(false)
const workflowComposerHasValue = computed(() => (
  props.workflowMode && (props.composerHasValue || workflowComposerObservedValue.value)
))
const WORKFLOW_INTERACTION_LEAVE_GRACE_MS = 120
let workflowInteractionLeaveTimer: number | undefined
let composerMotionContext: gsap.Context | null = null
let composerPlacementTween: gsap.core.Tween | null = null
let composerPlacementRevision = 0

onMounted(() => {
  if (!shellElement.value) return
  composerMotionContext = gsap.context(() => {}, shellElement.value)
  void nextTick(syncWorkflowComposerValue)
})

watch(
  [() => props.workflowMode, () => props.composerActionMode],
  () => {
    if (!props.workflowMode) {
      clearWorkflowInteractionLeave()
      workflowInteractionActive.value = false
    }
    void nextTick(syncWorkflowComposerValue)
  },
)

function isWorkflowInteractionTarget(target: EventTarget | null): boolean {
  return target instanceof Element
    && Boolean(target.closest('.floating-composer, .wf-convo-float'))
}

function clearWorkflowInteractionLeave(): void {
  if (workflowInteractionLeaveTimer === undefined) return
  window.clearTimeout(workflowInteractionLeaveTimer)
  workflowInteractionLeaveTimer = undefined
}

function onWorkflowInteractionPointerOver(event: PointerEvent): void {
  if (!props.workflowMode || !isWorkflowInteractionTarget(event.target)) return
  clearWorkflowInteractionLeave()
  workflowInteractionActive.value = true
}

function onWorkflowInteractionPointerOut(event: PointerEvent): void {
  if (!props.workflowMode || !isWorkflowInteractionTarget(event.target)) return
  if (isWorkflowInteractionTarget(event.relatedTarget)) return
  clearWorkflowInteractionLeave()
  workflowInteractionLeaveTimer = window.setTimeout(() => {
    workflowInteractionLeaveTimer = undefined
    workflowInteractionActive.value = false
  }, WORKFLOW_INTERACTION_LEAVE_GRACE_MS)
}

function syncWorkflowComposerValue(): void {
  if (!props.workflowMode) {
    workflowComposerObservedValue.value = false
    return
  }
  const textarea = shellElement.value?.querySelector<HTMLTextAreaElement>('.floating-composer textarea')
  workflowComposerObservedValue.value = Boolean(textarea?.value.trim())
}

function onShellInput(event: Event): void {
  if (!props.workflowMode) return
  const target = event.target
  if (!(target instanceof HTMLTextAreaElement) || !target.closest('.floating-composer')) return
  workflowComposerObservedValue.value = Boolean(target.value.trim())
}

watch(composerLayout.placement, async () => {
  const composer = shellElement.value?.querySelector<HTMLElement>('.floating-composer') ?? null
  if (!composer) return

  const revision = ++composerPlacementRevision
  const previousTop = composer.getBoundingClientRect().top
  await nextTick()
  if (revision !== composerPlacementRevision || !composer.isConnected) return

  const offsetY = previousTop - composer.getBoundingClientRect().top
  composerPlacementTween?.kill()
  composerPlacementTween = null
  gsap.set(composer, { clearProps: 'transform,willChange' })
  if (
    Math.abs(offsetY) < 1
    || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    || !composerMotionContext
  ) return

  composerMotionContext.add(() => {
    composerPlacementTween = gsap.fromTo(
      composer,
      { y: offsetY, willChange: 'transform' },
      {
        y: 0,
        duration: 0.5,
        ease: 'power3.inOut',
        overwrite: 'auto',
        clearProps: 'transform,willChange',
        onComplete: () => { composerPlacementTween = null },
      },
    )
  })
})

onUnmounted(() => {
  endSidebarResize()
  clearWorkflowInteractionLeave()
  composerPlacementRevision += 1
  composerPlacementTween?.kill()
  composerPlacementTween = null
  composerMotionContext?.revert()
  composerMotionContext = null
})

function syncComposerKeyboardInset(): void {
  composerLayout.syncKeyboardInset()
  composerLayout.scheduleKeyboardSync()
}

function onShellFocusIn(event: FocusEvent): void {
  const target = event.target
  if (target instanceof Element && target.closest('.floating-composer')) {
    syncWorkflowComposerValue()
    syncComposerKeyboardInset()
  }
}

function onShellFocusOut(): void {
  syncComposerKeyboardInset()
}

function onComposerSubmit(): void {
  composerLayout.enterBottom()
  emit('composer-submit')
  void nextTick(syncWorkflowComposerValue)
}

function onComposerDrop(event: DragEvent): void {
  emit('composer-drop', event)
}

function onSidebarTogglePinned() {
  toggleLeftPinned()
}

type SwipeGesture = {
  pointerId: number
  pointerType: string
  startX: number
  startY: number
  selectingText: boolean
}

// Mobile OSes reserve the physical screen edges for back navigation, so the
// drawer gesture deliberately starts anywhere in the shell. A clearly
// horizontal gesture is still required to preserve ordinary vertical scroll.
const SWIPE_TRIGGER_DISTANCE = 28
const SWIPE_AXIS_RATIO = 1.15
let swipeGesture: SwipeGesture | null = null

function onSwipePointerDown(event: PointerEvent): void {
  swipeGesture = null
  if (!isNarrowViewport.value || !['touch', 'pen', 'mouse'].includes(event.pointerType)) return
  if (event.pointerType === 'mouse' && event.button !== 0) return

  swipeGesture = {
    pointerId: event.pointerId,
    pointerType: event.pointerType,
    startX: event.clientX,
    startY: event.clientY,
    selectingText: false,
  }

  // The finger may leave the original child element while swiping. Capturing
  // it on the shell keeps move/up events together in WebViews and Tauri.
  const shell = event.currentTarget
  if (event.pointerType !== 'mouse' && shell instanceof HTMLElement && shell.setPointerCapture) {
    try {
      shell.setPointerCapture(event.pointerId)
    } catch {
      // Some test/WebView implementations do not support capture for a
      // synthetic or already-released pointer.
    }
  }
}

function onSwipePointerMove(event: PointerEvent): void {
  const gesture = swipeGesture
  if (!gesture || gesture.pointerId !== event.pointerId) return

  // Mouse dragging must remain available for native text selection. Touch and
  // pen have no desktop-style selection conflict and may suppress horizontal
  // browser handling once the gesture direction is clear.
  if (gesture.pointerType === 'mouse') return

  const deltaX = event.clientX - gesture.startX
  const deltaY = event.clientY - gesture.startY
  if (
    Math.abs(deltaX) >= Math.abs(deltaY) * SWIPE_AXIS_RATIO &&
    Math.abs(deltaX) > 6 &&
    event.cancelable
  ) {
    event.preventDefault()
  }
}

function onSwipeSelectStart(): void {
  if (swipeGesture?.pointerType === 'mouse') swipeGesture.selectingText = true
}

function onSwipePointerUp(event: PointerEvent): void {
  const gesture = swipeGesture
  swipeGesture = null
  if (!gesture || gesture.pointerId !== event.pointerId) return
  if (gesture.pointerType === 'mouse' && gesture.selectingText) return

  const deltaX = event.clientX - gesture.startX
  const deltaY = event.clientY - gesture.startY
  if (
    Math.abs(deltaX) < SWIPE_TRIGGER_DISTANCE ||
    Math.abs(deltaX) < Math.abs(deltaY) * SWIPE_AXIS_RATIO
  ) return

  if (deltaX > 0) openLeftDrawer()
  if (deltaX < 0 && props.showRightPanel) openRightDrawer()
}

function onSwipePointerCancel(): void {
  swipeGesture = null
  if (props.workflowMode) {
    clearWorkflowInteractionLeave()
    workflowInteractionActive.value = false
  }
}

// user:“点远程连接后看起来没反应”+(底部图标排开的是整版界面，手机上抽屉还盖在上面；
// 打开视图时把抽屉收起来，用户才看得到结果)。
function closeLeftDrawer(): void {
  leftOpen.value = false
}

watch(leftOpen, (value) => {
  emit('update:left-open', value)
}, { immediate: true })
watch(leftPinned, (value) => {
  emit('update:left-pinned', value)
})
watch(rightPinned, (value) => {
  emit('update:right-pinned', value)
})

// Sync theme/density/contentWidth from parent into useShellLayout state
watch(() => props.theme, (val) => {
  if (val !== undefined && val !== shellTheme.value) shellTheme.value = val
})
watch(() => props.density, (val) => {
  if (val !== undefined && val !== shellDensity.value) shellDensity.value = val
})
watch(() => props.contentWidth, (val) => {
  if (val !== undefined && val !== shellContentWidth.value) shellContentWidth.value = val
})

defineExpose({
  leftPinned,
  closeLeftDrawer,
  rightPinned,
  openLeftDrawer,
  toggleLeftDrawer,
  toggleLeftPinned,
  toggleRightPinned,
  resetComposerLayout: composerLayout.resetForSession,
})
</script>
