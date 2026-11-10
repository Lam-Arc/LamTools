<template>
  <div class="cu-root" :class="{ 'cu-root--paused': paused }">
    <!-- user:“覆盖层做成一个 4px 的有流动感的黯彩边框以表明此处被操作中”+
         (边框只画在最外层，不挡内容；任务暂停时减速并变暗。) -->
    <div class="cu-frame" aria-hidden="true" />

    <button ref="tipRef" type="button" class="cu-tip" @click="stop">
      <span class="cu-tip-dot" aria-hidden="true" />
      <span class="cu-tip-text">Sunday 正在操作你的电脑，esc 或点击此处以停止</span>
      <span class="cu-tip-count">{{ steps }}<span class="cu-tip-total">/{{ maxSteps }}</span></span>
    </button>

    <!-- user:“给 Agent 一套鼠标样式，渐变彩填充加 2px 纯白边线”+
         (这是 Agent 自己的光标，不跟随真实鼠标，只标出它下一步要动的位置。) -->
    <div v-if="cursor" class="cu-cursor" :style="cursorStyle" aria-hidden="true">
      <span class="cu-cursor-halo" />
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * user:“覆盖层说明 Sunday 正在操作你的电脑，esc 或点击此处以停止”+
 * (Esc 由 Rust 侧全局检测，这里只负责提示条点击和状态展示)。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

interface OverlayStatus {
  state?: string
  goal?: string
  steps?: number
  max_steps?: number
  cursor?: [number, number] | null
  pause_reason?: string
}

const POLL_MS = 900
const status = ref<OverlayStatus | null>(null)
const tipRef = ref<HTMLButtonElement | null>(null)
let timer: ReturnType<typeof setInterval> | null = null
let base: string | null = null
let disposed = false

const paused = computed(() => status.value?.state === 'paused')
const steps = computed(() => status.value?.steps ?? 0)
const maxSteps = computed(() => status.value?.max_steps ?? 0)

const cursor = computed<[number, number] | null>(() => {
  const point = status.value?.cursor
  if (!point || point.length !== 2) return null
  return point
})

const cursorStyle = computed(() => {
  const point = cursor.value
  if (!point) return {}
  const ratio = window.devicePixelRatio || 1
  return {
    left: `${point[0] / ratio}px`,
    top: `${point[1] / ratio}px`,
  }
})

async function tauriInvoke<T>(command: string, args?: Record<string, unknown>): Promise<T> {
  const module = await import('@tauri-apps/api/core')
  return await module.invoke<T>(command, args)
}

async function resolveBase(): Promise<string> {
  if (base !== null) return base
  try {
    base = await tauriInvoke<string>('get_api_base')
  } catch {
    base = ''
  }
  return base
}

async function poll(): Promise<void> {
  if (disposed) return
  try {
    const origin = await resolveBase()
    const response = await fetch(`${origin}/api/core/computer-use/status`)
    if (!response.ok) return
    const data = (await response.json()) as { active?: boolean; session?: OverlayStatus | null }
    if (!data.active || !data.session) {
      // 任务结束或后端重启：覆盖层没有继续存在的理由。
      await closeOverlay()
      return
    }
    status.value = data.session
    reportTipRect()
  } catch {
    // 后端还没起来或正在重启，保持当前画面。
  }
}

async function reportTipRect(): Promise<void> {
  const element = tipRef.value
  if (!element) return
  const box = element.getBoundingClientRect()
  const ratio = window.devicePixelRatio || 1
  const rect: [number, number, number, number] = [
    box.left * ratio,
    box.top * ratio,
    box.width * ratio,
    box.height * ratio,
  ]
  try {
    await tauriInvoke('computer_use_overlay_set_rects', { rects: [rect] })
  } catch {
    // 覆盖层窗口还没就绪时忽略。
  }
}

async function stop(): Promise<void> {
  try {
    const origin = await resolveBase()
    await fetch(`${origin}/api/core/computer-use/control`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'stop', reason: '用户点击覆盖层停止' }),
    })
  } finally {
    await closeOverlay()
  }
}

async function closeOverlay(): Promise<void> {
  disposed = true
  if (timer !== null) clearInterval(timer)
  try {
    await tauriInvoke('computer_use_overlay_close')
  } catch {
    // 窗口已经关掉时不用再报。
  }
}

onMounted(() => {
  void (async () => {
    await resolveBase()
    await poll()
    try {
      await tauriInvoke('computer_use_overlay_ready')
    } catch {
      // 页面先渲染后显示，失败就等下一轮轮询。
    }
    reportTipRect()
    timer = setInterval(() => void poll(), POLL_MS)
  })()
})

onBeforeUnmount(() => {
  disposed = true
  if (timer !== null) clearInterval(timer)
})
</script>

<style scoped>
.cu-root {
  position: fixed;
  inset: 0;
  pointer-events: none;
  overflow: hidden;
}

/* 4px 流动黯彩边框：mask 掉中间，只留最外一圈。 */
@property --cu-angle {
  syntax: '<angle>';
  initial-value: 0deg;
  inherits: false;
}

.cu-frame {
  position: fixed;
  inset: 0;
  padding: 4px;
  background: conic-gradient(
    from var(--cu-angle),
    #6b5aa6,
    #2f7a72,
    #8a4f63,
    #4f5f96,
    #6b5aa6
  );
  opacity: 0.72;
  -webkit-mask:
    linear-gradient(#000 0 0) content-box,
    linear-gradient(#000 0 0);
  -webkit-mask-composite: xor;
  mask:
    linear-gradient(#000 0 0) content-box,
    linear-gradient(#000 0 0);
  mask-composite: exclude;
  animation: cu-frame-flow 7s linear infinite;
  filter: saturate(0.85) brightness(0.92);
}

.cu-root--paused .cu-frame {
  opacity: 0.4;
  animation-duration: 18s;
}

.cu-tip {
  position: fixed;
  top: 16px;
  left: 50%;
  transform: translateX(-50%);
  display: inline-flex;
  align-items: center;
  gap: 9px;
  padding: 9px 15px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.14);
  background: rgba(18, 18, 22, 0.82);
  backdrop-filter: blur(16px);
  color: #f2f2f4;
  font-size: 12.5px;
  line-height: 1.2;
  cursor: pointer;
  pointer-events: auto;
  transition: background 0.16s ease, border-color 0.16s ease;
}

.cu-tip:hover {
  background: rgba(30, 30, 36, 0.9);
  border-color: rgba(255, 255, 255, 0.24);
}

.cu-tip-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #58c07a;
  box-shadow: 0 0 0 0 rgba(88, 192, 122, 0.55);
  animation: cu-tip-pulse 1.8s ease-out infinite;
  flex: none;
}

.cu-root--paused .cu-tip-dot {
  background: #d0a24a;
  animation: none;
}

.cu-tip-text {
  white-space: nowrap;
}

.cu-tip-count {
  margin-left: 2px;
  font-variant-numeric: tabular-nums;
  color: rgba(242, 242, 244, 0.62);
}

.cu-tip-total {
  color: rgba(242, 242, 244, 0.36);
}

/* Agent 光标：渐变彩填充 + 2px 纯白边线。 */
.cu-cursor {
  position: fixed;
  width: 20px;
  height: 20px;
  margin: -10px 0 0 -10px;
  border-radius: 50%;
  border: 2px solid #ffffff;
  background: conic-gradient(from 20deg, #ff7ab6, #7ad7ff, #b6ff7a, #ffd27a, #ff7ab6);
  box-shadow: 0 0 14px rgba(255, 255, 255, 0.35), 0 2px 8px rgba(0, 0, 0, 0.35);
  transition: left 0.16s ease-out, top 0.16s ease-out;
  pointer-events: none;
}

.cu-cursor-halo {
  position: absolute;
  inset: -7px;
  border-radius: 50%;
  border: 1px solid rgba(255, 255, 255, 0.28);
  animation: cu-cursor-halo 1.6s ease-out infinite;
}

@keyframes cu-frame-flow {
  to {
    --cu-angle: 360deg;
  }
}

@keyframes cu-tip-pulse {
  0% {
    box-shadow: 0 0 0 0 rgba(88, 192, 122, 0.55);
  }
  70% {
    box-shadow: 0 0 0 7px transparent;
  }
  100% {
    box-shadow: 0 0 0 0 transparent;
  }
}

@keyframes cu-cursor-halo {
  0% {
    transform: scale(0.9);
    opacity: 0.7;
  }
  70% {
    transform: scale(1.25);
    opacity: 0;
  }
  100% {
    transform: scale(1.25);
    opacity: 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .cu-frame,
  .cu-tip-dot,
  .cu-cursor-halo {
    animation: none;
  }
  .cu-cursor {
    transition: none;
  }
}
</style>
