/**
 * Tauri startup hand-off: native transparent first paint → Sunday mark → app shell.
 * Only the mark and shell entrance opacity/transforms are animated.
 */
import { gsap } from 'gsap'
import {
  SUNDAY_DARK_THEME,
  SUNDAY_LIGHT_THEME,
  gradientFromStops,
  migrateSundayThemeDefaults,
  normalizeTheme,
  type ThemeData,
  type ThemeMode,
} from '../helpers/theme'

const UI_PREFERENCES_STORAGE_KEY = 'lamtools.core.ui.preferences'
const LEGACY_UI_PREFERENCES_STORAGE_KEY = 'lamtools.core.ui'

type StartupThemeStorage = Pick<Storage, 'getItem'>

interface StoredUiPreferences {
  themeMode?: unknown
  theme?: Partial<ThemeData>
  lightTheme?: Partial<ThemeData>
  darkTheme?: Partial<ThemeData>
}

export interface StartupThemePresentation {
  effectiveMode: 'light' | 'dark'
  theme: ThemeData
  backdropBackground: string
}

interface StartupThemeWindow extends Window {
  __SUNDAY_STARTUP_THEME__?: {
    effectiveMode: 'light' | 'dark'
    backdropBackground: string
    backdropText: string
  }
}

let motionMedia: gsap.MatchMedia | null = null
let idleTimeline: gsap.core.Timeline | null = null
let completionTimeline: gsap.core.Timeline | null = null
let completionFallbackId: number | null = null

function getSplash(): HTMLElement | null {
  return document.querySelector<HTMLElement>('[data-startup-splash]')
}

function clearCompletionFallback(): void {
  if (completionFallbackId === null) return
  window.clearTimeout(completionFallbackId)
  completionFallbackId = null
}

function stopMotion(): void {
  idleTimeline?.kill()
  idleTimeline = null
  completionTimeline?.kill()
  completionTimeline = null
  motionMedia?.revert()
  motionMedia = null
  clearCompletionFallback()
}

function removeSplash(root: HTMLElement, entranceTargets: Element[] = []): void {
  clearCompletionFallback()
  if (entranceTargets.length) {
    gsap.set(entranceTargets, { clearProps: 'transform,opacity,visibility' })
  }
  root.remove()
  document.querySelector('#app')?.removeAttribute('aria-hidden')
}

function farthestCornerRadius(centerX: number, centerY: number): number {
  return Math.ceil(Math.hypot(
    Math.max(centerX, window.innerWidth - centerX),
    Math.max(centerY, window.innerHeight - centerY),
  ))
}

function readStoredUiPreferences(storage: StartupThemeStorage | null): StoredUiPreferences | null {
  if (!storage) return null
  for (const key of [UI_PREFERENCES_STORAGE_KEY, LEGACY_UI_PREFERENCES_STORAGE_KEY]) {
    try {
      const raw = storage.getItem(key)
      if (!raw) continue
      const parsed: unknown = JSON.parse(raw)
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        return parsed as StoredUiPreferences
      }
    } catch {
      // A damaged primary value or unavailable storage must not block legacy/default recovery.
    }
  }
  return null
}

/** Resolve the exact saved theme needed for the native first paint. */
export function resolveStartupThemePreference(
  systemPrefersDark = false,
  storage: StartupThemeStorage | null | undefined = undefined,
): StartupThemePresentation {
  let resolvedStorage = storage
  if (resolvedStorage === undefined && typeof window !== 'undefined') {
    try {
      resolvedStorage = window.localStorage
    } catch {
      resolvedStorage = null
    }
  }
  const preferences = readStoredUiPreferences(resolvedStorage ?? null)
  const storedMode = preferences?.themeMode
  const themeMode: ThemeMode = storedMode === 'light' || storedMode === 'dark' || storedMode === 'system'
    ? storedMode
    : 'system'
  const effectiveMode = themeMode === 'system'
    ? (systemPrefersDark ? 'dark' : 'light')
    : themeMode
  const defaultTheme = effectiveMode === 'dark' ? SUNDAY_DARK_THEME : SUNDAY_LIGHT_THEME
  const savedTheme = effectiveMode === 'dark' ? preferences?.darkTheme : preferences?.lightTheme
  const theme = migrateSundayThemeDefaults(normalizeTheme({
    ...defaultTheme,
    ...(savedTheme || preferences?.theme || {}),
  }), effectiveMode)

  return {
    effectiveMode,
    theme,
    backdropBackground: gradientFromStops(theme.backdropAngle, theme.backdropStops, 1),
  }
}

export function startStartupSplash(): void {
  const root = getSplash()
  if (!root) return

  stopMotion()
  document.querySelector('#app')?.setAttribute('aria-hidden', 'true')

  const systemPrefersDark = window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false
  const startupTheme = resolveStartupThemePreference(systemPrefersDark)
  const bootstrappedTheme = (window as StartupThemeWindow).__SUNDAY_STARTUP_THEME__
  const reveal = root.querySelector<HTMLElement>('[data-startup-reveal]')
  const backdropBackground = bootstrappedTheme?.backdropBackground || startupTheme.backdropBackground
  const backdropText = bootstrappedTheme?.backdropText || startupTheme.theme.backdropText
  // The native window and every pre-shell webview layer stay transparent. The
  // splash alone supplies a neutral tint over the native Acrylic backdrop;
  // the normal workspace shell owns its themed surface after Vue mounts.
  document.body.style.background = 'transparent'
  document.body.style.backgroundColor = 'transparent'
  document.body.style.color = backdropText
  root.style.background = 'var(--startup-glass-tint)'
  root.style.color = backdropText
  if (reveal) reveal.style.background = backdropBackground

  const mark = root.querySelector<HTMLElement>('[data-startup-mark]')
  if (!mark) return

  gsap.set(root, { autoAlpha: 1 })
  gsap.set(mark, { autoAlpha: 1, x: 0, y: 0, scale: 1, rotation: 0 })

  motionMedia = gsap.matchMedia()
  motionMedia.add('(prefers-reduced-motion: no-preference)', () => {
    idleTimeline = gsap.timeline({ defaults: { overwrite: 'auto' } })
      .fromTo(
        mark,
        { autoAlpha: 0.72, y: 5, scaleX: 0.94, scaleY: 1.06 },
        { autoAlpha: 1, y: 0, scaleX: 1.025, scaleY: 0.985, duration: 0.34, ease: 'power3.out' },
      )
      .to(mark, { scaleX: 1, scaleY: 1, duration: 0.24, ease: 'power2.out' })
      .to(mark, { y: -2, scale: 1.018, duration: 1.8, ease: 'sine.inOut', repeat: -1, yoyo: true })
  })
}

export function completeStartupSplash(): void {
  const root = getSplash()
  const app = document.querySelector<HTMLElement>('#app')
  if (!root) {
    app?.removeAttribute('aria-hidden')
    return
  }

  window.requestAnimationFrame(() => {
    if (!root.isConnected) {
      app?.removeAttribute('aria-hidden')
      return
    }

    const reveal = root.querySelector<HTMLElement>('[data-startup-reveal]')
    const mark = root.querySelector<HTMLElement>('[data-startup-mark]')
    const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
    const shell = app?.querySelector<HTMLElement>('.workspace-shell') ?? null
    const revealBackground = shell
      ? window.getComputedStyle(shell).getPropertyValue('--theme-backdrop-background').trim()
      : ''
    stopMotion()

    if (!reveal || !mark) {
      removeSplash(root)
      return
    }

    if (revealBackground) gsap.set(reveal, { background: revealBackground })

    const titlebar = app?.querySelector<HTMLElement>('.titlebar') ?? null
    const leftSidebar = app?.querySelector<HTMLElement>('[data-workspace-left-drawer]') ?? null
    const mainSurface = app?.querySelector<HTMLElement>('.workspace-main') ?? null
    const rightSidebar = app?.querySelector<HTMLElement>('[data-workspace-right-drawer]') ?? null
    const composer = app?.querySelector<HTMLElement>('.floating-composer') ?? null
    const entranceGroups = [titlebar, leftSidebar, mainSurface, rightSidebar, composer]
    const entranceTargets = entranceGroups.filter((target): target is HTMLElement => Boolean(target))

    if (reducedMotion) {
      gsap.set(reveal, { clipPath: 'none', autoAlpha: 1 })
      app?.removeAttribute('aria-hidden')
      completionFallbackId = window.setTimeout(() => removeSplash(root, entranceTargets), 180)
      completionTimeline = gsap.timeline({ onComplete: () => removeSplash(root, entranceTargets) })
        .to(mark, { autoAlpha: 0, duration: 0.08, ease: 'none' })
        .to(root, { autoAlpha: 0, duration: 0.08, ease: 'none' })
      return
    }

    const markRect = mark.getBoundingClientRect()
    const centerX = markRect.left + markRect.width / 2
    const centerY = markRect.top + markRect.height / 2
    const radius = farthestCornerRadius(centerX, centerY)

    gsap.set(reveal, {
      autoAlpha: 1,
      clipPath: `circle(0px at ${centerX}px ${centerY}px)`,
    })

    if (entranceTargets.length) gsap.set(entranceTargets, { autoAlpha: 0 })
    if (titlebar) gsap.set(titlebar, { y: -6 })
    if (leftSidebar) gsap.set(leftSidebar, { x: -10 })
    if (mainSurface) gsap.set(mainSurface, { y: 8 })
    if (rightSidebar) gsap.set(rightSidebar, { x: 10 })
    if (composer) gsap.set(composer, { y: 10 })
    // Keep the mounted shell hidden until its initial entrance state is in
    // place, otherwise a transparent splash can expose one unstyled frame.
    app?.removeAttribute('aria-hidden')

    completionFallbackId = window.setTimeout(() => removeSplash(root, entranceTargets), 1400)
    const timeline = gsap.timeline({
      defaults: { overwrite: 'auto' },
      onComplete: () => removeSplash(root, entranceTargets),
    })
      .to(mark, { scaleX: 1.055, scaleY: 0.955, duration: 0.14, ease: 'power2.out' }, 0)
      .to(mark, { scaleX: 0.985, scaleY: 1.025, duration: 0.14, ease: 'power2.inOut' }, 0.14)
      .to(reveal, {
        clipPath: `circle(${radius}px at ${centerX}px ${centerY}px)`,
        duration: 0.5,
        ease: 'power3.inOut',
      }, 0.06)
      .to(mark, { autoAlpha: 0, scale: 1.1, duration: 0.22, ease: 'power2.out' }, 0.3)
      .to(root, { autoAlpha: 0, duration: 0.36, ease: 'power2.out' }, 0.56)

    if (titlebar) {
      timeline.to(titlebar, { autoAlpha: 1, y: 0, duration: 0.34, ease: 'power3.out' }, 0.58)
    }
    const sidebars = [leftSidebar, rightSidebar].filter((target): target is HTMLElement => Boolean(target))
    if (sidebars.length) {
      timeline.to(sidebars, {
        autoAlpha: 1,
        x: 0,
        duration: 0.38,
        stagger: 0.045,
        ease: 'power3.out',
      }, 0.62)
    }
    const mainRegions = [mainSurface].filter((target): target is HTMLElement => Boolean(target))
    if (mainRegions.length) {
      timeline.to(mainRegions, {
        autoAlpha: 1,
        y: 0,
        duration: 0.4,
        stagger: 0.045,
        ease: 'power3.out',
      }, 0.68)
    }
    if (composer) {
      timeline.to(composer, { autoAlpha: 1, y: 0, duration: 0.38, ease: 'power3.out' }, 0.74)
    }
    completionTimeline = timeline
  })
}
