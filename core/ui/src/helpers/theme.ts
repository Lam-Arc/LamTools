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
export type ThemeMode = 'system' | 'light' | 'dark'

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

export function themeForMode(preset: ThemePreset, mode: Exclude<ThemeMode, 'system'>): Partial<ThemeData> {
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
  mainAngle: 180,
  mainStops: [{ color: '#1B1D22', position: 0 }],
  mainText: '#FBF7F0',
  mainOpacity: 1,
  composerAngle: 180,
  composerStops: [{ color: '#22242A', position: 0 }],
  composerText: '#FBF7F0',
  composerOpacity: 1,
  controlAngle: 180,
  controlStops: [{ color: '#FBF7F0', position: 0 }],
  controlText: '#2E3138',
  controlOpacity: 1,
  processIconColor: '#888990',
}

export const SUNDAY_LIGHT_THEME: ThemeData = {
  backdropStops: [{ color: '#D2D8E6', position: 0 }],
  backdropAngle: 180,
  backdropText: '#2E3138',
  mainStops: [{ color: '#FDFBF7', position: 0 }],
  mainAngle: 180,
  mainText: '#2E3138',
  mainOpacity: 1,
  composerStops: [{ color: '#F7F4EE', position: 0 }],
  composerAngle: 180,
  composerText: '#2E3138',
  composerOpacity: 1,
  controlStops: [{ color: '#2E3138', position: 0 }],
  controlAngle: 180,
  controlText: '#FBF7F0',
  controlOpacity: 1,
  processIconColor: '#C9D0DF',
}

/** Previous frame-gray dark backdrop, retained for exact migration. */
export const LEGACY_SUNDAY_FRAME_DARK_THEME: ThemeData = {
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
}

/** Previous Sunday defaults with composer and chat on the same solid. */
export const LEGACY_SUNDAY_UNIFIED_COMPOSER_DARK_THEME: ThemeData = {
  ...SUNDAY_DARK_THEME,
  composerStops: [{ color: '#1B1D22', position: 0 }],
}

export const LEGACY_SUNDAY_UNIFIED_COMPOSER_LIGHT_THEME: ThemeData = {
  ...SUNDAY_LIGHT_THEME,
  composerStops: [{ color: '#FDFBF7', position: 0 }],
}

/** Immediately previous sampled flat Sunday defaults, retained for exact migration. */
export const LEGACY_SUNDAY_FLAT_DARK_THEME: ThemeData = {
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
}

export const LEGACY_SUNDAY_FLAT_LIGHT_THEME: ThemeData = {
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
}

/** Immediately previous inverted-control defaults, retained for exact migration. */
export const LEGACY_SUNDAY_INVERTED_DARK_THEME: ThemeData = {
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
}

export const LEGACY_SUNDAY_INVERTED_LIGHT_THEME: ThemeData = {
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
}

/** Previous colorful Sunday defaults, retained only for exact migration. */
export const LEGACY_SUNDAY_DARK_THEME: ThemeData = {
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
}

export const LEGACY_SUNDAY_LIGHT_THEME: ThemeData = {
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
}

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
  mode?: Exclude<ThemeMode, 'system'>,
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
  '--theme-main-background': string
  '--theme-main-text': string
  '--theme-main-solid': string
  '--theme-main-soft-background': string
  '--theme-main-subtle-background': string
  '--theme-main-sunken-background': string
  '--theme-main-border': string
  '--theme-optical-glass-border-color': string
  '--theme-composer-background': string
  '--theme-composer-text': string
  '--theme-composer-soft-background': string
  '--theme-control-background': string
  '--theme-control-solid': string
  '--theme-control-text': string
  '--theme-control-soft-background': string
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
    '--theme-backdrop-background': gradientFromStops(theme.backdropAngle, theme.backdropStops, 1),
    '--theme-backdrop-text': theme.backdropText,
    '--theme-backdrop-solid': theme.backdropStops[0]?.color || '#202020',
    '--theme-main-background': gradientFromStops(theme.mainAngle, theme.mainStops, theme.mainOpacity),
    '--theme-main-text': theme.mainText,
    '--theme-main-solid': theme.mainStops[0]?.color || '#111111',
    '--theme-main-soft-background': lightMain ? 'rgba(255, 254, 250, 0.78)' : 'rgba(255, 255, 255, 0.045)',
    '--theme-main-subtle-background': lightMain ? 'rgba(255, 254, 250, 0.52)' : 'rgba(255, 255, 255, 0.028)',
    '--theme-main-sunken-background': lightMain ? 'rgba(31, 31, 31, 0.06)' : 'rgba(0, 0, 0, 0.32)',
    '--theme-main-border': mainBorder,
    '--theme-optical-glass-border-color': lightMain ? 'rgb(184 184 184)' : 'rgb(95 95 95)',
    '--theme-composer-background': gradientFromStops(theme.composerAngle, theme.composerStops, theme.composerOpacity),
    '--theme-composer-text': theme.composerText,
    '--theme-composer-soft-background': lightComposer ? 'rgba(255, 254, 250, 0.70)' : 'rgba(255, 255, 255, 0.045)',
    '--theme-control-background': gradientFromStops(theme.controlAngle, theme.controlStops, theme.controlOpacity),
    '--theme-control-solid': theme.controlStops[0]?.color || '#3a3834',
    '--theme-control-text': theme.controlText,
    '--theme-control-soft-background': lightControl ? 'rgba(255, 255, 252, 0.82)' : 'rgba(255, 255, 255, 0.055)',
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
