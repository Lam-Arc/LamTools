/**
 * useShellLayout — manages drawer open/pin state, density, content width,
 * keyboard shortcuts, and CSS variable injection for the workspace shell.
 *
 * Products use this instead of duplicating drawer logic in WorkbenchView.
 */

import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { type ThemeData, themeToCSSVars, type ThemeCSSVars, migrateThemeDefaults } from '../helpers/theme'
import { DEFAULT_THEME } from '../helpers/theme'

export type DensityMode = 'compact' | 'standard' | 'loose'
export type { ThemeData, ThemeCSSVars }

export interface ShellLayoutOptions {
  /** localStorage key prefix for the consuming member product */
  storageKey: string
  /** Initial density */
  density?: DensityMode
  /** Initial content width (560–1120) */
  contentWidth?: number
  /** Initial theme (defaults to DEFAULT_THEME) */
  theme?: ThemeData
  /** Whether the right panel is visible at all */
  showRightPanel?: boolean
  /** Callback when settings button is clicked */
  onSettings?: () => void
}

export function useShellLayout(options: ShellLayoutOptions) {
  // --- state ---
  const leftOpen = ref(true)
  const rightOpen = ref(false)
  const leftPinned = ref(true)
  const rightPinned = ref(false)
  const isNarrowViewport = ref(false)
  const density = ref<DensityMode>(options.density ?? 'standard')
  const contentWidth = ref(options.contentWidth ?? 780)
  const theme = ref<ThemeData>(options.theme ?? { ...DEFAULT_THEME })

  // --- shell class ---
  const shellClass = computed(() => ({
    'left-open': leftOpen.value,
    'right-open': rightOpen.value,
    [`density-${density.value}`]: true,
  }))

  // --- shell CSS variables ---
  const shellStyle = computed(() => {
    const cssVars = themeToCSSVars(theme.value)
    return {
      '--content-width': `${Math.min(1120, Math.max(560, contentWidth.value))}px`,
      ...cssVars,
    } as Record<string, string>
  })

  // --- drawer controls ---
  function toggleLeftPinned() {
    leftPinned.value = !leftPinned.value
    if (leftPinned.value) leftOpen.value = true
  }

  function toggleRightPinned() {
    rightPinned.value = !rightPinned.value
    if (rightPinned.value) rightOpen.value = true
  }

  function onLeftDrawerLeave() {
    if (!leftPinned.value) leftOpen.value = false
  }

  function onRightDrawerLeave() {
    if (!rightPinned.value) rightOpen.value = false
  }

  function openLeftDrawer() {
    if (isNarrowViewport.value) rightOpen.value = false
    leftOpen.value = true
  }

  function openRightDrawer() {
    if (isNarrowViewport.value) leftOpen.value = false
    rightOpen.value = true
  }

  function toggleLeftDrawer() {
    if (leftOpen.value) leftOpen.value = false
    else openLeftDrawer()
  }

  function toggleRightDrawer() {
    if (rightOpen.value) rightOpen.value = false
    else openRightDrawer()
  }

  function closeDrawers() {
    leftOpen.value = false
    rightOpen.value = false
  }

  function onPointerDown(event: PointerEvent) {
    const target = event.target as HTMLElement | null
    if (!target) return
    // Close composer menus
    if (!target.closest('.composer-menu') && !target.closest('.composer-pill')) {
      document.querySelectorAll('.composer-menu').forEach((el) => {
        ;(el as HTMLElement).style.display = 'none'
      })
    }
    // Close drawers when clicking outside
    if (
      !leftPinned.value &&
      leftOpen.value &&
      !target.closest('.drawer-left') &&
      !target.closest('.edge-left')
    ) {
      leftOpen.value = false
    }
    if (
      !rightPinned.value &&
      rightOpen.value &&
      !target.closest('.drawer-right') &&
      !target.closest('.edge-right')
    ) {
      rightOpen.value = false
    }
  }

  // --- keyboard shortcuts ---
  function onKeydown(event: KeyboardEvent) {
    // Ctrl+Tab → toggle left drawer
    if (event.ctrlKey && event.key.toLowerCase() === 'tab') {
      event.preventDefault()
      if (leftPinned.value) {
        leftPinned.value = false
        leftOpen.value = false
      } else {
        leftOpen.value = !leftOpen.value
      }
      return
    }
    // Ctrl+E → toggle right drawer
    if (event.ctrlKey && event.key.toLowerCase() === 'e') {
      event.preventDefault()
      rightOpen.value = !rightOpen.value
      return
    }
    // Escape → close drawers
    if (event.key === 'Escape') {
      if (isNarrowViewport.value) closeDrawers()
      else {
        if (!leftPinned.value) leftOpen.value = false
        if (!rightPinned.value) rightOpen.value = false
      }
      return
    }
  }

  let narrowMediaQuery: MediaQueryList | undefined
  function syncViewportMode(event: MediaQueryList | MediaQueryListEvent) {
    isNarrowViewport.value = event.matches
    if (!event.matches) return
    leftPinned.value = false
    rightPinned.value = false
    closeDrawers()
  }

  // --- auto-save with debounce ---
  let saveTimer: ReturnType<typeof setTimeout> | undefined
  watch([density, contentWidth, theme], () => {
    clearTimeout(saveTimer)
    saveTimer = setTimeout(saveSettings, 500)
  })

  onMounted(() => {
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeydown)
    narrowMediaQuery = window.matchMedia?.('(max-width: 640px)')
    if (narrowMediaQuery) {
      syncViewportMode(narrowMediaQuery)
      narrowMediaQuery.addEventListener('change', syncViewportMode)
    }
    loadSettings()
  })

  onUnmounted(() => {
    document.removeEventListener('pointerdown', onPointerDown)
    document.removeEventListener('keydown', onKeydown)
    narrowMediaQuery?.removeEventListener('change', syncViewportMode)
    clearTimeout(saveTimer)
  })

  // --- persistence ---
  function loadSettings() {
    try {
      const raw = localStorage.getItem(options.storageKey)
      if (!raw) return
      const saved = JSON.parse(raw)
      if (saved.density) density.value = saved.density
      if (saved.contentWidth) contentWidth.value = saved.contentWidth
      if (saved.theme) theme.value = migrateThemeDefaults({ ...DEFAULT_THEME, ...saved.theme })
    } catch {
      /* ignore */
    }
  }

  function saveSettings() {
    localStorage.setItem(
      options.storageKey,
      JSON.stringify({
        density: density.value,
        contentWidth: contentWidth.value,
        theme: theme.value,
      }),
    )
  }

  return {
    // state
    leftOpen,
    rightOpen,
    leftPinned,
    rightPinned,
    isNarrowViewport,
    density,
    contentWidth,
    theme,
    // computed
    shellClass,
    shellStyle,
    // actions
    toggleLeftPinned,
    toggleRightPinned,
    onLeftDrawerLeave,
    onRightDrawerLeave,
    openLeftDrawer,
    openRightDrawer,
    toggleLeftDrawer,
    toggleRightDrawer,
    closeDrawers,
    goSettings: options.onSettings ?? (() => {}),
    // persistence
    loadSettings,
    saveSettings,
  }
}
