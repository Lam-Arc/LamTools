import { describe, expect, it } from 'vitest'

import {
  LEGACY_SUNDAY_DARK_THEME,
  SUNDAY_DARK_THEME,
  migrateSundayThemeDefaults,
  normalizeTheme,
  themeAreaBackground,
  themeAreaFill,
  themeAreaGlass,
  themeAreaGlassFilter,
  themeAreaImageLayer,
  themeAreaImageRepeat,
  themeAreaImageSize,
  themeToCSSVars,
} from '../src/helpers/theme'

const gradientStops = [
  { color: '#112233', position: 0 },
  { color: '#445566', position: 100 },
]

const gifDataUrl = 'data:image/gif;base64,R0lGODlhAQABAAAAACw='

describe('主题区域填充样式', () => {
  it('旧主题按节点数量自动落到纯色或渐变，行为不变', () => {
    const solid = normalizeTheme({ ...SUNDAY_DARK_THEME })
    expect(themeAreaFill(solid, 'main')).toBe('solid')
    expect(themeToCSSVars(solid)['--theme-main-background']).toBe('rgba(27, 29, 34, 1)')

    // 旧文档没有样式字段：推断只能看节点数量。
    const gradient = normalizeTheme({ ...SUNDAY_DARK_THEME, mainFill: undefined, mainStops: gradientStops })
    expect(themeAreaFill(gradient, 'main')).toBe('gradient')
    expect(themeToCSSVars(gradient)['--theme-main-background']).toContain('linear-gradient(')
  })

  it('玻璃是独立偏好：开启后给同一个填充套上低透/高透着色，并挂滤镜', () => {
    const theme = normalizeTheme({ ...SUNDAY_DARK_THEME, mainGlass: 'low' })
    const css = themeToCSSVars(theme)
    expect(themeAreaGlass(theme, 'main')).toBe('low')
    // 纯色填充不变，玻璃只改着色浓度。
    expect(themeAreaBackground(theme, 'main')).toBe('rgba(27, 29, 34, 0.58)')
    expect(css['--theme-main-background']).toBe('rgba(27, 29, 34, 0.58)')
    expect(css['--theme-main-glass-filter']).toContain('blur(var(--optical-glass-blur')
    expect(css['--theme-composer-glass-filter']).toBe('none')
    expect(css['--theme-main-solid']).toBe('#1B1D22')
  })

  it('玻璃开启后渐变与图片也按材质浓度着色', () => {
    const gradient = normalizeTheme({ ...SUNDAY_DARK_THEME, mainFill: 'gradient', mainStops: gradientStops, mainGlass: 'high' })
    expect(themeAreaBackground(gradient, 'main'))
      .toContain('rgba(17, 34, 51, 0.22)')
    expect(themeAreaImageLayer(gradient, 'main'))
      .toContain('rgba(17, 34, 51, 0.22)')

    const image = normalizeTheme({
      ...SUNDAY_DARK_THEME,
      mainFill: 'image',
      mainImage: gifDataUrl,
      mainGlass: 'low',
    })
    // 图片上面盖一层同色薄雾，图片仍是原始 data URL。
    expect(themeAreaImageLayer(image, 'main')).toBe(
      `linear-gradient(rgba(27, 29, 34, 0.58), rgba(27, 29, 34, 0.58)), url("${gifDataUrl}")`,
    )
  })

  it('图片样式接受动图数据并带上适应方式', () => {
    const theme = normalizeTheme({
      ...SUNDAY_DARK_THEME,
      mainFill: 'image',
      mainImage: gifDataUrl,
      mainImageFit: 'tile',
    })
    const css = themeToCSSVars(theme)
    expect(themeAreaFill(theme, 'main')).toBe('image')
    // 底色留在 background 上给内部卡片用，图片只铺在主表面。
    expect(themeAreaBackground(theme, 'main')).toBe('rgba(27, 29, 34, 1)')
    expect(css['--theme-main-background']).toBe('rgba(27, 29, 34, 1)')
    expect(themeAreaImageLayer(theme, 'main')).toBe(`url("${gifDataUrl}")`)
    expect(css['--theme-main-image']).toBe(`url("${gifDataUrl}")`)
    expect(themeAreaImageSize(theme, 'main')).toBe('auto')
    expect(themeAreaImageRepeat(theme, 'main')).toBe('repeat')
    expect(themeAreaGlassFilter(theme, 'main')).toBe('none')
  })

  it('图片样式还没选图时退回底色，不留下空白区域', () => {
    const theme = normalizeTheme({ ...SUNDAY_DARK_THEME, composerFill: 'image' })
    expect(themeAreaBackground(theme, 'composer')).toBe('rgba(34, 36, 42, 1)')
  })

  it('旧版“玻璃填充”迁移成纯色填充 + 玻璃偏好，不会被当成旧默认主题迁移掉', () => {
    const legacyGlass = normalizeTheme({ ...LEGACY_SUNDAY_DARK_THEME, mainFill: 'glass' })
    expect(themeAreaFill(legacyGlass, 'main')).toBe('solid')
    expect(themeAreaGlass(legacyGlass, 'main')).toBe('high')
    expect(migrateSundayThemeDefaults(legacyGlass, 'dark')).toBe(legacyGlass)
  })
})
