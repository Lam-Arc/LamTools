/**
 * Theme helpers — gradient generation, normalization, preset utilities
 *
 * Shared theme helpers for member settings and workbench views.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ThemeStop {
  color: string
  position: number
}

export type ThemeArea = 'backdrop' | 'main' | 'composer' | 'control'

/**
 * user:“色彩渐变图像作为一个 mark 节点，然后玻璃应该单独作为一个 preference 节点”+
 * (填充只描述区域里放什么：纯色、渐变或图片；图片保留动图原样。)
 */
export type ThemeFillMode = 'solid' | 'gradient' | 'image'
/**
 * user:“玻璃应该单独作为一个 preference 节点”+
 * (玻璃是区域表面的材质偏好，与填充分开：关闭 / 高透着色 / 低透着色；
 *  填充的颜色、渐变或图片就是玻璃的着色内容。)
 */
export type ThemeGlassPreference = 'off' | 'high' | 'low'
export type ThemeImageFit = 'cover' | 'contain' | 'tile' | 'stretch'
export type ThemeMode = 'system' | 'light' | 'dark' | 'scheduled'
/** What a theme mode collapses to once the system preference or the schedule is evaluated. */
export type ResolvedThemeMode = 'light' | 'dark'

/** Daily switch points for `scheduled`: the local `HH:MM` the light and the dark stretch start. */
export interface ThemeSchedule {
  lightFrom: string
  darkFrom: string
}

export const DEFAULT_THEME_SCHEDULE: ThemeSchedule = { lightFrom: '07:00', darkFrom: '19:00' }

export function normalizeThemeSchedule(value: unknown): ThemeSchedule {
  const source = (value && typeof value === 'object' ? value : {}) as Partial<ThemeSchedule>
  return {
    lightFrom: normalizeClockTime(source.lightFrom) ?? DEFAULT_THEME_SCHEDULE.lightFrom,
    darkFrom: normalizeClockTime(source.darkFrom) ?? DEFAULT_THEME_SCHEDULE.darkFrom,
  }
}

/**
 * Which mode the schedule is on right now. `lightFrom` opens the light stretch
 * and `darkFrom` the dark one, so whichever starts later wraps past midnight;
 * identical times leave the whole day in the light stretch.
 */
export function resolveScheduledThemeMode(schedule: ThemeSchedule, now: Date = new Date()): ResolvedThemeMode {
  const light = minutesOfDay(schedule.lightFrom)
  const dark = minutesOfDay(schedule.darkFrom)
  if (light === null || dark === null || light === dark) return 'light'
  const minutes = now.getHours() * 60 + now.getMinutes()
  const inLightStretch = light < dark
    ? minutes >= light && minutes < dark
    : minutes >= light || minutes < dark
  return inLightStretch ? 'light' : 'dark'
}

function normalizeClockTime(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const match = /^(\d{1,2}):(\d{2})$/.exec(value.trim())
  if (!match) return null
  const hours = Number(match[1])
  const minutes = Number(match[2])
  if (hours > 23 || minutes > 59) return null
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`
}

function minutesOfDay(value: string): number | null {
  const normalized = normalizeClockTime(value)
  if (!normalized) return null
  const [hours, minutes] = normalized.split(':').map(Number)
  return hours * 60 + minutes
}

export interface ThemeData {
  backdropStops: ThemeStop[]
  backdropAngle: number
  backdropText: string
  backdropFill: ThemeFillMode
  backdropGlass: ThemeGlassPreference
  /** 图片样式的 data URL；空串表示还没选图。 */
  backdropImage: string
  backdropImageFit: ThemeImageFit
  mainStops: ThemeStop[]
  mainAngle: number
  mainText: string
  mainOpacity: number
  mainFill: ThemeFillMode
  mainGlass: ThemeGlassPreference
  mainImage: string
  mainImageFit: ThemeImageFit
  composerStops: ThemeStop[]
  composerAngle: number
  composerText: string
  composerOpacity: number
  composerFill: ThemeFillMode
  composerGlass: ThemeGlassPreference
  composerImage: string
  composerImageFit: ThemeImageFit
  controlStops: ThemeStop[]
  controlAngle: number
  controlText: string
  controlOpacity: number
  controlFill: ThemeFillMode
  controlGlass: ThemeGlassPreference
  controlImage: string
  controlImageFit: ThemeImageFit
  /** Accent used by non-semantic process-row state icons. */
  processIconColor: string
}

export interface ThemePreset {
  id: string
  group: 'gradient' | 'solid' | 'mixed' | 'theme'
  name: string
  note: string
  method?: string
  rationale?: string
  theme: Partial<ThemeData>
  lightTheme?: Partial<ThemeData>
  darkTheme?: Partial<ThemeData>
}

export function themeForMode(preset: ThemePreset, mode: ResolvedThemeMode): Partial<ThemeData> {
  return mode === 'dark' ? preset.darkTheme || preset.theme : preset.lightTheme || preset.theme
}

// ---------------------------------------------------------------------------
// Sunday defaults. The palette is deliberately flat: warm ivory in light
// mode, neutral graphite in dark mode, with high-contrast control surfaces
// pairing graphite with ivory in light mode and ivory with graphite in dark.
//
// These representatives come from the supplied 1254px reference marks. We
// sampled only opaque interior/frame regions, then used the median (rather
// than a single anti-aliased pixel): dark graphite #1d1f24, light ivory
// #fdfbf6, dark frame #818289, and light frame #d2d8e6. The light backdrop
// uses the sampled frame solid; the dark backdrop uses the user-selected
// graphite #3a3b3f. Chat surfaces use the sampled ivory/graphite
// solids, and controls use the paired brand solids so each area remains flat
// while retaining the reference's contrast hierarchy.
// DEFAULT_THEME stays the dark-compatible alias used by single-theme callers.
// ---------------------------------------------------------------------------

export const SUNDAY_DARK_THEME: ThemeData = {
  backdropAngle: 180,
  backdropStops: [{ color: '#3A3B3F', position: 0 }],
  backdropText: '#FBF7F0',
  backdropFill: 'solid',
  backdropGlass: 'off',
  backdropImage: '',
  backdropImageFit: 'cover',
  mainAngle: 180,
  mainStops: [{ color: '#1B1D22', position: 0 }],
  mainText: '#FBF7F0',
  mainOpacity: 1,
  mainFill: 'solid',
  mainGlass: 'off',
  mainImage: '',
  mainImageFit: 'cover',
  composerAngle: 180,
  composerStops: [{ color: '#22242A', position: 0 }],
  composerText: '#FBF7F0',
  composerOpacity: 1,
  composerFill: 'solid',
  composerGlass: 'off',
  composerImage: '',
  composerImageFit: 'cover',
  controlAngle: 180,
  controlStops: [{ color: '#FBF7F0', position: 0 }],
  controlText: '#2E3138',
  controlOpacity: 1,
  controlFill: 'solid',
  controlGlass: 'off',
  controlImage: '',
  controlImageFit: 'cover',
  processIconColor: '#888990',
}

export const SUNDAY_LIGHT_THEME: ThemeData = {
  backdropStops: [{ color: '#D2D8E6', position: 0 }],
  backdropAngle: 180,
  backdropText: '#2E3138',
  backdropFill: 'solid',
  backdropGlass: 'off',
  backdropImage: '',
  backdropImageFit: 'cover',
  mainStops: [{ color: '#FDFBF7', position: 0 }],
  mainAngle: 180,
  mainText: '#2E3138',
  mainOpacity: 1,
  mainFill: 'solid',
  mainGlass: 'off',
  mainImage: '',
  mainImageFit: 'cover',
  composerStops: [{ color: '#F7F4EE', position: 0 }],
  composerAngle: 180,
  composerText: '#2E3138',
  composerOpacity: 1,
  composerFill: 'solid',
  composerGlass: 'off',
  composerImage: '',
  composerImageFit: 'cover',
  controlStops: [{ color: '#2E3138', position: 0 }],
  controlAngle: 180,
  controlText: '#FBF7F0',
  controlOpacity: 1,
  controlFill: 'solid',
  controlGlass: 'off',
  controlImage: '',
  controlImageFit: 'cover',
  processIconColor: '#C9D0DF',
}

/** 旧主题没有样式字段：按节点数量推断，单节点=纯色，多节点=渐变。 */
export function inferThemeFill(stops: ThemeStop[] | undefined): ThemeFillMode {
  return Array.isArray(stops) && stops.length > 1 ? 'gradient' : 'solid'
}

export function normalizeThemeFill(value: unknown, stops?: ThemeStop[]): ThemeFillMode {
  if (value === 'solid' || value === 'gradient' || value === 'image') return value
  // 旧版把玻璃当成一种填充：迁移成纯色填充 + 玻璃材质（见 normalizeThemeGlass）。
  if (value === 'glass') return 'solid'
  return inferThemeFill(stops)
}

/** 旧数据里 fill 可能仍是 'glass'；类型已移除该值，运行时按未知值判断。 */
export function isLegacyGlassFill(value: unknown): boolean {
  return value === 'glass'
}

export function normalizeThemeGlass(value: unknown, legacyEnabled = false): ThemeGlassPreference {
  if (value === 'low' || value === 'high') return value
  // 旧版 fill='glass' 就等于玻璃开启：此时字段即使写着 off 也按高透迁移。
  return legacyEnabled ? 'high' : 'off'
}

export function normalizeThemeImageFit(value: unknown): ThemeImageFit {
  return value === 'contain' || value === 'tile' || value === 'stretch' ? value : 'cover'
}

type ThemeAppearanceKey =
  | `${ThemeArea}Fill`
  | `${ThemeArea}Glass`
  | `${ThemeArea}Image`
  | `${ThemeArea}ImageFit`

type ThemeCore = Omit<ThemeData, ThemeAppearanceKey>

/** 旧默认主题字面量补上推断出的样式字段，便于逐字比对迁移。 */
function withInferredFills(core: ThemeCore): ThemeData {
  const appearance = (stops: ThemeStop[]) => ({
    fill: inferThemeFill(stops),
    glass: 'off' as const,
    image: '',
    imageFit: 'cover' as const,
  })
  const backdrop = appearance(core.backdropStops)
  const main = appearance(core.mainStops)
  const composer = appearance(core.composerStops)
  const control = appearance(core.controlStops)
  return {
    ...core,
    backdropFill: backdrop.fill,
    backdropGlass: backdrop.glass,
    backdropImage: backdrop.image,
    backdropImageFit: backdrop.imageFit,
    mainFill: main.fill,
    mainGlass: main.glass,
    mainImage: main.image,
    mainImageFit: main.imageFit,
    composerFill: composer.fill,
    composerGlass: composer.glass,
    composerImage: composer.image,
    composerImageFit: composer.imageFit,
    controlFill: control.fill,
    controlGlass: control.glass,
    controlImage: control.image,
    controlImageFit: control.imageFit,
  }
}

/** Previous frame-gray dark backdrop, retained for exact migration. */
export const LEGACY_SUNDAY_FRAME_DARK_THEME: ThemeData = withInferredFills({
  backdropAngle: 180,
  backdropStops: [{ color: '#818289', position: 0 }],
  backdropText: '#FBF7F0',
  mainAngle: 180,
  mainStops: [{ color: '#1B1D22', position: 0 }],
  mainText: '#FBF7F0',
  mainOpacity: 1,
  composerAngle: 180,
  composerStops: [{ color: '#1B1D22', position: 0 }],
  composerText: '#FBF7F0',
  composerOpacity: 1,
  controlAngle: 180,
  controlStops: [{ color: '#FBF7F0', position: 0 }],
  controlText: '#2E3138',
  controlOpacity: 1,
  processIconColor: '#888990',
})

/** Previous Sunday defaults with composer and chat on the same solid. */
export const LEGACY_SUNDAY_UNIFIED_COMPOSER_DARK_THEME: ThemeData = withInferredFills({
  ...SUNDAY_DARK_THEME,
  composerStops: [{ color: '#1B1D22', position: 0 }],
})

export const LEGACY_SUNDAY_UNIFIED_COMPOSER_LIGHT_THEME: ThemeData = withInferredFills({
  ...SUNDAY_LIGHT_THEME,
  composerStops: [{ color: '#FDFBF7', position: 0 }],
})

/** Immediately previous sampled flat Sunday defaults, retained for exact migration. */
export const LEGACY_SUNDAY_FLAT_DARK_THEME: ThemeData = withInferredFills({
  backdropAngle: 180,
  backdropStops: [{ color: '#121419', position: 0 }],
  backdropText: '#FBF7F0',
  mainAngle: 180,
  mainStops: [{ color: '#1B1D22', position: 0 }],
  mainText: '#FBF7F0',
  mainOpacity: 1,
  composerAngle: 180,
  composerStops: [{ color: '#1B1D22', position: 0 }],
  composerText: '#FBF7F0',
  composerOpacity: 1,
  controlAngle: 180,
  controlStops: [{ color: '#35383F', position: 0 }],
  controlText: '#FBF7F0',
  controlOpacity: 1,
  processIconColor: '#888990',
})

export const LEGACY_SUNDAY_FLAT_LIGHT_THEME: ThemeData = withInferredFills({
  backdropAngle: 180,
  backdropStops: [{ color: '#FCF9F5', position: 0 }],
  backdropText: '#2E3138',
  mainAngle: 180,
  mainStops: [{ color: '#FDFBF7', position: 0 }],
  mainText: '#2E3138',
  mainOpacity: 1,
  composerAngle: 180,
  composerStops: [{ color: '#FDFBF7', position: 0 }],
  composerText: '#2E3138',
  composerOpacity: 1,
  controlAngle: 180,
  controlStops: [{ color: '#D6DCEA', position: 0 }],
  controlText: '#2E3138',
  controlOpacity: 1,
  processIconColor: '#C9D0DF',
})

/** Immediately previous inverted-control defaults, retained for exact migration. */
export const LEGACY_SUNDAY_INVERTED_DARK_THEME: ThemeData = withInferredFills({
  backdropAngle: 180,
  backdropStops: [{ color: '#121419', position: 0 }],
  backdropText: '#FBF7F0',
  mainAngle: 180,
  mainStops: [{ color: '#1B1D22', position: 0 }],
  mainText: '#FBF7F0',
  mainOpacity: 1,
  composerAngle: 180,
  composerStops: [{ color: '#1B1D22', position: 0 }],
  composerText: '#FBF7F0',
  composerOpacity: 1,
  controlAngle: 180,
  controlStops: [{ color: '#FBF7F0', position: 0 }],
  controlText: '#2E3138',
  controlOpacity: 1,
  processIconColor: '#888990',
})

export const LEGACY_SUNDAY_INVERTED_LIGHT_THEME: ThemeData = withInferredFills({
  backdropAngle: 180,
  backdropStops: [{ color: '#FCF9F5', position: 0 }],
  backdropText: '#2E3138',
  mainAngle: 180,
  mainStops: [{ color: '#FDFBF7', position: 0 }],
  mainText: '#2E3138',
  mainOpacity: 1,
  composerAngle: 180,
  composerStops: [{ color: '#FDFBF7', position: 0 }],
  composerText: '#2E3138',
  composerOpacity: 1,
  controlAngle: 180,
  controlStops: [{ color: '#2E3138', position: 0 }],
  controlText: '#FBF7F0',
  controlOpacity: 1,
  processIconColor: '#C9D0DF',
})

/** Previous colorful Sunday defaults, retained only for exact migration. */
export const LEGACY_SUNDAY_DARK_THEME: ThemeData = withInferredFills({
  backdropAngle: 112,
  backdropStops: [
    { color: '#171926', position: 0 },
    { color: '#241c31', position: 56 },
    { color: '#182438', position: 100 },
  ],
  backdropText: '#f4efff',
  mainAngle: 145,
  mainStops: [
    { color: '#11131d', position: 0 },
    { color: '#181521', position: 100 },
  ],
  mainText: '#f5f2fb',
  mainOpacity: 1,
  composerAngle: 105,
  composerStops: [
    { color: '#252538', position: 0 },
    { color: '#2b2137', position: 100 },
  ],
  composerText: '#f7f3fc',
  composerOpacity: 1,
  controlAngle: 105,
  controlStops: [
    { color: '#29416d', position: 0 },
    { color: '#503269', position: 100 },
  ],
  controlText: '#fbf7ff',
  controlOpacity: 1,
  processIconColor: '#a693ff',
})

export const LEGACY_SUNDAY_LIGHT_THEME: ThemeData = withInferredFills({
  backdropStops: [
    { color: '#fff0df', position: 0 },
    { color: '#f7efff', position: 58 },
    { color: '#edf2ff', position: 100 },
  ],
  backdropAngle: 112,
  backdropText: '#17265a',
  mainStops: [
    { color: '#fffdf8', position: 0 },
    { color: '#f9f9f4', position: 100 },
  ],
  mainAngle: 145,
  mainText: '#162451',
  mainOpacity: 1,
  composerStops: [
    { color: '#f8f6ff', position: 0 },
    { color: '#edf3ff', position: 100 },
  ],
  composerAngle: 105,
  composerText: '#17275a',
  composerOpacity: 1,
  controlStops: [
    { color: '#dcecff', position: 0 },
    { color: '#ecdfff', position: 100 },
  ],
  controlAngle: 105,
  controlText: '#183b83',
  controlOpacity: 1,
  processIconColor: '#6755e8',
})

export const DEFAULT_THEME: ThemeData = SUNDAY_DARK_THEME

// ---------------------------------------------------------------------------
// Utility helpers
// ---------------------------------------------------------------------------

export function clampNumber(value: unknown, min: number, max: number, fallback: number): number {
  const numberValue = Number(value)
  if (!Number.isFinite(numberValue)) return fallback
  return Math.min(max, Math.max(min, numberValue))
}

export function normalizeColor(value: unknown, fallback: string): string {
  return typeof value === 'string' && /^#[0-9a-fA-F]{6}$/.test(value) ? value : fallback
}

export function rgbaFromHex(hex: string, opacity: number): string {
  const clean = normalizeColor(hex, '#000000').slice(1)
  const value = Number.parseInt(clean, 16)
  const red = (value >> 16) & 255
  const green = (value >> 8) & 255
  const blue = value & 255
  return `rgba(${red}, ${green}, ${blue}, ${clampNumber(opacity, 0.1, 1, 1)})`
}

/** Normalize gradient stops, collapsing a solid color to its single source node. */
export function normalizeGradientStops(
  value: unknown,
  fallbackStart: string,
  fallbackEnd: string,
): ThemeStop[] {
  const rawStops = Array.isArray(value) ? value : []
  const stops = rawStops
    .map((stop: unknown): ThemeStop | null => {
      if (!stop || typeof stop !== 'object') return null
      const item = stop as Partial<ThemeStop>
      return {
        color: normalizeColor(item.color, fallbackStart),
        position: clampNumber(item.position, 0, 100, 0),
      }
    })
    .filter((s): s is ThemeStop => Boolean(s))

  const baseStops = stops.length
    ? stops
    : [{ color: fallbackStart, position: 0 }, { color: fallbackEnd, position: 100 }]
  const normalized = baseStops
    .slice(0, 8)
    .sort((a, b) => a.position - b.position)
    .map((stop, idx, src) => ({
      color: stop.color,
      position: src.length === 1 || idx === 0 ? 0 : idx === src.length - 1 ? 100 : stop.position,
    }))

  return normalized.every((stop) => stop.color.toLowerCase() === normalized[0].color.toLowerCase())
    ? [{ color: normalized[0].color, position: 0 }]
    : normalized
}

/** Generate a CSS linear-gradient from stops. */
export function gradientFromStops(
  angle: number,
  stops: ThemeStop[],
  opacity: number,
): string {
  const normalized = normalizeGradientStops(
    stops,
    stops[0]?.color || '#000000',
    stops[stops.length - 1]?.color || '#000000',
  )
  const solidColor = normalized.every(
    (stop) => stop.color.toLowerCase() === normalized[0].color.toLowerCase(),
  )
  if (solidColor) return rgbaFromHex(normalized[0].color, opacity)
  const parts = normalized.map(
    (stop) => `${rgbaFromHex(stop.color, opacity)} ${stop.position}%`,
  )
  return `linear-gradient(${clampNumber(angle, 0, 360, 180)}deg, ${parts.join(', ')})`
}

/** Shortcut: generate a 2-stop gradient from start/end colors. */
export function gradientFromThemeColors(
  angle: number,
  start: string,
  end: string,
  opacity: number,
): string {
  return gradientFromStops(angle, [
    { color: start, position: 0 },
    { color: end, position: 100 },
  ], opacity)
}

// ---------------------------------------------------------------------------
// Per-area fill modes: solid / gradient / glass / image
// ---------------------------------------------------------------------------

const AREA_KEYS = {
  backdrop: {
    stops: 'backdropStops', angle: 'backdropAngle', fill: 'backdropFill',
    glass: 'backdropGlass', image: 'backdropImage', imageFit: 'backdropImageFit',
  },
  main: {
    stops: 'mainStops', angle: 'mainAngle', fill: 'mainFill',
    glass: 'mainGlass', image: 'mainImage', imageFit: 'mainImageFit',
  },
  composer: {
    stops: 'composerStops', angle: 'composerAngle', fill: 'composerFill',
    glass: 'composerGlass', image: 'composerImage', imageFit: 'composerImageFit',
  },
  control: {
    stops: 'controlStops', angle: 'controlAngle', fill: 'controlFill',
    glass: 'controlGlass', image: 'controlImage', imageFit: 'controlImageFit',
  },
} as const

export function themeAreaStops(theme: Partial<ThemeData>, area: ThemeArea): ThemeStop[] {
  return (theme[AREA_KEYS[area].stops] as ThemeStop[] | undefined) ?? []
}

export function themeAreaFill(theme: Partial<ThemeData>, area: ThemeArea): ThemeFillMode {
  return normalizeThemeFill(theme[AREA_KEYS[area].fill], themeAreaStops(theme, area))
}

export function themeAreaGlass(theme: Partial<ThemeData>, area: ThemeArea): ThemeGlassPreference {
  return normalizeThemeGlass(theme[AREA_KEYS[area].glass])
}

export function themeAreaImage(theme: Partial<ThemeData>, area: ThemeArea): string {
  return normalizeThemeImage(theme[AREA_KEYS[area].image])
}

export function themeAreaImageFit(theme: Partial<ThemeData>, area: ThemeArea): ThemeImageFit {
  return normalizeThemeImageFit(theme[AREA_KEYS[area].imageFit])
}

/**
 * 玻璃着色浓度，与 variables.css 的玻璃令牌同值：
 * 高透取 `--optical-glass-fallback-tint`（22%），低透取
 * `--optical-glass-low-trans-fallback-tint`（58%）。
 * 这里写死数值而不是 var()：var 在使用处才解析，低透玻璃容器会把自己的
 * 令牌覆盖进同一条声明，导致高透区域被改成低透。
 */
const GLASS_ALPHA: Record<Exclude<ThemeGlassPreference, 'off'>, number> = {
  high: 0.22,
  low: 0.58,
}

const GLASS_FILTER = 'blur(var(--optical-glass-blur, 8px)) saturate(var(--optical-glass-saturation, 1.14)) brightness(var(--optical-glass-brightness, 1.02)) contrast(var(--optical-glass-contrast, 1.03))'

function normalizeThemeImage(value: unknown): string {
  return typeof value === 'string' && value.startsWith('data:image/') ? value : ''
}

function safeImageUrl(value: string): string {
  // data URL 由 FileReader 生成，正常只有 base64/百分号编码；这里再挡一层引号与换行。
  return value.replace(/["\\\n\r]/g, '')
}

function areaOpacity(theme: Partial<ThemeData>, area: ThemeArea): number {
  if (area === 'backdrop') return 1
  const opacity = area === 'main'
    ? theme.mainOpacity
    : area === 'composer'
      ? theme.composerOpacity
      : theme.controlOpacity
  return clampNumber(opacity, 0.1, 1, 1)
}

/** 玻璃开启时由材质决定着色浓度；关闭时沿用区域自己的透明度。 */
function effectiveAlpha(theme: Partial<ThemeData>, area: ThemeArea): number {
  const glass = themeAreaGlass(theme, area)
  return glass === 'off' ? areaOpacity(theme, area) : GLASS_ALPHA[glass]
}

/**
 * user:“色彩渐变图像作为一个 mark 节点，然后玻璃应该单独作为一个 preference 节点”+
 * (底色按填充编译：纯色=单色，渐变=节点渐变，图片=首节点颜色垫底、图片另走
 *  themeAreaImageLayer；玻璃开启时浓度改用材质的两档，关闭时用区域透明度。)
 */
export function themeAreaBackground(theme: Partial<ThemeData>, area: ThemeArea): string {
  const stops = themeAreaStops(theme, area)
  const fill = themeAreaFill(theme, area)
  const base = stops[0]?.color || '#000000'
  const alpha = effectiveAlpha(theme, area)
  if (fill === 'solid' || fill === 'image') return rgbaFromHex(base, alpha)
  const angle = (theme[AREA_KEYS[area].angle] as number | undefined) ?? 180
  return gradientFromStops(angle, stops, alpha)
}

/**
 * 主表面要写的 background-image 层：图片=图片，渐变=渐变，其余=none。
 * 单独一层是因为 `background` 简写后必须再声明一次 image，否则渐变会被默认值抹掉。
 * 玻璃开启时图片上面再盖一层同色薄雾，让图片也呈现玻璃的着色。
 */
export function themeAreaImageLayer(theme: Partial<ThemeData>, area: ThemeArea): string {
  const fill = themeAreaFill(theme, area)
  if (fill === 'image') {
    const image = themeAreaImage(theme, area)
    if (!image) return 'none'
    const layer = `url("${safeImageUrl(image)}")`
    const glass = themeAreaGlass(theme, area)
    if (glass === 'off') return layer
    const tint = rgbaFromHex(themeAreaStops(theme, area)[0]?.color || '#000000', GLASS_ALPHA[glass])
    return `linear-gradient(${tint}, ${tint}), ${layer}`
  }
  if (fill !== 'gradient') return 'none'
  const angle = (theme[AREA_KEYS[area].angle] as number | undefined) ?? 180
  return gradientFromStops(angle, themeAreaStops(theme, area), effectiveAlpha(theme, area))
}

/** 只有开启玻璃材质时挂毛玻璃滤镜；关闭时返回 none，不产生额外合成层。 */
export function themeAreaGlassFilter(theme: Partial<ThemeData>, area: ThemeArea): string {
  return themeAreaGlass(theme, area) === 'off' ? 'none' : GLASS_FILTER
}

export function themeAreaImageSize(theme: Partial<ThemeData>, area: ThemeArea): string {
  switch (themeAreaImageFit(theme, area)) {
    case 'contain': return 'contain'
    case 'tile': return 'auto'
    case 'stretch': return '100% 100%'
    default: return 'cover'
  }
}

export function themeAreaImageRepeat(theme: Partial<ThemeData>, area: ThemeArea): string {
  return themeAreaImageFit(theme, area) === 'tile' ? 'repeat' : 'no-repeat'
}

/** 背面玻璃需要窗口本体透出来，否则玻璃后面永远是同一块实色。 */
export function themeBackdropWindow(theme: Partial<ThemeData>): string {
  return themeAreaGlass(theme, 'backdrop') !== 'off'
    ? 'transparent'
    : rgbaFromHex(themeAreaStops(theme, 'backdrop')[0]?.color || '#000000', 1)
}


// ---------------------------------------------------------------------------
// Normalize a full theme object (fills missing fields from defaults)
// ---------------------------------------------------------------------------

export function normalizeTheme(raw: Partial<ThemeData>): ThemeData {
  const t = { ...DEFAULT_THEME, ...raw }

  t.backdropStops = normalizeGradientStops(
    t.backdropStops,
    DEFAULT_THEME.backdropStops[0].color,
    DEFAULT_THEME.backdropStops[DEFAULT_THEME.backdropStops.length - 1].color,
  )
  t.backdropText = normalizeColor(t.backdropText, DEFAULT_THEME.backdropText)
  t.backdropAngle = clampNumber(t.backdropAngle, 0, 360, DEFAULT_THEME.backdropAngle)

  t.mainStops = normalizeGradientStops(
    t.mainStops,
    DEFAULT_THEME.mainStops[0].color,
    DEFAULT_THEME.mainStops[DEFAULT_THEME.mainStops.length - 1].color,
  )
  t.mainText = normalizeColor(t.mainText, DEFAULT_THEME.mainText)
  t.mainAngle = clampNumber(t.mainAngle, 0, 360, DEFAULT_THEME.mainAngle)
  t.mainOpacity = clampNumber(t.mainOpacity, 0.1, 1, DEFAULT_THEME.mainOpacity)

  t.composerStops = normalizeGradientStops(
    t.composerStops,
    DEFAULT_THEME.composerStops[0].color,
    DEFAULT_THEME.composerStops[DEFAULT_THEME.composerStops.length - 1].color,
  )
  t.composerText = normalizeColor(t.composerText, DEFAULT_THEME.composerText)
  t.composerAngle = clampNumber(t.composerAngle, 0, 360, DEFAULT_THEME.composerAngle)
  t.composerOpacity = clampNumber(t.composerOpacity, 0.1, 1, DEFAULT_THEME.composerOpacity)

  t.controlStops = normalizeGradientStops(
    t.controlStops,
    DEFAULT_THEME.controlStops[0].color,
    DEFAULT_THEME.controlStops[DEFAULT_THEME.controlStops.length - 1].color,
  )
  t.controlText = normalizeColor(t.controlText, DEFAULT_THEME.controlText)
  t.controlAngle = clampNumber(t.controlAngle, 0, 360, DEFAULT_THEME.controlAngle)
  t.controlOpacity = clampNumber(t.controlOpacity, 0.1, 1, DEFAULT_THEME.controlOpacity)
  t.processIconColor = normalizeColor(t.processIconColor, DEFAULT_THEME.processIconColor)

  // 样式字段读 raw 而不是合并结果：合并进来的默认值会把旧主题的渐变推断成纯色。
  t.backdropFill = normalizeThemeFill(raw.backdropFill, t.backdropStops)
  t.backdropGlass = normalizeThemeGlass(raw.backdropGlass, isLegacyGlassFill(raw.backdropFill))
  t.backdropImage = normalizeThemeImage(raw.backdropImage)
  t.backdropImageFit = normalizeThemeImageFit(raw.backdropImageFit)
  t.mainFill = normalizeThemeFill(raw.mainFill, t.mainStops)
  t.mainGlass = normalizeThemeGlass(raw.mainGlass, isLegacyGlassFill(raw.mainFill))
  t.mainImage = normalizeThemeImage(raw.mainImage)
  t.mainImageFit = normalizeThemeImageFit(raw.mainImageFit)
  t.composerFill = normalizeThemeFill(raw.composerFill, t.composerStops)
  t.composerGlass = normalizeThemeGlass(raw.composerGlass, isLegacyGlassFill(raw.composerFill))
  t.composerImage = normalizeThemeImage(raw.composerImage)
  t.composerImageFit = normalizeThemeImageFit(raw.composerImageFit)
  t.controlFill = normalizeThemeFill(raw.controlFill, t.controlStops)
  t.controlGlass = normalizeThemeGlass(raw.controlGlass, isLegacyGlassFill(raw.controlFill))
  t.controlImage = normalizeThemeImage(raw.controlImage)
  t.controlImageFit = normalizeThemeImageFit(raw.controlImageFit)

  return t
}

function isSolidStops(stops: ThemeStop[], color: string): boolean {
  return stops.length >= 1
    && stops.every((stop) => stop.color.toLowerCase() === color.toLowerCase())
}

function themesEqual(left: ThemeData, right: ThemeData): boolean {
  const scalarKeys = [
    'backdropAngle', 'backdropText',
    'mainAngle', 'mainText', 'mainOpacity',
    'composerAngle', 'composerText', 'composerOpacity',
    'controlAngle', 'controlText', 'controlOpacity',
    'backdropFill', 'backdropGlass', 'backdropImage', 'backdropImageFit',
    'mainFill', 'mainGlass', 'mainImage', 'mainImageFit',
    'composerFill', 'composerGlass', 'composerImage', 'composerImageFit',
    'controlFill', 'controlGlass', 'controlImage', 'controlImageFit',
    'processIconColor',
  ] as const
  if (scalarKeys.some((key) => left[key] !== right[key])) return false
  return (['backdrop', 'main', 'composer', 'control'] as ThemeArea[]).every((area) => {
    const leftStops = left[`${area}Stops`]
    const rightStops = right[`${area}Stops`]
    return leftStops.length === rightStops.length && leftStops.every((stop, index) => (
      stop.color === rightStops[index].color && stop.position === rightStops[index].position
    ))
  })
}

function cloneTheme(theme: ThemeData): ThemeData {
  return {
    ...theme,
    backdropStops: theme.backdropStops.map((stop) => ({ ...stop })),
    mainStops: theme.mainStops.map((stop) => ({ ...stop })),
    composerStops: theme.composerStops.map((stop) => ({ ...stop })),
    controlStops: theme.controlStops.map((stop) => ({ ...stop })),
  }
}

/** Replace only exact previous Sunday defaults; preserve every custom theme. */
export function migrateSundayThemeDefaults(
  theme: ThemeData,
  mode?: ResolvedThemeMode,
): ThemeData {
  const legacyMode = themesEqual(theme, LEGACY_SUNDAY_UNIFIED_COMPOSER_LIGHT_THEME)
    ? 'light'
    : themesEqual(theme, LEGACY_SUNDAY_UNIFIED_COMPOSER_DARK_THEME)
      ? 'dark'
      : themesEqual(theme, LEGACY_SUNDAY_INVERTED_LIGHT_THEME)
        ? 'light'
        : themesEqual(theme, LEGACY_SUNDAY_INVERTED_DARK_THEME)
          ? 'dark'
          : themesEqual(theme, LEGACY_SUNDAY_FLAT_LIGHT_THEME)
            ? 'light'
            : themesEqual(theme, LEGACY_SUNDAY_FLAT_DARK_THEME)
              ? 'dark'
              : themesEqual(theme, LEGACY_SUNDAY_LIGHT_THEME)
                ? 'light'
                : themesEqual(theme, LEGACY_SUNDAY_DARK_THEME)
                  ? 'dark'
                  : themesEqual(theme, LEGACY_SUNDAY_FRAME_DARK_THEME)
                    ? 'dark'
                    : null
  if (!legacyMode) return theme
  return cloneTheme((mode || legacyMode) === 'dark' ? SUNDAY_DARK_THEME : SUNDAY_LIGHT_THEME)
}

export function migrateThemeDefaults(theme: ThemeData): ThemeData {
  const migratedSunday = migrateSundayThemeDefaults(theme)
  if (migratedSunday !== theme) return migratedSunday
  if (
    theme.backdropAngle === 180
    && isSolidStops(theme.backdropStops, '#000000')
    && theme.mainAngle === 180
    && isSolidStops(theme.mainStops, '#202020')
    && theme.mainOpacity === 1
  ) {
    return {
      ...theme,
      backdropStops: DEFAULT_THEME.backdropStops.map((stop) => ({ ...stop })),
      mainStops: DEFAULT_THEME.mainStops.map((stop) => ({ ...stop })),
    }
  }
  return theme
}

// ---------------------------------------------------------------------------
// Generate CSS custom properties for a theme
// ---------------------------------------------------------------------------

export interface ThemeCSSVars {
  '--theme-backdrop-background': string
  '--theme-backdrop-text': string
  '--theme-backdrop-solid': string
  '--theme-backdrop-glass-filter': string
  '--theme-backdrop-image': string
  '--theme-backdrop-image-size': string
  '--theme-backdrop-image-repeat': string
  '--theme-backdrop-window': string
  '--theme-main-background': string
  '--theme-main-text': string
  '--theme-main-solid': string
  '--theme-main-soft-background': string
  '--theme-main-subtle-background': string
  '--theme-main-sunken-background': string
  '--theme-main-border': string
  '--theme-main-glass-filter': string
  '--theme-main-image': string
  '--theme-main-image-size': string
  '--theme-main-image-repeat': string
  '--theme-optical-glass-border-color': string
  '--theme-composer-background': string
  '--theme-composer-text': string
  '--theme-composer-soft-background': string
  '--theme-composer-glass-filter': string
  '--theme-composer-image': string
  '--theme-composer-image-size': string
  '--theme-composer-image-repeat': string
  '--theme-control-background': string
  '--theme-control-solid': string
  '--theme-control-text': string
  '--theme-control-soft-background': string
  '--theme-control-glass-filter': string
  '--theme-control-image': string
  '--theme-control-image-size': string
  '--theme-control-image-repeat': string
  '--theme-process-icon-color': string
}

export function relativeLuminance(hex: string): number {
  const clean = normalizeColor(hex, '#000000').slice(1)
  const value = Number.parseInt(clean, 16)
  const channels = [
    (value >> 16) & 255,
    (value >> 8) & 255,
    value & 255,
  ].map((channel) => {
    const srgb = channel / 255
    return srgb <= 0.03928 ? srgb / 12.92 : ((srgb + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
}

export function themeToCSSVars(theme: ThemeData): ThemeCSSVars {
  const lightMain = relativeLuminance(theme.mainText) < 0.45
  const lightComposer = relativeLuminance(theme.composerText) < 0.45
  const lightControl = relativeLuminance(theme.controlText) < 0.45
  const mainBorder = themesEqual(theme, SUNDAY_LIGHT_THEME)
    ? '#D2D8E6'
    : themesEqual(theme, SUNDAY_DARK_THEME)
      ? '#818289'
      : lightMain ? 'rgba(31, 31, 31, 0.10)' : 'rgba(255, 255, 255, 0.10)'
  return {
    '--theme-backdrop-background': themeAreaBackground(theme, 'backdrop'),
    '--theme-backdrop-text': theme.backdropText,
    '--theme-backdrop-solid': theme.backdropStops[0]?.color || '#202020',
    '--theme-backdrop-glass-filter': themeAreaGlassFilter(theme, 'backdrop'),
    '--theme-backdrop-image': themeAreaImageLayer(theme, 'backdrop'),
    '--theme-backdrop-image-size': themeAreaImageSize(theme, 'backdrop'),
    '--theme-backdrop-image-repeat': themeAreaImageRepeat(theme, 'backdrop'),
    '--theme-backdrop-window': themeBackdropWindow(theme),
    '--theme-main-background': themeAreaBackground(theme, 'main'),
    '--theme-main-text': theme.mainText,
    '--theme-main-solid': theme.mainStops[0]?.color || '#111111',
    '--theme-main-soft-background': lightMain ? 'rgba(255, 254, 250, 0.78)' : 'rgba(255, 255, 255, 0.045)',
    '--theme-main-subtle-background': lightMain ? 'rgba(255, 254, 250, 0.52)' : 'rgba(255, 255, 255, 0.028)',
    '--theme-main-sunken-background': lightMain ? 'rgba(31, 31, 31, 0.06)' : 'rgba(0, 0, 0, 0.32)',
    '--theme-main-border': mainBorder,
    '--theme-main-glass-filter': themeAreaGlassFilter(theme, 'main'),
    '--theme-main-image': themeAreaImageLayer(theme, 'main'),
    '--theme-main-image-size': themeAreaImageSize(theme, 'main'),
    '--theme-main-image-repeat': themeAreaImageRepeat(theme, 'main'),
    '--theme-optical-glass-border-color': lightMain ? 'rgb(184 184 184)' : 'rgb(95 95 95)',
    '--theme-composer-background': themeAreaBackground(theme, 'composer'),
    '--theme-composer-text': theme.composerText,
    '--theme-composer-soft-background': lightComposer ? 'rgba(255, 254, 250, 0.70)' : 'rgba(255, 255, 255, 0.045)',
    '--theme-composer-glass-filter': themeAreaGlassFilter(theme, 'composer'),
    '--theme-composer-image': themeAreaImageLayer(theme, 'composer'),
    '--theme-composer-image-size': themeAreaImageSize(theme, 'composer'),
    '--theme-composer-image-repeat': themeAreaImageRepeat(theme, 'composer'),
    '--theme-control-background': themeAreaBackground(theme, 'control'),
    '--theme-control-solid': theme.controlStops[0]?.color || '#3a3834',
    '--theme-control-text': theme.controlText,
    '--theme-control-soft-background': lightControl ? 'rgba(255, 255, 252, 0.82)' : 'rgba(255, 255, 255, 0.055)',
    '--theme-control-glass-filter': themeAreaGlassFilter(theme, 'control'),
    '--theme-control-image': themeAreaImageLayer(theme, 'control'),
    '--theme-control-image-size': themeAreaImageSize(theme, 'control'),
    '--theme-control-image-repeat': themeAreaImageRepeat(theme, 'control'),
    '--theme-process-icon-color': theme.processIconColor,
  }
}

// ---------------------------------------------------------------------------
// Gradient stop editing helpers
// ---------------------------------------------------------------------------

export function addGradientStop(stops: ThemeStop[]): ThemeStop[] {
  if (stops.length >= 8) return stops
  if (stops.length === 1) {
    return [
      { color: stops[0].color, position: 0 },
      { color: stops[0].color, position: 100 },
    ]
  }
  const middle =
    stops.length > 1
      ? Math.round(
          (stops[stops.length - 2].position + stops[stops.length - 1].position) / 2,
        )
      : 50
  const newStops = [...stops]
  newStops.splice(newStops.length - 1, 0, {
    color: stops[stops.length - 1]?.color || '#222222',
    position: middle,
  })
  // Keep the just-added duplicate long enough for the user to choose its new
  // color. The next color/position commit runs sortGradientStops and folds it
  // back into one node if it remains a solid color.
  return newStops
}

export function removeGradientStop(stops: ThemeStop[], index: number): ThemeStop[] {
  if (stops.length <= 1) return stops
  const newStops = [...stops]
  newStops.splice(index, 1)
  return normalizeGradientStops(
    newStops,
    newStops[0].color,
    newStops[newStops.length - 1].color,
  )
}

export function sortGradientStops(stops: ThemeStop[]): ThemeStop[] {
  return normalizeGradientStops(
    stops,
    stops[0]?.color || '#000000',
    stops[stops.length - 1]?.color || '#000000',
  )
}
