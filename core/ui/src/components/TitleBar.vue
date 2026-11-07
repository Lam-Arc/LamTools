<template>
  <div v-if="shouldDisplayTitleBar" class="titlebar" data-tauri-drag-region data-ui-id="shell.titlebar">
    <div class="titlebar-left">
      <span class="brand" :class="{ 'brand--session': Boolean(props.sessionTitle) }">
        <strong class="brand-name">Sunday</strong>
        <!-- user:“小尺寸时（独屏）标题换到“sunday”那里，不占地”+(窄窗口把会话标题
             放进标题栏，原来的会话标题行不再单独占一行。) -->
        <strong v-if="props.sessionTitle" class="brand-session-name" :title="props.sessionTitle">{{ props.sessionTitle }}</strong>
      </span>
    </div>

    <div class="titlebar-workflow-tabs" data-titlebar-workflow-tabs></div>

    <div class="titlebar-right">
      <!-- sidebar pin buttons -->
      <div class="titlebar-sidebar-controls" data-titlebar-sidebar-controls>
        <button
          class="pin-btn"
          :class="{ active: props.leftPinned }"
          :title="props.leftPinned ? t('取消固定左侧栏') : t('固定左侧栏')"
          @click="$emit('toggleLeftPinned')"
        >
          <svg viewBox="0 0 14 14" class="pin-icon pin-left">
            <rect x="1" y="2" width="5.5" height="10" rx="2" fill="currentColor" />
            <rect x="7.5" y="2" width="5.5" height="10" rx="2" fill="none" stroke="currentColor" stroke-width="1.5" />
          </svg>
        </button>
        <button
          class="pin-btn"
          :class="{ active: props.rightPinned }"
          :title="props.rightPinned ? t('取消固定右侧栏') : t('固定右侧栏')"
          @click="$emit('toggleRightPinned')"
        >
          <svg viewBox="0 0 14 14" class="pin-icon pin-right">
            <rect x="1" y="2" width="5.5" height="10" rx="2" fill="none" stroke="currentColor" stroke-width="1.5" />
            <rect x="7.5" y="2" width="5.5" height="10" rx="2" fill="currentColor" />
          </svg>
        </button>
      </div>

      <!-- window controls -->
      <div class="window-controls">
        <button class="ctrl-btn" :title="t('最小化')" @click="onMinimize">
          <svg viewBox="0 0 14 14"><rect x="2" y="6" width="10" height="1.5" rx="0.75" /></svg>
        </button>
        <button
          ref="maximizeButton"
          class="ctrl-btn"
          :class="{ 'native-hover': maximizeNativeHover, 'native-active': maximizeNativeActive }"
          :title="t('最大化')"
          @click="onMaximize"
        >
          <svg viewBox="0 0 14 14"><rect x="2" y="2" width="10" height="10" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.5" /></svg>
        </button>
        <button class="ctrl-btn close" :title="t('关闭')" @click="onClose">
          <svg viewBox="0 0 14 14"><path d="M3.5 3.5l7 7M10.5 3.5l-7 7" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" /></svg>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { t } from '@/i18n/index.ts'

import { computed, ref, onMounted, onUnmounted, watch } from 'vue'

const props = defineProps<{
  leftPinned?: boolean
  rightPinned?: boolean
  modeLabel?: string
  modeTitle?: string
  canToggleMode?: boolean
  /** 小窗口（独屏）时显示在“Sunday”位置的当前会话标题。 */
  sessionTitle?: string
  showInPreview?: boolean
  hideOnMobile?: boolean
}>()

const emit = defineEmits<{
  toggleLeftPinned: []
  toggleRightPinned: []
  cycleMode: []
}>()

type TauriInternals = {
  invoke?: (command: string, args?: Record<string, unknown>) => Promise<unknown>
}

const tauriWindow = typeof window === 'undefined'
  ? null
  : window as Window & { __TAURI_INTERNALS__?: TauriInternals }
const isTauri = ref(Boolean(tauriWindow?.__TAURI_INTERNALS__?.invoke))
const shouldDisplayTitleBar = computed(() => !props.hideOnMobile && (isTauri.value || props.showInPreview === true))
const maximizeButton = ref<HTMLButtonElement | null>(null)
const maximizeNativeHover = ref(false)
const maximizeNativeActive = ref(false)
let tauriInvoke: ((cmd: string, args?: Record<string, unknown>) => Promise<any>) | null = null
let maximizeBoundsFrame: number | null = null

function syncMaximizeButtonBounds(): void {
  if (!tauriInvoke || !maximizeButton.value) return
  const bounds = maximizeButton.value.getBoundingClientRect()
  void tauriInvoke('set_maximize_button_bounds', {
    x: bounds.x,
    top: bounds.y,
    width: bounds.width,
    height: bounds.height,
  }).catch(() => undefined)
}

function scheduleMaximizeButtonBoundsSync(): void {
  if (maximizeBoundsFrame !== null) cancelAnimationFrame(maximizeBoundsFrame)
  maximizeBoundsFrame = requestAnimationFrame(() => {
    maximizeBoundsFrame = null
    syncMaximizeButtonBounds()
  })
}

function handleMaximizeNativeHover(event: Event): void {
  maximizeNativeHover.value = Boolean((event as CustomEvent<boolean>).detail)
}

function handleMaximizeNativePress(event: Event): void {
  maximizeNativeActive.value = Boolean((event as CustomEvent<boolean>).detail)
}

function syncTitlebarOffset(): void {
  // user:“把布局规则全部都做成变量”+(标题栏只登记原生高度，
  //  --titlebar-offset 由 variables.css 统一推导，编辑器布局变量才能覆盖)
  if (shouldDisplayTitleBar.value) {
    document.documentElement.style.setProperty('--titlebar-native-height', '36px')
  } else {
    document.documentElement.style.removeProperty('--titlebar-native-height')
  }
}

watch(shouldDisplayTitleBar, syncTitlebarOffset)

onMounted(() => {
  const tauri = tauriWindow?.__TAURI_INTERNALS__
  if (tauri && tauri.invoke) {
    isTauri.value = true
    const invoke = tauri.invoke
    tauriInvoke = (cmd: string, args?: Record<string, unknown>) => invoke(cmd, args)
    scheduleMaximizeButtonBoundsSync()
  }
  syncTitlebarOffset()
  window.addEventListener('resize', scheduleMaximizeButtonBoundsSync)
  window.addEventListener('lamtools:maximize-hover', handleMaximizeNativeHover)
  window.addEventListener('lamtools:maximize-press', handleMaximizeNativePress)
})

function onMinimize() { tauriInvoke?.('minimize_window') }
function onMaximize() { tauriInvoke?.('toggle_maximize_window') }
function onClose() { tauriInvoke?.('close_window') }

onUnmounted(() => {
  if (maximizeBoundsFrame !== null) cancelAnimationFrame(maximizeBoundsFrame)
  document.documentElement.style.removeProperty('--titlebar-native-height')
  window.removeEventListener('resize', scheduleMaximizeButtonBoundsSync)
  window.removeEventListener('lamtools:maximize-hover', handleMaximizeNativeHover)
  window.removeEventListener('lamtools:maximize-press', handleMaximizeNativePress)
})
</script>

<style scoped>
.titlebar {
  position: fixed;
  inset: 0 0 auto 0;
  z-index: var(--z-toast, 90);
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 36px;
  padding: 0 8px;
  background: transparent;
  user-select: none;
}

.brand {
  display: inline-flex;
  align-items: baseline;
  gap: var(--space-2);
  color: color-mix(in srgb, var(--theme-backdrop-text, #f2efeb) 76%, transparent);
  line-height: 22px;   /* match .mode-toggle height → shared vertical center */
  white-space: nowrap;
}

.brand-name {
  color: var(--theme-backdrop-text, #f2efeb);
  font-size: 13px;
  font-weight: 680;
  letter-spacing: .01em;
}

/* 会话标题默认不占位；窄窗口下顶替 Sunday 品牌名。 */
.brand-session-name {
  display: none;
  min-width: 0;
  max-width: 42vw;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--theme-backdrop-text, #f2efeb);
  font-size: 13px;
  font-weight: 680;
  letter-spacing: .01em;
}

@media (max-width: 820px) {
  .brand--session .brand-name { display: none; }
  .brand-session-name { display: inline-block; }
}

.titlebar-left {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: var(--space-2);
}

.titlebar-workflow-tabs {
  position: absolute;
  top: 0;
  right: max(
    calc(var(--titlebar-main-right, 18px) + var(--radius-xl) + var(--space-6)),
    190px
  );
  bottom: 0;
  left: max(
    calc(var(--titlebar-main-left, 18px) + var(--radius-xl) + var(--space-6)),
    190px
  );
  min-width: 0;
  pointer-events: none;
  transition:
    left var(--dur-morph) var(--ease-inout),
    right var(--dur-morph) var(--ease-inout);
}

/* ── Generic application mode toggle ── */
.mode-toggle {
  display: inline-grid;
  align-items: center;
  justify-items: start;
  padding: 0;
  height: 22px;
  border: none;
  background: transparent;
  cursor: pointer;
  -webkit-app-region: no-drag;
  app-region: no-drag;
  font-family: inherit;
  font-size: 12px;
  color: color-mix(in srgb, var(--theme-backdrop-text, #f2efeb) 62%, transparent);
}

.mode-toggle:disabled {
  cursor: default;
}

.mode-toggle:focus-visible {
  outline: 2px solid var(--blue, #79bcff);
  outline-offset: 1px;
}

.mode-word {
  grid-area: 1 / 1;
  white-space: nowrap;
  line-height: 22px;        /* match .brand → shared baseline */
  font-weight: 560;
  color: color-mix(in srgb, var(--theme-backdrop-text, #f2efeb) 58%, transparent);
}

.titlebar-right {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 4px;
  -webkit-app-region: no-drag;
  app-region: no-drag;
}

.titlebar-sidebar-controls {
  display: flex;
  align-items: center;
  gap: 4px;
}

/* ── Pin buttons ── */
.pin-btn {
  width: 26px;
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background 0.12s ease;
  color: color-mix(in srgb, var(--theme-backdrop-text, #f2efeb) 30%, transparent);
}

.pin-btn:hover {
  background: color-mix(in srgb, var(--theme-backdrop-text, #f2efeb) var(--alpha-hover), transparent);
  color: color-mix(in srgb, var(--theme-backdrop-text, #f2efeb) 62%, transparent);
}

.pin-btn.active {
  color: var(--green);
}

.pin-icon {
  width: 13px;
  height: 13px;
}

/* ── Window controls ── */
.window-controls {
  display: flex;
  align-items: center;
  gap: 2px;
}

.ctrl-btn {
  width: 32px;
  height: 26px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background 0.12s ease;
  color: color-mix(in srgb, var(--theme-backdrop-text, #f2efeb) 42%, transparent);
}

.ctrl-btn:hover,
.ctrl-btn.native-hover {
  background: color-mix(in srgb, var(--theme-backdrop-text, #f2efeb) var(--alpha-hover), transparent);
  color: color-mix(in srgb, var(--theme-backdrop-text, #f2efeb) 92%, transparent);
}

.ctrl-btn.native-active {
  background: color-mix(in srgb, var(--theme-backdrop-text, #f2efeb) var(--alpha-active), transparent);
  color: color-mix(in srgb, var(--theme-backdrop-text, #f2efeb) 92%, transparent);
}

.ctrl-btn.close:hover {
  background: var(--red);
  color: var(--theme-backdrop-text, #f2efeb);
}

.ctrl-btn svg {
  width: 13px;
  height: 13px;
  fill: currentColor;
}

@media (prefers-reduced-motion: reduce) {
  .titlebar-workflow-tabs {
    transition: none;
  }
}

@media (max-width: 640px) {
  .titlebar-sidebar-controls {
    display: none;
  }
}
</style>
