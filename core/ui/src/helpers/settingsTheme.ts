import { relativeLuminance, themeAreaBackground, type ThemeData } from './theme.ts'

// user:“统一与去重：建立统一的 Design Tokens 和可复用组件体系”+(设置、插件、搜索、连接和项目页面共用主题映射，保留渐变首色和浅色覆盖)。
export function settingsThemeVars(theme?: ThemeData | null): Record<string, string> {
  if (!theme) return {}
  const lightMain = relativeLuminance(theme.mainText) < 0.45
  return {
    '--settings-backdrop-background': themeAreaBackground(theme, 'backdrop'),
    '--settings-backdrop-text': theme.backdropText,
    '--settings-main-background': themeAreaBackground(theme, 'main'),
    '--settings-main-text': theme.mainText,
    '--settings-main-solid': theme.mainStops[0]?.color || '#111111',
    '--settings-card-background': 'color-mix(in srgb, var(--settings-main-solid) 96%, var(--settings-main-text) 4%)',
    '--settings-card-text': theme.mainText,
    '--settings-control-background': themeAreaBackground(theme, 'control'),
    '--settings-control-text': theme.controlText,
    '--settings-control-solid': theme.controlStops[0]?.color || '#3a3834',
    ...(lightMain ? { '--settings-panel-2': '#f0efeb', '--settings-line': '#d4d0cc', '--settings-muted': '#8a8580' } : {}),
  }
}
