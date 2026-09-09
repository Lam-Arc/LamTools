<template>
  <div v-if="isTauri" class="titlebar" data-tauri-drag-region>
    <div class="titlebar-left">
      <span class="brand">Core</span>

      <!-- mode toggle: shows the current application mode -->
      <button
        class="mode-toggle"
        :title="props.modeTitle"
        :disabled="!props.canToggleMode"
        @click="$emit('cycleMode')"
      >
        <span class="mode-word mode-current">{{ props.modeLabel }}</span>
      </button>
    </div>

    <div class="titlebar-right">
      <!-- sidebar pin buttons -->
      <button
        class="pin-btn"
        :class="{ active: props.leftPinned }"
        :title="props.leftPinned ? '取消固定左侧栏' : '固定左侧栏'"
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
        :title="props.rightPinned ? '取消固定右侧栏' : '固定右侧栏'"
        @click="$emit('toggleRightPinned')"
      >
        <svg viewBox="0 0 14 14" class="pin-icon pin-right">
          <rect x="1" y="2" width="5.5" height="10" rx="2" fill="none" stroke="currentColor" stroke-width="1.5" />
          <rect x="7.5" y="2" width="5.5" height="10" rx="2" fill="currentColor" />
        </svg>
      </button>

      <div ref="mobilePairingAnchor" class="mobile-pairing-anchor">
        <button
          class="pin-btn mobile-pairing-trigger"
          :class="{ active: mobilePairingOpen, ready: Boolean(props.mobilePairingCode) }"
          type="button"
          title="账号与设备"
          aria-label="打开账号与设备"
          :aria-expanded="mobilePairingOpen ? 'true' : 'false'"
          @click.stop="toggleMobilePairing"
        >
          <Smartphone :size="14" :stroke-width="1.8" aria-hidden="true" />
          <span v-if="props.mobilePairingCode" class="mobile-pairing-ready-dot" aria-hidden="true" />
        </button>

        <div
          v-if="mobilePairingOpen"
          class="mobile-pairing-card"
          role="dialog"
          aria-label="手机配对"
          @click.stop
        >
          <div class="mobile-pairing-card-header">
            <div>
              <strong>账号与设备</strong>
              <small v-if="accountStatus">{{ accountStatus.username }} · 已登录</small>
              <small v-else>尚未登录服务器账号</small>
            </div>
            <button class="mobile-pairing-close" type="button" aria-label="关闭配对码" @click="mobilePairingOpen = false">×</button>
          </div>

          <section v-if="accountStatus" class="mobile-account-devices" aria-label="归属此账号的设备">
            <div v-for="device in accountDevices" :key="device.nodeId" class="mobile-account-device">
              <span><strong>{{ device.label }}</strong><small>{{ device.detail }}</small></span>
              <span class="mobile-account-device-state" :class="{ offline: !device.online }"><i aria-hidden="true" />{{ device.online ? '在线' : '离线' }}</span>
            </div>
            <p v-if="!accountDevices?.length" class="mobile-pairing-empty">这个账号还没有已登记设备。</p>
          </section>

          <details class="mobile-account-more">
            <summary>更多</summary>
            <div v-if="props.mobilePairingCode" class="mobile-pairing-code-block">
              <span>当前配对码</span>
              <strong class="mobile-pairing-code" aria-label="当前六位配对码">{{ props.mobilePairingCode }}</strong>
              <small v-if="mobilePairingExpiresLabel">有效期至 {{ mobilePairingExpiresLabel }}</small>
              <button class="text-btn mobile-pairing-copy" type="button" @click="copyPairingCode">{{ copyLabel }}</button>
            </div>
            <p v-else-if="props.mobilePairingLoading" class="mobile-pairing-empty" role="status">正在生成配对码…</p>
            <div v-else class="mobile-pairing-empty">
              <p>尚未生成配对码。</p>
              <button class="text-btn mobile-pairing-action" type="button" @click="$emit('mobilePairingCreate')">生成配对码</button>
            </div>
          </details>
        </div>
      </div>

      <!-- window controls -->
      <div class="window-controls">
        <button class="ctrl-btn" title="最小化" @click="onMinimize">
          <svg viewBox="0 0 14 14"><rect x="2" y="6" width="10" height="1.5" rx="0.75" /></svg>
        </button>
        <button class="ctrl-btn" title="最大化" @click="onMaximize">
          <svg viewBox="0 0 14 14"><rect x="2" y="2" width="10" height="10" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.5" /></svg>
        </button>
        <button class="ctrl-btn close" title="关闭" @click="onClose">
          <svg viewBox="0 0 14 14"><path d="M3.5 3.5l7 7M10.5 3.5l-7 7" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" /></svg>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { Smartphone } from 'lucide-vue-next'
import type { MobileControlAccountDevice, MobileControlAccountStatus } from './MobileControlPanel.vue'

const props = defineProps<{
  leftPinned?: boolean
  rightPinned?: boolean
  modeLabel?: string
  modeTitle?: string
  canToggleMode?: boolean
  mobilePairingCode?: string | null
  mobilePairingExpiresAtMs?: number | null
  mobilePairingLoading?: boolean
  accountStatus?: MobileControlAccountStatus | null
  accountDevices?: MobileControlAccountDevice[]
}>()

const emit = defineEmits<{
  toggleLeftPinned: []
  toggleRightPinned: []
  cycleMode: []
  mobilePairingCreate: []
}>()

type TauriInternals = {
  invoke?: (command: string) => Promise<unknown>
}

const tauriWindow = typeof window === 'undefined'
  ? null
  : window as Window & { __TAURI_INTERNALS__?: TauriInternals }
const isTauri = ref(Boolean(tauriWindow?.__TAURI_INTERNALS__?.invoke))
const mobilePairingOpen = ref(false)
const mobilePairingAnchor = ref<HTMLElement | null>(null)
const copyLabel = ref('复制数字码')
let tauriInvoke: ((cmd: string) => Promise<any>) | null = null

const mobilePairingExpiresLabel = computed(() => {
  const expiresAt = props.mobilePairingExpiresAtMs
  return expiresAt
    ? new Date(expiresAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : ''
})

function toggleMobilePairing(): void {
  mobilePairingOpen.value = !mobilePairingOpen.value
}

async function copyPairingCode(): Promise<void> {
  if (!props.mobilePairingCode || !navigator.clipboard) return
  try {
    await navigator.clipboard.writeText(props.mobilePairingCode)
    copyLabel.value = '已复制'
    window.setTimeout(() => { copyLabel.value = '复制数字码' }, 1600)
  } catch {
    copyLabel.value = '复制失败'
  }
}

function handleDocumentPointerDown(event: PointerEvent): void {
  const target = event.target
  if (target instanceof Node && mobilePairingAnchor.value?.contains(target)) return
  mobilePairingOpen.value = false
}

function handleDocumentKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') mobilePairingOpen.value = false
}

onMounted(() => {
  const tauri = tauriWindow?.__TAURI_INTERNALS__
  if (tauri && tauri.invoke) {
    isTauri.value = true
    const invoke = tauri.invoke
    tauriInvoke = (cmd: string) => invoke(cmd)
    document.documentElement.style.setProperty('--titlebar-offset', '36px')
  }
  document.addEventListener('pointerdown', handleDocumentPointerDown)
  document.addEventListener('keydown', handleDocumentKeydown)
})

function onMinimize() { tauriInvoke?.('minimize_window') }
function onMaximize() { tauriInvoke?.('toggle_maximize_window') }
function onClose() { tauriInvoke?.('close_window') }

onUnmounted(() => {
  document.documentElement.style.removeProperty('--titlebar-offset')
  document.removeEventListener('pointerdown', handleDocumentPointerDown)
  document.removeEventListener('keydown', handleDocumentKeydown)
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
  font-size: 15px;
  font-weight: 600;
  color: color-mix(in srgb, var(--theme-backdrop-text, #f2efeb) 62%, transparent);
  letter-spacing: 0.3px;
  padding-left: 4px;
  line-height: 22px;   /* match .mode-toggle height → shared vertical center */
}

.titlebar-left {
  display: flex;
  align-items: center;
  gap: 0;   /* spacing lives in .mode-toggle's left padding → ~one space */
}

/* ── Generic application mode toggle ── */
.mode-toggle {
  display: inline-grid;
  align-items: center;
  justify-items: start;
  padding: 0 2px;
  height: 22px;
  border: none;
  background: transparent;
  cursor: pointer;
  -webkit-app-region: no-drag;
  app-region: no-drag;
  font-family: inherit;
  font-size: 15px;
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
  font-weight: 700;         /* 加粗 */
  color: color-mix(in srgb, var(--theme-backdrop-text, #f2efeb) 78%, transparent);
}

.titlebar-right {
  display: flex;
  align-items: center;
  gap: 4px;
  -webkit-app-region: no-drag;
  app-region: no-drag;
}

.mobile-pairing-anchor {
  position: relative;
  -webkit-app-region: no-drag;
  app-region: no-drag;
}

.mobile-pairing-trigger {
  position: relative;
}

.mobile-pairing-trigger.ready,
.mobile-pairing-trigger.active {
  color: var(--blue);
}

.mobile-pairing-ready-dot {
  position: absolute;
  top: 2px;
  right: 3px;
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--blue);
}

.mobile-pairing-card {
  --text: var(--theme-main-text);
  position: absolute;
  top: calc(100% + var(--space-2));
  right: 0;
  z-index: var(--z-popover);
  display: grid;
  gap: var(--space-3);
  width: 280px;
  box-sizing: border-box;
  padding: var(--space-3);
  border: 1px solid var(--theme-main-border);
  border-radius: var(--radius);
  background: var(--theme-main-background);
  color: var(--text);
  box-shadow: var(--shadow-md);
  -webkit-app-region: no-drag;
  app-region: no-drag;
}

.mobile-pairing-card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-2);
}

.mobile-pairing-card-header > div {
  display: grid;
  gap: var(--space-1);
}

.mobile-pairing-card-header strong {
  font-size: 13px;
}

.mobile-pairing-card-header small,
.mobile-pairing-code-block > span,
.mobile-pairing-code-block > small,
.mobile-pairing-empty {
  color: color-mix(in srgb, var(--text) 62%, transparent);
  font-size: 11px;
  line-height: 1.5;
}

.mobile-pairing-close {
  width: 24px;
  height: 24px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--text) 62%, transparent);
  font: inherit;
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
}

.mobile-pairing-close:hover {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  color: var(--text);
}

.mobile-pairing-code-block {
  display: grid;
  justify-items: center;
  gap: var(--space-1);
  padding: var(--space-2) 0;
}

.mobile-pairing-code {
  color: var(--blue);
  font-family: var(--font-mono);
  font-size: 28px;
  font-weight: 700;
  letter-spacing: .18em;
  line-height: 1.15;
  text-indent: .18em;
}

.mobile-pairing-copy,
.mobile-pairing-action {
  min-height: 28px;
  padding: 0 var(--space-2);
  color: color-mix(in srgb, var(--text) 72%, transparent);
}

.mobile-pairing-copy:hover,
.mobile-pairing-action:hover {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  color: var(--text);
}

.mobile-pairing-empty {
  display: grid;
  gap: var(--space-2);
  margin: 0;
}

.mobile-pairing-empty p {
  margin: 0;
}

.mobile-account-devices {
  display: grid;
  gap: var(--space-1);
  max-height: 180px;
  overflow-y: auto;
}

.mobile-account-device {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  min-height: 38px;
  padding: var(--space-1) var(--space-2);
}

.mobile-account-device > span:first-child {
  display: grid;
  min-width: 0;
  gap: var(--space-1);
}

.mobile-account-device strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
}

.mobile-account-device small {
  color: color-mix(in srgb, var(--text) 55%, transparent);
  font-size: 10px;
}

.mobile-account-device-state {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: var(--space-1);
  color: var(--green);
  font-size: 10px;
}

.mobile-account-device-state i {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: currentColor;
}

.mobile-account-device-state.offline {
  color: color-mix(in srgb, var(--text) 42%, transparent);
}

.mobile-account-more {
  padding-top: var(--space-2);
  border-top: 1px solid color-mix(in srgb, var(--text) 12%, transparent);
}

.mobile-account-more summary {
  color: color-mix(in srgb, var(--text) 62%, transparent);
  font-size: 11px;
  cursor: pointer;
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

.ctrl-btn:hover {
  background: color-mix(in srgb, var(--theme-backdrop-text, #f2efeb) var(--alpha-hover), transparent);
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
  .mobile-pairing-card,
  .mobile-pairing-trigger {
    transition: none;
  }
}
</style>
