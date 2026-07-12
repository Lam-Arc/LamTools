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
  const bottomThresholdPx = options.bottomThresholdPx ?? CORE_SCROLL_BOTTOM_THRESHOLD_PX

  function isNearBottom(): boolean {
    return coreIsScrollNearBottom(elementRef.value, bottomThresholdPx)
  }

  function handleWheel(event: Pick<WheelEvent, 'deltaY'>) {
    if (event.deltaY < 0) autoFollow.value = false
  }

  function handleScroll() {
    if (isNearBottom()) autoFollow.value = true
  }

  async function scrollToBottom(force = false, behavior: ScrollBehavior = 'auto') {
    await (options.afterDomUpdate?.() ?? nextTick())
    const el = elementRef.value
    if (!el) return
    if (!force && !autoFollow.value) return
    if (behavior === 'smooth' && !(options.reduceMotion?.() ?? shouldReduceMotion())) {
      el.scrollTo?.({ top: el.scrollHeight, behavior: 'smooth' })
      autoFollow.value = true
      return
    }
    el.scrollTop = el.scrollHeight
    await (options.afterFrame?.() ?? afterFrame())
    el.scrollTop = el.scrollHeight
    autoFollow.value = true
  }

  return {
    autoFollow,
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
