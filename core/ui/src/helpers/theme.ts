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

export interface ThemeData {
  backdropStops: ThemeStop[]
  backdropAngle: number
  backdropText: string
  mainStops: ThemeStop[]
  mainAngle: number
  mainText: string
  mainOpacity: number
  composerStops: ThemeStop[]
  composerAngle: number
  composerText: string
  composerOpacity: number
  controlStops: ThemeStop[]
  controlAngle: number
  controlText: string
  controlOpacity: number
}

export interface ThemePreset {
  id: string
  group: 'gradient' | 'solid' | 'mixed'
  name: string
  note: string
  method?: string
  rationale?: string
  theme: Partial<ThemeData>
}

// ---------------------------------------------------------------------------
// Default theme (neutral dark)
// ---------------------------------------------------------------------------

export const DEFAULT_THEME: ThemeData = {
  backdropAngle: 180,
  backdropStops: [
    { color: '#202020', position: 0 },
    { color: '#202020', position: 100 },
  ],
  backdropText: '#f2efeb',
  mainAngle: 180,
  mainStops: [
    { color: '#111111', position: 0 },
    { color: '#111111', position: 100 },
  ],
  mainText: '#f2efeb',
  mainOpacity: 1,
  composerAngle: 180,
  composerStops: [
    { color: '#2c2b29', position: 0 },
    { color: '#222525', position: 100 },
  ],
  composerText: '#f2eee8',
  composerOpacity: 1,
  controlAngle: 180,
  controlStops: [
    { color: '#3a3834', position: 0 },
    { color: '#2d302f', position: 100 },
  ],
  controlText: '#f3efe8',
  controlOpacity: 1,
}

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

/** Normalize an array of gradient stops — ensures at least 2 stops, sorted, capped at 8. */
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

  const baseStops =
    stops.length >= 2
      ? stops
      : [
          { color: fallbackStart, position: 0 },
          { color: fallbackEnd, position: 100 },
        ]

  return baseStops
    .slice(0, 8)
    .sort((a, b) => a.position - b.position)
    .map((stop, idx, src) => ({
      color: stop.color,
      position: idx === 0 ? 0 : idx === src.length - 1 ? 100 : stop.position,
    }))
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

  return t
}

function isSolidStops(stops: ThemeStop[], color: string): boolean {
  return stops.length === 2
    && stops.every((stop) => stop.color.toLowerCase() === color.toLowerCase())
}

export function migrateThemeDefaults(theme: ThemeData): ThemeData {
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
  '--theme-main-background': string
  '--theme-main-text': string
  '--theme-main-solid': string
  '--theme-main-soft-background': string
  '--theme-main-subtle-background': string
  '--theme-main-sunken-background': string
  '--theme-main-border': string
  '--theme-composer-background': string
  '--theme-composer-text': string
  '--theme-composer-soft-background': string
  '--theme-control-background': string
  '--theme-control-text': string
  '--theme-control-soft-background': string
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
  return {
    '--theme-backdrop-background': gradientFromStops(theme.backdropAngle, theme.backdropStops, 1),
    '--theme-backdrop-text': theme.backdropText,
    '--theme-backdrop-solid': theme.backdropStops[0]?.color || '#202020',
    '--theme-main-background': gradientFromStops(theme.mainAngle, theme.mainStops, theme.mainOpacity),
    '--theme-main-text': theme.mainText,
    '--theme-main-solid': theme.mainStops[0]?.color || '#111111',
    '--theme-main-soft-background': lightMain ? 'rgba(255, 254, 250, 0.78)' : 'rgba(255, 255, 255, 0.045)',
    '--theme-main-subtle-background': lightMain ? 'rgba(255, 254, 250, 0.52)' : 'rgba(255, 255, 255, 0.028)',
    '--theme-main-sunken-background': lightMain ? 'rgba(31, 31, 31, 0.06)' : 'rgba(0, 0, 0, 0.32)',
    '--theme-main-border': lightMain ? 'rgba(31, 31, 31, 0.10)' : 'rgba(255, 255, 255, 0.10)',
    '--theme-composer-background': gradientFromStops(theme.composerAngle, theme.composerStops, theme.composerOpacity),
    '--theme-composer-text': theme.composerText,
    '--theme-composer-soft-background': lightComposer ? 'rgba(255, 254, 250, 0.70)' : 'rgba(255, 255, 255, 0.045)',
    '--theme-control-background': gradientFromStops(theme.controlAngle, theme.controlStops, theme.controlOpacity),
    '--theme-control-text': theme.controlText,
    '--theme-control-soft-background': lightControl ? 'rgba(255, 255, 252, 0.82)' : 'rgba(255, 255, 255, 0.055)',
  }
}

// ---------------------------------------------------------------------------
// Gradient stop editing helpers
// ---------------------------------------------------------------------------

export function addGradientStop(stops: ThemeStop[]): ThemeStop[] {
  if (stops.length >= 8) return stops
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
  return normalizeGradientStops(
    newStops,
    newStops[0].color,
    newStops[newStops.length - 1].color,
  )
}

export function removeGradientStop(stops: ThemeStop[], index: number): ThemeStop[] {
  if (stops.length <= 2) return stops
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
