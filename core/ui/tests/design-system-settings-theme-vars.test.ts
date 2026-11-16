import { describe, expect, it } from 'vitest'
import { SUNDAY_DARK_THEME, SUNDAY_LIGHT_THEME, themeAreaBackground } from '../src/helpers/theme'
import { settingsThemeVars } from '../src/helpers/settingsTheme'
describe('shared settings theme mapping', () => {
  it('maps all theme areas and retains light-theme overrides and gradient fallback colors', () => {
    expect(settingsThemeVars(null)).toEqual({})
    for (const theme of [SUNDAY_DARK_THEME, SUNDAY_LIGHT_THEME]) {
      const vars = settingsThemeVars(theme)
      expect(vars['--settings-main-background']).toBe(themeAreaBackground(theme, 'main'))
      expect(vars['--settings-main-text']).toBe(theme.mainText)
      expect(vars['--settings-control-background']).toBe(themeAreaBackground(theme, 'control'))
      expect(vars['--settings-control-text']).toBe(theme.controlText)
      expect(vars['--settings-main-solid']).toBe(theme.mainStops[0].color)
      expect(vars['--settings-control-solid']).toBe(theme.controlStops[0].color)
    }
    expect(settingsThemeVars(SUNDAY_LIGHT_THEME)['--settings-panel-2']).toBe('#f0efeb')
    expect(settingsThemeVars(SUNDAY_DARK_THEME)['--settings-panel-2']).toBeUndefined()
    const gradient = structuredClone(SUNDAY_DARK_THEME)
    gradient.mainStops = [{ color: '#123456', position: 0 }, { color: '#abcdef', position: 100 }]
    expect(settingsThemeVars(gradient)['--settings-main-solid']).toBe('#123456')
    expect(settingsThemeVars(gradient)['--settings-card-background']).toContain('var(--settings-main-solid)')
  })
})
