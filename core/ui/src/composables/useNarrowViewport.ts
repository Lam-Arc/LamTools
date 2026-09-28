import { onMounted, onUnmounted, ref, type Ref } from 'vue'

/** The breakpoint the workspace styles switch on for phones. */
export const NARROW_VIEWPORT_MAX_WIDTH = 640

/**
 * Follow the same `max-width` breakpoint the styles use, so a component can
 * pick the narrow-screen default (phones, or a desktop window dragged narrow)
 * instead of guessing from the user agent.
 */
export function useNarrowViewport(maxWidth: number = NARROW_VIEWPORT_MAX_WIDTH): Ref<boolean> {
  const matches = ref(false)
  const query = typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    ? window.matchMedia(`(max-width: ${maxWidth}px)`)
    : null

  const update = (): void => {
    matches.value = query ? query.matches : false
  }
  // Read at setup rather than on mount: the first paint must already use the
  // narrow default, otherwise a phone renders one frame in the wide mode.
  update()

  onMounted(() => {
    query?.addEventListener?.('change', update)
  })
  onUnmounted(() => {
    query?.removeEventListener?.('change', update)
  })

  return matches
}
