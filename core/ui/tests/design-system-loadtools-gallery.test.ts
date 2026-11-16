import { mount, flushPromises } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'

describe('tool mode gallery', () => {
  it('previews and saves a local example without real services', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('CoreLoadToolsEditor')
    await vi.waitFor(() => expect(wrapper.find('input[aria-label="搜索模式"]').exists()).toBe(true), { timeout: 5000 })
    await wrapper.get('input[aria-label="搜索模式"]').setValue('consider')
    expect(wrapper.findAll('.mode-picker-item')).toHaveLength(1)
    await wrapper.get('input[aria-label="搜索模式"]').setValue('')
    await wrapper.get('.tool-row input').setValue(false)
    await wrapper.get('.loadtools-save').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('示例已保存')
    wrapper.unmount()
  })
})
