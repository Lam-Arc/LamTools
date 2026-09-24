import { describe, expect, it } from 'vitest'

import {
  DEFAULT_THEME,
  LEGACY_SUNDAY_DARK_THEME,
  LEGACY_SUNDAY_FLAT_DARK_THEME,
  LEGACY_SUNDAY_FRAME_DARK_THEME,
  LEGACY_SUNDAY_UNIFIED_COMPOSER_DARK_THEME,
  LEGACY_SUNDAY_UNIFIED_COMPOSER_LIGHT_THEME,
  LEGACY_SUNDAY_FLAT_LIGHT_THEME,
  LEGACY_SUNDAY_INVERTED_DARK_THEME,
  LEGACY_SUNDAY_INVERTED_LIGHT_THEME,
  LEGACY_SUNDAY_LIGHT_THEME,
  SUNDAY_DARK_THEME,
  SUNDAY_LIGHT_THEME,
  migrateSundayThemeDefaults,
  normalizeGradientStops,
  normalizeTheme,
  relativeLuminance,
  themeToCSSVars,
} from '../src/helpers/theme'
import { THEME_PRESETS } from '../src/data/theme-presets'

describe('theme gradient normalization', () => {
  it('collapses legacy duplicate solid stops into one source node', () => {
    expect(normalizeGradientStops([
      { color: '#AABBCC', position: 0 },
      { color: '#aabbcc', position: 100 },
    ], '#000000', '#ffffff')).toEqual([
      { color: '#AABBCC', position: 0 },
    ])
  })

  it('preserves user gradients while keeping every Sunday area flat', () => {
    expect(normalizeGradientStops([
      { color: '#111111', position: 0 },
      { color: '#222222', position: 100 },
    ], '#000000', '#ffffff')).toHaveLength(2)
    for (const sundayTheme of [SUNDAY_LIGHT_THEME, SUNDAY_DARK_THEME]) {
      expect(sundayTheme.backdropStops).toHaveLength(1)
      expect(sundayTheme.mainStops).toHaveLength(1)
      expect(sundayTheme.composerStops).toHaveLength(1)
      expect(sundayTheme.controlStops).toHaveLength(1)
      expect(sundayTheme.composerStops).not.toEqual(sundayTheme.mainStops)
      const css = themeToCSSVars(sundayTheme)
      expect(css['--theme-backdrop-background']).not.toContain('linear-gradient')
      expect(css['--theme-main-background']).not.toContain('linear-gradient')
      expect(css['--theme-composer-background']).not.toContain('linear-gradient')
      expect(css['--theme-control-background']).not.toContain('linear-gradient')
    }
    expect(normalizeTheme(DEFAULT_THEME).processIconColor).toBe('#888990')
  })

  it('keeps the default pure-color preset as a single node', () => {
    expect(THEME_PRESETS.map((preset) => preset.id)).not.toContain('solid-paper')
    expect(THEME_PRESETS.map((preset) => preset.id)).toEqual(['sunday', 'default', 'berry-teal', 'morning-mist'])
    const defaultPreset = THEME_PRESETS.find((preset) => preset.id === 'default')!
    expect(defaultPreset.lightTheme?.mainStops).toHaveLength(1)
    expect(defaultPreset.darkTheme?.mainStops).toHaveLength(1)
    expect(themeToCSSVars(normalizeTheme(defaultPreset.lightTheme || {}))['--theme-main-border'])
      .toBe('rgba(31, 31, 31, 0.10)')
    expect(themeToCSSVars(normalizeTheme(defaultPreset.darkTheme || {}))['--theme-main-border'])
      .toBe('rgba(255, 255, 255, 0.10)')
  })

  it('ships matched Sunday light and dark variants', () => {
    const sunday = THEME_PRESETS.find((preset) => preset.id === 'sunday')!
    expect(sunday.lightTheme).toMatchObject({
      backdropStops: [{ color: '#D2D8E6', position: 0 }],
      backdropText: '#2E3138',
      mainStops: [{ color: '#FDFBF7', position: 0 }],
      mainText: '#2E3138',
      composerStops: [{ color: '#F7F4EE', position: 0 }],
      composerText: '#2E3138',
      controlStops: [{ color: '#2E3138', position: 0 }],
      controlText: '#FBF7F0',
      processIconColor: '#C9D0DF',
    })
    expect(sunday.darkTheme).toMatchObject({
      backdropStops: [{ color: '#3A3B3F', position: 0 }],
      backdropText: '#FBF7F0',
      mainStops: [{ color: '#1B1D22', position: 0 }],
      mainText: '#FBF7F0',
      composerStops: [{ color: '#22242A', position: 0 }],
      composerText: '#FBF7F0',
      controlStops: [{ color: '#FBF7F0', position: 0 }],
      controlText: '#2E3138',
      processIconColor: '#888990',
    })

    const lightVars = themeToCSSVars(SUNDAY_LIGHT_THEME)
    const darkVars = themeToCSSVars(SUNDAY_DARK_THEME)
    expect(lightVars['--theme-main-border']).toBe('#D2D8E6')
    expect(darkVars['--theme-main-border']).toBe('#818289')
    expect(lightVars['--theme-optical-glass-border-color']).toBe('rgb(184 184 184)')
    expect(darkVars['--theme-optical-glass-border-color']).toBe('rgb(95 95 95)')
    expect(lightVars['--theme-backdrop-background']).toBe('rgba(210, 216, 230, 1)')
    expect(darkVars['--theme-backdrop-background']).toBe('rgba(58, 59, 63, 1)')
    expect(lightVars['--theme-control-background']).toBe('rgba(46, 49, 56, 1)')
    expect(lightVars['--theme-control-solid']).toBe('#2E3138')
    expect(lightVars['--theme-control-text']).toBe('#FBF7F0')
    expect(darkVars['--theme-control-background']).toBe('rgba(251, 247, 240, 1)')
    expect(darkVars['--theme-control-solid']).toBe('#FBF7F0')
    expect(darkVars['--theme-control-text']).toBe('#2E3138')

    const contrast = (foreground: string, background: string) => {
      const bright = Math.max(relativeLuminance(foreground), relativeLuminance(background))
      const dark = Math.min(relativeLuminance(foreground), relativeLuminance(background))
      return (bright + 0.05) / (dark + 0.05)
    }
    expect(contrast(SUNDAY_LIGHT_THEME.mainText, SUNDAY_LIGHT_THEME.mainStops[0].color)).toBeGreaterThan(10)
    expect(contrast(SUNDAY_DARK_THEME.mainText, SUNDAY_DARK_THEME.mainStops[0].color)).toBeGreaterThan(10)
    expect(contrast(SUNDAY_LIGHT_THEME.controlText, SUNDAY_LIGHT_THEME.controlStops[0].color)).toBeGreaterThan(10)
    expect(contrast(SUNDAY_DARK_THEME.controlText, SUNDAY_DARK_THEME.controlStops[0].color)).toBeGreaterThan(10)
  })

  it('migrates only exact previous Sunday defaults', () => {
    const oldLight = normalizeTheme({ ...LEGACY_SUNDAY_LIGHT_THEME })
    const oldDark = normalizeTheme({ ...LEGACY_SUNDAY_DARK_THEME })
    expect(migrateSundayThemeDefaults(oldLight, 'light')).toEqual(SUNDAY_LIGHT_THEME)
    expect(migrateSundayThemeDefaults(oldDark, 'dark')).toEqual(SUNDAY_DARK_THEME)

    const customized = { ...oldLight, mainText: '#232323' }
    expect(migrateSundayThemeDefaults(customized, 'light')).toBe(customized)
  })

  it('migrates the immediately previous sampled flat defaults without touching customizations', () => {
    const previousLight = normalizeTheme({ ...LEGACY_SUNDAY_FLAT_LIGHT_THEME })
    const previousDark = normalizeTheme({ ...LEGACY_SUNDAY_FLAT_DARK_THEME })
    expect(migrateSundayThemeDefaults(previousLight, 'light')).toEqual(SUNDAY_LIGHT_THEME)
    expect(migrateSundayThemeDefaults(previousDark, 'dark')).toEqual(SUNDAY_DARK_THEME)

    const customizedLight = { ...previousLight, controlText: '#F8F2E8' }
    const customizedDark = { ...previousDark, controlText: '#30333A' }
    expect(migrateSundayThemeDefaults(customizedLight, 'light')).toBe(customizedLight)
    expect(migrateSundayThemeDefaults(customizedDark, 'dark')).toBe(customizedDark)
  })

  it('migrates the shipped inverted-control defaults when only the backdrop was stale', () => {
    const previousLight = normalizeTheme({ ...LEGACY_SUNDAY_INVERTED_LIGHT_THEME })
    const previousDark = normalizeTheme({ ...LEGACY_SUNDAY_INVERTED_DARK_THEME })
    expect(migrateSundayThemeDefaults(previousLight, 'light')).toEqual(SUNDAY_LIGHT_THEME)
    expect(migrateSundayThemeDefaults(previousDark, 'dark')).toEqual(SUNDAY_DARK_THEME)

    const customizedLight = { ...previousLight, backdropText: '#24262C' }
    const customizedDark = { ...previousDark, mainOpacity: 0.96 }
    expect(migrateSundayThemeDefaults(customizedLight, 'light')).toBe(customizedLight)
    expect(migrateSundayThemeDefaults(customizedDark, 'dark')).toBe(customizedDark)
  })

  it('migrates the previous frame-gray dark backdrop default', () => {
    expect(migrateSundayThemeDefaults(normalizeTheme({ ...LEGACY_SUNDAY_FRAME_DARK_THEME }), 'dark'))
      .toEqual(SUNDAY_DARK_THEME)
  })

  it('migrates the previous unified composer defaults', () => {
    expect(migrateSundayThemeDefaults(normalizeTheme({ ...LEGACY_SUNDAY_UNIFIED_COMPOSER_LIGHT_THEME }), 'light'))
      .toEqual(SUNDAY_LIGHT_THEME)
    expect(migrateSundayThemeDefaults(normalizeTheme({ ...LEGACY_SUNDAY_UNIFIED_COMPOSER_DARK_THEME }), 'dark'))
      .toEqual(SUNDAY_DARK_THEME)
  })

  it('uses the requested gradient for the berry-teal preset background', () => {
    const preset = THEME_PRESETS.find((candidate) => candidate.id === 'berry-teal')!
    expect(preset.lightTheme?.backdropAngle).toBe(180)
    expect(preset.lightTheme?.backdropStops).toEqual([
      { color: '#e3d9dc', position: 0 },
      { color: '#d8d8e4', position: 50 },
      { color: '#d3e1e3', position: 100 },
    ])
    expect(preset.darkTheme?.backdropStops).toEqual([
      { color: '#281a1f', position: 0 },
      { color: '#272734', position: 50 },
      { color: '#1e2429', position: 100 },
    ])
    expect(preset.lightTheme?.mainStops).toEqual([{ color: '#f8f8ef', position: 0 }])
    expect(preset.darkTheme?.mainStops).toEqual([{ color: '#151515', position: 0 }])
  })

  it('uses the requested light background for the morning-mist preset', () => {
    const preset = THEME_PRESETS.find((candidate) => candidate.id === 'morning-mist')!
    expect(preset.lightTheme?.backdropAngle).toBe(185)
    expect(preset.lightTheme?.backdropStops).toEqual([
      { color: '#c1d8e2', position: 0 },
      { color: '#fff2db', position: 100 },
    ])
    expect(preset.lightTheme?.backdropText).toBe('#1f1f1f')
    expect(preset.lightTheme?.mainStops).toEqual([{ color: '#eeeeea', position: 0 }])
    expect(preset.lightTheme?.mainText).toBe('#242625')
    expect(preset.lightTheme?.composerStops).toEqual([
      { color: '#e6e8e4', position: 0 },
      { color: '#e2e4e0', position: 100 },
    ])
    expect(preset.lightTheme?.controlStops).toEqual([{ color: '#d3d6d2', position: 0 }])
    expect(preset.lightTheme?.controlText).toBe('#1f1f1f')
    expect(preset.darkTheme?.backdropAngle).toBe(185)
    expect(preset.darkTheme?.backdropStops).toEqual([
      { color: '#110e11', position: 0 },
      { color: '#1a140f', position: 100 },
    ])
    expect(preset.darkTheme?.backdropText).toBe('#f2efeb')
    expect(preset.darkTheme?.mainStops).toEqual([{ color: '#151514', position: 0 }])
    expect(preset.darkTheme?.composerStops).toEqual([
      { color: '#242525', position: 0 },
      { color: '#282929', position: 100 },
    ])
    expect(preset.darkTheme?.controlStops).toEqual([{ color: '#1a2824', position: 0 }])
    expect(preset.darkTheme?.controlText).toBe('#f3eee8')
  })
})
