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

/**
 * How long `.drawer-right` takes to retract. Must stay equal to the
 * `--right-drawer-retract` token in variables.css: the raised layer is held for
 * exactly this long so the panel lowers only after it has finished retracting.
 */
export const RIGHT_DRAWER_RETRACT_MS = 180

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
  // 整界面切走：宿主进入整版分区（资料库/定时任务/…）或插件整面时，
  // 会话栏整列退场，只剩最左竖栏；退出后回到原状态。
  const sidebarCollapsed = ref(false)
  const isNarrowViewport = ref(false)
  const density = ref<DensityMode>(options.density ?? 'standard')
  const contentWidth = ref(options.contentWidth ?? 780)
  const theme = ref<ThemeData>(options.theme ?? { ...DEFAULT_THEME })

  // --- shell class ---
  const shellClass = computed(() => ({
    'left-open': leftOpen.value && !sidebarCollapsed.value,
    'right-open': rightOpen.value,
    'right-pinned': rightPinned.value,
    [`density-${density.value}`]: true,
  }))

  const rightDrawerModal = computed(() => rightOpen.value && isNarrowViewport.value)

  /** True whenever the right rail occupies the workspace. */
  const rightDrawerShown = computed(() => rightOpen.value)

  // The native title bar lives outside `.workspace-shell`, so mirror only the
  // two live main-surface insets to :root for title-bar extensions such as
  // Workflow tabs. This keeps them aligned while drawers open, close or pin.
  const titlebarMainInsets = computed(() => {
    // 右侧抽屉只剩贴边图标竖栏，宽度恒等于 --right-rail-width。
    const rightWidth = 46
    return {
      left: leftOpen.value ? 'var(--sidebar-width)' : '18px',
      right: (rightOpen.value && rightPinned.value) ? `${rightWidth}px` : '18px',
    }
  })

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
      '--theme-titlebar-bg': titlebarBg,
      ...cssVars,
    } as Record<string, string>
  })

  // Sync all theme CSS variables to :root — title bar & meta tag for the Edge
  // app window, and everything teleported to body (modals/onboarding) inherits
  // the theme instead of falling back to hardcoded dark values.
  let appliedThemeKeys: string[] = []
  watch(
    () => shellStyle.value,
    (style) => {
      if (typeof document === 'undefined') return
      // Remove previously-applied keys first so unmounting / hot-swapping a
      // shell never leaves stale theme vars on :root (audit 19 S3).
      for (const key of appliedThemeKeys) document.documentElement.style.removeProperty(key)
      appliedThemeKeys = []
      for (const [key, value] of Object.entries(style)) {
        if (key.startsWith('--theme-')) {
          document.documentElement.style.setProperty(key, value)
          appliedThemeKeys.push(key)
        }
      }
      const meta = document.querySelector('meta[name="theme-color"]')
      if (meta && style['--theme-titlebar-bg']) meta.setAttribute('content', style['--theme-titlebar-bg'])
    },
    { immediate: true },
  )

  watch(
    titlebarMainInsets,
    ({ left, right }) => {
      if (typeof document === 'undefined') return
      document.documentElement.style.setProperty('--titlebar-main-left', left)
      document.documentElement.style.setProperty('--titlebar-main-right', right)
    },
    { immediate: true },
  )

  // --- drawer controls ---
  function setSidebarCollapsed(collapsed: boolean) {
    sidebarCollapsed.value = collapsed
  }

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

  // The right rail retracts first and only then drops back to the background
  // layer. Lowering the layer up front hid the whole exit behind the opaque
  // main card, so the panel appeared to vanish rather than retract.
  const rightRetracting = ref(false)
  let rightRetractTimer: ReturnType<typeof setTimeout> | undefined

  function clearRightRetract(): void {
    if (rightRetractTimer === undefined) return
    clearTimeout(rightRetractTimer)
    rightRetractTimer = undefined
  }

  watch(rightDrawerShown, (shown) => {
    clearRightRetract()
    // A pinned rail sits beside the main card instead of above it, so it has
    // no raised layer to hold; phones keep drawers raised from the stylesheet.
    rightRetracting.value = !shown && !rightPinned.value
    if (!rightRetracting.value) return
    rightRetractTimer = setTimeout(() => {
      rightRetractTimer = undefined
      rightRetracting.value = false
    }, RIGHT_DRAWER_RETRACT_MS)
  })

  function onPointerDown(event: PointerEvent) {
    const target = event.target as HTMLElement | null
    if (!target) return
    // Close drawers when clicking outside (composer menus are closed by the
    // menu components themselves — reaching into .composer-menu from here
    // bypassed their open state and coupled this composable to their DOM,
    // audit 19 S3).
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
      !target.closest('.edge-right') &&
      // 悬停卡与其搭桥层浮在抽屉之外，点它们上面的控件同样不算“点在抽屉外”。
      !target.closest('[data-right-sidebar-card],[data-right-sidebar-bridge]')
    ) {
      rightOpen.value = false
    }
  }

  // --- keyboard shortcuts ---
  const EDITABLE_SELECTOR = 'input, textarea, select, [contenteditable]'
  function isTypingTarget(target: EventTarget | null): boolean {
    return target instanceof HTMLElement && Boolean(target.closest(EDITABLE_SELECTOR))
  }

  function onKeydown(event: KeyboardEvent) {
    // Never hijack keys while the user is typing (IME composition, input
    // fields) or when a repeat is held (audit 19 S3).
    if (event.repeat || isTypingTarget(event.target)) return
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
    const wasNarrow = isNarrowViewport.value
    isNarrowViewport.value = event.matches
    if (event.matches === wasNarrow) return
    if (!event.matches) {
      leftPinned.value = true
      leftOpen.value = true
      return
    }
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
      // Old Safari/WebViews only implement the deprecated addListener API.
      if (typeof narrowMediaQuery.addEventListener === 'function') {
        narrowMediaQuery.addEventListener('change', syncViewportMode)
      } else {
        narrowMediaQuery.addListener(syncViewportMode)
      }
    }
    loadSettings()
  })

  onUnmounted(() => {
    document.documentElement.style.removeProperty('--titlebar-main-left')
    document.documentElement.style.removeProperty('--titlebar-main-right')
    document.removeEventListener('pointerdown', onPointerDown)
    document.removeEventListener('keydown', onKeydown)
    if (narrowMediaQuery) {
      if (typeof narrowMediaQuery.removeEventListener === 'function') {
        narrowMediaQuery.removeEventListener('change', syncViewportMode)
      } else {
        narrowMediaQuery.removeListener(syncViewportMode)
      }
    }
    // Restore :root theme vars we wrote (audit 19 S3).
    if (typeof document !== 'undefined') {
      for (const key of appliedThemeKeys) document.documentElement.style.removeProperty(key)
      appliedThemeKeys = []
    }
    clearTimeout(saveTimer)
    clearRightRetract()
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
    try {
      localStorage.setItem(
        options.storageKey,
        JSON.stringify({
          density: density.value,
          contentWidth: contentWidth.value,
          theme: theme.value,
        }),
      )
    } catch {
      /* storage unavailable (private mode / quota) — persistence is best-effort */
    }
  }

  return {
    // state
    leftOpen,
    rightOpen,
    leftPinned,
    rightPinned,
    rightRetracting,
    isNarrowViewport,
    density,
    contentWidth,
    theme,
    // computed
    shellClass,
    shellStyle,
    rightDrawerModal,
    rightDrawerShown,
    sidebarCollapsed,
    // actions
    setSidebarCollapsed,
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
