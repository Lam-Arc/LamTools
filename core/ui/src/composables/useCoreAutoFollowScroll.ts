import { nextTick, ref, type Ref } from 'vue'

export const CORE_SCROLL_BOTTOM_THRESHOLD_PX = 80

export interface CoreScrollableElement {
  scrollHeight: number
  scrollTop: number
  clientHeight: number
  scrollTo?: (options: ScrollToOptions) => void
}

export interface UseCoreAutoFollowScrollOptions {
  bottomThresholdPx?: number
  afterDomUpdate?: () => Promise<void>
  afterFrame?: () => Promise<void>
  reduceMotion?: () => boolean
}

export interface CoreAutoFollowScrollController {
  autoFollow: Ref<boolean>
  atBottom: Ref<boolean>
  isNearBottom: () => boolean
  handleWheel: (event: Pick<WheelEvent, 'deltaY'>) => void
  handleScroll: () => void
  scrollToBottom: (force?: boolean, behavior?: ScrollBehavior) => Promise<void>
}

export function coreIsScrollNearBottom(
  element: Pick<CoreScrollableElement, 'scrollHeight' | 'scrollTop' | 'clientHeight'> | null | undefined,
  thresholdPx = CORE_SCROLL_BOTTOM_THRESHOLD_PX,
): boolean {
  if (!element) return true
  return element.scrollHeight - element.scrollTop - element.clientHeight <= thresholdPx
}

export function useCoreAutoFollowScroll(
  elementRef: Ref<CoreScrollableElement | null>,
  options: UseCoreAutoFollowScrollOptions = {},
): CoreAutoFollowScrollController {
  const autoFollow = ref(true)
  // Whether the viewport currently sits near the bottom. Drives the
  // "jump to latest" affordance. Kept separate from `autoFollow` (the
  // "should we follow new content" intent) so a forced scroll can show
  // we've arrived at the bottom even while a stream tick is in flight.
  const atBottom = ref(true)
  const bottomThresholdPx = options.bottomThresholdPx ?? CORE_SCROLL_BOTTOM_THRESHOLD_PX

  function isNearBottom(): boolean {
    return coreIsScrollNearBottom(elementRef.value, bottomThresholdPx)
  }

  function handleWheel(event: Pick<WheelEvent, 'deltaY'>) {
    // Wheel fires before the resulting scroll event, so we can seize
    // control immediately on an upward swipe for a snappier feel.
    if (event.deltaY < 0) {
      autoFollow.value = false
      atBottom.value = false
    }
  }

  function handleScroll() {
    // Two-way: any scroll that lands near the bottom re-enables follow,
    // any scroll that leaves the bottom disables it. The scroll event
    // covers every input method (wheel, scrollbar drag, trackpad, keyboard),
    // so this is the single source of truth — unlike a wheel-only gate
    // which silently let scrollbar/trackpad users get yanked back down.
    const near = isNearBottom()
    autoFollow.value = near
    atBottom.value = near
  }

  async function scrollToBottom(force = false, behavior: ScrollBehavior = 'auto') {
    await (options.afterDomUpdate?.() ?? nextTick())
    const el = elementRef.value
    if (!el) return
    if (!force && !autoFollow.value) return
    if (behavior === 'smooth' && !(options.reduceMotion?.() ?? shouldReduceMotion())) {
      el.scrollTo?.({ top: el.scrollHeight, behavior: 'smooth' })
      autoFollow.value = true
      atBottom.value = true
      return
    }
    el.scrollTop = el.scrollHeight
    await (options.afterFrame?.() ?? afterFrame())
    // Correct only when content kept growing past the first write — avoids a
    // second forced layout on every stream tick.
    if (el.scrollTop !== el.scrollHeight) {
      el.scrollTop = el.scrollHeight
    }
    autoFollow.value = true
    atBottom.value = true
  }

  return {
    autoFollow,
    atBottom,
    isNearBottom,
    handleWheel,
    handleScroll,
    scrollToBottom,
  }
}

function shouldReduceMotion(): boolean {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

function afterFrame(): Promise<void> {
  if (typeof requestAnimationFrame !== 'function') return Promise.resolve()
  return new Promise(resolve => requestAnimationFrame(() => resolve()))
}
