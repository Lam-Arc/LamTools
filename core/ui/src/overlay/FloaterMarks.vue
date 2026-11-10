<template>
  <div class="floaters" aria-hidden="true">
    <div
      v-for="mark in floaters"
      :key="mark.id"
      class="floater"
      :class="`floater--${mark.kind}`"
      :style="styleFor(mark)"
    >
      <div class="floater__move" :style="moveStyleFor(mark)">
        <div class="floater__body" :style="fadeStyleFor(mark)">
          <img
            v-if="mark.image"
            :src="assetUrl(mark.image.asset)"
            :style="imageStyle(mark)"
            :alt="mark.text || '表情包'"
            draggable="false"
          />
          <span v-else>{{ mark.text }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 弹幕与表情包浮层。
 *
 * user:“弹幕流畅一点，不要一顿一顿地飘”“弹幕位置调整一下，30%上方屏幕，
 * 速度根据长度调整快慢”“表情包（图片）…让它们流畅一些”+
 * (位移和淡出交给 CSS 动画，跑在合成线程上，不受每帧 JS 更新影响；
 *  每个标记的动画参数只算一次并缓存，轮询刷新状态时不会重启动画。)
 */
import { computed, watch } from 'vue'
import type { OverlayMark } from './model.ts'
import { danmakuLayout, type DanmakuSettings } from './motion.ts'

const props = defineProps<{
  marks: OverlayMark[]
  /** 屏幕物理高度：锚点坐标是物理像素，算轨道比例要用它。 */
  overlayHeight: number
  viewportWidth: number
  viewportHeightCss: number
  /** 物理像素 → 页面 CSS 像素，表情包必须换算，不然会偏到右下角。 */
  toPage: (point: [number, number]) => [number, number]
  settings: DanmakuSettings
  assetUrl: (asset: string) => string
}>()

const floaters = computed(() => props.marks)

/** 每个标记只算一次动画参数：轮询换掉数组时样式字符串不变，动画不会跳。 */
const cache = new Map<string, Record<string, string>>()
const moveCache = new Map<string, Record<string, string>>()
const fadeCache = new Map<string, Record<string, string>>()

const viewport = computed(() => ({
  cssHeight: props.viewportHeightCss,
  physicalHeight: props.overlayHeight,
}))

watch(
  // 交互层几何也算参数：换显示器或窗口位置变了，轨道和表情包位置必须重算。
  () => [
    props.settings.speed,
    props.settings.fontSize,
    props.settings.fontFamily,
    props.viewportWidth,
    props.viewportHeightCss,
    props.overlayHeight,
  ],
  () => {
    cache.clear()
    moveCache.clear()
    fadeCache.clear()
  },
)

// 标记走了就把缓存一起丢掉：长时间开着也不会越攒越多。
watch(
  () => props.marks.map(mark => mark.id).join(','),
  ids => {
    const alive = new Set(ids ? ids.split(',') : [])
    for (const map of [cache, moveCache, fadeCache]) {
      for (const key of map.keys()) {
        if (!alive.has(key)) map.delete(key)
      }
    }
  },
)

function elapsedOf(mark: OverlayMark): number {
  // 首次看到它时可能已经飘了一会儿：用负延迟把动画对到正确位置。
  return Math.max(0, Date.now() / 1000 - mark.created_at)
}

function styleFor(mark: OverlayMark): Record<string, string> {
  const hit = cache.get(mark.id)
  if (hit) return hit
  const style: Record<string, string> =
    mark.kind === 'danmaku' ? danmakuWrapper(mark) : stickerWrapper(mark)
  cache.set(mark.id, style)
  return style
}

function moveStyleFor(mark: OverlayMark): Record<string, string> {
  const hit = moveCache.get(mark.id)
  if (hit) return hit
  const style = mark.kind === 'danmaku' ? danmakuFlow(mark) : stickerPop(mark)
  moveCache.set(mark.id, style)
  return style
}

function fadeStyleFor(mark: OverlayMark): Record<string, string> {
  const hit = fadeCache.get(mark.id)
  if (hit) return hit
  const style = fadeTiming(mark)
  fadeCache.set(mark.id, style)
  return style
}

function danmakuWrapper(mark: OverlayMark): Record<string, string> {
  const layout = danmakuLayout(
    mark,
    viewport.value,
    props.viewportWidth,
    props.settings,
  )
  return {
    top: `${layout.top.toFixed(2)}px`,
    '--dm-width': `${layout.width.toFixed(1)}px`,
  }
}

function danmakuFlow(mark: OverlayMark): Record<string, string> {
  const layout = danmakuLayout(
    mark,
    viewport.value,
    props.viewportWidth,
    props.settings,
  )
  const start = layout.fromLeft ? -layout.width : props.viewportWidth
  const end = layout.fromLeft ? props.viewportWidth : -layout.width
  return {
    '--dm-from': `${start.toFixed(1)}px`,
    '--dm-to': `${end.toFixed(1)}px`,
    animation: `overlay-danmaku-flow ${layout.duration.toFixed(2)}s linear ${(-elapsedOf(mark)).toFixed(2)}s both`,
  }
}

function stickerWrapper(mark: OverlayMark): Record<string, string> {
  // 锚点是屏幕物理像素，页面用的是 CSS 像素：不换算在高缩放下会偏出去。
  const [x, y] = props.toPage(mark.points[0] ?? [0, 0])
  return { left: `${x.toFixed(1)}px`, top: `${y.toFixed(1)}px` }
}

function stickerPop(mark: OverlayMark): Record<string, string> {
  const duration = Math.max(0.15, mark.motion?.duration ?? 0.6)
  return {
    animation: `overlay-sticker-pop ${duration.toFixed(2)}s cubic-bezier(.2,1.4,.4,1) ${(-elapsedOf(mark)).toFixed(2)}s both`,
  }
}

function fadeTiming(mark: OverlayMark): Record<string, string> {
  const ttl = Math.max(0.2, mark.ttl)
  const fade = Math.min(mark.motion?.fade ?? 0.4, ttl * 0.8)
  const elapsed = elapsedOf(mark)
  // 淡出只在最后一小段跑，前面保持不透明。
  const outDelay = -(elapsed - (ttl - fade))
  return {
    animation: `overlay-floater-in 0.18s ease-out ${(-elapsed).toFixed(2)}s both, `
      + `overlay-floater-out ${fade.toFixed(2)}s linear ${outDelay.toFixed(2)}s forwards`,
  }
}

function imageStyle(mark: OverlayMark): Record<string, string> {
  const width = mark.image?.width ?? (mark.kind === 'danmaku' ? props.settings.fontSize * 1.7 : 160)
  return { width: `${width}px` }
}
</script>

<style scoped>
.floaters {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
}

.floater {
  position: absolute;
  left: 0;
  will-change: transform, opacity;
  pointer-events: none;
}

/* 弹幕：只在轨道里横向移动，绝不影响布局。 */
.floater--danmaku {
  white-space: nowrap;
}

.floater__move {
  will-change: transform;
}

.floater__body {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  white-space: nowrap;
  filter: drop-shadow(0 2px 10px rgba(0, 0, 0, 0.55));
}

.floater--danmaku .floater__body {
  font-size: var(--dm-font-size, 24px);
  font-family: var(--dm-font-family, var(--font-sans));
  font-weight: 650;
  line-height: 1.4;
  color: #ffffff;
  text-shadow: 0 2px 8px rgba(0, 0, 0, 0.7);
}

.floater--danmaku img {
  display: block;
  height: auto;
}

.floater--sticker .floater__body {
  font-size: var(--sticker-font-size, 64px);
  line-height: 1;
  font-family: 'Segoe UI Emoji', 'Apple Color Emoji', 'Noto Color Emoji', var(--font-sans);
}

.floater--sticker {
  transform: translate(-50%, -50%);
}

.floater--sticker img {
  display: block;
  height: auto;
  max-width: none;
}

</style>

<style>
/* user:“弹幕流畅一点，不要一顿一顿地飘”+(关键帧必须全局：动画名由 JS 写进内联
   样式，scoped 样式会把 @keyframes 改名，内联的名字就对不上了，动画等于没跑)。 */
@keyframes overlay-danmaku-flow {
  from {
    transform: translate3d(var(--dm-from, 100vw), 0, 0);
  }
  to {
    transform: translate3d(var(--dm-to, -100vw), 0, 0);
  }
}

@keyframes overlay-sticker-pop {
  0% {
    transform: scale(0.4);
  }
  60% {
    transform: scale(1.08);
  }
  100% {
    transform: scale(1);
  }
}

@keyframes overlay-floater-in {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

@keyframes overlay-floater-out {
  from {
    opacity: 1;
  }
  to {
    opacity: 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .floater__move,
  .floater__body {
    animation-duration: 0.01s !important;
  }
}
</style>
