<template>
  <div
    ref="shellElement"
    class="workspace-shell"
    :class="[
      shellClass,
      composerShellClass,
      {
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
      aria-label="关闭面板"
      @click="closeDrawers"
    ></button>

    <!-- Edge hover triggers -->
    <div
      class="edge edge-left"
      :inert="rightDrawerModal || undefined"
      role="button"
      tabindex="0"
      aria-label="打开左侧会话栏"
      @mouseenter="!leftPinned && openLeftDrawer()"
      @focus="!leftPinned && openLeftDrawer()"
      @keydown.enter.prevent="openLeftDrawer"
      @keydown.space.prevent="openLeftDrawer"
    ></div>
    <div
      v-if="showRightPanel"
      class="edge edge-right"
      role="button"
      tabindex="0"
      aria-label="打开右侧面板"
      @mouseenter="openRightDrawer"
      @focus="openRightDrawer"
      @keydown.enter.prevent="openRightDrawer"
      @keydown.space.prevent="openRightDrawer"
    ></div>

    <!-- ===== Left Drawer ===== -->
    <LeftSidebarShell
      :id="leftDrawerId"
      :open="leftOpen || stageOpen"
      :pinned="leftPinned"
      :title="sidebarTitle"
      :show-sidebar-header="showSidebarHeader"
      :show-default-header-action="showSidebarHeaderAction"
      :show-search-action="showSidebarSearchAction"
      :show-plugins-action="showSidebarPluginsAction"
      :show-settings-action="showSidebarSettingsAction"
      @close="closeDrawers"
      @toggle-pinned="onSidebarTogglePinned"
      @mouseleave="onLeftDrawerLeave"
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
      <template v-if="$slots['sidebar-body']" #sidebar-body>
        <slot name="sidebar-body" />
      </template>
      <template v-if="$slots['sidebar-footer']" #sidebar-footer>
        <slot name="sidebar-footer" />
      </template>
    </LeftSidebarShell>

    <!-- ===== Main Area ===== -->
    <main class="workspace-main" :inert="rightDrawerModal || undefined">
      <div class="workspace-runtime-overlay">
        <slot name="runtime-overlay" />
      </div>
      <slot name="main-header" />
      <slot name="main-content">
        <section class="thread">
          <slot name="thread-content" />
        </section>
      </slot>
    </main>

    <!-- ===== Stage Pane (behind main card) ===== -->
    <div
      class="workspace-stage"
      :inert="!stageOpen || undefined"
      :aria-hidden="!stageOpen"
    >
      <slot name="stage" :open="stageOpen" :toggle="toggleStage" />
      <div
        v-if="stageOpen"
        class="stage-resize-handle"
        @pointerdown="startStageResize"
        @pointermove="onStageResizeMove"
        @pointerup="endStageResize"
        @pointercancel="endStageResize"
      ></div>
    </div>

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
      variant="floating"
      :placeholder="composerPlaceholder"
      :disabled="composerDisabled"
      :action-mode="composerActionMode"
      :send-label="composerSendLabel"
      :stop-label="composerStopLabel"
      :send-title="composerSendTitle"
      :stop-title="composerStopTitle"
      @submit="onComposerSubmit"
      @drop="onComposerDrop"
    >
      <template #popover>
        <slot name="composer-popover" />
      </template>
      <template #preamble>
        <slot v-if="!workflowMode" name="composer-preamble" />
      </template>
      <template #status>
        <slot v-if="!workflowMode" name="composer-status" />
      </template>
      <template #textarea>
        <slot name="composer-textarea">
          <textarea
            :placeholder="composerPlaceholder"
            :aria-label="composerPlaceholder"
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
            :send-title="composerSendTitle"
            :stop-title="composerStopTitle"
          />
        </slot>
      </template>
    </ComposerBar>

    <!-- ===== Right Drawer ===== -->
    <aside
      v-if="showRightPanel"
      :id="rightDrawerId"
      data-workspace-right-drawer
      class="workspace-drawer drawer-right optical-glass"
      :class="{ open: rightDrawerShown, pinned: rightPinned, 'drawer-retracting': rightRetracting }"
      :inert="!rightDrawerShown || undefined"
      :aria-hidden="!rightDrawerShown"
      @mouseleave="onRightDrawerLeave"
    >
      <header v-if="showRightPanelHeader" class="drawer-head">
        <strong>{{ rightPanelTitle }}</strong>
      </header>
      <div class="drawer-body right-body">
        <slot name="right-panel" />
      </div>
    </aside>

    <!-- ===== Modal slot ===== -->
    <slot name="modals" />
  </div>
</template>

<script setup lang="ts">
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
import { useComposerLayout } from '../composables/useComposerLayout'
import { useShellLayout } from '../composables/useShellLayout'
import type { ThemeData } from '../composables/useShellLayout'
import ComposerBar from './ComposerBar.vue'
import CoreSendStopButton from './CoreSendStopButton.vue'
import CoreToastHost from './CoreToastHost.vue'
import LeftSidebarShell from './LeftSidebarShell.vue'

const props = withDefaults(
  defineProps<{
    productName: string
    sidebarTitle?: string
    showSidebarHeader?: boolean
    showSidebarHeaderAction?: boolean
    showSidebarSearchAction?: boolean
    showSidebarPluginsAction?: boolean
    showSidebarSettingsAction?: boolean
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
    composerActionMode?: 'send' | 'stop'
    composerSendLabel?: string
    composerStopLabel?: string
    composerSendTitle?: string
    composerStopTitle?: string
    showRightPanel?: boolean
    stageOpen?: boolean
    hideComposer?: boolean
    /** Host-controlled layout state for a Core session with no messages yet. */
    emptySession?: boolean
    /** Stable host session identity used to retain working-state placement. */
    composerSessionKey?: string | null
    /** False while the host is still loading the selected session history. */
    composerSessionReady?: boolean
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
    showRightPanel: true,
    stageOpen: false,
    emptySession: false,
    composerSessionKey: null,
    composerSessionReady: true,
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
  'composer-submit': []
  'composer-drop': [event: DragEvent]
  'update:stageOpen': [value: boolean]
}>()

// IME guard for the fallback textarea: composition-confirm Enter must not
// submit the message (audit 19 S3).
function onComposerEnter(event: KeyboardEvent) {
  if (event.isComposing) return
  event.preventDefault()
  emit('composer-submit')
}

const drawerId = useId()
const leftDrawerId = `${drawerId}-left-drawer`
const rightDrawerId = `${drawerId}-right-drawer`

const {
  leftOpen,
  rightOpen,
  leftPinned,
  rightPinned,
  rightRetracting,
  stageOpen,
  stageHeight,
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
  onRightDrawerLeave,
  openLeftDrawer,
  openRightDrawer,
  closeDrawers,
  toggleStage,
  startStageResize,
  onStageResizeMove,
  endStageResize,
} = useShellLayout({
  storageKey: props.storageKey,
  density: props.density,
  contentWidth: props.contentWidth,
  theme: props.theme,
  showRightPanel: props.showRightPanel,
})

const shellElement = ref<HTMLElement | null>(null)
const composerLayout = useComposerLayout({
  root: shellElement,
  emptySession: toRef(props, 'emptySession'),
  viewportOpen: stageOpen,
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

// Sync stageOpen: prop → useShellLayout, and useShellLayout → emit
watch(() => props.stageOpen, (val) => {
  if (val !== stageOpen.value) stageOpen.value = val
})
watch(stageOpen, (val) => {
  if (val !== props.stageOpen) emit('update:stageOpen', val)
})
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
  rightPinned,
  openLeftDrawer,
  toggleLeftPinned,
  toggleRightPinned,
  resetComposerLayout: composerLayout.resetForSession,
})
</script>
