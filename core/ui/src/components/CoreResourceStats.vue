<template>
  <div
    v-if="variant === 'composer'"
    class="core-resource-line"
    :class="{ 'has-data': summary?.hasContext }"
    :style="resourceStyle"
    role="meter"
    aria-label="上下文占用"
    :aria-valuenow="summary?.currentPct ?? 0"
    aria-valuemin="0"
    aria-valuemax="100"
    :title="composerTitle"
  >
    <span></span>
  </div>
  <section v-else ref="widgetEl" class="runtime-widget core-resource-widget">
    <div class="runtime-widget-head">
      <h3>{{ title }}</h3>
      <strong v-if="summary" class="core-resource-state">{{ summary.statusLabel }}</strong>
    </div>
    <template v-if="summary">
      <div class="core-resource-main">
        <div class="core-resource-section-label">上下文</div>
        <div class="core-resource-values">
          <strong>{{ summary.contextLabel }}</strong>
          <strong>{{ summary.percentLabel }}</strong>
        </div>
        <div class="core-resource-bar" :style="resourceStyle" role="meter" :aria-valuenow="summary.currentPct" aria-valuemin="0" aria-valuemax="100">
          <span class="core-resource-used"></span>
          <span class="core-resource-blocked"></span>
        </div>
        <div class="core-resource-legend">
          <span>可用至 {{ summary.thresholdPct }}%</span>
          <span>灰色区压缩</span>
        </div>
      </div>
      <div class="core-resource-section-label core-resource-usage-label">
        <span>Provider Usage</span>
        <span>{{ summary.usageStatusLabel }}</span>
      </div>
      <div class="core-resource-stats" :style="{ gridTemplateColumns: `repeat(${summary.callItems.length}, minmax(0, 1fr))` }">
        <div v-for="item in summary.callItems" :key="item.label">
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
        </div>
      </div>
      <template v-if="cacheTrend.length">
        <div class="core-resource-section-label core-resource-cache-label">
          <span>缓存命中率</span>
          <span>{{ cacheTrendLatestLabel }}</span>
        </div>
        <div class="core-resource-cache-block">
          <div class="core-resource-cache-scale" aria-hidden="true">
            <span
              class="core-resource-cache-scale-label core-resource-cache-scale-max"
              :style="{ top: cacheScaleMaxTop }"
            >100%</span>
            <span
              class="core-resource-cache-scale-label core-resource-cache-scale-min"
              :style="{ top: cacheScaleMinTop }"
            >0%</span>
          </div>
          <div class="core-resource-cache-figure">
            <svg
              class="core-resource-cache-plot"
              :viewBox="`0 0 ${CACHE_CHART_WIDTH} ${CACHE_CHART_HEIGHT}`"
              preserveAspectRatio="none"
              aria-hidden="true"
            >
              <line
                class="core-resource-cache-grid"
                :x1="CACHE_CHART_PAD_X"
                :y1="cacheTrendCeilingY"
                :x2="CACHE_CHART_WIDTH - CACHE_CHART_PAD_X"
                :y2="cacheTrendCeilingY"
                vector-effect="non-scaling-stroke"
              />
              <polygon v-if="cacheTrendAreaPoints" class="core-resource-cache-area" :points="cacheTrendAreaPoints" />
              <polyline
                v-if="cacheTrendLinePoints"
                class="core-resource-cache-line"
                :points="cacheTrendLinePoints"
                vector-effect="non-scaling-stroke"
              />
            </svg>
            <span
              v-if="cacheTrendMarker"
              class="core-resource-cache-dot"
              :style="cacheTrendMarkerStyle"
            ></span>
          </div>
          <div class="core-resource-cache-axis" aria-hidden="true">
            <span>0 次调用</span>
            <span>{{ cacheTrendMaxCallsLabel }}</span>
          </div>
        </div>
      </template>
    </template>
    <div v-else class="core-resource-empty">暂无资源统计。</div>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { gsap } from 'gsap'
import type { CoreMessage } from '../types'
import {
  buildCacheTrend,
  buildCoreResourceSummary,
  CORE_CONTEXT_COMPACTION_TRIGGER_RATIO,
  formatPercent,
} from '../runtime/resources'

const props = withDefaults(defineProps<{
  /** 缺省为空：宿主没有会话消息时资源卡仍要能挂载（显示暂无统计）。 */
  messages?: Array<Pick<CoreMessage, 'metadata' | 'id'> & Partial<Pick<CoreMessage, 'parts'>>>
  contextWindow?: number | null
  variant?: 'panel' | 'composer'
  title?: string
}>(), {
  messages: () => [],
  contextWindow: null,
  variant: 'panel',
  title: '资源',
})

const summary = computed(() => buildCoreResourceSummary(props.messages, props.contextWindow))
const resourceStyle = computed(() => ({
  '--core-resource-used': String(summary.value?.currentRatio ?? 0),
  '--core-resource-threshold': `${((summary.value?.thresholdRatio ?? CORE_CONTEXT_COMPACTION_TRIGGER_RATIO) * 100).toFixed(2)}%`,
}))
const composerTitle = computed(() => summary.value?.hasContext
  ? `上下文 ${summary.value.contextLabel}（${summary.value.percentLabel}）`
  : '暂无上下文统计')

// ── 缓存趋势图：横轴累计调用次数（旧在左、新在右），纵轴该回合缓存命中率
// （0–100% 固定域）──。坐标在 100×H 的 viewBox 里归一化：宽随容器 100% 伸缩，
// 高按 6:1 比例跟随宽度并被钳在 32–72px（窄卡不塌、宽卡不无限变高）；
// 描边走 non-scaling-stroke，纵向压缩不会把线拉粗。末端样本始终画一枚数据点
// （HTML 圆点，按百分比定位在绘图区上，拉伸不失真），只有一个样本时图表也
// 有可读的主体。无缓存数据的回合不产出点，全程无点时整块隐藏。
const CACHE_CHART_WIDTH = 100
const CACHE_CHART_HEIGHT = 44
const CACHE_CHART_PAD = 4
const CACHE_CHART_PAD_X = 3

const cacheTrend = computed(() => buildCacheTrend(props.messages))
const cacheTrendMaxCalls = computed(() => cacheTrend.value.reduce((max, point) => Math.max(max, point.calls), 0))
const cacheTrendLast = computed(() => cacheTrend.value[cacheTrend.value.length - 1] ?? null)
const cacheTrendCeilingY = trendY(1)

function trendX(calls: number): number {
  const max = cacheTrendMaxCalls.value
  if (max <= 0) return CACHE_CHART_PAD_X
  return CACHE_CHART_PAD_X + (calls / max) * (CACHE_CHART_WIDTH - CACHE_CHART_PAD_X * 2)
}

function trendY(rate: number): number {
  const span = CACHE_CHART_HEIGHT - CACHE_CHART_PAD * 2
  return CACHE_CHART_PAD + (1 - rate) * span
}

// 纵轴刻度标签按绘图区高度百分比锚定到对应刻度线的确切位置（translateY 居中），
// 图高怎么伸缩都贴住刻度线，不再依赖弹性分布。
const cacheScaleMaxTop = `${((CACHE_CHART_PAD / CACHE_CHART_HEIGHT) * 100).toFixed(3)}%`
const cacheScaleMinTop = `${(((CACHE_CHART_HEIGHT - CACHE_CHART_PAD) / CACHE_CHART_HEIGHT) * 100).toFixed(3)}%`

const cacheTrendLinePoints = computed(() => (
  cacheTrend.value.length >= 2
    ? cacheTrend.value.map((point) => `${trendX(point.calls).toFixed(2)},${trendY(point.rate).toFixed(2)}`).join(' ')
    : ''
))
const cacheTrendAreaPoints = computed(() => {
  if (cacheTrend.value.length < 2) return ''
  const first = cacheTrend.value[0]
  const last = cacheTrend.value[cacheTrend.value.length - 1]
  return [
    ...cacheTrend.value.map((point) => `${trendX(point.calls).toFixed(2)},${trendY(point.rate).toFixed(2)}`),
    `${trendX(last.calls).toFixed(2)},${trendY(0).toFixed(2)}`,
    `${trendX(first.calls).toFixed(2)},${trendY(0).toFixed(2)}`,
  ].join(' ')
})
const cacheTrendMarker = computed(() => {
  const last = cacheTrendLast.value
  if (!last) return null
  return { x: trendX(last.calls), y: trendY(last.rate) }
})
const cacheTrendMarkerStyle = computed(() => {
  const marker = cacheTrendMarker.value
  if (!marker) return {}
  return {
    left: `${(marker.x / CACHE_CHART_WIDTH) * 100}%`,
    top: `${(marker.y / CACHE_CHART_HEIGHT) * 100}%`,
  }
})
const cacheTrendLatestLabel = computed(() => (cacheTrendLast.value ? formatPercent(cacheTrendLast.value.rate) : ''))
const cacheTrendMaxCallsLabel = computed(() => `${cacheTrendMaxCalls.value} 次调用`)

// ── 数字滚动（C13）：数值文本在 settle 变化时 300ms 滚动到位 ──
// 流式热路径保护：live 消息存在时（每 tick 数值都在变）不启动 tween、不写额外 DOM；
// 回合结束/会话切换等离散变化才播动画。watcher 用 flush:'pre'（DOM 仍是上一目标值），
// 播完后 textContent 交给 Vue 的最终渲染。
const widgetEl = ref<HTMLElement | null>(null)
const statTweens = new Map<HTMLElement, gsap.core.Tween>()
const isLiveStreaming = computed(() => props.messages.some((m) => m.metadata?.live))

interface ParsedNum {
  value: number
  suffix: string
  scale: number
}

function parseNumeric(text: string): ParsedNum | null {
  const m = String(text).trim().match(/^(-?\d+(?:\.\d+)?)([kK]?)([%a-zA-Z]*)$/)
  if (!m) return null
  const scale = m[2] ? 1000 : 1
  return { value: parseFloat(m[1]) * scale, suffix: m[3] || (m[2] ? 'k' : ''), scale }
}

function formatNumber(p: ParsedNum): string {
  let v = p.value
  let suffix = p.suffix
  if (p.scale === 1000) {
    v /= 1000
    suffix = suffix || 'k'
  }
  const display = Number.isInteger(v) ? String(v) : v.toFixed(1)
  return display + suffix
}

function animateStat(el: HTMLElement, nextText: string) {
  const next = parseNumeric(nextText)
  const shouldSkipMotion = (
    typeof window === 'undefined'
    || typeof window.matchMedia !== 'function'
    || window.matchMedia('(prefers-reduced-motion: reduce)').matches
    || typeof requestAnimationFrame !== 'function'
  )
  if (!next || shouldSkipMotion) {
    el.textContent = nextText
    return
  }
  const cur = parseNumeric(el.textContent ?? '')
  if (cur && cur.value === next.value) return
  statTweens.get(el)?.kill()
  const proxy = { v: cur ? cur.value : 0 }
  const tween = gsap.to(proxy, {
    v: next.value,
    duration: 0.3,
    ease: 'power1.out',
    overwrite: true,
    onUpdate: () => { el.textContent = formatNumber({ ...next, value: proxy.v }) },
    onComplete: () => { el.textContent = nextText; statTweens.delete(el) },
  })
  statTweens.set(el, tween)
}

watch(summary, (s) => {
  if (isLiveStreaming.value || !widgetEl.value || !s) return
  const percent = widgetEl.value.querySelector<HTMLElement>('.core-resource-values strong:nth-child(2)')
  if (percent) animateStat(percent, s.percentLabel)
  const statEls = widgetEl.value.querySelectorAll<HTMLElement>('.core-resource-stats > div > strong')
  s.callItems.forEach((item, i) => {
    const el = statEls[i]
    if (el) animateStat(el, item.value)
  })
}, { flush: 'pre' })

onBeforeUnmount(() => {
  statTweens.forEach((t) => t.kill())
  statTweens.clear()
})
</script>

<style scoped>
.core-resource-widget { --core-resource-ease: cubic-bezier(0.22, 1, 0.36, 1); }
.core-resource-state { color: var(--green); font-size: 12px; font-weight: 800; }
.core-resource-main { display: grid; gap: 6px; }
.core-resource-section-label { color: color-mix(in srgb, var(--theme-backdrop-text) 62%, transparent); font-size: 11px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; }
.core-resource-usage-label { display: flex; justify-content: space-between; gap: 8px; margin-top: 10px; }
.core-resource-values, .core-resource-legend { display: flex; justify-content: space-between; gap: 8px; }
.core-resource-values strong { color: var(--theme-backdrop-text); font-family: var(--font-mono); font-size: 14px; }
.core-resource-bar { position: relative; height: 6px; overflow: hidden; background: color-mix(in srgb, var(--theme-backdrop-text) 10%, transparent); }
.core-resource-used, .core-resource-blocked { position: absolute; inset: 0; }
.core-resource-used { background: var(--green); transform: scaleX(var(--core-resource-used)); transform-origin: left; transition: transform 180ms var(--core-resource-ease); }
.core-resource-blocked { left: var(--core-resource-threshold); background: color-mix(in srgb, var(--theme-backdrop-text) 14%, transparent); }
.core-resource-legend, .core-resource-empty, .core-resource-stats span { color: color-mix(in srgb, var(--theme-backdrop-text) 56%, transparent); font-size: 12px; }
.core-resource-stats { display: grid; gap: 8px; margin-top: 8px; padding-top: 10px; border-top: 1px solid color-mix(in srgb, var(--theme-backdrop-text) 11%, transparent); }
.core-resource-stats > div { display: grid; gap: 3px; min-width: 0; }
.core-resource-stats strong { overflow: hidden; color: var(--theme-backdrop-text); font-family: var(--font-mono); font-size: 13px; text-overflow: ellipsis; }
.core-resource-cache-label { display: flex; justify-content: space-between; gap: 8px; margin-top: 10px; }
/* 图块：左列纵轴刻度、右列图形。刻度标签按百分比锚定到对应刻度线的确切高度
   （translateY 居中），图高按 6:1 跟随宽度伸缩并被钳在 32–72px——窄卡不塌、
   宽卡不无限变高。末端样本画 HTML 数据点（百分比定位，图形拉伸不失真）。 */
.core-resource-cache-block { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 2px 6px; margin-top: 4px; }
.core-resource-cache-scale { position: relative; }
.core-resource-cache-scale-label { position: absolute; left: 0; transform: translateY(-50%); color: color-mix(in srgb, var(--theme-backdrop-text) 45%, transparent); font-size: 10px; line-height: 1; }
.core-resource-cache-figure { position: relative; aspect-ratio: 6 / 1; min-height: 32px; max-height: 72px; }
.core-resource-cache-plot { position: absolute; inset: 0; display: block; width: 100%; height: 100%; }
.core-resource-cache-dot { position: absolute; width: 7px; height: 7px; border-radius: 50%; background: var(--green); box-shadow: 0 0 0 3px color-mix(in srgb, var(--green) 18%, transparent); transform: translate(-50%, -50%); pointer-events: none; }
.core-resource-cache-grid { stroke: color-mix(in srgb, var(--theme-backdrop-text) 14%, transparent); stroke-width: 1; stroke-dasharray: 3 3; }
.core-resource-cache-area { fill: color-mix(in srgb, var(--green) 14%, transparent); }
.core-resource-cache-line { fill: none; stroke: var(--green); stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.core-resource-cache-axis { grid-column: 2; display: flex; justify-content: space-between; gap: 8px; color: color-mix(in srgb, var(--theme-backdrop-text) 45%, transparent); font-size: 10px; }
.core-resource-empty { padding: 8px 0; }
.core-resource-line { --core-resource-ease: cubic-bezier(0.22, 1, 0.36, 1); position: absolute; z-index: 3; top: 0; left: 0; right: 0; height: 1px; overflow: hidden; background: color-mix(in srgb, var(--theme-composer-text) 10%, transparent); pointer-events: none; }
.core-resource-line span { display: block; width: 100%; height: 100%; background: color-mix(in srgb, var(--theme-composer-text) 36%, transparent); opacity: 0; transform: scaleX(var(--core-resource-used)); transform-origin: left; transition: transform 180ms var(--core-resource-ease), opacity 120ms ease; }
.core-resource-line.has-data span { opacity: 1; }
@media (prefers-reduced-motion: reduce) { .core-resource-used, .core-resource-line span { transition-duration: .01ms !important; } }
</style>
