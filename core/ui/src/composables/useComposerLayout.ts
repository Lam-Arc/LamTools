import {
  computed,
  nextTick,
  onMounted,
  onUnmounted,
  reactive,
  ref,
  watch,
  type ComputedRef,
  type Ref,
} from 'vue'

export type ComposerPlacement = 'center' | 'bottom'

export interface ComposerLayoutState {
  placement: ComposerPlacement
  keyboardInset: number
  safeAreaBottom: number
  composerHeight: number
  viewportOpen: boolean
  hasEnteredWorkMode: boolean
}

export interface ComposerVisualViewportLike {
  height: number
  offsetTop?: number
  scale?: number
}

export interface ComposerLayoutOptions {
  root: Ref<HTMLElement | null>
  emptySession: Readonly<Ref<boolean>> | ComputedRef<boolean>
  viewportOpen: Readonly<Ref<boolean>> | ComputedRef<boolean>
  sessionKey: Readonly<Ref<string | null>> | ComputedRef<string | null>
  sessionReady: Readonly<Ref<boolean>> | ComputedRef<boolean>
}

/**
 * Calculate the part of the layout viewport covered by a virtual keyboard.
 * The visual viewport is intentionally optional: desktop browsers and older
 * WebViews can expose no VisualViewport API, in which case the inset is zero.
 */
export function calculateKeyboardInset(
  innerHeight: number,
  visualViewport?: ComposerVisualViewportLike | null,
): number {
  if (!visualViewport || !Number.isFinite(innerHeight) || !Number.isFinite(visualViewport.height)) {
    return 0
  }
  return Math.max(0, innerHeight - visualViewport.height - (visualViewport.offsetTop ?? 0))
}

function readSafeAreaBottom(): number {
  if (typeof document === 'undefined' || !document.body) return 0

  const probe = document.createElement('div')
  probe.style.position = 'fixed'
  probe.style.visibility = 'hidden'
  probe.style.pointerEvents = 'none'
  probe.style.height = 'env(safe-area-inset-bottom, 0px)'
  document.body.appendChild(probe)
  try {
    const value = Number.parseFloat(window.getComputedStyle(probe).height)
    return Number.isFinite(value) ? Math.max(0, value) : 0
  } catch {
    return 0
  } finally {
    probe.remove()
  }
}

/**
 * Owns the only composer placement state for WorkspaceShell.
 *
 * Placement is deliberately monotonic for a session: once the user enters
 * the working state it stays docked until the host selects/resets a session.
 * Keyboard and safe-area values are layout inputs, not extra placement modes.
 */
export function useComposerLayout(options: ComposerLayoutOptions) {
  const enteredWorkModeSessions = reactive(new Set<string>())
  const unkeyedHasEnteredWorkMode = ref(false)
  const keyboardInset = ref(0)
  const safeAreaBottom = ref(0)
  // A useful first-frame fallback before ResizeObserver can measure the card.
  const composerHeight = ref(120)

  const viewportOpen = computed(() => options.viewportOpen.value)
  const sessionKey = computed(() => options.sessionKey.value)
  const sessionReady = computed(() => options.sessionReady.value)
  const hasEnteredWorkMode = computed(() => (
    sessionKey.value
      ? enteredWorkModeSessions.has(sessionKey.value)
      : unkeyedHasEnteredWorkMode.value
  ))
  const placement = ref<ComposerPlacement>('bottom')

  function syncPlacementForSession(): void {
    // During history loading the host has not established whether this is an
    // empty or populated session yet. Keep the current visual state and settle
    // it once sessionReady becomes true.
    if (!sessionReady.value) return

    if (viewportOpen.value || !options.emptySession.value) {
      placement.value = 'bottom'
      if (sessionKey.value) enteredWorkModeSessions.add(sessionKey.value)
      else unkeyedHasEnteredWorkMode.value = true
      return
    }

    placement.value = hasEnteredWorkMode.value ? 'bottom' : 'center'
  }

  syncPlacementForSession()

  const state = computed<ComposerLayoutState>(() => ({
    placement: placement.value,
    keyboardInset: keyboardInset.value,
    safeAreaBottom: safeAreaBottom.value,
    composerHeight: composerHeight.value,
    viewportOpen: viewportOpen.value,
    hasEnteredWorkMode: hasEnteredWorkMode.value,
  }))
  const style = computed<Record<string, string>>(() => ({
    '--keyboard-inset': `${keyboardInset.value}px`,
    // Keep the CSS env() expression live for devices whose safe-area value can
    // change after rotation. The numeric ref is exposed in state for callers
    // and tests that need the measured value.
    '--safe-area-bottom': 'env(safe-area-inset-bottom, 0px)',
    '--composer-bottom-offset': 'max(var(--keyboard-inset), var(--safe-area-bottom))',
    '--composer-height': `${composerHeight.value}px`,
  }))
  const shellClass = computed(() => `workspace-shell--composer-${placement.value}`)
  const rootClass = computed(() => `composer-root--composer-${placement.value}`)

  function enterBottom(): void {
    placement.value = 'bottom'
    if (sessionKey.value) enteredWorkModeSessions.add(sessionKey.value)
    else unkeyedHasEnteredWorkMode.value = true
  }

  function resetForSession(): void {
    syncPlacementForSession()
  }

  function syncKeyboardInset(): void {
    if (typeof window === 'undefined') return
    const activeElement = document.activeElement
    const isTextEntryFocused = activeElement instanceof HTMLElement
      && Boolean(activeElement.closest('input, textarea, select, [contenteditable]:not([contenteditable="false"])'))
    const nextInset = calculateKeyboardInset(window.innerHeight, window.visualViewport)
    keyboardInset.value = isTextEntryFocused ? nextInset : 0
    safeAreaBottom.value = readSafeAreaBottom()
  }

  let keyboardSyncFrame: number | undefined

  function scheduleKeyboardSync(): void {
    if (keyboardSyncFrame !== undefined || typeof window === 'undefined') return
    const callback = () => {
      keyboardSyncFrame = undefined
      syncKeyboardInset()
    }
    if (typeof window.requestAnimationFrame === 'function') {
      keyboardSyncFrame = window.requestAnimationFrame(callback)
    } else {
      keyboardSyncFrame = Number(window.setTimeout(callback, 0))
    }
  }

  let observedComposer: HTMLElement | null = null
  let resizeObserver: ResizeObserver | null = null
  let mutationObserver: MutationObserver | null = null
  let measureFrame: number | undefined

  function measureComposer(): void {
    const composer = options.root.value?.querySelector<HTMLElement>('.floating-composer') ?? null
    if (!composer) {
      composerHeight.value = 0
      return
    }
    const height = composer.getBoundingClientRect().height
    if (height > 0 && Number.isFinite(height)) composerHeight.value = Math.ceil(height)
  }

  function scheduleMeasure(): void {
    if (measureFrame !== undefined) return
    const callback = () => {
      measureFrame = undefined
      observeComposer()
      measureComposer()
    }
    if (typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function') {
      measureFrame = window.requestAnimationFrame(callback)
    } else {
      measureFrame = Number(window.setTimeout(callback, 0))
    }
  }

  function observeComposer(): void {
    const composer = options.root.value?.querySelector<HTMLElement>('.floating-composer') ?? null
    if (composer === observedComposer) return

    resizeObserver?.disconnect()
    resizeObserver = null
    observedComposer = composer
    if (!composer) {
      composerHeight.value = 0
      return
    }
    if (typeof ResizeObserver === 'undefined') return

    resizeObserver = new ResizeObserver(() => {
      measureComposer()
    })
    resizeObserver.observe(composer)
  }

  function onViewportChange(): void {
    syncKeyboardInset()
    scheduleMeasure()
  }

  function attachObservers(): void {
    const root = options.root.value
    if (!root) return

    mutationObserver?.disconnect()
    mutationObserver = typeof MutationObserver === 'undefined' ? null : new MutationObserver(() => {
      scheduleMeasure()
    })
    mutationObserver?.observe(root, { childList: true, subtree: true })
    observeComposer()
    measureComposer()
  }

  watch([
    options.sessionKey,
    options.sessionReady,
    options.emptySession,
    options.viewportOpen,
  ], syncPlacementForSession)
  watch(options.sessionKey, () => {
    // Session changes normally blur the composer. Clear the transient keyboard
    // compensation immediately; a still-open keyboard will be measured again
    // by the next viewport event or the focus sync path.
    keyboardInset.value = 0
    safeAreaBottom.value = readSafeAreaBottom()
  })
  watch(options.root, () => {
    void nextTick(() => {
      attachObservers()
      scheduleMeasure()
    })
  })

  onMounted(() => {
    syncKeyboardInset()
    window.addEventListener('resize', onViewportChange, { passive: true })
    window.addEventListener('orientationchange', onViewportChange, { passive: true })
    window.visualViewport?.addEventListener('resize', onViewportChange, { passive: true })
    window.visualViewport?.addEventListener('scroll', onViewportChange, { passive: true })
    void nextTick(() => {
      attachObservers()
      scheduleMeasure()
    })
  })

  onUnmounted(() => {
    window.removeEventListener('resize', onViewportChange)
    window.removeEventListener('orientationchange', onViewportChange)
    window.visualViewport?.removeEventListener('resize', onViewportChange)
    window.visualViewport?.removeEventListener('scroll', onViewportChange)
    resizeObserver?.disconnect()
    mutationObserver?.disconnect()
    resizeObserver = null
    mutationObserver = null
    if (measureFrame !== undefined) {
      if (typeof window.cancelAnimationFrame === 'function') window.cancelAnimationFrame(measureFrame)
      else window.clearTimeout(measureFrame)
      measureFrame = undefined
    }
    if (keyboardSyncFrame !== undefined) {
      if (typeof window.cancelAnimationFrame === 'function') window.cancelAnimationFrame(keyboardSyncFrame)
      else window.clearTimeout(keyboardSyncFrame)
      keyboardSyncFrame = undefined
    }
  })

  return {
    placement,
    state,
    style,
    shellClass,
    rootClass,
    enterBottom,
    syncKeyboardInset,
    scheduleKeyboardSync,
    resetForSession,
  }
}
