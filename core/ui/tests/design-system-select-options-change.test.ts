import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import UiSelect from '../src/components/UiSelect.vue'

describe('select options changing while open', () => {
  it('moves focus to an available option, then back to the trigger if none remain', async () => {
    const wrapper = mount(UiSelect, { attachTo: document.body, props: { modelValue: 'a', options: [{ value: 'a', label: '甲' }, { value: 'b', label: '乙' }] } })
    await wrapper.get('.ui-select-trigger').trigger('click')
    await new Promise(resolve => requestAnimationFrame(resolve))
    const buttons = document.querySelectorAll<HTMLButtonElement>('.ui-select-option')
    buttons[1].focus()
    await wrapper.setProps({ options: [{ value: 'a', label: '甲' }, { value: 'b', label: '乙', disabled: true }] })
    await wrapper.vm.$nextTick()
    expect(document.activeElement).toBe(buttons[0])
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    await wrapper.setProps({ options: [{ value: 'a', label: '甲', disabled: true }] })
    await wrapper.vm.$nextTick()
    expect(document.activeElement).toBe(wrapper.get('.ui-select-trigger').element)
    await wrapper.get('.ui-select-trigger').trigger('keydown', { key: 'Tab' })
    expect(document.querySelector('.ui-select-menu')).toBeNull()
    wrapper.unmount()
  })
})
