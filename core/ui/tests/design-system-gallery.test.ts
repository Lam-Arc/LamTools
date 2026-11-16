import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import Gallery from '../src/design-system/Gallery.vue'
import UiSelect from '../src/components/UiSelect.vue'

describe('component gallery', () => {
  it('filters real components and updates an interactive preview', async () => {
    const wrapper = mount(Gallery, { attachTo: document.body })
    expect(wrapper.text()).toContain('SundaySwitch')
    await wrapper.get('input[aria-label="搜索组件"]').setValue('SundaySwitch')
    expect(wrapper.text()).not.toContain('SundayRange')
    const toggle = wrapper.get('[role="switch"]')
    await toggle.setValue(true)
    expect((toggle.element as HTMLInputElement).checked).toBe(true)
    expect(wrapper.text()).toContain('src/components/SundaySwitch.vue')
    wrapper.unmount()
  })
  it('filters categories and exposes variant comparisons', async () => {
    const wrapper = mount(Gallery)
    wrapper.get('[data-gallery-category]').getComponent(UiSelect).vm.$emit('update:modelValue', '选择')
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('UiSelect')
    expect(wrapper.text()).not.toContain('SundaySwitch')
    wrapper.get('[data-gallery-category]').getComponent(UiSelect).vm.$emit('update:modelValue', '全部')
    await wrapper.vm.$nextTick()
    expect(wrapper.findAll('[role="switch"]').length).toBeGreaterThan(1)
    wrapper.unmount()
  })
})
