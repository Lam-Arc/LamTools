/**
 * 消息流（Message Stream）样式的唯一数据源。
 *
 * user:“在「设置 → 界面」新增「消息流（Message Stream）」配置模块，把配置落成全局 CSS 变量 + 根元素 data 属性，
 * 供会话内过程行与正文消费”
 * +(设置页只改这一份配置；会话里的正文与过程行通过 document.documentElement 上的
 *   --ms-* 变量与 data-ms-* 属性消费，两边不互相 import 组件)。
 */

/** 正文/过程行可选的字体档位；过程行另外多一个「继承正文」。 */
export type MessageStreamFontKey = 'system' | 'sans' | 'serif' | 'mono' | 'custom'
export type MessageStreamInheritFontKey = 'inherit' | MessageStreamFontKey
export type MessageStreamBodyContainer = 'none' | 'bordered' | 'card'
export type MessageStreamTitleContainer = 'none' | 'bordered' | 'pill'
export type MessageStreamBorderStyle = 'solid' | 'dashed' | 'dotted'
export type MessageStreamColorTheme = 'mono' | 'chromatic'
export type MessageStreamFillPreset = 'surface' | 'accent' | 'neutral' | 'custom'
export type MessageStreamShimmerScope = 'running' | 'always'

/** 三层配置：消息正文 / 过程行标题 / 过程行展开内容，外加共用的容器与色彩规则。 */
export interface MessageStreamSettings {
  // —— 消息正文 ——
  bodyFont: MessageStreamFontKey
  bodyFontCustom: string
  bodyFontSize: number
  bodyLineHeight: number
  /** 段落间距（px），正文专属参数。 */
  bodyParaGap: number
  bodyContainer: MessageStreamBodyContainer

  // —— 过程行标题 ——
  procTitleFont: MessageStreamInheritFontKey
  procTitleFontCustom: string
  procTitleFontSize: number
  /** 图标显隐开关；落成 --ms-proc-title-icon 的 1/0。 */
  procTitleIcon: boolean
  procTitleContainer: MessageStreamTitleContainer

  // —— 过程行展开内容 ——
  procBodyFont: MessageStreamInheritFontKey
  procBodyFontCustom: string
  procBodyFontSize: number
  procBodyLineHeight: number
  /** 一级内容高度（行）；二级高度单独配。 */
  procLines1: number
  procLines2: number
  procBodyContainer: MessageStreamBodyContainer

  // —— 容器共用：描边 / 填充 / 毛玻璃 ——
  borderStyle: MessageStreamBorderStyle
  borderWidth: number
  /** 空串表示跟随色彩主题自动推导。 */
  borderColor: string
  fillPreset: MessageStreamFillPreset
  fillColor: string
  /** 透明度 0~100（步长 5）；落成 --ms-proc-fill-alpha 时是百分比字符串，例如 "40%"。 */
  fillAlpha: number
  blur: boolean

  // —— 色彩主题与流光 ——
  colorTheme: MessageStreamColorTheme
  monoFollowAccent: boolean
  monoColor: string
  shimmer: boolean
  shimmerScope: MessageStreamShimmerScope
}

export const MESSAGE_STREAM_EXPORT_VERSION = 1
export const MESSAGE_STREAM_EXPORT_KIND = 'lamtools.messageStream'

/** 「边框」模式下可选的描边粗细；胶囊/卡片会被强制成 2px。 */
export const MESSAGE_STREAM_BORDER_WIDTHS = [1, 1.5, 2, 3] as const

/** 过程行内容上下内边距，过程行高度公式要用它。 */
export const MESSAGE_STREAM_BODY_PAD_Y = 10

export const DEFAULT_MESSAGE_STREAM: MessageStreamSettings = {
  bodyFont: 'system',
  bodyFontCustom: '',
  bodyFontSize: 14,
  // user:“消息正文 行距 1.2~2.0”+(默认取会话正文现有观感 14px/1.5，装好设置项后
  // 不改设置时排版与之前完全一致。)
  bodyLineHeight: 1.5,
  bodyParaGap: 12,
  bodyContainer: 'none',

  procTitleFont: 'inherit',
  procTitleFontCustom: '',
  procTitleFontSize: 12,
  procTitleIcon: true,
  procTitleContainer: 'none',

  procBodyFont: 'inherit',
  procBodyFontCustom: '',
  procBodyFontSize: 12,
  // user:“--ms-proc-body-line-height 默认 1.65（范围 1.2~1.8）”+(与过程行已写死的兜底 6/10/1.65 对齐，设置项一动观感才不跳)。
  procBodyLineHeight: 1.65,
  procLines1: 6,
  procLines2: 10,
  // user:“所有过程行展开后均需配备专属容器，严禁直接裸露纯文本”+“思考过程 推荐默认
  // 容器形态 卡片式”+(过程行展开内容的默认容器是卡片，不是裸文本。)
  procBodyContainer: 'card',

  borderStyle: 'solid',
  borderWidth: 1,
  borderColor: '',
  fillPreset: 'surface',
  fillColor: '',
  fillAlpha: 40,
  blur: false,

  colorTheme: 'mono',
  monoFollowAccent: true,
  monoColor: '#8b5cf6',
  shimmer: false,
  shimmerScope: 'running',
}

/** 幻彩主题：浅色走高饱和通透的 Vibrant，深色切低明度防刺眼的 Muted/Neon-Dark。 */
const CHROMATIC_PALETTES = {
  light: {
    fill: '#8b5cf6',
    border: '#a855f7',
    shimmer: '#f472b6',
    gradient: 'linear-gradient(120deg, #ff8a3d 0%, #ff4d8d 32%, #8b5cf6 66%, #22d3ee 100%)',
  },
  dark: {
    fill: '#4c3a86',
    border: '#6d54b5',
    shimmer: '#c084fc',
    gradient: 'linear-gradient(120deg, #7a3f1f 0%, #7a2f52 32%, #4a3a8f 66%, #1f6a7a 100%)',
  },
} as const

const FONT_STACKS = {
  system: 'system-ui, -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
  sans: 'var(--font-sans, Inter, "Noto Sans SC", sans-serif)',
  serif: 'Georgia, "Songti SC", "Noto Serif SC", "Times New Roman", serif',
  mono: 'var(--font-mono, "JetBrains Mono", Consolas, monospace)',
} as const

const HEX_COLOR = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/
const RGB_COLOR = /^rgba?\(\s*\d{1,3}\s*[, ]\s*\d{1,3}\s*[, ]\s*\d{1,3}\s*(?:[,/]\s*(?:\d{1,3}%?|0?\.\d+)\s*)?\)$/

/** 只接受 HEX / RGB / RGBA 字面量，其它输入一律回落，避免把任意字符串塞进 CSS。 */
export function normalizeCssColor(value: unknown, fallback: string): string {
  if (typeof value !== 'string') return fallback
  const text = value.trim()
  if (HEX_COLOR.test(text) || RGB_COLOR.test(text)) return text
  return fallback
}

function clampNumber(value: unknown, min: number, max: number, fallback: number, step = 1): number {
  const numeric = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(numeric)) return fallback
  const stepped = step > 0 ? Math.round(numeric / step) * step : numeric
  const bounded = Math.min(max, Math.max(min, stepped))
  // 浮点步长（0.1）会留下 1.5000000000000002 这类尾巴，统一收到三位小数。
  return Math.round(bounded * 1000) / 1000
}

function pickOption<T extends string>(value: unknown, options: readonly T[], fallback: T): T {
  return typeof value === 'string' && (options as readonly string[]).includes(value) ? value as T : fallback
}

function normalizeBorderWidth(value: unknown): number {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return DEFAULT_MESSAGE_STREAM.borderWidth
  return MESSAGE_STREAM_BORDER_WIDTHS.reduce(
    (best, candidate) => (Math.abs(candidate - numeric) < Math.abs(best - numeric) ? candidate : best),
    MESSAGE_STREAM_BORDER_WIDTHS[0] as number,
  )
}

/** 自定义字体名只留安全字符，避免把引号/分号之类的语法片段带进 CSS。 */
export function sanitizeFontName(value: unknown): string {
  if (typeof value !== 'string') return ''
  return value
    .replace(/[^\p{L}\p{N} \-_.]/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 60)
}

function fontStack(key: MessageStreamFontKey, custom: string): string {
  if (key === 'custom') {
    const name = sanitizeFontName(custom)
    return name ? `"${name}", ${FONT_STACKS.sans}` : FONT_STACKS.sans
  }
  return FONT_STACKS[key] ?? FONT_STACKS.system
}

function inheritFontStack(key: MessageStreamInheritFontKey, custom: string): string {
  return key === 'inherit' ? 'inherit' : fontStack(key, custom)
}

/**
 * 脏输入夹到合法区间：老版本数据缺字段、手改 JSON、跨版本导入都从这里过一遍，
 * 永远返回一份可以直接渲染的完整配置。
 */
export function normalizeMessageStream(input: unknown): MessageStreamSettings {
  const source = (input && typeof input === 'object' && !Array.isArray(input) ? input : {}) as Record<string, unknown>
  const d = DEFAULT_MESSAGE_STREAM
  return {
    bodyFont: pickOption(source.bodyFont, ['system', 'sans', 'serif', 'mono', 'custom'] as const, d.bodyFont),
    bodyFontCustom: sanitizeFontName(source.bodyFontCustom),
    bodyFontSize: clampNumber(source.bodyFontSize, 12, 20, d.bodyFontSize, 1),
    // user:“--ms-proc-body-line-height 默认 1.65”+(1.65 不在 0.1 的网格上，行距统一按 0.05 吸附：
    // 滑条仍是 0.1 步长，导入/默认值也不会被改写成 1.6)。
    bodyLineHeight: clampNumber(source.bodyLineHeight, 1.2, 2, d.bodyLineHeight, 0.05),
    bodyParaGap: clampNumber(source.bodyParaGap, 0, 24, d.bodyParaGap, 2),
    bodyContainer: pickOption(source.bodyContainer, ['none', 'bordered', 'card'] as const, d.bodyContainer),

    procTitleFont: pickOption(source.procTitleFont, ['inherit', 'system', 'sans', 'serif', 'mono', 'custom'] as const, d.procTitleFont),
    procTitleFontCustom: sanitizeFontName(source.procTitleFontCustom),
    procTitleFontSize: clampNumber(source.procTitleFontSize, 11, 16, d.procTitleFontSize, 1),
    procTitleIcon: typeof source.procTitleIcon === 'boolean' ? source.procTitleIcon : d.procTitleIcon,
    procTitleContainer: pickOption(source.procTitleContainer, ['none', 'bordered', 'pill'] as const, d.procTitleContainer),

    procBodyFont: pickOption(source.procBodyFont, ['inherit', 'system', 'sans', 'serif', 'mono', 'custom'] as const, d.procBodyFont),
    procBodyFontCustom: sanitizeFontName(source.procBodyFontCustom),
    procBodyFontSize: clampNumber(source.procBodyFontSize, 11, 16, d.procBodyFontSize, 1),
    procBodyLineHeight: clampNumber(source.procBodyLineHeight, 1.2, 1.8, d.procBodyLineHeight, 0.05),
    procLines1: clampNumber(source.procLines1, 3, 8, d.procLines1, 1),
    procLines2: clampNumber(source.procLines2, 8, 20, d.procLines2, 1),
    procBodyContainer: pickOption(source.procBodyContainer, ['none', 'bordered', 'card'] as const, d.procBodyContainer),

    borderStyle: pickOption(source.borderStyle, ['solid', 'dashed', 'dotted'] as const, d.borderStyle),
    borderWidth: normalizeBorderWidth(source.borderWidth),
    borderColor: normalizeCssColor(source.borderColor, ''),
    fillPreset: pickOption(source.fillPreset, ['surface', 'accent', 'neutral', 'custom'] as const, d.fillPreset),
    fillColor: normalizeCssColor(source.fillColor, ''),
    fillAlpha: clampNumber(source.fillAlpha, 0, 100, d.fillAlpha, 5),
    blur: typeof source.blur === 'boolean' ? source.blur : d.blur,

    colorTheme: pickOption(source.colorTheme, ['mono', 'chromatic'] as const, d.colorTheme),
    monoFollowAccent: typeof source.monoFollowAccent === 'boolean' ? source.monoFollowAccent : d.monoFollowAccent,
    monoColor: normalizeCssColor(source.monoColor, d.monoColor),
    shimmer: typeof source.shimmer === 'boolean' ? source.shimmer : d.shimmer,
    shimmerScope: pickOption(source.shimmerScope, ['running', 'always'] as const, d.shimmerScope),
  }
}

function accentColor(settings: MessageStreamSettings): string {
  return settings.monoFollowAccent
    ? 'var(--blue, #79bcff)'
    : normalizeCssColor(settings.monoColor, DEFAULT_MESSAGE_STREAM.monoColor)
}

function resolveFill(settings: MessageStreamSettings, themeMode: 'light' | 'dark'): { color: string; gradient: string } {
  // user:“浅色模式自动用高饱和通透的 Vibrant 渐变色阶，深色模式自动切低明度防刺眼的 Muted/Neon-Dark”
  // +(幻彩主题不吃填充预设：它的色阶只由 effectiveThemeMode 决定，不允许手动挑。)
  if (settings.colorTheme === 'chromatic') {
    const palette = CHROMATIC_PALETTES[themeMode]
    return { color: palette.fill, gradient: palette.gradient }
  }
  if (settings.fillPreset === 'custom') {
    return { color: normalizeCssColor(settings.fillColor, accentColor(settings)), gradient: 'none' }
  }
  if (settings.fillPreset === 'accent') return { color: accentColor(settings), gradient: 'none' }
  if (settings.fillPreset === 'neutral') return { color: 'var(--muted, #a7a29b)', gradient: 'none' }
  return { color: 'var(--panel-2, #1d1e1e)', gradient: 'none' }
}

function resolveBorderColor(settings: MessageStreamSettings, themeMode: 'light' | 'dark'): string {
  const explicit = normalizeCssColor(settings.borderColor, '')
  if (explicit) return explicit
  if (settings.colorTheme === 'chromatic') return CHROMATIC_PALETTES[themeMode].border
  return 'color-mix(in srgb, var(--theme-main-text, #f2efeb) 22%, transparent)'
}

function resolveShimmerColor(settings: MessageStreamSettings, themeMode: 'light' | 'dark'): string {
  if (settings.colorTheme === 'chromatic') return CHROMATIC_PALETTES[themeMode].shimmer
  return `color-mix(in srgb, ${accentColor(settings)} 60%, var(--theme-main-text, #ffffff))`
}

/**
 * user:“边框粗细分容器：新增 --ms-proc-border-width-bordered（1/1.5/2/3 可选），
 * 把现有的 --ms-proc-border-width 留给 pill/card 恒为 2px”
 * +(两条变量各管一边：bordered 与 card 同时存在时不会再互相拉扯。)
 */

/** 胶囊与卡片的描边粗细恒为 2px（胶囊是单行视觉签名，卡片靠 2px 立住轮廓）。 */
export const MESSAGE_STREAM_SIGNATURE_BORDER_WIDTH = 2

/** 「边框」模式自己的粗细：1 / 1.5 / 2 / 3。 */
export function messageStreamBorderedWidth(settings: MessageStreamSettings): number {
  return normalizeBorderWidth(settings.borderWidth)
}

/** 正文=卡片 且 过程行内容=卡片：内层要降一级明度对比，否则嵌套脏乱。 */
export function isNestedCardConflict(settings: MessageStreamSettings): boolean {
  return settings.bodyContainer === 'card' && settings.procBodyContainer === 'card'
}

/** 落成 document.documentElement 上的 CSS 变量集合。 */
export function messageStreamCssVars(
  input: unknown,
  options: { themeMode?: 'light' | 'dark' } = {},
): Record<string, string> {
  const settings = normalizeMessageStream(input)
  const themeMode = options.themeMode === 'dark' ? 'dark' : 'light'
  const fill = resolveFill(settings, themeMode)
  const borderedWidth = messageStreamBorderedWidth(settings)
  const nested = isNestedCardConflict(settings)
  return {
    // —— 消息正文 ——
    '--ms-body-font-family': fontStack(settings.bodyFont, settings.bodyFontCustom),
    '--ms-body-font-size': `${settings.bodyFontSize}px`,
    '--ms-body-line-height': String(settings.bodyLineHeight),
    '--ms-body-para-gap': `${settings.bodyParaGap}px`,

    // —— 过程行标题（固定单行垂直居中，所以只给字号不给行距）——
    '--ms-proc-title-font-family': inheritFontStack(settings.procTitleFont, settings.procTitleFontCustom),
    '--ms-proc-title-font-size': `${settings.procTitleFontSize}px`,
    '--ms-proc-title-icon': settings.procTitleIcon ? '1' : '0',

    // —— 过程行展开内容 ——
    '--ms-proc-body-font-family': inheritFontStack(settings.procBodyFont, settings.procBodyFontCustom),
    '--ms-proc-body-font-size': `${settings.procBodyFontSize}px`,
    '--ms-proc-body-line-height': String(settings.procBodyLineHeight),
    '--ms-proc-lines-1': String(settings.procLines1),
    '--ms-proc-lines-2': String(settings.procLines2),
    '--ms-proc-body-pad-y': `${MESSAGE_STREAM_BODY_PAD_Y}px`,

    // —— 容器共用 ——
    '--ms-proc-radius-sm': '8px',
    '--ms-proc-radius-lg': '12px',
    // user:“把现有的 --ms-proc-border-width 留给 pill/card 恒为 2px”+(bordered 走下面那条)。
    '--ms-proc-border-width': `${MESSAGE_STREAM_SIGNATURE_BORDER_WIDTH}px`,
    '--ms-proc-border-width-bordered': `${borderedWidth}px`,
    '--ms-proc-border-style': settings.borderStyle,
    '--ms-proc-border-color': resolveBorderColor(settings, themeMode),
    '--ms-proc-fill-color': fill.color,
    // 注意：这是**百分比字符串**（"40%"），不是 0~1 小数，也不是裸数字。
    // 正确消费：color-mix(in srgb, var(--ms-proc-fill-color) var(--ms-proc-fill-alpha), transparent)
    '--ms-proc-fill-alpha': `${settings.fillAlpha}%`,
    '--ms-proc-blur': settings.blur ? 'blur(10px)' : 'none',
    '--ms-proc-shimmer-color': resolveShimmerColor(settings, themeMode),

    // —— 附加：幻彩渐变色阶与嵌套降级 ——
    '--ms-proc-fill-gradient': fill.gradient,
    '--ms-proc-fill-color-inner': fill.color,
    '--ms-proc-fill-alpha-inner': `${nested ? Math.max(0, settings.fillAlpha - 20) : settings.fillAlpha}%`,
  }
}

/** 落成 document.documentElement 上的 data-* 属性。 */
export function messageStreamRootAttrs(
  input: unknown,
  themeMode: 'light' | 'dark' = 'light',
): Record<string, string> {
  const settings = normalizeMessageStream(input)
  return {
    'data-ms-body-container': settings.bodyContainer,
    'data-ms-proc-title-container': settings.procTitleContainer,
    'data-ms-proc-body-container': settings.procBodyContainer,
    'data-ms-shimmer': settings.shimmer ? '1' : '0',
    'data-ms-shimmer-scope': settings.shimmerScope,
    'data-ms-theme-mode': themeMode === 'dark' ? 'dark' : 'light',
  }
}

/** 导出给用户复制的 JSON：带 kind + version，方便以后迁移。 */
export function exportMessageStreamJson(settings: MessageStreamSettings): string {
  return JSON.stringify({
    kind: MESSAGE_STREAM_EXPORT_KIND,
    version: MESSAGE_STREAM_EXPORT_VERSION,
    settings: normalizeMessageStream(settings),
  }, null, 2)
}

/**
 * 导入 JSON：坏 JSON 抛可读错误（调用方接住即可，界面不炸），
 * 字段越界一律夹紧而不是报错。
 */
export function importMessageStreamJson(raw: string): MessageStreamSettings {
  let parsed: unknown
  try {
    parsed = JSON.parse(typeof raw === 'string' ? raw : String(raw ?? ''))
  } catch {
    throw new Error('样式 JSON 解析失败：内容不是合法 JSON')
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('样式 JSON 解析失败：顶层必须是对象')
  }
  const record = parsed as Record<string, unknown>
  if (record.kind !== undefined && record.kind !== MESSAGE_STREAM_EXPORT_KIND) {
    throw new Error('样式 JSON 解析失败：这不是消息流样式的配置')
  }
  if (typeof record.version === 'number' && record.version > MESSAGE_STREAM_EXPORT_VERSION) {
    throw new Error(`样式 JSON 版本 ${record.version} 高于当前支持的 ${MESSAGE_STREAM_EXPORT_VERSION}`)
  }
  // 兼容直接贴裸设置对象的情况。
  const payload = record.settings ?? record
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    throw new Error('样式 JSON 解析失败：缺少 settings 字段')
  }
  return normalizeMessageStream(payload)
}
