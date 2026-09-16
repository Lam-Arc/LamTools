import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'
import { resolveStartupThemePreference } from '../src/motion/startupSplash'
import {
  LEGACY_SUNDAY_DARK_THEME,
  LEGACY_SUNDAY_FRAME_DARK_THEME,
  LEGACY_SUNDAY_FLAT_DARK_THEME,
  LEGACY_SUNDAY_INVERTED_DARK_THEME,
} from '../src/helpers/theme'

const desktopHtml = readFileSync(resolve(process.cwd(), '../desktop/index.html'), 'utf8')
const desktopMainSource = readFileSync(resolve(process.cwd(), '../desktop/src/main.ts'), 'utf8')
const desktopRustSource = readFileSync(resolve(process.cwd(), '../desktop/src-tauri/src/main.rs'), 'utf8')
const tauriConfig = JSON.parse(readFileSync(resolve(process.cwd(), '../desktop/src-tauri/tauri.conf.json'), 'utf8')) as {
  app?: { windows?: Array<Record<string, unknown>> }
}
const motionSource = readFileSync(resolve(process.cwd(), 'src/motion/startupSplash.ts'), 'utf8')
const bootstrapSource = desktopHtml.match(/<script id="sunday-theme-bootstrap">([\s\S]*?)<\/script>/)?.[1] || ''

function storage(values: Record<string, string>): Pick<Storage, 'getItem'> {
  return { getItem: (key: string) => values[key] ?? null }
}

function runBootstrap(values: Record<string, string>, systemDark = false, throws = false) {
  const properties: Record<string, string> = {}
  const browserWindow = {
    localStorage: {
      getItem: (key: string) => {
        if (throws) throw new Error('storage unavailable')
        return values[key] ?? null
      },
    },
    matchMedia: () => ({ matches: systemDark }),
  } as unknown as Window
  const browserDocument = {
    documentElement: {
      style: { setProperty: (key: string, value: string) => { properties[key] = value } },
    },
  } as unknown as Document
  Function('window', 'document', bootstrapSource)(browserWindow, browserDocument)
  return {
    properties,
    theme: (browserWindow as Window & { __SUNDAY_STARTUP_THEME__: Record<string, string> }).__SUNDAY_STARTUP_THEME__,
  }
}

describe('Sunday desktop transparent startup', () => {
  it('uses a native transparent window with only a centered startup mark', () => {
    const mainWindow = tauriConfig.app?.windows?.[0]

    expect(desktopHtml).toContain('<title>Sunday</title>')
    expect(mainWindow?.transparent).toBe(true)
    expect(mainWindow?.backgroundColor).toBe('#00000000')
    expect(mainWindow?.shadow).toBe(true)
    expect(mainWindow?.windowEffects).toBeUndefined()
    expect(desktopMainSource).toContain('window.requestAnimationFrame')
    expect(desktopMainSource).toContain("invoke('enable_startup_glass')")
    expect(desktopRustSource).toContain('fn enable_startup_glass(window: WebviewWindow)')
    expect(desktopRustSource).toContain('.effect(Effect::Acrylic)')
    expect(desktopRustSource).toContain('.color((58, 59, 63, 32).into())')
    expect(desktopHtml).toContain('html, body, #app')
    expect(desktopHtml).toContain('background: transparent !important')
    expect(desktopHtml).toContain('data-startup-mark')
    expect(desktopHtml).not.toContain('sunday-app-icon-dark-display.png')
    expect(desktopHtml).not.toContain('sunday-app-icon-light-display.png')
    expect(desktopHtml).toContain('--startup-icon-surface')
    expect(desktopHtml).toContain('--startup-icon-face')
    expect(desktopHtml).toMatch(/data-startup-mark[\s\S]*?<svg/)
    expect(desktopHtml).toContain('id="startup-icon-frame"')
    expect(desktopHtml).toContain('cx="367.5" cy="421.7"')
    expect(desktopHtml).toContain('M599.8 442.4C647.1 408.3 694.7 405.8 726.3 435.3')
    expect(desktopHtml).toContain('M318.1 581.4C410.9 697.3 603.9 694.6 703.4 582.6')
    expect(desktopHtml).toContain('--startup-glass-tint: rgba(58, 59, 63, 0.12)')
    expect(desktopHtml).toContain('background: var(--startup-glass-tint)')
    expect(desktopHtml).toContain('backdrop-filter: blur(18px) saturate(1.04) brightness(0.985) contrast(1.02)')
    expect(desktopHtml).toContain('--startup-glass-optics:')
    expect(desktopHtml).toContain('--startup-glass-edge:')
    expect(desktopHtml).toContain('#startup-splash::before')
    expect(desktopHtml).toContain('#startup-splash::after')
    expect(desktopHtml).toContain('mask-composite: exclude')
    expect(desktopHtml).not.toMatch(/#startup-splash\s*\{[^}]*\bborder\s*:/s)
    expect(desktopHtml).not.toMatch(/#startup-splash::(?:before|after)\s*\{[^}]*\banimation\s*:/s)
    expect(desktopHtml).toContain('data-startup-reveal')
    expect(desktopHtml).toContain('clip-path: circle(0 at 50% 50%)')
    expect(desktopHtml).not.toContain('--startup-splash-background')
    expect(desktopHtml).not.toContain('startup-splash__panel')
    expect(desktopHtml).not.toContain('startup-splash__copy')
    expect(bootstrapSource).not.toBe('')
    expect(desktopHtml.indexOf('sunday-theme-bootstrap')).toBeLessThan(desktopHtml.indexOf('<style>'))
  })

  it('bootstraps saved dark mode before the first stylesheet paint', () => {
    const result = runBootstrap({
      'lamtools.core.ui.preferences': JSON.stringify({ themeMode: 'dark' }),
    })

    expect(result.theme.effectiveMode).toBe('dark')
    expect(result.properties['--startup-body-text']).toBe('#FBF7F0')
    expect(result.properties['--startup-mark-color']).toBe('#FBF7F0')
    expect(result.properties['--startup-mark-shadow']).toContain('rgba(0, 0, 0, 0.24)')
    expect(result.properties['--startup-body-background']).toBeUndefined()
  })

  it('uses the frame-colored Sunday workbench for light and dark reveal fallbacks', () => {
    const light = runBootstrap({
      'lamtools.core.ui.preferences': JSON.stringify({ themeMode: 'light' }),
    })
    const dark = runBootstrap({
      'lamtools.core.ui.preferences': JSON.stringify({ themeMode: 'dark' }),
    })

    expect(light.theme.backdropBackground).toBe('#D2D8E6')
    expect(light.properties['--startup-reveal-background']).toBe('#D2D8E6')
    expect(dark.theme.backdropBackground).toBe('#3A3B3F')
    expect(dark.properties['--startup-reveal-background']).toBe('#3A3B3F')
  })

  it('bootstraps a custom dark backdrop and supports system mode', () => {
    const result = runBootstrap({
      'lamtools.core.ui.preferences': JSON.stringify({
        themeMode: 'system',
        darkTheme: {
          backdropAngle: 42,
          backdropText: '#fafafa',
          backdropStops: [
            { color: '#102030', position: 0 },
            { color: '#405060', position: 100 },
          ],
        },
      }),
    }, true)

    expect(result.theme.effectiveMode).toBe('dark')
    expect(result.theme.backdropBackground).toBe('linear-gradient(42deg, #102030 0%, #405060 100%)')
    expect(result.properties['--startup-reveal-background']).toBe('linear-gradient(42deg, #102030 0%, #405060 100%)')
  })

  it('keeps an explicit light preference on a dark system', () => {
    const result = runBootstrap({
      'lamtools.core.ui.preferences': JSON.stringify({ themeMode: 'light' }),
    }, true)

    expect(result.theme.effectiveMode).toBe('light')
    expect(result.properties['--startup-body-text']).toBe('#2E3138')
    expect(result.properties['--startup-mark-color']).toBe('#2E3138')
    expect(result.properties['--startup-mark-shadow']).toContain('rgba(23, 36, 81, 0.12)')
    expect(result.properties['--startup-body-background']).toBeUndefined()
  })

  it('bootstraps from the legacy key and survives storage failures', () => {
    const legacy = runBootstrap({
      'lamtools.core.ui': JSON.stringify({ themeMode: 'dark' }),
    })
    const unavailable = runBootstrap({}, true, true)

    expect(legacy.theme.effectiveMode).toBe('dark')
    expect(unavailable.theme.effectiveMode).toBe('dark')
    expect(unavailable.properties['--startup-body-background']).toBeUndefined()
  })

  it('migrates the exact previous Sunday palette before first paint', () => {
    const result = runBootstrap({
      'lamtools.core.ui.preferences': JSON.stringify({
        themeMode: 'dark',
        darkTheme: LEGACY_SUNDAY_DARK_THEME,
      }),
    })

    expect(result.theme.backdropBackground).toBe('#3A3B3F')
    expect(result.properties['--startup-reveal-background']).toBe('#3A3B3F')
  })

  it('migrates the shipped inverted-control palette before first paint', () => {
    const result = runBootstrap({
      'lamtools.core.ui.preferences': JSON.stringify({
        themeMode: 'dark',
        darkTheme: LEGACY_SUNDAY_INVERTED_DARK_THEME,
      }),
    })

    expect(result.theme.backdropBackground).toBe('#3A3B3F')
    expect(result.properties['--startup-reveal-background']).toBe('#3A3B3F')
  })

  it('migrates the previous gray-control palette before first paint', () => {
    const result = runBootstrap({
      'lamtools.core.ui.preferences': JSON.stringify({
        themeMode: 'dark',
        darkTheme: LEGACY_SUNDAY_FLAT_DARK_THEME,
      }),
    })

    expect(result.theme.backdropBackground).toBe('#3A3B3F')
    expect(result.properties['--startup-reveal-background']).toBe('#3A3B3F')
  })

  it('migrates the previous frame-gray dark backdrop before first paint', () => {
    const result = runBootstrap({
      'lamtools.core.ui.preferences': JSON.stringify({
        themeMode: 'dark',
        darkTheme: LEGACY_SUNDAY_FRAME_DARK_THEME,
      }),
    })

    expect(result.theme.backdropBackground).toBe('#3A3B3F')
    expect(result.properties['--startup-reveal-background']).toBe('#3A3B3F')
  })

  it('expands the current theme from the centered mark before revealing shell regions', () => {
    expect(motionSource).toContain("document.body.style.background = 'transparent'")
    expect(motionSource).toContain("root.style.background = 'var(--startup-glass-tint)'")
    expect(motionSource).toContain("app?.removeAttribute('aria-hidden')")
    expect(motionSource).toContain("'[data-startup-reveal]'")
    expect(motionSource).toContain('clipPath: `circle(${radius}px')
    expect(motionSource).toContain('farthestCornerRadius(centerX, centerY)')
    expect(motionSource).toContain("getPropertyValue('--theme-backdrop-background')")
    expect(motionSource).toContain("'[data-workspace-left-drawer]'")
    expect(motionSource).toContain("'.workspace-main'")
    expect(motionSource).toContain("'.floating-composer'")
    expect(motionSource).toContain('stagger: 0.045')
    expect(motionSource).toContain("timeline.to(titlebar, { autoAlpha: 1, y: 0, duration: 0.34, ease: 'power3.out' }, 0.58)")
    expect(motionSource).not.toMatch(/\? \[[a-zA-Z]+\] : \[\]/)
    expect(motionSource).toContain('(prefers-reduced-motion: reduce)')
    expect(motionSource).toContain('duration: 0.08')
    expect(motionSource).not.toMatch(/bounce|elastic/)
  })

  it('honors an explicit dark mode even when the system is light', () => {
    const result = resolveStartupThemePreference(false, storage({
      'lamtools.core.ui.preferences': JSON.stringify({ themeMode: 'dark' }),
    }))

    expect(result.effectiveMode).toBe('dark')
    expect(result.theme.backdropText).toBe('#FBF7F0')
    expect(result.backdropBackground).toBe('rgba(58, 59, 63, 1)')
  })

  it('uses the dark Sunday theme for system mode on a dark system', () => {
    const result = resolveStartupThemePreference(true, storage({
      'lamtools.core.ui.preferences': JSON.stringify({ themeMode: 'system' }),
    }))

    expect(result.effectiveMode).toBe('dark')
    expect(result.theme.processIconColor).toBe('#888990')
  })

  it('carries a saved custom dark backdrop into the first paint', () => {
    const result = resolveStartupThemePreference(false, storage({
      'lamtools.core.ui.preferences': JSON.stringify({
        themeMode: 'dark',
        darkTheme: {
          backdropAngle: 42,
          backdropStops: [
            { color: '#102030', position: 0 },
            { color: '#405060', position: 100 },
          ],
        },
      }),
    }))

    expect(result.backdropBackground).toBe('linear-gradient(42deg, rgba(16, 32, 48, 1) 0%, rgba(64, 80, 96, 1) 100%)')
  })

  it('falls back safely when the stored JSON is damaged', () => {
    const result = resolveStartupThemePreference(false, storage({
      'lamtools.core.ui.preferences': '{not-json',
    }))

    expect(result.effectiveMode).toBe('light')
    expect(result.theme.backdropText).toBe('#2E3138')
  })

  it('falls back safely when storage access fails', () => {
    const result = resolveStartupThemePreference(true, {
      getItem: () => { throw new Error('storage unavailable') },
    })

    expect(result.effectiveMode).toBe('dark')
    expect(result.theme.backdropText).toBe('#FBF7F0')
  })

  it('reads the legacy preferences key when the primary key is absent', () => {
    const result = resolveStartupThemePreference(true, storage({
      'lamtools.core.ui': JSON.stringify({ themeMode: 'light' }),
    }))

    expect(result.effectiveMode).toBe('light')
    expect(result.theme.processIconColor).toBe('#C9D0DF')
  })
})
