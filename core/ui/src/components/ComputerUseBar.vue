<template>
  <Transition name="cu-bar">
    <div v-if="visible" class="cu-layer">
      <!-- user:“胶囊与屏幕边框使用连续的呼吸感暗彩流光边框 2px”+
           (整圈窗口边框也画流光，胶囊坐在上沿，两边连成一条线。) -->
      <div class="cu-screen-frame" aria-hidden="true" />

      <div class="cu-bar-slot">
        <div class="cu-bar" :class="{ 'cu-bar--paused': paused }" role="status">
          <!-- user:“既有缝也有颜色跳变”+(胶囊边线从 y=0 起画接住屏幕顶边，
               渐变与屏幕边框共用同一个视口色场，交界处不许断、不许跳色。) -->
          <span class="cu-bar-ring" aria-hidden="true" />
          <span class="cu-bar-text">{{ paused ? '已暂停操作' : '正在控制电脑' }}</span>
          <button
            type="button"
            class="cu-bar-btn"
            :title="paused ? '继续' : '暂停'"
            :aria-label="paused ? '继续' : '暂停'"
            @click="togglePause"
          >
            <svg v-if="paused" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M8 5.5v13l11-6.5z" fill="currentColor" />
            </svg>
            <svg v-else viewBox="0 0 24 24" aria-hidden="true">
              <rect x="7" y="5" width="3.6" height="14" rx="1.2" fill="currentColor" />
              <rect x="13.4" y="5" width="3.6" height="14" rx="1.2" fill="currentColor" />
            </svg>
          </button>
          <button type="button" class="cu-bar-btn" title="结束" aria-label="结束" @click="stop">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path
                d="M6.6 6.6l10.8 10.8M17.4 6.6L6.6 17.4"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                fill="none"
              />
            </svg>
          </button>
        </div>
      </div>
    </div>
  </Transition>
</template>

<script setup lang="ts">
/**
 * user:“现在那个正在操作桌面的卡片太臃肿了，也太挡视野了，把它改成在紧贴屏幕上方
 * 只有一个很小的胶囊，上方直角与屏幕上沿贴合，胶囊与屏幕边框使用连续的呼吸感暗彩
 * 流光边框 2px，胶囊上沿与屏幕边框重合处不需要流光边框，黑底白字「正在控制电脑」
 * 和一个暂停图标和一个 x 图标”+(状态条缩成顶部小胶囊；窗口四边也画同一条流光，
 * 胶囊上沿压在边框上，重合处不再重复画线)。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

interface ComputerUseSession {
  state?: string
  goal?: string
}

const props = defineProps<{
  /** 预览页用：给了就不轮询后端，直接按这个状态画。 */
  previewState?: 'running' | 'paused'
}>()

const POLL_INTERVAL_MS = 1500
const status = ref<ComputerUseSession | null>(null)
let timer: ReturnType<typeof setInterval> | null = null
let base: string | null = null
let disposed = false
let overlayOpen = false

const state = computed(() => props.previewState || status.value?.state || 'idle')
const visible = computed(() => state.value === 'running' || state.value === 'paused')
const paused = computed(() => state.value === 'paused')

async function resolveBase(): Promise<string> {
  if (base !== null) return base
  const internals = (globalThis as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__
  if (!internals) {
    base = ''
    return base
  }
  try {
    const { invoke } = await import('@tauri-apps/api/core')
    base = await invoke<string>('get_api_base')
  } catch {
    base = ''
  }
  return base
}

async function poll(): Promise<void> {
  if (disposed || props.previewState) return
  try {
    const origin = await resolveBase()
    const response = await fetch(`${origin}/api/core/computer-use/status`)
    if (!response.ok) return
    const data = (await response.json()) as { active?: boolean; session?: ComputerUseSession | null }
    status.value = data?.active ? data.session || null : null
    await syncOverlay(Boolean(data?.active))
  } catch {
    // 后端还没起来或正在重启，保持上一次状态。
  }
}

async function syncOverlay(active: boolean): Promise<void> {
  if (active === overlayOpen) return
  try {
    if (active) {
      await invokeTauri('computer_use_overlay_open')
    } else {
      await invokeTauri('computer_use_overlay_close')
    }
    overlayOpen = active
  } catch {
    // 桌面端不支持时静默跳过。
  }
}

async function invokeTauri(command: string, args?: Record<string, unknown>): Promise<unknown> {
  const internals = (globalThis as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__
  if (!internals) return null
  const { invoke } = await import('@tauri-apps/api/core')
  return await invoke(command, args)
}

async function control(action: 'pause' | 'resume' | 'stop'): Promise<void> {
  if (props.previewState) {
    if (action === 'pause') status.value = { state: 'paused' }
    if (action === 'resume') status.value = { state: 'running' }
    return
  }
  try {
    const origin = await resolveBase()
    await fetch(`${origin}/api/core/computer-use/control`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action }),
    })
  } finally {
    await poll()
  }
}

function togglePause(): void {
  void control(paused.value ? 'resume' : 'pause')
}

function stop(): void {
  void control('stop')
}

onMounted(() => {
  if (props.previewState) return
  void poll()
  timer = setInterval(() => void poll(), POLL_INTERVAL_MS)
})

onBeforeUnmount(() => {
  disposed = true
  if (timer !== null) clearInterval(timer)
})
</script>

<style scoped>
.cu-layer {
  position: fixed;
  inset: 0;
  z-index: 59;
  pointer-events: none;
  /* 流光角度只在共同父层跑，边框和胶囊继承同一个值，两边相位永远一致。 */
  animation: cu-bar-flow 6.5s linear infinite;
}

/* 整圈窗口边框：2px 流光，和胶囊共用同一套颜色与节奏。 */
.cu-screen-frame {
  position: absolute;
  inset: 0;
  padding: 2px;
  background: conic-gradient(
    from var(--cu-bar-angle),
    #7b62c9,
    #2f8f84,
    #a4566d,
    #4f68b8,
    #7b62c9
  );
  -webkit-mask:
    linear-gradient(#000 0 0) content-box,
    linear-gradient(#000 0 0);
  -webkit-mask-composite: xor;
  mask:
    linear-gradient(#000 0 0) content-box,
    linear-gradient(#000 0 0);
  mask-composite: exclude;
  animation: cu-bar-breathe 2.8s ease-in-out infinite;
  pointer-events: none;
}

/* 胶囊横向居中槽位：不上 transform，避免 fixed 背景被降级成局部坐标系。 */
.cu-bar-slot {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  display: flex;
  justify-content: center;
  pointer-events: none;
}

/* 胶囊压在顶部边框上：黑底盖住穿过去的那条线，只画左右和下。 */
.cu-bar {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 30px;
  padding: 0 6px 0 10px;
  border-radius: 0 0 12px 12px;
  background: #08080a;
  color: #ffffff;
  font-size: 12px;
  line-height: 1;
  letter-spacing: 0.01em;
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.35);
  pointer-events: auto;
  user-select: none;
}

/* 胶囊边线：左右从 y=0 起画，正好接住屏幕顶边；上沿不画线。
   background-attachment: fixed 让渐变按视口坐标取色，圆心与屏幕边框同源，
   交界处连续同色。 */
.cu-bar-ring {
  position: absolute;
  inset: 0;
  border: 2px solid transparent;
  border-top: 0;
  border-radius: inherit;
  background: conic-gradient(
      from var(--cu-bar-angle),
      #7b62c9,
      #2f8f84,
      #a4566d,
      #4f68b8,
      #7b62c9
    )
    border-box;
  background-attachment: fixed;
  -webkit-mask:
    linear-gradient(#000 0 0) padding-box,
    linear-gradient(#000 0 0);
  -webkit-mask-composite: xor;
  mask:
    linear-gradient(#000 0 0) padding-box,
    linear-gradient(#000 0 0);
  mask-composite: exclude;
  animation: cu-bar-breathe 2.8s ease-in-out infinite;
  pointer-events: none;
}

.cu-layer:has(.cu-bar--paused) {
  animation-play-state: paused;
}

.cu-layer:has(.cu-bar--paused) .cu-screen-frame,
.cu-bar--paused .cu-bar-ring {
  animation-play-state: paused;
  opacity: 0.45;
}

.cu-bar-text {
  white-space: nowrap;
}

.cu-bar-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  padding: 0;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: rgba(255, 255, 255, 0.82);
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}

.cu-bar-btn svg {
  width: 13px;
  height: 13px;
  display: block;
}

.cu-bar-btn:hover {
  background: rgba(255, 255, 255, 0.12);
  color: #ffffff;
}

.cu-bar-btn:last-child:hover {
  background: rgba(208, 90, 90, 0.24);
  color: #ffffff;
}

.cu-bar-enter-active,
.cu-bar-leave-active {
  transition: opacity 0.16s ease;
}

.cu-bar-enter-from,
.cu-bar-leave-to {
  opacity: 0;
}

@property --cu-bar-angle {
  syntax: '<angle>';
  initial-value: 0deg;
  /* 继承：父层跑一次流转，边框和胶囊拿到的角度永远同步，交界处不会一快一慢。 */
  inherits: true;
}

@keyframes cu-bar-flow {
  to {
    --cu-bar-angle: 360deg;
  }
}

@keyframes cu-bar-breathe {
  0%,
  100% {
    opacity: 0.72;
  }
  50% {
    opacity: 1;
  }
}

@media (prefers-reduced-motion: reduce) {
  .cu-layer,
  .cu-screen-frame,
  .cu-bar-ring {
    animation: none;
  }
}
</style>
