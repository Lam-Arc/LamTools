import { nextTick, type Directive, type DirectiveBinding } from 'vue'
import { coreIsScrollNearBottom } from '../composables/useCoreAutoFollowScroll'

interface AutoFollowState {
  follow: boolean
  onScroll: () => void
  onWheel: (event: WheelEvent) => void
}

const states = new WeakMap<HTMLElement, AutoFollowState>()

function scrollToBottom(element: HTMLElement, state: AutoFollowState) {
  if (!state.follow) return
  element.scrollTop = element.scrollHeight
  void nextTick().then(() => {
    if (state.follow) element.scrollTop = element.scrollHeight
  })
}

export const autoFollowScrollDirective: Directive<HTMLElement, string> = {
  mounted(element) {
    const state: AutoFollowState = {
      follow: true,
      onScroll: () => {
        state.follow = coreIsScrollNearBottom(element)
      },
      onWheel: (event) => {
        if (event.deltaY < 0) state.follow = false
      },
    }
    states.set(element, state)
    element.addEventListener('scroll', state.onScroll, { passive: true })
    element.addEventListener('wheel', state.onWheel, { passive: true })
    scrollToBottom(element, state)
  },
  updated(element, binding: DirectiveBinding<string>) {
    if (binding.value === binding.oldValue) return
    const state = states.get(element)
    if (state) scrollToBottom(element, state)
  },
  unmounted(element) {
    const state = states.get(element)
    if (!state) return
    element.removeEventListener('scroll', state.onScroll)
    element.removeEventListener('wheel', state.onWheel)
    states.delete(element)
  },
}
