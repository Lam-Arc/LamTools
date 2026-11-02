<script setup lang="ts">
/**
 * Ping 环：主轮盘 + 同心的二三级外圈。
 *
 * user:“参考这个实现环，图片也一样适配一下，紫色改为白色”+
 * (整块扇形填充、细白描边、中心深色圆盘与十字、悬停扇区用实色高亮；
 *  高亮色统一用白色而不是紫色。图片/动图背景按整个轮盘裁切。)
 * user:“第二级和第三级依旧还是扇形或完整圆环”“它不会使之前的圆环消失”+
 * (二三级不是浮层：主轮盘原地不动，悬停一级项时在更大的半径上长出项目环，
 *  悬停项目再长出会话环；所有层级同时可见。)
 * user:"ping 环跟桌宠应当是解耦的，它们是两个独立的功能"+
 * (组件只依赖 Ping 运行时（ping/），不引用桌宠运行时与宠物实例。)
 */
import { computed } from 'vue'
import type { PingRuntime } from '../ping/usePingRuntime.ts'

const props = defineProps<{ ping: PingRuntime }>()

const WHEEL_CLIP_ID = 'ping-ring-wheel-clip'

const scaleFactor = computed(() => Math.max(0.1, props.ping.overlay.width / Math.max(1, window.innerWidth)))

interface TierView {
  radius: number
  width: number
  iconSize: number
  labelSize: number
  arcs: {
    id: string
    icon: string
    label: string
    fullLabel: string
    active: boolean
    path: string
    iconX: number
    iconY: number
    labelX: number
    labelY: number
    rotation: number
  }[]
}

const geometry = computed(() => {
  const ring = props.ping.ring
  const sectors = ring.sectors
  if (!ring.visible || sectors.length === 0) return null
  const radius = props.ping.config.ping.radius
  const band = props.ping.config.ping.ringWidth
  const tiers = props.ping.tiers
  const step = (Math.PI * 2) / sectors.length
  const gap = Math.min(step * 0.035, 0.022)
  const outer = radius + band / 2
  const maxOuter = Math.max(
    outer,
    tiers.l2.visible ? tiers.l2.radius + tiers.l2.width / 2 : 0,
    tiers.l3.visible ? tiers.l3.radius + tiers.l3.width / 2 : 0,
  )
  const pad = Math.max(16, band * 1.2)
  const size = (maxOuter + pad) * 2
  const center = size / 2
  const hub = clamp(
    props.ping.config.ping.hubRadius ?? outer * 0.42,
    band * 1.4,
    outer * 0.82,
  )
  const iconSize = Math.max(18, outer * 0.15)
  const labelSize = Math.max(11, outer * 0.075)
  const iconRadius = hub + (outer - hub) * 0.52
  const corner = Math.max(3, Math.min(10, outer * 0.032))

  const arcs = sectors.map((sector, index) => {
    const start = -Math.PI / 2 + index * step + gap / 2
    const end = start + step - gap
    const mid = (start + end) / 2
    const iconX = center + Math.cos(mid) * iconRadius
    const iconY = center + Math.sin(mid) * iconRadius
    return {
      id: sector.id,
      icon: sector.icon,
      label: sector.label,
      active: ring.hovered === sector.id
        || (Boolean(tiers.expanded) && tiers.expanded === sector.id),
      slicePath: describeSlice(center, center, hub, outer, start, end, corner),
      iconX,
      iconY,
      labelX: iconX,
      labelY: iconY + iconSize * 0.82 + labelSize * 0.9,
    }
  })

  function buildTier(tier: typeof tiers.l2): TierView | null {
    if (!tier.visible || tier.sectors.length === 0 || tier.width <= 0) return null
    const slots = tier.slots.length === tier.sectors.length
      ? tier.slots
      : tier.sectors.map(() => tier.span / Math.max(1, tier.sectors.length))
    const inner = Math.max(1, tier.radius - tier.width / 2)
    const tOuter = tier.radius + tier.width / 2
    const tCorner = Math.max(3, Math.min(10, tier.width * 0.22))
    const tLabelSize = Math.max(10, Math.min(12, tier.width * 0.24))
    let cursor = tier.start
    const tierArcs = tier.sectors.map((sector, index) => {
      const slot = slots[index] || 0.16
      const gap = Math.min(slot * 0.06, 0.012)
      const start = cursor + gap
      const end = cursor + slot - gap
      cursor += slot
      const mid = (start + end) / 2
      const itemX = center + Math.cos(mid) * tier.radius
      const itemY = center + Math.sin(mid) * tier.radius
      // user:“那个文字不要让它完全水平，按照其项的角度来就行”“为什么文字角度反了
      // 180°”+(严格按扇区的径向角度旋转，不做可读性翻转。)
      const rotation = (mid * 180) / Math.PI
      const arcWidth = slot * tier.radius
      const maxTextWidth = Math.max(36, Math.min(140, arcWidth * 0.92))
      return {
        id: sector.id,
        icon: sector.icon,
        label: truncateLabel(sector.label, maxTextWidth, tLabelSize),
        fullLabel: sector.label,
        active: tier.hovered === sector.id,
        path: describeSlice(center, center, inner, tOuter, start, end, tCorner),
        iconX: itemX,
        iconY: itemY,
        labelX: itemX,
        labelY: itemY,
        rotation,
      }
    })
    return {
      radius: tier.radius,
      width: tier.width,
      iconSize: 0,
      labelSize: tLabelSize,
      arcs: tierArcs,
    }
  }

  const tierViews = [buildTier(tiers.l2), buildTier(tiers.l3)].filter(Boolean) as TierView[]
  const cssSize = size / scaleFactor.value
  const centerX = (ring.x - props.ping.overlay.x) / scaleFactor.value
  const centerY = (ring.y - props.ping.overlay.y) / scaleFactor.value
  return {
    size,
    center,
    outer,
    hub,
    iconSize,
    labelSize,
    cssSize,
    left: centerX - cssSize / 2,
    top: centerY - cssSize / 2,
    background: props.ping.config.ping.background || '',
    arcs,
    tierViews,
  }
})

function describeSlice(
  cx: number,
  cy: number,
  inner: number,
  outer: number,
  start: number,
  end: number,
  corner: number,
): string {
  // 外缘两个角用二次曲线倒圆：沿半径退让 corner，再沿弧线退让 corner/outer。
  const r = Math.max(0, Math.min(corner, (outer - inner) * 0.4, (outer * (end - start)) * 0.3))
  const cornerAngle = outer > 0 ? r / outer : 0
  const arcStart = start + Math.min(cornerAngle, (end - start) * 0.25)
  const arcEnd = end - Math.min(cornerAngle, (end - start) * 0.25)
  const innerStart = polar(cx, cy, inner, start)
  const innerEnd = polar(cx, cy, inner, end)
  const outerStart = polar(cx, cy, outer, start)
  const outerEnd = polar(cx, cy, outer, end)
  const beforeOuterStart = polar(cx, cy, outer - r, start)
  const afterOuterStart = polar(cx, cy, outer, arcStart)
  const beforeOuterEnd = polar(cx, cy, outer, arcEnd)
  const afterOuterEnd = polar(cx, cy, outer - r, end)
  const largeArc = arcEnd - arcStart > Math.PI ? 1 : 0
  return [
    `M ${innerStart.x} ${innerStart.y}`,
    `L ${beforeOuterStart.x} ${beforeOuterStart.y}`,
    `Q ${outerStart.x} ${outerStart.y} ${afterOuterStart.x} ${afterOuterStart.y}`,
    `A ${outer} ${outer} 0 ${largeArc} 1 ${beforeOuterEnd.x} ${beforeOuterEnd.y}`,
    `Q ${outerEnd.x} ${outerEnd.y} ${afterOuterEnd.x} ${afterOuterEnd.y}`,
    `L ${innerEnd.x} ${innerEnd.y}`,
    `A ${inner} ${inner} 0 ${largeArc} 0 ${innerStart.x} ${innerStart.y}`,
    'Z',
  ].join(' ')
}

function polar(cx: number, cy: number, radius: number, angle: number): { x: number; y: number } {
  return {
    x: cx + Math.cos(angle) * radius,
    y: cy + Math.sin(angle) * radius,
  }
}

function estimateTextWidth(text: string, fontSize: number): number {
  let units = 0
  for (const char of text) {
    units += /[⺀-鿿＀-￯]/.test(char) ? 1 : 0.58
  }
  return units * fontSize
}

/** 超出可用弧长时用省略号截断；完整文本放到 title 里悬停可见。 */
function truncateLabel(text: string, maxWidth: number, fontSize: number): string {
  if (estimateTextWidth(text, fontSize) <= maxWidth) return text
  let output = ''
  for (const char of text) {
    if (estimateTextWidth(`${output}${char}…`, fontSize) > maxWidth) break
    output += char
  }
  return output ? `${output}…` : '…'
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}
</script>

<template>
  <div v-if="geometry" class="ping-ring" data-region="ping-ring">
    <svg
      class="ping-ring__svg"
      :style="{ left: `${geometry.left}px`, top: `${geometry.top}px`, width: `${geometry.cssSize}px`, height: `${geometry.cssSize}px` }"
      :viewBox="`0 0 ${geometry.size} ${geometry.size}`"
    >
      <defs>
        <clipPath :id="WHEEL_CLIP_ID" :clipPathUnits="'userSpaceOnUse'">
          <circle :cx="geometry.center" :cy="geometry.center" :r="geometry.outer" />
        </clipPath>
      </defs>

      <!-- 图片 / GIF / WebP 动图背景：按主轮盘裁切，透过扇形底色显示。 -->
      <image
        v-if="geometry.background"
        :href="geometry.background"
        x="0"
        y="0"
        :width="geometry.size"
        :height="geometry.size"
        preserveAspectRatio="xMidYMid slice"
        :clip-path="`url(#${WHEEL_CLIP_ID})`"
        class="ping-ring__media"
      />

      <!-- 二三级：同心的外圈扇形环，主轮盘保持不动。 -->
      <g v-for="(tier, tierIndex) in geometry.tierViews" :key="`tier-${tierIndex}`" class="ping-ring__tier">
        <path
          v-for="arc in tier.arcs"
          :key="`${arc.id}-slice`"
          :d="arc.path"
          :fill="arc.active ? '#ffffff' : 'rgba(14, 16, 22, 0.86)'"
          :fill-opacity="arc.active ? 0.96 : 1"
          :stroke="arc.active ? '#ffffff' : 'rgba(255, 255, 255, 0.3)'"
          stroke-width="1.3"
          stroke-linejoin="round"
          :class="{ 'ping-ring__slice--active': arc.active }"
        />
        <g
          v-for="arc in tier.arcs"
          :key="`${arc.id}-item`"
          class="ping-ring__item"
          :class="{ 'is-active': arc.active }"
        >
          <title>{{ arc.fullLabel }}</title>
          <!-- user:“会话名称那儿不用带图标，一个文本就行了”“项目名称也是”+
               (二三级项只渲染文字；整段按扇区角度旋转。) -->
          <text
            :x="arc.labelX"
            :y="arc.labelY"
            text-anchor="middle"
            dominant-baseline="central"
            :transform="`rotate(${arc.rotation} ${arc.labelX} ${arc.labelY})`"
            :fill="arc.active ? '#1a1c22' : 'rgba(226, 234, 248, 0.78)'"
            :font-size="tier.labelSize"
            font-weight="600"
          >{{ arc.label }}</text>
        </g>
      </g>

      <!-- 主轮盘：深色玻璃底 + 细白描边；悬停/展开扇区实色填充（白色高亮）。 -->
      <path
        v-for="arc in geometry.arcs"
        :key="arc.id"
        :d="arc.slicePath"
        :fill="arc.active
          ? '#ffffff'
          : (geometry.background ? 'rgba(14, 16, 22, 0.72)' : 'rgba(16, 18, 24, 0.88)')"
        :fill-opacity="arc.active ? 0.96 : 1"
        :stroke="arc.active ? '#ffffff' : 'rgba(255, 255, 255, 0.3)'"
        stroke-width="1.3"
        stroke-linejoin="round"
        :class="{ 'ping-ring__slice--active': arc.active }"
      />

      <!-- user:“中间的圆心完全透明”+(中心不放任何填充和十字，直接透出桌面。) -->

      <!-- 主轮盘图标 + 标签。 -->
      <g
        v-for="arc in geometry.arcs"
        :key="`${arc.id}-item`"
        class="ping-ring__item"
        :class="{ 'is-active': arc.active }"
      >
        <text
          :x="arc.iconX"
          :y="arc.iconY"
          text-anchor="middle"
          dominant-baseline="central"
          :fill="arc.active ? '#15171d' : 'rgba(244, 247, 255, 0.94)'"
          :font-size="geometry.iconSize"
          font-weight="650"
        >{{ arc.icon }}</text>
        <text
          :x="arc.labelX"
          :y="arc.labelY"
          text-anchor="middle"
          dominant-baseline="central"
          :fill="arc.active ? '#1a1c22' : 'rgba(226, 234, 248, 0.76)'"
          :font-size="geometry.labelSize"
          font-weight="600"
        >{{ arc.label }}</text>
      </g>
    </svg>
  </div>
</template>

<style scoped>
.ping-ring {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.ping-ring__svg {
  position: absolute;
  overflow: visible;
  transform-origin: 50% 50%;
  animation: ping-ring-in 150ms var(--ease-out, cubic-bezier(0.16, 1, 0.3, 1));
  filter: drop-shadow(0 10px 28px rgba(0, 0, 0, 0.45));
}

.ping-ring__media {
  pointer-events: none;
}

.ping-ring__tier {
  transform-box: view-box;
  transform-origin: center;
  animation: ping-ring-tier-in 180ms var(--ease-out, cubic-bezier(0.16, 1, 0.3, 1));
}

@keyframes ping-ring-tier-in {
  from { opacity: 0; transform: scale(0.9); }
  to { opacity: 1; transform: scale(1); }
}

@keyframes ping-ring-in {
  from { opacity: 0; transform: scale(0.95); }
  to { opacity: 1; transform: scale(1); }
}
</style>
