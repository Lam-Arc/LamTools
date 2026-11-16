<template>
  <div class="cu-capsule" :class="{ 'cu-capsule--paused': paused }">
    <!-- user:“现在那个正在操作桌面的卡片太臃肿了…把它改成在紧贴屏幕上方只有一个很小的
         胶囊，上方直角与屏幕上沿贴合，胶囊与屏幕边框使用连续的呼吸感暗彩流光边框 2px”+
         (整块屏幕四边画同一条 2px 流光，胶囊压在上沿正中，上沿不重复画线。) -->
    <!-- user:“内圆”+(外沿贴着屏幕四角保持直角，内侧收成圆弧，四角不是硬方框。) -->
    <div
      ref="frameEl"
      class="cu-screen-frame"
      :style="{ clipPath: frameClip, webkitClipPath: frameClip }"
      aria-hidden="true"
    />

    <!-- user:“我不是说这个胶囊放在屏幕的最上方，紧贴屏幕上面吗”+
         (胶囊锚在屏幕最上沿：top 0、左右居中、上边两角直角贴边。) -->
    <div class="cu-bar-slot">
      <div ref="barEl" class="cu-bar" role="status">
        <span class="cu-bar-ring" aria-hidden="true" />
        <span class="cu-bar-text">{{ label }}</span>
        <!-- user:“只留一个结束”+(胶囊里只保留结束按钮。) -->
        <button type="button" class="cu-bar-btn" title="结束" aria-label="结束" @click="emit('stop')">
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
</template>

<script setup lang="ts">
/**
 * 屏幕级状态胶囊：整圈 2px 呼吸流光边框 + 贴顶小胶囊。
 * 只画界面，不连后端、不做业务判断；覆盖层和预览页共用这一份。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'

withDefaults(
  defineProps<{
    label?: string
    paused?: boolean
  }>(),
  {
    label: '正在控制电脑',
    paused: false,
  },
)

const emit = defineEmits<{ (event: 'stop'): void }>()

/** 覆盖层要按胶囊位置开点击区域，所以把节点交给调用方量矩形。 */
const barEl = ref<HTMLDivElement | null>(null)
const frameEl = ref<HTMLDivElement | null>(null)

/** 边框线宽和四角内侧圆弧半径。 */
const STROKE = 2
const CORNER_RADIUS = 6

/**
 * 外方内圆：外圈是贴着屏幕四边的直角矩形，内圈是带圆角的矩形。
 * 两条子路径方向相反，nonzero 填充规则下自然挖空成一条 2px 的框，
 * 四角外侧保持贴住屏幕角，内侧收成圆弧。
 */
function buildFramePath(width: number, height: number): string {
  const radius = Math.max(
    0,
    Math.min(CORNER_RADIUS, Math.min(width, height) / 2 - STROKE),
  )
  const left = STROKE
  const top = STROKE
  const right = width - STROKE
  const bottom = height - STROKE
  const outer = `M 0 0 L ${width} 0 L ${width} ${height} L 0 ${height} Z`
  // 逆时针，和外圈方向相反，才能挖出中间的洞。
  const inner = [
    `M ${right - radius} ${top}`,
    `L ${left + radius} ${top}`,
    `A ${radius} ${radius} 0 0 0 ${left} ${top + radius}`,
    `L ${left} ${bottom - radius}`,
    `A ${radius} ${radius} 0 0 0 ${left + radius} ${bottom}`,
    `L ${right - radius} ${bottom}`,
    `A ${radius} ${radius} 0 0 0 ${right} ${bottom - radius}`,
    `L ${right} ${top + radius}`,
    `A ${radius} ${radius} 0 0 0 ${right - radius} ${top}`,
    'Z',
  ].join(' ')
  return `path("${outer} ${inner}")`
}

const frameClip = ref(buildFramePath(window.innerWidth, window.innerHeight))
let observer: ResizeObserver | null = null

function syncFrameClip(): void {
  const element = frameEl.value
  const width = element?.clientWidth || window.innerWidth
  const height = element?.clientHeight || window.innerHeight
  if (width < STROKE * 4 || height < STROKE * 4) return
  frameClip.value = buildFramePath(width, height)
}

onMounted(() => {
  syncFrameClip()
  if (typeof ResizeObserver === 'undefined') return
  observer = new ResizeObserver(() => syncFrameClip())
  if (frameEl.value) observer.observe(frameEl.value)
})

onBeforeUnmount(() => {
  observer?.disconnect()
  observer = null
})

defineExpose({ barEl })
</script>

<style scoped>
.cu-capsule {
  position: absolute;
  inset: 0;
  pointer-events: none;
  /* 流光角度由页面根节点统一驱动，胶囊继承同一个值，和光标、屏幕边框永远同相。 */
}

@property --cu-angle {
  syntax: '<angle>';
  initial-value: 0deg;
  /* 继承：父层跑一次流转，边框和胶囊拿到的角度永远同步，交界处不会一快一慢。 */
  inherits: true;
}

/* 整圈屏幕边框：2px 流光，和胶囊共用同一套颜色与节奏。 */
.cu-screen-frame {
  position: absolute;
  inset: 0;
  background: conic-gradient(
    from var(--cu-angle),
    #7b62c9,
    #2f8f84,
    #a4566d,
    #4f68b8,
    #7b62c9
  );
  /* 形状由外方内圆的裁剪路径给，这里只铺色和呼吸。 */
  animation: cu-capsule-breathe 2.8s ease-in-out infinite;
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

/* 胶囊压在屏幕顶边上：黑底盖住穿过去的那条线，只画左右和下。 */
.cu-bar {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 30px;
  padding: 0 6px 0 12px;
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
      from var(--cu-angle),
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
  animation: cu-capsule-breathe 2.8s ease-in-out infinite;
  pointer-events: none;
}

.cu-capsule--paused {
  animation-play-state: paused;
}

.cu-capsule--paused .cu-screen-frame,
.cu-capsule--paused .cu-bar-ring {
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
  background: rgba(208, 90, 90, 0.3);
  color: #ffffff;
}

@keyframes cu-capsule-breathe {
  0%,
  100% {
    opacity: 0.72;
  }
  50% {
    opacity: 1;
  }
}

/* user:“梳理所有可见的组件、样式、布局、动效及交互”+(减少动态效果时也停止驱动边框渐变的父层动画)。 */
@media (prefers-reduced-motion: reduce) {
  .cu-capsule,
  .cu-screen-frame,
  .cu-bar-ring {
    animation: none;
  }
}
</style>
