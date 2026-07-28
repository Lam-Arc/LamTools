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
  const stageOpen = ref(false)
  const stageHeight = ref(300)
  const isNarrowViewport = ref(false)
  const density = ref<DensityMode>(options.density ?? 'standard')
  const contentWidth = ref(options.contentWidth ?? 780)
  const theme = ref<ThemeData>(options.theme ?? { ...DEFAULT_THEME })

  // --- shell class ---
  const shellClass = computed(() => ({
    'left-open': leftOpen.value,
    'right-open': rightOpen.value,
    'stage-open': stageOpen.value,
    [`density-${density.value}`]: true,
  }))

  const rightDrawerModal = computed(() => rightOpen.value && isNarrowViewport.value)

  // --- shell CSS variables ---
  const shellStyle = computed(() => {
    const cssVars = themeToCSSVars(theme.value)
    // Extract the first gradient stop color for the Edge title bar.
    const stops = [...(theme.value.backdropStops || [])].sort(
      (a, b) => (a.position ?? 0) - (b.position ?? 0),
    )
    const titlebarBg = stops.length > 0 ? (stops[0].color || '#111111') : '#111111'
    return {
      '--content-width': `${Math.min(1120, Math.max(560, contentWidth.value))}px`,
      '--stage-height': `${stageHeight.value}px`,
      '--theme-titlebar-bg': titlebarBg,
      ...cssVars,
    } as Record<string, string>
  })

  // Sync title bar color to :root and meta tag for Edge app window.
  watch(
    () => [shellStyle.value['--theme-titlebar-bg'], shellStyle.value['--theme-main-solid']] as const,
    ([titlebarBg, mainSolid]) => {
      if (typeof document === 'undefined') return
      if (titlebarBg) document.documentElement.style.setProperty('--theme-titlebar-bg', titlebarBg)
      if (mainSolid) document.documentElement.style.setProperty('--theme-main-solid', mainSolid)
      const meta = document.querySelector('meta[name="theme-color"]')
      if (meta && titlebarBg) meta.setAttribute('content', titlebarBg)
    },
    { immediate: true },
  )

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

  function toggleStage() {
    stageOpen.value = !stageOpen.value
  }

  // --- stage resize (drag handle) ---
  let resizeActive = false
  function startStageResize(event: PointerEvent) {
    resizeActive = true
    const target = event.target as HTMLElement
    target.setPointerCapture(event.pointerId)
    target.classList.add('dragging')
    document.body.style.cursor = 'ns-resize'
    document.body.style.userSelect = 'none'
  }
  function onStageResizeMove(event: PointerEvent) {
    if (!resizeActive) return
    const newHeight = Math.max(80, Math.min(window.innerHeight - 120, event.clientY))
    stageHeight.value = newHeight
  }
  function endStageResize(event: PointerEvent) {
    if (!resizeActive) return
    resizeActive = false
    const target = event.target as HTMLElement
    target.classList.remove('dragging')
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
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
  watch([density, contentWidth, theme, stageHeight], () => {
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
      if (saved.stageOpen !== undefined) stageOpen.value = saved.stageOpen
      if (saved.stageHeight) stageHeight.value = saved.stageHeight
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
        stageOpen: stageOpen.value,
        stageHeight: stageHeight.value,
      }),
    )
  }

  return {
    // state
    leftOpen,
    rightOpen,
    leftPinned,
    rightPinned,
    stageOpen,
    stageHeight,
    isNarrowViewport,
    density,
    contentWidth,
    theme,
    // computed
    shellClass,
    shellStyle,
    rightDrawerModal,
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
    toggleStage,
    startStageResize,
    onStageResizeMove,
    endStageResize,
    goSettings: options.onSettings ?? (() => {}),
    // persistence
    loadSettings,
    saveSettings,
  }
}
