import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'
import { resolveStartupThemePreference } from '../src/motion/startupSplash'

const desktopHtml = readFileSync(resolve(process.cwd(), '../desktop/index.html'), 'utf8')
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

describe('Sunday desktop startup reveal', () => {
  it('uses a bare centered mark over a translucent theme veil', () => {
    expect(desktopHtml).toContain('<title>Sunday</title>')
    expect(desktopHtml).toContain('data-startup-reveal')
    expect(desktopHtml).toContain('data-startup-mark')
    expect(desktopHtml).toContain('backdrop-filter: blur(18px)')
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
    expect(result.properties['--startup-body-background']).toContain('#171926')
    expect(result.properties['--startup-body-text']).toBe('#f4efff')
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
    expect(result.properties['--startup-reveal-background']).toBe('linear-gradient(42deg, #102030 0%, #405060 100%)')
  })

  it('keeps an explicit light preference on a dark system', () => {
    const result = runBootstrap({
      'lamtools.core.ui.preferences': JSON.stringify({ themeMode: 'light' }),
    }, true)

    expect(result.theme.effectiveMode).toBe('light')
    expect(result.properties['--startup-body-background']).toContain('#fff0df')
    expect(result.properties['--startup-body-text']).toBe('#17265a')
    expect(result.properties['--startup-mark-shadow']).toContain('rgba(23, 36, 81, 0.12)')
    expect(desktopHtml).not.toMatch(/@media \(prefers-color-scheme: dark\)[\s\S]*?\bbody\s*\{/)
  })

  it('bootstraps from the legacy key and survives storage failures', () => {
    const legacy = runBootstrap({
      'lamtools.core.ui': JSON.stringify({ themeMode: 'dark' }),
    })
    const unavailable = runBootstrap({}, true, true)

    expect(legacy.theme.effectiveMode).toBe('dark')
    expect(unavailable.theme.effectiveMode).toBe('dark')
    expect(unavailable.properties['--startup-body-background']).toContain('#171926')
  })

  it('expands a compositor-isolated theme plane then reveals shell regions in stages', () => {
    expect(motionSource).toContain('clipPath: `circle(${radius}px')
    expect(motionSource).toContain("'[data-workspace-left-drawer]'")
    expect(motionSource).toContain("'.workspace-main'")
    expect(motionSource).toContain("'.floating-composer'")
    expect(motionSource).toContain("getPropertyValue('--theme-backdrop-background')")
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
    expect(result.theme.backdropText).toBe('#f4efff')
    expect(result.backdropBackground).toContain('rgba(23, 25, 38, 1)')
  })

  it('uses the dark Sunday theme for system mode on a dark system', () => {
    const result = resolveStartupThemePreference(true, storage({
      'lamtools.core.ui.preferences': JSON.stringify({ themeMode: 'system' }),
    }))

    expect(result.effectiveMode).toBe('dark')
    expect(result.theme.processIconColor).toBe('#a693ff')
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
    expect(result.theme.backdropText).toBe('#17265a')
  })

  it('falls back safely when storage access fails', () => {
    const result = resolveStartupThemePreference(true, {
      getItem: () => { throw new Error('storage unavailable') },
    })

    expect(result.effectiveMode).toBe('dark')
    expect(result.theme.backdropText).toBe('#f4efff')
  })

  it('reads the legacy preferences key when the primary key is absent', () => {
    const result = resolveStartupThemePreference(true, storage({
      'lamtools.core.ui': JSON.stringify({ themeMode: 'light' }),
    }))

    expect(result.effectiveMode).toBe('light')
    expect(result.theme.processIconColor).toBe('#6755e8')
  })
})
