<template>
  <div class="workspace-shell" :class="shellClass" :style="shellStyle">
    <!-- Notifications: single global host fed by the useCoreToast service.
         errorText/noticeText props are bridged into the service for legacy
         hosts (audit: previously two fixed slots, no dismissal, no
         auto-expiry for several error sources). -->
    <CoreToastHost />

    <nav class="mobile-shell-nav" aria-label="工作区面板">
      <span class="mobile-shell-title">{{ productName }}</span>
      <button
        ref="leftToggleButton"
        class="mobile-shell-button"
        type="button"
        data-mobile-left-toggle
        :aria-controls="leftDrawerId"
        :aria-expanded="leftOpen"
        :aria-label="leftOpen ? '关闭会话与导航' : '打开会话与导航'"
        @click="toggleLeftDrawer"
      >
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16" /></svg>
      </button>
      <button
        v-if="showRightPanel"
        ref="rightToggleButton"
        class="mobile-shell-button"
        type="button"
        data-mobile-right-toggle
        :aria-controls="rightDrawerId"
        :aria-expanded="rightOpen"
        :aria-label="rightOpen ? '关闭运行状态' : '打开运行状态'"
        @click="toggleRightDrawer"
      >
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h16v14H4zM15 5v14M7 9h5M7 13h5" /></svg>
      </button>
    </nav>

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
      ref="rightToggle"
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
    <aside
      :id="leftDrawerId"
      data-workspace-left-drawer
      class="workspace-drawer drawer-left"
      :class="{ open: leftOpen || stageOpen, pinned: leftPinned }"
      :inert="(!leftOpen && !stageOpen) || undefined"
      :aria-hidden="!leftOpen && !stageOpen"
      @mouseleave="onLeftDrawerLeave"
    >
      <header class="drawer-head">
        <span class="sidebar-label">项目</span>
        <slot name="sidebar-header-action">
          <button class="icon-btn" title="新建" aria-label="新建会话" @click="$emit('new-session')">+</button>
        </slot>
      </header>

      <div class="drawer-body">
        <slot name="sidebar-body">
          <div class="sidebar-empty">No content</div>
        </slot>
      </div>

      <footer class="drawer-footer">
        <button class="settings-entry" aria-label="打开搜索" @click="$emit('search')">
          <span aria-hidden="true"><Search :size="14" :stroke-width="1.8" /></span>
          <span>搜索</span>
        </button>
        <button class="settings-entry" aria-label="打开插件" @click="$emit('plugins')">
          <span aria-hidden="true"><Puzzle :size="14" :stroke-width="1.8" /></span>
          <span>插件</span>
        </button>
        <button class="settings-entry" aria-label="打开设置" @click="$emit('settings')">
          <span aria-hidden="true"><Command :size="14" :stroke-width="1.8" /></span>
          <span>设置</span>
        </button>
        <slot name="sidebar-footer" />
      </footer>
    </aside>

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
      :inert="rightDrawerModal || undefined"
      variant="floating"
      :placeholder="composerPlaceholder"
      :disabled="composerDisabled"
      :active="composerActive"
      :action-mode="composerActionMode"
      :send-label="composerSendLabel"
      :stop-label="composerStopLabel"
      :send-title="composerSendTitle"
      :stop-title="composerStopTitle"
      @submit="$emit('composer-submit')"
      @drop="$emit('composer-drop', $event)"
    >
      <template #preamble>
        <slot name="composer-preamble" />
      </template>
      <template #status>
        <slot name="composer-status" />
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
          <button
            class="send"
            :class="{ 'send--stop': composerActionMode === 'stop' }"
            type="submit"
            :disabled="composerActionMode === 'send' && composerDisabled"
            :title="composerActionMode === 'stop' ? composerStopTitle : composerSendTitle"
            :aria-label="composerActionMode === 'stop' ? composerStopTitle : composerSendTitle"
          >{{ composerActionMode === 'stop' ? composerStopLabel : composerSendLabel }}</button>
        </slot>
      </template>
    </ComposerBar>

    <!-- ===== Right Drawer ===== -->
    <aside
      v-if="showRightPanel"
      :id="rightDrawerId"
      data-workspace-right-drawer
      class="workspace-drawer drawer-right"
      :class="{ open: rightOpen || stageOpen, pinned: rightPinned }"
      :inert="(!rightOpen && !stageOpen) || undefined"
      :aria-hidden="!rightOpen && !stageOpen"
      @mouseleave="onRightDrawerLeave"
    >
      <header class="drawer-head">
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
import { ref, useId, watch } from 'vue'
import { Command, Puzzle, Search } from 'lucide-vue-next'
import { useShellLayout } from '../composables/useShellLayout'
import type { ThemeData } from '../composables/useShellLayout'
import { dismissToast, showToast } from '../composables/useCoreToast'
import ComposerBar from './ComposerBar.vue'
import CoreToastHost from './CoreToastHost.vue'

const props = withDefaults(
  defineProps<{
    productName: string
    sidebarTitle?: string
    storageKey?: string
    density?: 'compact' | 'standard' | 'loose'
    contentWidth?: number
    theme?: ThemeData
    rightPanelTitle?: string
    composerPlaceholder?: string
    composerDisabled?: boolean
    composerActionMode?: 'send' | 'stop'
    composerSendLabel?: string
    composerStopLabel?: string
    composerSendTitle?: string
    composerStopTitle?: string
    errorText?: string
    noticeText?: string
    showRightPanel?: boolean
    stageOpen?: boolean
    hideComposer?: boolean
    /** 透传给 ComposerBar：运行时驱动输入框背景粒子动效 */
    composerActive?: boolean
  }>(),
  {
    storageKey: 'lamtools.ui',
    sidebarTitle: '',
    density: 'standard',
    contentWidth: 780,
    rightPanelTitle: '运行状态',
    composerPlaceholder: '输入内容...',
    composerDisabled: false,
    composerActionMode: 'send',
    composerSendLabel: 'send',
    composerStopLabel: 'stop',
    composerSendTitle: '发送',
    composerStopTitle: '停止运行',
    errorText: '',
    noticeText: '',
    showRightPanel: true,
    stageOpen: false,
    composerActive: false,
  },
)

const emit = defineEmits<{
  'new-session': []
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
const leftToggleButton = ref<HTMLButtonElement | null>(null)
const rightToggleButton = ref<HTMLButtonElement | null>(null)

// Legacy props bridge: hosts that still pass errorText/noticeText get them
// routed through the global toast service (auto-expiry + manual dismiss)
// instead of the removed fixed two-slot render. Clearing the prop dismisses
// the toast it opened.
const propToastIds: Record<'error' | 'notice', number | null> = { error: null, notice: null }
watch(() => props.errorText, (value) => {
  if (value) {
    propToastIds.error = showToast('error', value)
  } else if (propToastIds.error !== null) {
    dismissToast(propToastIds.error)
    propToastIds.error = null
  }
}, { immediate: true })
watch(() => props.noticeText, (value) => {
  if (value) {
    propToastIds.notice = showToast('notice', value)
  } else if (propToastIds.notice !== null) {
    dismissToast(propToastIds.notice)
    propToastIds.notice = null
  }
}, { immediate: true })

const {
  leftOpen,
  rightOpen,
  leftPinned,
  rightPinned,
  stageOpen,
  stageHeight,
  isNarrowViewport,
  shellClass,
  shellStyle,
  rightDrawerModal,
  density: shellDensity,
  contentWidth: shellContentWidth,
  theme: shellTheme,
  toggleLeftPinned,
  toggleRightPinned,
  onLeftDrawerLeave,
  onRightDrawerLeave,
  openLeftDrawer,
  openRightDrawer,
  toggleLeftDrawer,
  toggleRightDrawer,
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

let lastMobileDrawer: 'left' | 'right' | null = null
watch([leftOpen, rightOpen], ([left, right], [previousLeft, previousRight]) => {
  if (!isNarrowViewport.value) return
  if (!previousLeft && left) lastMobileDrawer = 'left'
  if (!previousRight && right) lastMobileDrawer = 'right'
  if (left || right || lastMobileDrawer === null) return

  const target = lastMobileDrawer === 'left' ? leftToggleButton : rightToggleButton
  lastMobileDrawer = null
  target.value?.focus()
}, { flush: 'post' })

// Sync stageOpen: prop → useShellLayout, and useShellLayout → emit
watch(() => props.stageOpen, (val) => {
  if (val !== stageOpen.value) stageOpen.value = val
})
watch(stageOpen, (val) => {
  if (val !== props.stageOpen) emit('update:stageOpen', val)
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

defineExpose({ leftPinned, rightPinned, toggleLeftPinned, toggleRightPinned })
</script>

<style scoped>
/* 移动端导航条标题：桌面端不渲染（无独立 CSS 曾导致桌面显示多余 productName 行） */
.mobile-shell-title {
  display: none;
}
.sidebar-label {
  flex: 1;
  font-size: 13px;
  font-weight: 650;
  color: var(--text, #f2efeb);
  opacity: 0.8;
  letter-spacing: -0.02em;
}
.icon-btn {
  width: 28px;
  height: 28px;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--theme-backdrop-text, #f2efeb) 8%, transparent);
  color: color-mix(in srgb, var(--theme-backdrop-text, #f2efeb) 56%, transparent);
  display: grid;
  place-items: center;
  font-size: 18px;
  font-weight: 700;
}
.icon-btn:hover {
  background: color-mix(in srgb, var(--theme-backdrop-text, #f2efeb) 14%, transparent);
  color: var(--theme-backdrop-text, #f2efeb);
}
</style>
