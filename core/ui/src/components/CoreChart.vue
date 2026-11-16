<template>
  <figure class="core-chart" :data-chart-type="spec?.type || 'invalid'">
    <figcaption v-if="spec?.title" class="core-chart__title">{{ spec.title }}</figcaption>
    <div
      ref="host"
      class="core-chart__plot"
      :style="{ height: `${plotHeight}px` }"
      role="img"
      :aria-label="ariaLabel"
    />
    <p v-if="error" class="core-chart__error" role="status">{{ error }}</p>
  </figure>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { EChartsCoreOption, EChartsType } from 'echarts/core'

import { parseChartSpec, type ChartSpec } from '@/helpers/chartSpec.ts'
import { t } from '@/i18n/index.ts'

/**
 * user:“图表落地，柱状，折线，饼图都支持，自己去找合适的库”+(echarts 按需注册三种图，
 * 配色与文字色一律从主题变量读取，绝不写死颜色；尺寸由容器决定，隐藏时延后初始化。)
 */
/**
 * user:“自己去找合适的库”+(echarts 按需注册，且只在第一次真的要画图时才下载：
 * 没有图表的会话不为它付启动成本。)
 */
type EChartsModule = typeof import('echarts/core')
let echartsLib: EChartsModule | null = null
let echartsLoading: Promise<EChartsModule | null> | null = null

function loadEcharts(): Promise<EChartsModule | null> {
  if (echartsLib) return Promise.resolve(echartsLib)
  if (!echartsLoading) {
    echartsLoading = (async () => {
      try {
        const [core, charts, components, renderers] = await Promise.all([
          import('echarts/core'),
          import('echarts/charts'),
          import('echarts/components'),
          import('echarts/renderers'),
        ])
        core.use([
          charts.BarChart,
          charts.LineChart,
          charts.PieChart,
          charts.RadarChart,
          components.GridComponent,
          components.TooltipComponent,
          components.LegendComponent,
          components.RadarComponent,
          components.AriaComponent,
          renderers.CanvasRenderer,
        ])
        echartsLib = core
        return core
      } catch {
        echartsLoading = null
        return null
      }
    })()
  }
  return echartsLoading
}

const props = defineProps<{ source: string }>()

const host = ref<HTMLElement | null>(null)
let chart: EChartsType | null = null
let resizeObserver: ResizeObserver | null = null
let themeObserver: MutationObserver | null = null

const parsed = computed(() => parseChartSpec(props.source))
const spec = computed<ChartSpec | null>(() => (parsed.value.ok ? parsed.value.spec : null))
const error = computed(() => (parsed.value.ok ? '' : parsed.value.error))
const plotHeight = computed(() => (spec.value?.type === 'pie' ? 240 : 220))

const ariaLabel = computed(() => {
  if (!spec.value) return t('图表')
  const names = spec.value.series.map(item => item.name).join('、')
  return t('{0}：{1}', { 0: spec.value.title || t('图表'), 1: names })
})

/* ── 主题色：从容器继承的 CSS 变量读取 ───────────────────────────── */
function readToken(name: string, fallback: string): string {
  const el = host.value
  if (!el) return fallback
  const value = getComputedStyle(el).getPropertyValue(name).trim()
  return value || fallback
}

function alpha(color: string, opacity: number): string {
  const hex = color.trim()
  if (hex.startsWith('#')) {
    const raw = hex.slice(1)
    const full = raw.length === 3
      ? raw.split('').map(char => char + char).join('')
      : raw.slice(0, 6)
    const r = Number.parseInt(full.slice(0, 2), 16)
    const g = Number.parseInt(full.slice(2, 4), 16)
    const b = Number.parseInt(full.slice(4, 6), 16)
    if ([r, g, b].every(Number.isFinite)) return `rgba(${r}, ${g}, ${b}, ${opacity})`
  }
  if (/^rgba?\(/i.test(hex)) {
    return hex.replace(/^rgba?\(([^)]+)\)$/i, (_match, body: string) => {
      const parts = body.split(',').slice(0, 3).map(part => part.trim()).join(', ')
      return `rgba(${parts}, ${opacity})`
    })
  }
  return hex
}

function prefersReducedMotion(): boolean {
  return typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches
}

/**
 * user:“是否支持渐变面积图”+(面积填充用同色渐变而不是纯色块：上浓下透，避免压住网格线。)
 */
function areaGradient(color: string) {
  return {
    type: 'linear' as const,
    x: 0,
    y: 0,
    x2: 0,
    y2: 1,
    colorStops: [
      { offset: 0, color: alpha(color, 0.28) },
      { offset: 1, color: alpha(color, 0.02) },
    ],
  }
}

function buildOption(): EChartsCoreOption | null {
  const current = spec.value
  if (!current) return null

  const text = readToken('--theme-main-text', '#e9e7e2')
  const surface = readToken('--theme-main-soft-background', '#141518')
  const border = readToken('--theme-main-border', alpha(text, 0.12))
  const secondary = alpha(text, 0.65)
  const faint = alpha(text, 0.45)
  const grid = alpha(text, 0.12)
  const axis = alpha(text, 0.26)
  const palette = [
    readToken('--green', '#32d17d'),
    readToken('--blue', '#79bcff'),
    readToken('--orange', '#ff9142'),
    readToken('--red', '#f5555d'),
    readToken('--purple', '#bd8cff'),
  ]

  const tooltip = {
    backgroundColor: surface,
    borderColor: border,
    borderWidth: 1,
    padding: [6, 9],
    textStyle: { color: text, fontSize: 11 },
    extraCssText: 'border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,.35);',
  }
  const base: EChartsCoreOption = {
    backgroundColor: 'transparent',
    textStyle: { color: text, fontSize: 11 },
    animation: !prefersReducedMotion(),
    animationDuration: 320,
    aria: { enabled: true },
  }
  const showLegend = current.series.length > 1 || current.type === 'pie'
  const legend = showLegend
    ? {
      bottom: 0,
      icon: 'roundRect',
      itemWidth: 8,
      itemHeight: 8,
      itemGap: 12,
      textStyle: { color: secondary, fontSize: 10 },
    }
    : undefined

  if (current.type === 'pie') {
    const first = current.series[0]
    return {
      ...base,
      tooltip: { ...tooltip, trigger: 'item' },
      legend,
      series: [{
        type: 'pie',
        radius: ['42%', '68%'],
        center: ['50%', '46%'],
        avoidLabelOverlap: true,
        itemStyle: { borderColor: readToken('--theme-main-background', '#0c0d0f'), borderWidth: 2 },
        label: { color: secondary, fontSize: 10, formatter: '{b} {d}%' },
        labelLine: { length: 6, length2: 6, lineStyle: { color: axis } },
        color: palette,
        data: current.categories.map((label, index) => ({
          name: label,
          value: first.data[index] ?? 0,
        })),
      }],
    }
  }

  if (current.type === 'radar') {
    const peak = Math.max(1, ...current.series.flatMap(item => item.data))
    const max = peak <= 1 ? 1 : Math.ceil(peak / 10) * 10
    return {
      ...base,
      tooltip: { ...tooltip, trigger: 'item' },
      legend,
      radar: {
        indicator: current.categories.map(name => ({ name, max })),
        radius: '62%',
        center: ['50%', '46%'],
        axisName: { color: secondary, fontSize: 10 },
        axisLine: { lineStyle: { color: grid } },
        splitLine: { lineStyle: { color: grid } },
        splitArea: { areaStyle: { color: ['transparent', alpha(text, 0.02)] } },
      },
      series: [{
        type: 'radar',
        data: current.series.map((item, index) => {
          const color = palette[index % palette.length]
          return {
            name: item.name,
            value: item.data,
            symbolSize: 3,
            lineStyle: { width: 2 },
            itemStyle: { color },
            areaStyle: { color: alpha(color, 0.14) },
          }
        }),
      }],
    }
  }

  const series = current.series.map((item, index) => {
    const kind = item.type ?? (current.type as 'bar' | 'line')
    const color = palette[index % palette.length]
    if (kind === 'bar') {
      return {
        name: item.name,
        type: 'bar' as const,
        data: item.data,
        barMaxWidth: 22,
        itemStyle: { color, borderRadius: [3, 3, 0, 0] },
      }
    }
    return {
      name: item.name,
      type: 'line' as const,
      data: item.data,
      smooth: current.smooth,
      symbol: 'circle',
      symbolSize: 5,
      lineStyle: { width: 2 },
      itemStyle: { color },
      ...(current.area ? { areaStyle: { color: areaGradient(color) } } : {}),
    }
  })

  return {
    ...base,
    tooltip: {
      ...tooltip,
      trigger: 'axis',
      axisPointer: { type: 'line', lineStyle: { color: axis } },
      valueFormatter: current.unit
        ? (value: unknown) => `${value}${current.unit}`
        : undefined,
    },
    legend,
    grid: { left: 4, right: 10, top: 10, bottom: showLegend ? 26 : 4, containLabel: true },
    xAxis: {
      type: 'category',
      data: current.categories,
      axisLine: { lineStyle: { color: axis } },
      axisTick: { show: false },
      axisLabel: { color: faint, fontSize: 10, hideOverlap: true },
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: grid } },
      axisLabel: {
        color: faint,
        fontSize: 10,
        formatter: current.unit ? `{value}${current.unit}` : '{value}',
      },
    },
    series,
  }
}

function disposeChart() {
  chart?.dispose()
  chart = null
}

async function render() {
  const el = host.value
  if (!el) return
  // Hidden panels (collapsed process rows, off-screen panes) report zero size;
  // initializing there produces a 0×0 canvas that never recovers.
  if (!el.clientWidth || !el.clientHeight) return
  const option = buildOption()
  if (!option) return
  const lib = await loadEcharts()
  if (!lib || !host.value) return
  if (!chart) chart = lib.init(el, undefined, { renderer: 'canvas' })
  chart.setOption(option, true)
}

function syncTheme() {
  const option = buildOption()
  if (chart && option) chart.setOption(option, true)
}

onMounted(() => {
  void nextTick(() => void render())
  if (typeof ResizeObserver === 'function') {
    resizeObserver = new ResizeObserver(() => {
      if (!chart) void render()
      else chart.resize()
    })
    if (host.value) resizeObserver.observe(host.value)
  }
  if (typeof MutationObserver === 'function' && host.value) {
    themeObserver = new MutationObserver(syncTheme)
    for (let node = host.value.parentElement; node; node = node.parentElement) {
      themeObserver.observe(node, { attributes: true, attributeFilter: ['class', 'style', 'data-theme'] })
    }
  }
})

watch(() => props.source, () => {
  disposeChart()
  void nextTick(() => void render())
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  themeObserver?.disconnect()
  disposeChart()
})
</script>

<style scoped>
.core-chart {
  margin: 8px 0;
  padding: 8px 10px 6px;
  border: 1px solid var(--theme-main-border, rgba(127, 127, 127, 0.16));
  border-radius: var(--radius, 12px);
  background: var(--theme-main-soft-background, rgba(127, 127, 127, 0.05));
}

.core-chart__title {
  margin: 0 0 4px;
  color: var(--theme-main-text, currentColor);
  font-size: 12px;
  font-weight: 560;
}

.core-chart__plot {
  width: 100%;
}

.core-chart__error {
  margin: 0;
  color: color-mix(in srgb, var(--theme-main-text, currentColor) 45%, transparent);
  font-size: 11px;
}

@media (prefers-reduced-motion: reduce) {
  .core-chart {
    transition: none;
  }
}
</style>
