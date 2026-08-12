/**
 * useTheme — theme loading, saving, preset application, normalization
 *
 * Used by both ThemeEditor (SettingsView) and WorkspaceShell (WorkbenchView).
 * Products call loadTheme() on mount; saveTheme() on changes.
 */

import { ref, computed } from 'vue'
import {
  type ThemeData,
  type ThemeStop,
  type ThemeArea,
  DEFAULT_THEME,
  normalizeTheme,
  migrateThemeDefaults,
  gradientFromStops,
  themeToCSSVars,
  relativeLuminance,
  addGradientStop,
  removeGradientStop,
  sortGradientStops,
} from '../helpers/theme'
import type { ThemePreset } from '../helpers/theme'
import { THEME_PRESETS, THEME_PRESET_GROUPS } from '../data/theme-presets'

export function useTheme(storageKey: string) {
  const theme = ref<ThemeData>({ ...DEFAULT_THEME })

  // --- CSS variable injection for settings page ---
  const settingsThemeStyle = computed(() => {
    const lightMain = relativeLuminance(theme.value.mainText) < 0.45
    return {
      '--settings-backdrop-background': gradientFromStops(
        theme.value.backdropAngle,
        theme.value.backdropStops,
        1,
      ),
      '--settings-backdrop-text': theme.value.backdropText,
      '--settings-main-background': gradientFromStops(
        theme.value.mainAngle,
        theme.value.mainStops,
        theme.value.mainOpacity,
      ),
      '--settings-main-text': theme.value.mainText,
      // main 区首停点纯色：卡片实色底（渐变值不可用于 color-mix）
      '--settings-main-solid': theme.value.mainStops[0]?.color || '#111111',
      // 卡片/浮层面板：main 实色 + 文字色 4% 微调，不透明、与内容区有层级
      '--settings-card-background': 'color-mix(in srgb, var(--settings-main-solid) 96%, var(--settings-main-text) 4%)',
      '--settings-card-text': theme.value.mainText,
      '--settings-control-solid': theme.value.controlStops[0]?.color || '#3a3834',
      '--settings-panel-2': lightMain ? '#f0efeb' : '#1d1e1e',
      '--settings-line': lightMain ? '#d4d0cc' : '#3b3a38',
      '--settings-muted': lightMain ? '#8a8580' : '#a7a29b',
    }
  })

  // --- Preview styles ---
  const themePreviewStyle = computed(() => ({
    background: gradientFromStops(theme.value.backdropAngle, theme.value.backdropStops, 1),
    color: theme.value.backdropText,
  }))
  const themePreviewMainStyle = computed(() => ({
    background: gradientFromStops(
      theme.value.mainAngle,
      theme.value.mainStops,
      theme.value.mainOpacity,
    ),
    color: theme.value.mainText,
  }))
  const themePreviewComposerStyle = computed(() => ({
    background: gradientFromStops(
      theme.value.composerAngle,
      theme.value.composerStops,
      theme.value.composerOpacity,
    ),
    color: theme.value.composerText,
  }))
  const themePreviewControlStyle = computed(() => ({
    background: gradientFromStops(
      theme.value.controlAngle,
      theme.value.controlStops,
      theme.value.controlOpacity,
    ),
    color: theme.value.controlText,
  }))

  // --- Presets ---
  const presets = THEME_PRESETS
  const presetGroups = THEME_PRESET_GROUPS

  function presetsByGroup(group: ThemePreset['group']): ThemePreset[] {
    return presets.filter((p) => p.group === group)
  }

  function applyPreset(preset: ThemePreset) {
    theme.value = normalizeTheme({ ...DEFAULT_THEME, ...preset.theme })
    saveTheme()
  }

  function resetTheme() {
    theme.value = { ...DEFAULT_THEME }
    saveTheme()
  }

  // --- Gradient stop editing ---
  function getStops(area: ThemeArea): ThemeStop[] {
    return theme.value[`${area}Stops` as const] as ThemeStop[]
  }

  function setStops(area: ThemeArea, stops: ThemeStop[]) {
    ;(theme.value as Record<string, unknown>)[`${area}Stops`] = stops
    saveTheme()
  }

  function onAddGradientStop(area: ThemeArea) {
    setStops(area, addGradientStop(getStops(area)))
  }

  function onRemoveGradientStop(area: ThemeArea, index: number) {
    setStops(area, removeGradientStop(getStops(area), index))
  }

  function onSortGradientStops(area: ThemeArea) {
    setStops(area, sortGradientStops(getStops(area)))
  }

  // --- Persistence ---
  function loadTheme() {
    try {
      const raw = localStorage.getItem(storageKey)
      if (!raw) return
      const saved = JSON.parse(raw)
      if (saved.theme) {
        theme.value = migrateThemeDefaults(normalizeTheme({ ...DEFAULT_THEME, ...saved.theme }))
      }
    } catch {
      /* ignore */
    }
  }

  function saveTheme() {
    localStorage.setItem(
      storageKey,
      JSON.stringify({
        theme: theme.value,
      }),
    )
  }

  // --- Shell CSS variables (for WorkspaceShell) ---
  const shellCSSVars = computed(() => themeToCSSVars(theme.value))

  return {
    theme,
    // preview
    settingsThemeStyle,
    themePreviewStyle,
    themePreviewMainStyle,
    themePreviewComposerStyle,
    themePreviewControlStyle,
    // presets
    presets,
    presetGroups,
    presetsByGroup,
    applyPreset,
    resetTheme,
    // gradient editing
    getStops,
    onAddGradientStop,
    onRemoveGradientStop,
    onSortGradientStops,
    // persistence
    loadTheme,
    saveTheme,
    // shell vars
    shellCSSVars,
  }
}
