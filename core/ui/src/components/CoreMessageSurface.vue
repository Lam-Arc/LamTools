<script setup lang="ts">
/**
 * user:“全部统一以这个为示例 可复用化，可调参数为胶囊/卡片,填充颜色,是否玻璃”
 * +(消息气泡的唯一外壳：形状、填充、玻璃三个参数；排布与尺寸仍由宿主类负责，
 *   surface=false 时只做一个普通容器，用于“无气泡正文”等不套材质的地方)。
 *
 * user:“这里的阴影为什么会有清晰边界？能够解决吗？”+
 * (backdrop-filter 会把投影一起纳入模糊层，纹理背景上就出现一块矩形硬边；
 *  所以投影留在外层 message-surface，模糊和填充放在内层 message-surface__body，
 *  两层分开后模糊层的边界不再包含投影)。
 *
 * user:“按对角线”+(玻璃边分界按元素宽高算角度：右上角 θ = atan2(w, h)，
 * 左下角是 180°+θ；用 ResizeObserver 把 θ 写进 --message-surface-edge-angle)。
 *
 * 材质配方在 styles/message-surface.css，这里只把 props 翻译成类名与 CSS 变量。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { messageSurfaceEdgeAngle } from '@/helpers/messageSurfaceAngle.ts'

const props = withDefaults(
  defineProps<{
    /** card=28px 圆角卡片；capsule=两端全圆的胶囊 */
    shape?: 'card' | 'capsule'
    /** 填充颜色：任意 CSS 颜色；留空用角色默认色（用户淡粉 / 助手淡蓝） */
    fill?: string
    /** 是否玻璃：开=毛玻璃，关=实色填充 */
    glass?: boolean
    /** 是否套材质；关闭时只渲染容器，不产生任何气泡外观 */
    surface?: boolean
    /** 角色默认色：不依赖外层类名，类名缺失或构建缓存过期时也不会退回灰色 */
    tone?: 'user' | 'assistant' | ''
  }>(),
  { shape: 'card', fill: '', glass: true, surface: true, tone: '' },
)

const toneColor = computed(() => {
  if (props.tone === 'user') return 'var(--message-bubble-user-color, #f2a3b7)'
  if (props.tone === 'assistant') return 'var(--message-bubble-assistant-color, #a7c6f5)'
  return ''
})

const surfaceStyle = computed(() => {
  const style: Record<string, string> = {}
  if (props.fill) style['--message-surface-fill'] = props.fill
  if (toneColor.value) style['--message-surface-color'] = toneColor.value
  return Object.keys(style).length > 0 ? style : undefined
})

const surfaceEl = ref<HTMLElement | null>(null)
let resizeObserver: ResizeObserver | null = null

function syncEdgeAngle(): void {
  const el = surfaceEl.value
  if (!el) return
  const { width, height } = el.getBoundingClientRect()
  const angle = messageSurfaceEdgeAngle(width, height)
  el.style.setProperty('--message-surface-edge-angle', `${angle.toFixed(2)}deg`)
}

onMounted(() => {
  if (!props.surface) return
  syncEdgeAngle()
  if (typeof ResizeObserver === 'undefined') return
  resizeObserver = new ResizeObserver(syncEdgeAngle)
  if (surfaceEl.value) resizeObserver.observe(surfaceEl.value)
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
})
</script>

<template>
  <div
    v-if="surface"
    ref="surfaceEl"
    class="message-surface"
    :class="[
      `message-surface--${shape}`,
      glass ? 'message-surface--glass' : 'message-surface--solid',
    ]"
    :style="surfaceStyle"
  >
    <div class="message-surface__body">
      <slot />
    </div>
  </div>
  <div v-else>
    <slot />
  </div>
</template>
