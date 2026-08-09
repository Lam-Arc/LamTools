<template>
  <div v-if="isTauri" class="titlebar" data-tauri-drag-region>
    <div class="titlebar-left">
      <span class="brand">Core</span>

      <!-- mode toggle: shows the *current* mode, click to switch -->
      <button
        class="mode-toggle"
        :class="{ 'is-workflow': workflowMode }"
        :title="workflowMode ? '切换到 Agent 模式' : '切换到工作流模式'"
        @click="$emit('toggleWorkflowMode')"
      >
      <span class="mode-word mode-agent" :class="{ 'is-on': !workflowMode }">Agent</span>
      <span class="mode-word mode-workflow" :class="{ 'is-on': workflowMode }">Workflow</span>
      </button>
    </div>

    <div class="titlebar-right">
      <!-- sidebar pin buttons -->
      <button
        class="pin-btn"
        :class="{ active: leftPinned }"
        :title="leftPinned ? '取消固定左侧栏' : '固定左侧栏'"
        @click="$emit('toggleLeftPinned')"
      >
        <svg viewBox="0 0 14 14" class="pin-icon pin-left">
          <rect x="1" y="2" width="5.5" height="10" rx="2" fill="currentColor" />
          <rect x="7.5" y="2" width="5.5" height="10" rx="2" fill="none" stroke="currentColor" stroke-width="1.5" />
        </svg>
      </button>
      <button
        class="pin-btn"
        :class="{ active: rightPinned }"
        :title="rightPinned ? '取消固定右侧栏' : '固定右侧栏'"
        @click="$emit('toggleRightPinned')"
      >
        <svg viewBox="0 0 14 14" class="pin-icon pin-right">
          <rect x="1" y="2" width="5.5" height="10" rx="2" fill="none" stroke="currentColor" stroke-width="1.5" />
          <rect x="7.5" y="2" width="5.5" height="10" rx="2" fill="currentColor" />
        </svg>
      </button>

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
import { ref, onMounted, onUnmounted } from 'vue'

defineProps<{
  leftPinned?: boolean
  rightPinned?: boolean
  workflowMode?: boolean
}>()

defineEmits<{
  toggleLeftPinned: []
  toggleRightPinned: []
  toggleWorkflowMode: []
}>()

const isTauri = ref(false)
let tauriInvoke: ((cmd: string) => Promise<any>) | null = null

onMounted(() => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const tauri = (window as any).__TAURI_INTERNALS__
  if (tauri && tauri.invoke) {
    isTauri.value = true
    tauriInvoke = (cmd: string) => tauri.invoke(cmd)
    document.documentElement.style.setProperty('--titlebar-offset', '36px')
  }
})

function onMinimize() { tauriInvoke?.('minimize_window') }
function onMaximize() { tauriInvoke?.('toggle_maximize_window') }
function onClose() { tauriInvoke?.('close_window') }

onUnmounted(() => {
  document.documentElement.style.removeProperty('--titlebar-offset')
})
</script>

<style scoped>
.titlebar {
  position: fixed;
  inset: 0 0 auto 0;
  z-index: var(--z-toast);
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 36px;
  padding: 0 8px;
  background: var(--theme-titlebar-bg, #202020);
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

/* ── Mode toggle (agent ⇄ workflow) ── */
/* inline-grid so both words share one cell (overlap → cross-fade) and the
   button auto-sizes to the longer word. justify-items: start left-aligns both
   → the first letter stays put, the longer word just extends right. Same font
   family/size/color as .brand so it reads as a uniform "Core Agent" label. */
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

.mode-toggle:focus-visible {
  outline: 2px solid var(--blue, #79bcff);
  outline-offset: 1px;
}

.mode-word {
  grid-area: 1 / 1;
  white-space: nowrap;
  line-height: 22px;        /* match .brand → shared baseline */
  font-weight: 700;         /* 加粗 */
  opacity: 0;
  transform: scale(0.94);
  transform-origin: left center;  /* scales from the first letter */
  transition:
    opacity 0.28s ease,
    transform 0.28s ease,
    color 0.12s ease;
}

.mode-word.is-on {
  opacity: 1;
  transform: scale(1);
}

/* per-mode tint on the text itself (no background). Desaturated so the tint
   reads as a subtle wash rather than a bright color. 底色取标题栏文字色降饱和。 */
.mode-agent { color: color-mix(in srgb, var(--blue) 62%, color-mix(in srgb, var(--theme-backdrop-text, #f2efeb) 62%, transparent)); }    /* 淡蓝,降饱和 */
.mode-workflow { color: color-mix(in srgb, var(--orange) 62%, color-mix(in srgb, var(--theme-backdrop-text, #f2efeb) 62%, transparent)); } /* 淡橙,降饱和 */

/* hover brightens the visible word toward its lighter shade */
.mode-toggle:hover .mode-agent.is-on { color: color-mix(in srgb, var(--blue) 70%, color-mix(in srgb, var(--theme-backdrop-text, #f2efeb) 85%, transparent)); }
.mode-toggle:hover .mode-workflow.is-on { color: color-mix(in srgb, var(--orange) 70%, color-mix(in srgb, var(--theme-backdrop-text, #f2efeb) 85%, transparent)); }




.titlebar-right {
  display: flex;
  align-items: center;
  gap: 4px;
  -webkit-app-region: no-drag;
  app-region: no-drag;
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
</style>