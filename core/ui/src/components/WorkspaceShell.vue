<template>
  <div class="workspace-shell" :class="shellClass" :style="shellStyle">
    <!-- Notifications -->
    <div v-if="errorText" class="error-toast">{{ errorText }}</div>
    <div v-if="noticeText" class="notice-toast">{{ noticeText }}</div>

    <!-- Edge hover triggers -->
    <div
      class="edge edge-left"
      :inert="rightDrawerModal || undefined"
      role="button"
      tabindex="0"
      aria-label="打开左侧会话栏"
      @mouseenter="!leftPinned && (leftOpen = true)"
      @focus="!leftPinned && (leftOpen = true)"
      @keydown.enter.prevent="leftOpen = true"
      @keydown.space.prevent="leftOpen = true"
    ></div>
    <button
      v-if="showRightPanel"
      ref="rightToggle"
      class="edge edge-right"
      data-workspace-right-toggle
      type="button"
      :aria-label="rightOpen ? '关闭右侧面板' : '打开右侧面板'"
      aria-controls="workspace-right-panel"
      :aria-expanded="rightOpen"
      @pointerenter="openRightDrawerFromPointer"
      @click="toggleRightDrawer"
    >
      <span class="edge-right-label" aria-hidden="true">{{ rightOpen ? '关闭' : '工具' }}</span>
    </button>

    <!-- ===== Left Drawer ===== -->
    <aside
      class="workspace-drawer drawer-left"
      :class="{ open: leftOpen, pinned: leftPinned }"
      :inert="rightDrawerModal || undefined"
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
      ref="rightDrawer"
      id="workspace-right-panel"
      class="workspace-drawer drawer-right"
      :class="{ open: rightOpen, pinned: rightPinned }"
      :inert="!rightOpen || undefined"
      :aria-hidden="!rightOpen || undefined"
      :aria-label="rightPanelTitle"
      tabindex="-1"
      @mouseleave="onRightDrawerPointerLeave"
      @keydown.esc.stop.prevent="closeRightDrawer"
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
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
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

const rightToggle = ref<HTMLButtonElement | null>(null)
const rightDrawer = ref<HTMLElement | null>(null)
const compactViewport = ref(false)
const rightDrawerModal = computed(() => rightOpen.value && compactViewport.value)

function syncCompactViewport() {
  compactViewport.value = typeof window !== 'undefined' && window.innerWidth <= 640
}

function toggleRightDrawer() {
  if (rightOpen.value) {
    closeRightDrawer()
    return
  }
  rightOpen.value = true
}

function closeRightDrawer() {
  rightOpen.value = false
  void nextTick(() => rightToggle.value?.focus())
}

function onRightDrawerPointerLeave() {
  if (!compactViewport.value) onRightDrawerLeave()
}

function openRightDrawerFromPointer(event: PointerEvent) {
  if (event.pointerType === 'mouse') rightOpen.value = true
}

watch(rightDrawerModal, async (active) => {
  if (!active) return
  leftOpen.value = false
  await nextTick()
  rightDrawer.value?.focus()
})

onMounted(() => {
  syncCompactViewport()
  window.addEventListener('resize', syncCompactViewport)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', syncCompactViewport)
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
