<template>
  <div class="cu-root" :class="{ 'cu-root--paused': paused }">
    <!-- user:“现在那个正在操作桌面的卡片太臃肿了…把它改成在紧贴屏幕上方只有一个很小的
         胶囊…用浏览器让我看一下效果”+(覆盖层本身就是整块屏幕，胶囊和 2px 流光都由
         共享的胶囊组件画在最外沿。) -->
    <ComputerUseCapsule
      ref="capsuleRef"
      :label="paused ? '已暂停操作' : '正在控制电脑'"
      :paused="paused"
      @stop="stop"
    />

    <!-- user:“给 Agent 一套鼠标样式，渐变彩填充加 2px 纯白边线”+
         (这是 Agent 自己的光标，不跟随真实鼠标，只标出它下一步要动的位置。) -->
    <ComputerUseCursor v-if="cursorPoint" :x="cursorPoint[0]" :y="cursorPoint[1]" />
  </div>
</template>

<script setup lang="ts">
/**
 * user:“覆盖层说明 Sunday 正在操作你的电脑，esc 或点击此处以停止”+
 * (Esc 由 Rust 侧全局检测；这里只负责离开请求、Agent 光标和点击区域上报)。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import ComputerUseCapsule from './ComputerUseCapsule.vue'
import ComputerUseCursor from './ComputerUseCursor.vue'

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
const capsuleRef = ref<InstanceType<typeof ComputerUseCapsule> | null>(null)
let timer: ReturnType<typeof setInterval> | null = null
let base: string | null = null
let disposed = false

const paused = computed(() => status.value?.state === 'paused')

const cursor = computed<[number, number] | null>(() => {
  const point = status.value?.cursor
  if (!point || point.length !== 2) return null
  return point
})

/** 后端给的是物理像素，转成覆盖层里的 CSS 坐标。 */
const cursorPoint = computed<[number, number] | null>(() => {
  const point = cursor.value
  if (!point) return null
  const ratio = window.devicePixelRatio || 1
  return [point[0] / ratio, point[1] / ratio]
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
    await reportCapsuleRect()
  } catch {
    // 后端还没起来或正在重启，保持当前画面。
  }
}

/**
 * 把胶囊的实际位置报给 Rust：只有这块矩形吃鼠标，屏幕其余部分继续穿透。
 * 胶囊贴在上沿正中，窗口尺寸或缩放变化时也要重新量。
 */
async function reportCapsuleRect(): Promise<void> {
  const element = capsuleRef.value?.barEl
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

// user:“结束并非结束回合，而是返回一个用户结束了你的 computer use”+
// (这里只发结束请求并收掉覆盖层，回合怎么走由后端把结果交还给 Agent 决定。)
async function stop(): Promise<void> {
  try {
    const origin = await resolveBase()
    await fetch(`${origin}/api/core/computer-use/control`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'stop', reason: '用户点了胶囊上的结束' }),
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

function onResize(): void {
  void reportCapsuleRect()
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
    await reportCapsuleRect()
    window.addEventListener('resize', onResize)
    timer = setInterval(() => void poll(), POLL_MS)
  })()
})

onBeforeUnmount(() => {
  disposed = true
  window.removeEventListener('resize', onResize)
  if (timer !== null) clearInterval(timer)
})
</script>

<style scoped>
.cu-root {
  position: fixed;
  inset: 0;
  pointer-events: none;
  overflow: hidden;
  /* user:“同角度，转起来”+(流光角度只在这里转一次，标签、胶囊、光标都继承同一个值。) */
  animation: cu-angle-flow 6.5s linear infinite;
}

.cu-root--paused {
  animation-play-state: paused;
}

@keyframes cu-angle-flow {
  to {
    --cu-angle: 360deg;
  }
}


</style>
