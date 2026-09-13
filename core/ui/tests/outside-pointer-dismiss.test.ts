import { defineComponent, ref } from 'vue'
import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useOutsidePointerDismiss } from '../src/composables/useOutsidePointerDismiss'

function dispatchPointerEvent(
  target: Element,
  type: 'pointerdown' | 'pointerup' | 'pointercancel',
  pointerId = 1,
): void {
  const event = new Event(type, { bubbles: true, cancelable: true })
  Object.defineProperties(event, {
    pointerId: { configurable: true, value: pointerId },
    pointerType: { configurable: true, value: 'mouse' },
    button: { configurable: true, value: 0 },
    isPrimary: { configurable: true, value: true },
  })
  target.dispatchEvent(event)
}

describe('useOutsidePointerDismiss', () => {
  const mountedWrappers: Array<ReturnType<typeof mount>> = []

  afterEach(() => {
    for (const wrapper of mountedWrappers.splice(0)) wrapper.unmount()
  })

  function mountOverlay(onDismiss: () => void) {
    const overlay = ref<HTMLElement | null>(null)
    const card = ref<HTMLElement | null>(null)
    const TestOverlay = defineComponent({
      setup() {
        useOutsidePointerDismiss({
          overlay,
          card,
          onDismiss,
        })
        return { overlay, card }
      },
      template: '<div ref="overlay" data-overlay><div ref="card" data-card><button>卡片内容</button></div></div>',
    })
    const wrapper = mount(TestOverlay, { attachTo: document.body })
    mountedWrappers.push(wrapper)
    return wrapper
  }

  it('does not dismiss when a pointer leaves the card before release', () => {
    const onDismiss = vi.fn()
    const wrapper = mountOverlay(onDismiss)
    const card = wrapper.get('[data-card]').element
    const overlay = wrapper.get('[data-overlay]').element

    dispatchPointerEvent(card, 'pointerdown')
    dispatchPointerEvent(overlay, 'pointerup')

    expect(onDismiss).not.toHaveBeenCalled()
  })

  it('dismisses only when both pointerdown and pointerup are outside the card', () => {
    const onDismiss = vi.fn()
    const wrapper = mountOverlay(onDismiss)
    const card = wrapper.get('[data-card]').element
    const overlay = wrapper.get('[data-overlay]').element

    dispatchPointerEvent(overlay, 'pointerdown')
    dispatchPointerEvent(card, 'pointerup')
    expect(onDismiss).not.toHaveBeenCalled()

    dispatchPointerEvent(overlay, 'pointerdown', 2)
    dispatchPointerEvent(overlay, 'pointerup', 2)
    expect(onDismiss).toHaveBeenCalledTimes(1)
  })

  it('clears an incomplete pointer click on cancellation', () => {
    const onDismiss = vi.fn()
    const wrapper = mountOverlay(onDismiss)
    const overlay = wrapper.get('[data-overlay]').element

    dispatchPointerEvent(overlay, 'pointerdown')
    dispatchPointerEvent(overlay, 'pointercancel')
    dispatchPointerEvent(overlay, 'pointerup')

    expect(onDismiss).not.toHaveBeenCalled()
  })
})
