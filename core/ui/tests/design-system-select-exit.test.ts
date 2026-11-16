import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import UiSelect from '../src/components/UiSelect.vue'

describe('select empty and keyboard exit states', () => {
  it('closes with Escape even when every option is disabled', async () => {
    const wrapper = mount(UiSelect, { attachTo: document.body, props: { modelValue: '', options: [{ value: 'x', label: '不可用', disabled: true }] } })
    const trigger = wrapper.get('.ui-select-trigger')
    ;(trigger.element as HTMLButtonElement).focus()
    await trigger.trigger('click')
    await wrapper.vm.$nextTick()
    await trigger.trigger('keydown', { key: 'Escape' })
    expect(trigger.attributes('aria-expanded')).toBe('false')
    wrapper.unmount()
  })
  it('closes when Tab leaves the menu without stealing focus back', async () => {
    const wrapper = mount(UiSelect, { attachTo: document.body, props: { modelValue: 'a', options: [{ value: 'a', label: '可选' }] } })
    const trigger = wrapper.get('.ui-select-trigger')
    await trigger.trigger('click')
    await new Promise(resolve => requestAnimationFrame(resolve))
    const option = document.querySelector<HTMLButtonElement>('.ui-select-option')!
    option.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }))
    await wrapper.vm.$nextTick()
    expect(trigger.attributes('aria-expanded')).toBe('false')
    wrapper.unmount()
  })
})
