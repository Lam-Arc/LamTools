import { computed, onMounted, onUnmounted, ref } from 'vue'
import {
  DEFAULT_THEME,
  SUNDAY_DARK_THEME,
  SUNDAY_LIGHT_THEME,
  addGradientStop,
  normalizeTheme,
  normalizeColor,
  migrateSundayThemeDefaults,
  removeGradientStop,
  sortGradientStops,
  type ThemeArea,
  type ThemeData,
  type ThemeMode,
  type ThemePreset,
  type ThemeStop,
  themeForMode,
} from '../helpers/theme'

export type CoreUiDensity = 'compact' | 'standard' | 'loose'
export interface CoreUiPreferencesValue {
  density: CoreUiDensity
  contentWidth: number
  theme: ThemeData
  themeMode: ThemeMode
  lightTheme: ThemeData
  darkTheme: ThemeData
}
export interface CoreUiPreferencesAdapter {
  read?(): Promise<Partial<CoreUiPreferencesValue> | null>
  write?(value: CoreUiPreferencesValue): Promise<void>
}

type ThemeTransitionDocument = Document & {
  startViewTransition?: (update: () => void | Promise<void>) => unknown
}

function runThemeTransition(update: () => void) {
  if (typeof document === 'undefined' || typeof window === 'undefined') {
    update()
    return
  }
  const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  const transitionDocument = document as ThemeTransitionDocument
  if (reducedMotion || typeof transitionDocument.startViewTransition !== 'function') {
    update()
    return
  }
  transitionDocument.startViewTransition(() => {
    update()
  })
}

export function useCoreUiPreferences(storageKey: string, adapter: CoreUiPreferencesAdapter = {}) {
  const density = ref<CoreUiDensity>('standard')
  const contentWidth = ref(780)
  const themeMode = ref<ThemeMode>('system')
  const systemPrefersDark = ref(false)
  const lightTheme = ref<ThemeData>(normalizeTheme({ ...SUNDAY_LIGHT_THEME }))
  const darkTheme = ref<ThemeData>(normalizeTheme({ ...SUNDAY_DARK_THEME }))
  const effectiveThemeMode = computed<'light' | 'dark'>(() => (
    themeMode.value === 'system' ? (systemPrefersDark.value ? 'dark' : 'light') : themeMode.value
  ))
  const theme = computed<ThemeData>(() => (
    effectiveThemeMode.value === 'dark' ? darkTheme.value : lightTheme.value
  ))
  let systemThemeQuery: MediaQueryList | null = null

  function updateSystemTheme(query: MediaQueryList | MediaQueryListEvent) {
    systemPrefersDark.value = query.matches
  }

  function handleSystemThemeChange(query: MediaQueryListEvent) {
    runThemeTransition(() => updateSystemTheme(query))
  }

  // Legacy key: before the shell/preferences keys were split, both wrote
  // 'lamtools.core.ui' with different schemas (audit 19 S3). We still read
  // it as a fallback so existing users keep their density/theme.
  const LEGACY_KEY = 'lamtools.core.ui'

  async function load() {
    let value: Partial<CoreUiPreferencesValue> | null = null
    try { value = await adapter.read?.() || null } catch { value = null }
    if (!value) {
      try { value = JSON.parse(localStorage.getItem(storageKey) || 'null') } catch { value = null }
    }
    if (!value && storageKey !== LEGACY_KEY) {
      try { value = JSON.parse(localStorage.getItem(LEGACY_KEY) || 'null') } catch { value = null }
    }
    if (!value) return
    if (value.density === 'compact' || value.density === 'standard' || value.density === 'loose') density.value = value.density
    contentWidth.value = clampWidth(value.contentWidth)
    if (value.themeMode === 'system' || value.themeMode === 'light' || value.themeMode === 'dark') themeMode.value = value.themeMode
    const legacyTheme = normalizeTheme({ ...DEFAULT_THEME, ...(value.theme || {}) })
    lightTheme.value = migrateSundayThemeDefaults(
      normalizeTheme({ ...DEFAULT_THEME, ...(value.lightTheme || legacyTheme) }),
      'light',
    )
    darkTheme.value = migrateSundayThemeDefaults(
      normalizeTheme({ ...DEFAULT_THEME, ...(value.darkTheme || legacyTheme) }),
      'dark',
    )
  }

  async function save() {
    const value = snapshot()
    try {
      localStorage.setItem(storageKey, JSON.stringify(value))
    } catch {
      /* storage unavailable (private mode / quota) — persistence is best-effort */
    }
    await adapter.write?.(value)
  }

  function snapshot(): CoreUiPreferencesValue {
    return {
      density: density.value,
      contentWidth: contentWidth.value,
      theme: theme.value,
      themeMode: themeMode.value,
      lightTheme: lightTheme.value,
      darkTheme: darkTheme.value,
    }
  }
  function setDensity(value: CoreUiDensity) { density.value = value; void save() }
  function setContentWidth(value: number) { contentWidth.value = clampWidth(value); void save() }
  function setThemeMode(value: ThemeMode) {
    if (themeMode.value === value) return
    runThemeTransition(() => {
      themeMode.value = value
      void save()
    })
  }
  function resetTheme() {
    runThemeTransition(() => {
      lightTheme.value = normalizeTheme({ ...SUNDAY_LIGHT_THEME })
      darkTheme.value = normalizeTheme({ ...SUNDAY_DARK_THEME })
      void save()
    })
  }
  function applyThemePreset(preset: ThemePreset) {
    runThemeTransition(() => {
      lightTheme.value = normalizeTheme({ ...DEFAULT_THEME, ...themeForMode(preset, 'light') })
      darkTheme.value = normalizeTheme({ ...DEFAULT_THEME, ...themeForMode(preset, 'dark') })
      void save()
    })
  }
  function updateThemeStops(area: ThemeArea, stops: ThemeStop[]) { setThemeField(`${area}Stops`, sortGradientStops(stops)) }
  function updateThemeAngle(area: ThemeArea, value: number) { setThemeField(`${area}Angle`, value) }
  function updateThemeOpacity(area: ThemeArea, value: number) { setThemeField(`${area}Opacity`, value) }
  function updateThemeText(area: ThemeArea, value: string) { setThemeField(`${area}Text`, value) }
  function updateProcessIconColor(value: string) {
    setThemeField('processIconColor', normalizeColor(value, theme.value.processIconColor))
  }
  function addStop(area: ThemeArea) { editStops(area, addGradientStop) }
  function removeStop(area: ThemeArea, index: number) { editStops(area, stops => removeGradientStop(stops, index)) }
  function sortStops(area: ThemeArea) { editStops(area, sortGradientStops) }
  function editStops(area: ThemeArea, edit: (stops: ThemeStop[]) => ThemeStop[]) {
    const stops = theme.value[`${area}Stops` as keyof ThemeData] as ThemeStop[]
    setThemeField(`${area}Stops`, edit(stops))
  }
  function setThemeField(key: string, value: unknown) {
    const target = effectiveThemeMode.value === 'dark' ? darkTheme : lightTheme
    target.value = { ...target.value, [key]: value } as ThemeData
    void save()
  }

  onMounted(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return
    systemThemeQuery = window.matchMedia('(prefers-color-scheme: dark)')
    updateSystemTheme(systemThemeQuery)
    systemThemeQuery.addEventListener('change', handleSystemThemeChange)
  })

  onUnmounted(() => {
    systemThemeQuery?.removeEventListener('change', handleSystemThemeChange)
    systemThemeQuery = null
  })

  return {
    density, contentWidth, theme, themeMode, effectiveThemeMode, load, save, snapshot, setDensity, setContentWidth, setThemeMode,
    resetTheme, applyThemePreset, updateThemeStops, updateThemeAngle, updateThemeOpacity,
    updateThemeText, updateProcessIconColor, addStop, removeStop, sortStops,
  }
}

function clampWidth(value: unknown): number {
  return Math.min(1120, Math.max(560, Number(value) || 780))
}
