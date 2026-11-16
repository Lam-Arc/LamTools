import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'
import UiSelect from '../src/components/UiSelect.vue'
import AutoTextarea from '../src/components/AutoTextarea.vue'

describe('gallery component parameters', () => {
  it('adjusts menu direction, width and disabled-option state on the real select', async () => {
    const wrapper = mount(Gallery, { attachTo: document.body })
    await wrapper.get('input[aria-label="搜索组件"]').setValue('UiSelect')
    wrapper.get('[data-gallery-direction]').getComponent(UiSelect).vm.$emit('update:modelValue', 'up')
    await wrapper.vm.$nextTick()
    await wrapper.get('input[aria-label="菜单宽度"]').setValue('180')
    await wrapper.get('input[aria-label="禁用第二项"]').setValue(true)
    const select = wrapper.get('[data-select-preview]').getComponent(UiSelect)
    expect(select.props('direction')).toBe('up')
    expect(select.props('menuWidth')).toBe(180)
    expect(select.props('options')[1].disabled).toBe(true)
    wrapper.unmount()
  })
  it('adjusts textarea line limits and keeps independent selection previews', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('AutoTextarea')
    await wrapper.get('input[aria-label="最少行数"]').setValue('3')
    expect(wrapper.getComponent(AutoTextarea).props('minRows')).toBe(3)
    expect((wrapper.get('textarea').element as HTMLTextAreaElement).style.minHeight).toContain('3 *')
    await wrapper.get('input[aria-label="搜索组件"]').setValue('')
    const radios = wrapper.findAll('[role="radio"]')
    await radios[1].trigger('click')
    expect(wrapper.get('[data-select-preview]').getComponent(UiSelect).props('modelValue')).toBe('a')
    wrapper.unmount()
  })
})
