<script setup lang="ts">
/**
 * 受控 SVG 的流式渲染。
 *
 * user:“SVG 如果能像流式一样逐渐画出，而不是直接贴一个完整的”
 * “不用专门分段，而是做流式渲染”+
 * (每个图形从它到达那一刻开始描边，后追加的图形接着画；用 pathLength=1
 *  归一化任意长度的路径，不依赖 getTotalLength，也不会因为路径长而断断续续。)
 */
import { computed } from 'vue'
import { strokeStyle } from './motion.ts'
import type { MarkDraw, SvgShape } from './model.ts'

const props = defineProps<{
  rect: { x: number; y: number; width: number; height: number }
  viewBox: [number, number, number, number]
  shapes: SvgShape[]
  draw?: MarkDraw
  now: number
  color: string
}>()

const viewBoxText = computed(() => props.viewBox.join(' '))

function styleOf(shape: SvgShape): Record<string, unknown> {
  const style = strokeStyle(shape, props.draw, props.now)
  const fill = shape.fill ?? 'none'
  const stroke = shape.stroke ?? props.color
  return {
    fill: String(fill),
    stroke: String(stroke),
    'stroke-width': Number(shape.strokeWidth ?? 2),
    'stroke-linecap': 'round',
    'stroke-linejoin': 'round',
    'stroke-dasharray': style.strokeDasharray ?? (shape.strokeDasharray ? String(shape.strokeDasharray) : undefined),
    'stroke-dashoffset': style.strokeDashoffset,
    'fill-opacity': style.fillOpacity,
    opacity: shape.opacity === undefined ? undefined : Number(shape.opacity),
    transform: shape.transform ? String(shape.transform) : undefined,
    pathLength: style.pathLength,
  }
}

function numberValue(value: unknown, fallback = 0): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}
</script>

<template>
  <svg
    :x="rect.x"
    :y="rect.y"
    :width="rect.width"
    :height="rect.height"
    :viewBox="viewBoxText"
    preserveAspectRatio="none"
    overflow="visible"
  >
    <template v-for="(shape, index) in shapes" :key="index">
      <path
        v-if="shape.type === 'path'"
        v-bind="styleOf(shape)"
        :d="String(shape.d ?? '')"
      />
      <line
        v-else-if="shape.type === 'line'"
        v-bind="styleOf(shape)"
        :x1="numberValue(shape.x1)"
        :y1="numberValue(shape.y1)"
        :x2="numberValue(shape.x2)"
        :y2="numberValue(shape.y2)"
      />
      <rect
        v-else-if="shape.type === 'rect'"
        v-bind="styleOf(shape)"
        :x="numberValue(shape.x)"
        :y="numberValue(shape.y)"
        :width="numberValue(shape.width)"
        :height="numberValue(shape.height)"
        :rx="numberValue(shape.rx)"
        :ry="numberValue(shape.ry)"
      />
      <circle
        v-else-if="shape.type === 'circle'"
        v-bind="styleOf(shape)"
        :cx="numberValue(shape.cx)"
        :cy="numberValue(shape.cy)"
        :r="numberValue(shape.r)"
      />
      <ellipse
        v-else-if="shape.type === 'ellipse'"
        v-bind="styleOf(shape)"
        :cx="numberValue(shape.cx)"
        :cy="numberValue(shape.cy)"
        :rx="numberValue(shape.rx)"
        :ry="numberValue(shape.ry)"
      />
      <polyline
        v-else-if="shape.type === 'polyline'"
        v-bind="styleOf(shape)"
        :points="String(shape.points ?? '')"
      />
      <polygon
        v-else-if="shape.type === 'polygon'"
        v-bind="styleOf(shape)"
        :points="String(shape.points ?? '')"
      />
      <text
        v-else-if="shape.type === 'text'"
        v-bind="styleOf(shape)"
        :x="numberValue(shape.x)"
        :y="numberValue(shape.y)"
        :font-size="numberValue(shape.fontSize, 14)"
        :text-anchor="String(shape.textAnchor ?? 'start')"
        stroke="none"
      >
        {{ shape.text }}
      </text>
    </template>
  </svg>
</template>
