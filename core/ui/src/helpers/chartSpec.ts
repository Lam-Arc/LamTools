/**
 * user:“图表落地，柱状，折线，饼图都支持”+(图表是结构化数据，先在这里把载荷规范化并校验；
 * 渲染器只负责画，不负责猜。)
 * user:“是否支持渐变面积图，多维雷达图，曲线图，折、曲、柱混搭图”+(四种形态都在同一份
 * schema 里表达：area/smooth 是折线的修饰，series[].type 负责混搭，radar 是独立类型。)
 *
 * The model writes a ```chart fence containing this JSON. Everything that can be
 * wrong is rejected here with a short, actionable message, so a bad spec shows an
 * error line instead of an empty canvas.
 */

export type ChartType = 'bar' | 'line' | 'pie' | 'radar'
export type SeriesType = 'bar' | 'line'

export interface ChartSeries {
  name: string
  data: number[]
  /** 混搭：单条系列可以覆盖图表类型，柱线同轴。 */
  type?: SeriesType
}

export interface ChartSpec {
  type: ChartType
  title: string
  unit: string
  categories: string[]
  series: ChartSeries[]
  /** 折线是否走平滑曲线。 */
  smooth: boolean
  /** 折线是否填充渐变面积。 */
  area: boolean
}

export type ChartParseResult =
  | { ok: true; spec: ChartSpec }
  | { ok: false; error: string }

const MAX_SERIES = 12
const MAX_RADAR_SERIES = 6
const MAX_POINTS = 500
const MAX_LABEL = 60

const CHART_TYPES: ChartType[] = ['bar', 'line', 'pie', 'radar']
const SERIES_TYPES: SeriesType[] = ['bar', 'line']

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function readLabel(value: unknown): string {
  const text = typeof value === 'string' ? value.trim() : ''
  return text.length > MAX_LABEL ? `${text.slice(0, MAX_LABEL)}…` : text
}

function readNumbers(value: unknown): number[] | null {
  if (!Array.isArray(value)) return null
  const result: number[] = []
  for (const item of value) {
    if (typeof item !== 'number' || !Number.isFinite(item)) return null
    result.push(item)
  }
  return result
}

export function parseChartSpec(source: string): ChartParseResult {
  const text = String(source || '').trim()
  if (!text) return { ok: false, error: '图表数据为空' }

  let raw: unknown
  try {
    raw = JSON.parse(text)
  } catch {
    return { ok: false, error: '图表数据不是合法 JSON' }
  }

  const record = asRecord(raw)
  if (!record) return { ok: false, error: '图表数据必须是一个对象' }

  const type = String(record.type || '').trim() as ChartType
  if (!CHART_TYPES.includes(type)) {
    return { ok: false, error: `type 必须是 ${CHART_TYPES.join(' / ')}` }
  }

  const rawSeries = Array.isArray(record.series) ? record.series : []
  if (rawSeries.length === 0) return { ok: false, error: '缺少 series' }
  if (rawSeries.length > MAX_SERIES) return { ok: false, error: `series 最多 ${MAX_SERIES} 组` }

  const series: ChartSeries[] = []
  for (const [index, item] of rawSeries.entries()) {
    const entry = asRecord(item)
    const data = readNumbers(entry ? entry.data : item)
    if (!data || data.length === 0) return { ok: false, error: `series[${index}].data 必须是数字数组` }
    const override = entry && typeof entry.type === 'string' ? entry.type.trim() as SeriesType : undefined
    if (override !== undefined && !SERIES_TYPES.includes(override)) {
      return { ok: false, error: `series[${index}].type 只能是 bar / line` }
    }
    if (type === 'pie' && override !== undefined) {
      return { ok: false, error: '饼图不支持 series[].type' }
    }
    series.push({
      name: readLabel(entry?.name) || `系列 ${index + 1}`,
      data,
      ...(override ? { type: override } : {}),
    })
  }

  const categories = Array.isArray(record.categories)
    ? record.categories.map(item => readLabel(item))
    : []

  const totalPoints = series.reduce((sum, item) => sum + item.data.length, 0)
  if (totalPoints > MAX_POINTS) return { ok: false, error: `数据点最多 ${MAX_POINTS} 个` }

  const smooth = record.smooth === true
  const area = record.area === true

  if (type === 'pie') {
    const first = series[0]
    if (first.data.length < 2) return { ok: false, error: '饼图至少需要 2 个扇区' }
    if (categories.length > 0 && categories.length !== first.data.length) {
      return {
        ok: false,
        error: `categories 与 series[0].data 长度不一致（${categories.length} vs ${first.data.length}）`,
      }
    }
    return {
      ok: true,
      spec: {
        type,
        title: readLabel(record.title),
        unit: readLabel(record.unit),
        categories: categories.length > 0
          ? categories
          : first.data.map((_, index) => `第 ${index + 1} 项`),
        series: [first],
        smooth: false,
        area: false,
      },
    }
  }

  if (type === 'radar') {
    if (categories.length < 3) return { ok: false, error: '雷达图至少需要 3 个维度（categories）' }
    if (series.length > MAX_RADAR_SERIES) return { ok: false, error: `雷达图最多 ${MAX_RADAR_SERIES} 组数据` }
    for (const [index, item] of series.entries()) {
      if (item.data.length !== categories.length) {
        return {
          ok: false,
          error: `series[${index}] 数据点与维度数量不一致（${item.data.length} vs ${categories.length}）`,
        }
      }
    }
    return {
      ok: true,
      spec: {
        type,
        title: readLabel(record.title),
        unit: readLabel(record.unit),
        categories,
        series,
        smooth: false,
        area: false,
      },
    }
  }

  if (categories.length === 0) {
    return { ok: false, error: `${type === 'bar' ? '柱状图' : '折线图'}需要 categories` }
  }
  for (const [index, item] of series.entries()) {
    if (item.data.length !== categories.length) {
      return {
        ok: false,
        error: `series[${index}] 数据点与 categories 数量不一致（${item.data.length} vs ${categories.length}）`,
      }
    }
  }

  return {
    ok: true,
    spec: {
      type,
      title: readLabel(record.title),
      unit: readLabel(record.unit),
      categories,
      series,
      smooth,
      area,
    },
  }
}
