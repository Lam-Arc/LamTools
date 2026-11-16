import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import UiSelect from '../src/components/UiSelect.vue'

describe('select disabled during interaction', () => {
  it('closes the open menu and cannot change a disabled value', async () => {
    const wrapper = mount(UiSelect, { attachTo: document.body, props: { modelValue: 'a', options: [{ value: 'a', label: '甲' }, { value: 'b', label: '乙' }] } })
    await wrapper.get('.ui-select-trigger').trigger('click')
    await new Promise(resolve => requestAnimationFrame(resolve))
    expect(document.querySelector('.ui-select-menu')).not.toBeNull()
    const option = document.querySelectorAll<HTMLButtonElement>('.ui-select-option')[1]
    await wrapper.setProps({ disabled: true })
    expect(document.querySelector('.ui-select-menu')).toBeNull()
    expect(wrapper.get('.ui-select-trigger').attributes('aria-expanded')).toBe('false')
    option.click()
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    wrapper.unmount()
  })
  it('closes when Tab leaves a menu with no available options', async () => {
    const wrapper = mount(UiSelect, { attachTo: document.body, props: { modelValue: '', options: [{ value: 'a', label: '不可用', disabled: true }] } })
    const trigger = wrapper.get('.ui-select-trigger')
    await trigger.trigger('click')
    await new Promise(resolve => requestAnimationFrame(resolve))
    await trigger.trigger('keydown', { key: 'Tab' })
    expect(trigger.attributes('aria-expanded')).toBe('false')
    expect(document.querySelector('.ui-select-menu')).toBeNull()
    wrapper.unmount()
  })
})
