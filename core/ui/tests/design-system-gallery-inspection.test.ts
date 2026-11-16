import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import Gallery from '../src/design-system/Gallery.vue'
import UiSelect from '../src/components/UiSelect.vue'

describe('gallery inspection controls', () => {
  it('switches the actual theme and restores the previous root theme on unmount', async () => {
    document.documentElement.style.setProperty('--theme-main-text', 'rgb(1, 2, 3)')
    const wrapper = mount(Gallery)
    const darkText = document.documentElement.style.getPropertyValue('--theme-main-text')
    wrapper.get('[data-gallery-theme]').getComponent(UiSelect).vm.$emit('update:modelValue', 'light')
    await wrapper.vm.$nextTick()
    expect(document.documentElement.style.getPropertyValue('--theme-main-text')).not.toBe(darkText)
    wrapper.unmount()
    expect(document.documentElement.style.getPropertyValue('--theme-main-text')).toBe('rgb(1, 2, 3)')
  })
  it('adjusts a range parameter and opens the actual component source', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="滑条最大值"]').setValue('200')
    expect(wrapper.get('input[aria-label="数值"]').attributes('max')).toBe('200')
    await wrapper.get('[data-source="SundayRange"]').trigger('click')
    expect(wrapper.get('[data-source-content="SundayRange"]').text()).toContain('defineOptions')
    wrapper.unmount()
  })
  it('locates both the switch component and its shared style', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('[data-source="SundaySwitch"]').trigger('click')
    expect(wrapper.get('[data-source-content="SundaySwitch"]').text()).toContain('defineModel')
    expect(wrapper.text()).toContain('src/styles/sunday-switch.css')
    wrapper.unmount()
  })
  it('renders and edits the shared textarea and file badge variants', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('AutoTextarea')
    const textarea = wrapper.get('textarea')
    await textarea.setValue('真实输入')
    expect((textarea.element as HTMLTextAreaElement).value).toBe('真实输入')
    await wrapper.get('input[aria-label="搜索组件"]').setValue('FileTypeBadge')
    expect(wrapper.findAll('.file-type-badge')).toHaveLength(3)
    wrapper.unmount()
  })
})
