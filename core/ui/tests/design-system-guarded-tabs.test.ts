import { defineComponent, h, ref } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { onManualTabGroupKeydown } from '../src/composables/radioGroupKeyboard'

// user:“确保视觉、功能和交互不退化”+(手动标签导航不劫持标签内的独立关闭操作)。
describe('guarded tabs keyboard', () => {
  it('moves focus without activation and ignores keys on an inner close control', async () => {
    const activate = vi.fn(); const close = vi.fn()
    const Test = defineComponent({ setup() { const active = ref(0); return () => h('nav', { role: 'tablist', onKeydown: onManualTabGroupKeydown }, [0, 1].map(i => h('button', { role: 'tab', tabindex: active.value === i ? 0 : -1, onClick: () => { activate(i); active.value = i } }, [String(i), h('span', { role: 'button', tabindex: 0, onClick: (e: Event) => { e.stopPropagation(); close(i) } }, '关闭')])) ) } })
    const wrapper = mount(Test, { attachTo: document.body })
    const tabs = wrapper.findAll('[role="tab"]'); const closeButton = tabs[0].get('[role="button"]')
    ;(tabs[0].element as HTMLElement).focus()
    await tabs[0].trigger('keydown', { key: 'ArrowRight' })
    expect(document.activeElement).toBe(tabs[1].element); expect(activate).not.toHaveBeenCalled()
    ;(closeButton.element as HTMLElement).focus()
    await closeButton.trigger('keydown', { key: 'ArrowRight' })
    expect(document.activeElement).toBe(closeButton.element)
    await closeButton.trigger('click')
    expect(close).toHaveBeenCalledWith(0); expect(activate).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
