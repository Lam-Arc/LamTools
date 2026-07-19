<template>
  <div class="workspace-shell" :class="shellClass" :style="shellStyle">
    <!-- Notifications -->
    <div v-if="errorText" class="error-toast" role="alert" aria-atomic="true">{{ errorText }}</div>
    <div v-if="noticeText" class="notice-toast" role="status" aria-atomic="true">{{ noticeText }}</div>

    <nav class="mobile-shell-nav" aria-label="工作区面板">
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
    <button
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
      :class="{ open: leftOpen, pinned: leftPinned }"
      :inert="!leftOpen || undefined"
      :aria-hidden="!leftOpen"
      @mouseleave="onLeftDrawerLeave"
    >
      <header class="drawer-head">
        <button
          class="pin-plain"
          :class="{ active: leftPinned }"
          :title="leftPinned ? '取消固定' : '固定侧栏'"
          :aria-label="leftPinned ? '取消固定左侧栏' : '固定左侧栏'"
          @click="toggleLeftPinned"
        >
          {{ leftPinned ? '◆' : '◇' }}
        </button>
        <strong>{{ sidebarTitle || productName }}</strong>
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
        <button class="settings-entry" aria-label="打开设置" @click="$emit('settings')">
          <span>⌘</span>
          <span>Settings</span>
        </button>
        <slot name="sidebar-footer" />
      </footer>
    </aside>

    <!-- ===== Main Area ===== -->
    <main class="workspace-main" :inert="rightDrawerModal || undefined">
      <slot name="main-header" />
      <slot name="main-content">
        <section class="thread">
          <slot name="thread-content" />
        </section>
      </slot>
    </main>

    <!-- ===== Floating Composer ===== -->
    <ComposerBar
      :inert="rightDrawerModal || undefined"
      variant="floating"
      :placeholder="composerPlaceholder"
      :disabled="composerDisabled"
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
            @keydown.enter.exact.prevent="$emit('composer-submit')"
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
      :class="{ open: rightOpen, pinned: rightPinned }"
      :inert="!rightOpen || undefined"
      :aria-hidden="!rightOpen"
      @mouseleave="onRightDrawerLeave"
    >
      <header class="drawer-head">
        <strong>{{ rightPanelTitle }}</strong>
        <button
          class="pin-plain"
          :class="{ active: rightPinned }"
          :title="rightPinned ? '取消固定' : '固定侧栏'"
          :aria-label="rightPinned ? '取消固定右侧栏' : '固定右侧栏'"
          @click="toggleRightPinned"
        >
          {{ rightPinned ? '◆' : '◇' }}
        </button>
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
import { useShellLayout } from '../composables/useShellLayout'
import type { ThemeData } from '../composables/useShellLayout'
import ComposerBar from './ComposerBar.vue'

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
  },
)

const emit = defineEmits<{
  'new-session': []
  settings: []
  'composer-submit': []
  'composer-drop': [event: DragEvent]
}>()

const drawerId = useId()
const leftDrawerId = `${drawerId}-left-drawer`
const rightDrawerId = `${drawerId}-right-drawer`
const leftToggleButton = ref<HTMLButtonElement | null>(null)
const rightToggleButton = ref<HTMLButtonElement | null>(null)

const {
  leftOpen,
  rightOpen,
  leftPinned,
  rightPinned,
  isNarrowViewport,
  shellClass,
  shellStyle,
  toggleLeftPinned,
  toggleRightPinned,
  onLeftDrawerLeave,
  onRightDrawerLeave,
  openLeftDrawer,
  openRightDrawer,
  toggleLeftDrawer,
  toggleRightDrawer,
  closeDrawers,
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
</script>

<style scoped>
.icon-btn {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.08);
  color: var(--muted);
  display: grid;
  place-items: center;
  font-size: 18px;
  font-weight: 700;
}
.icon-btn:hover {
  background: rgba(255, 255, 255, 0.14);
  color: var(--text);
}
</style>
