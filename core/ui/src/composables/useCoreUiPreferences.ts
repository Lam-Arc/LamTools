import { ref } from 'vue'
import {
  DEFAULT_THEME,
  addGradientStop,
  normalizeTheme,
  removeGradientStop,
  sortGradientStops,
  type ThemeArea,
  type ThemeData,
  type ThemePreset,
  type ThemeStop,
} from '../helpers/theme'

export type CoreUiDensity = 'compact' | 'standard' | 'loose'
export interface CoreUiPreferencesValue { density: CoreUiDensity; contentWidth: number; theme: ThemeData }
export interface CoreUiPreferencesAdapter {
  read?(): Promise<Partial<CoreUiPreferencesValue> | null>
  write?(value: CoreUiPreferencesValue): Promise<void>
}

export function useCoreUiPreferences(storageKey: string, adapter: CoreUiPreferencesAdapter = {}) {
  const density = ref<CoreUiDensity>('standard')
  const contentWidth = ref(780)
  const theme = ref<ThemeData>(normalizeTheme({ ...DEFAULT_THEME }))

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
    theme.value = normalizeTheme({ ...DEFAULT_THEME, ...(value.theme || {}) })
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
    return { density: density.value, contentWidth: contentWidth.value, theme: theme.value }
  }
  function setDensity(value: CoreUiDensity) { density.value = value; void save() }
  function setContentWidth(value: number) { contentWidth.value = clampWidth(value); void save() }
  function resetTheme() { theme.value = normalizeTheme({ ...DEFAULT_THEME }); void save() }
  function applyThemePreset(preset: ThemePreset) { theme.value = normalizeTheme({ ...DEFAULT_THEME, ...preset.theme }); void save() }
  function updateThemeStops(area: ThemeArea, stops: ThemeStop[]) { setThemeField(`${area}Stops`, stops) }
  function updateThemeAngle(area: ThemeArea, value: number) { setThemeField(`${area}Angle`, value) }
  function updateThemeOpacity(area: ThemeArea, value: number) { setThemeField(`${area}Opacity`, value) }
  function updateThemeText(area: ThemeArea, value: string) { setThemeField(`${area}Text`, value) }
  function addStop(area: ThemeArea) { editStops(area, addGradientStop) }
  function removeStop(area: ThemeArea, index: number) { editStops(area, stops => removeGradientStop(stops, index)) }
  function sortStops(area: ThemeArea) { editStops(area, sortGradientStops) }
  function editStops(area: ThemeArea, edit: (stops: ThemeStop[]) => ThemeStop[]) {
    const stops = theme.value[`${area}Stops` as keyof ThemeData] as ThemeStop[]
    setThemeField(`${area}Stops`, edit(stops))
  }
  function setThemeField(key: string, value: unknown) {
    ;(theme.value as Record<string, unknown>)[key] = value
    void save()
  }

  return {
    density, contentWidth, theme, load, save, snapshot, setDensity, setContentWidth,
    resetTheme, applyThemePreset, updateThemeStops, updateThemeAngle, updateThemeOpacity,
    updateThemeText, addStop, removeStop, sortStops,
  }
}

function clampWidth(value: unknown): number {
  return Math.min(1120, Math.max(560, Number(value) || 780))
}
