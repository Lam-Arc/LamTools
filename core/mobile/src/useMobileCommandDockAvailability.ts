import { onMounted, onUnmounted, ref } from 'vue'

export const MOBILE_COMMAND_DOCK_QUERY = '(max-width: 640px)'

export function createMobileCommandDockAvailability(mediaQuery: MediaQueryList | null) {
  const available = ref(mediaQuery?.matches ?? false)
  const update = (event: MediaQueryListEvent) => { available.value = event.matches }

  return {
    available,
    start: () => mediaQuery?.addEventListener('change', update),
    stop: () => mediaQuery?.removeEventListener('change', update),
  }
}

export function useMobileCommandDockAvailability() {
  const mediaQuery = typeof window === 'undefined'
    ? null
    : window.matchMedia(MOBILE_COMMAND_DOCK_QUERY)
  const state = createMobileCommandDockAvailability(mediaQuery)

  onMounted(state.start)
  onUnmounted(state.stop)
  return state.available
}
