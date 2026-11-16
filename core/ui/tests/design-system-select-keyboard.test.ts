import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import UiSelect from '../src/components/UiSelect.vue'

describe('shared select keyboard interaction', () => {
  it('focuses an enabled option, skips disabled choices, selects and restores focus', async () => {
    const wrapper = mount(UiSelect, { attachTo: document.body, props: { modelValue: 'a', ariaLabel: '选择', options: [
      { value: 'a', label: '一' }, { value: 'b', label: '二', disabled: true }, { value: 'c', label: '三' },
    ] } })
    await wrapper.get('button').trigger('click')
    await new Promise(resolve => requestAnimationFrame(resolve))
    const options = [...document.querySelectorAll<HTMLButtonElement>('.ui-select-option')]
    expect(document.activeElement).toBe(options[0])
    expect(options[1].disabled).toBe(true)
    options[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }))
    expect(document.activeElement).toBe(options[2])
    options[2].click()
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['c'])
    expect(document.activeElement).toBe(wrapper.get('button').element)
    wrapper.unmount()
  })
  it('closes with Escape and returns focus to the trigger', async () => {
    const wrapper = mount(UiSelect, { attachTo: document.body, props: { modelValue: 'a', options: [{ value: 'a', label: '一' }] } })
    await wrapper.get('button').trigger('click')
    await new Promise(resolve => requestAnimationFrame(resolve))
    document.activeElement?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await wrapper.vm.$nextTick()
    expect(document.querySelector('.ui-select-menu')).toBeNull()
    expect(document.activeElement).toBe(wrapper.get('button').element)
    wrapper.unmount()
  })
})
