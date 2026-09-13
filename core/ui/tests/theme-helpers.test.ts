import { describe, expect, it } from 'vitest'

import { DEFAULT_THEME, normalizeGradientStops, normalizeTheme } from '../src/helpers/theme'
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

  it('preserves multi-color gradients and the Sunday default composition', () => {
    expect(normalizeGradientStops([
      { color: '#111111', position: 0 },
      { color: '#222222', position: 100 },
    ], '#000000', '#ffffff')).toHaveLength(2)
    expect(normalizeTheme(DEFAULT_THEME).backdropStops).toHaveLength(3)
    expect(normalizeTheme(DEFAULT_THEME).mainStops).toHaveLength(2)
    expect(normalizeTheme(DEFAULT_THEME).processIconColor).toBe('#a693ff')
  })

  it('keeps the default pure-color preset as a single node', () => {
    expect(THEME_PRESETS.map((preset) => preset.id)).not.toContain('solid-paper')
    expect(THEME_PRESETS.map((preset) => preset.id)).toEqual(['sunday', 'default', 'berry-teal', 'morning-mist'])
    const defaultPreset = THEME_PRESETS.find((preset) => preset.id === 'default')!
    expect(defaultPreset.lightTheme?.mainStops).toHaveLength(1)
    expect(defaultPreset.darkTheme?.mainStops).toHaveLength(1)
  })

  it('ships matched Sunday light and dark variants', () => {
    const sunday = THEME_PRESETS.find((preset) => preset.id === 'sunday')!
    expect(sunday.lightTheme?.mainText).toBe('#162451')
    expect(sunday.lightTheme?.processIconColor).toBe('#6755e8')
    expect(sunday.darkTheme?.mainText).toBe('#f5f2fb')
    expect(sunday.darkTheme?.processIconColor).toBe('#a693ff')
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
