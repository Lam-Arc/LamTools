<template>
  <div class="workspace-shell" :class="shellClass" :style="shellStyle">
    <!-- Notifications -->
    <div v-if="errorText" class="error-toast">{{ errorText }}</div>
    <div v-if="noticeText" class="notice-toast">{{ noticeText }}</div>

    <!-- Edge hover triggers -->
    <div
      class="edge edge-left"
      role="button"
      tabindex="0"
      aria-label="打开左侧会话栏"
      @mouseenter="!leftPinned && (leftOpen = true)"
      @focus="!leftPinned && (leftOpen = true)"
      @keydown.enter.prevent="leftOpen = true"
      @keydown.space.prevent="leftOpen = true"
    ></div>
    <div
      class="edge edge-right"
      role="button"
      tabindex="0"
      aria-label="打开右侧面板"
      @mouseenter="rightOpen = true"
      @focus="rightOpen = true"
      @keydown.enter.prevent="rightOpen = true"
      @keydown.space.prevent="rightOpen = true"
    ></div>

    <!-- ===== Left Drawer ===== -->
    <aside
      class="workspace-drawer drawer-left"
      :class="{ open: leftOpen, pinned: leftPinned }"
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
        <strong>{{ productName }}</strong>
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
    <main class="workspace-main">
      <slot name="main-header" />
      <slot name="main-content">
        <section class="thread">
          <slot name="thread-content" />
        </section>
      </slot>
    </main>

    <!-- ===== Floating Composer ===== -->
    <form
      class="floating-composer"
      @submit.prevent="$emit('composer-submit')"
      @dragover.prevent
      @drop.prevent="$emit('composer-drop', $event)"
    >
      <slot name="composer-preamble" />
      <div class="composer-main-card">
        <slot name="composer-textarea">
          <textarea
            :placeholder="composerPlaceholder"
            rows="1"
            @keydown.enter.exact.prevent="$emit('composer-submit')"
          ></textarea>
        </slot>
        <div class="composer-bottom">
          <div class="tool-row">
            <slot name="composer-tools" />
          </div>
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
        </div>
      </div>
      <div class="drop-hint">拖拽到这里</div>
    </form>

    <!-- ===== Right Drawer ===== -->
    <aside
      v-if="showRightPanel"
      class="workspace-drawer drawer-right"
      :class="{ open: rightOpen, pinned: rightPinned }"
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
import { useShellLayout } from '../composables/useShellLayout'
import type { ThemeData } from '../composables/useShellLayout'

const props = withDefaults(
  defineProps<{
    productName: string
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

const {
  leftOpen,
  rightOpen,
  leftPinned,
  rightPinned,
  shellClass,
  shellStyle,
  toggleLeftPinned,
  toggleRightPinned,
  onLeftDrawerLeave,
  onRightDrawerLeave,
} = useShellLayout({
  storageKey: props.storageKey,
  density: props.density,
  contentWidth: props.contentWidth,
  theme: props.theme,
  showRightPanel: props.showRightPanel,
})
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
