import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'

// user:“直接渲染项目真实组件…交互测试”+(资料库标签补全只操作本地示例)。
describe('materials gallery', () => {
  it('uses local tags for keyboard completion without opening a real file', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('MaterialsView'); await flushPromises()
    await vi.waitFor(() => expect(wrapper.find('[data-material-tag-input="sample-a"]').exists()).toBe(true), { timeout: 10000 })
    const input = wrapper.get('[data-material-tag-input="sample-a"]')
    await input.trigger('focus'); await input.setValue('but'); await input.trigger('keydown', { key: 'ArrowDown' }); await input.trigger('keydown', { key: 'Enter' }); await flushPromises()
    expect(wrapper.text()).toContain('本地标签：button')
    wrapper.unmount()
  }, 15000)

  it('uploads, favorites and removes local samples through the real view', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('MaterialsView'); await flushPromises()
    await vi.waitFor(() => expect(wrapper.find('[data-material="sample-a"]').exists()).toBe(true))
    await wrapper.get('[data-materials-new]').trigger('click'); await flushPromises()
    expect(wrapper.find('[data-material="sample-upload-1"]').exists()).toBe(true)
    await wrapper.get('[data-material-check="sample-a"]').trigger('click')
    await wrapper.get('[data-materials-favorite-selected]').trigger('click'); await flushPromises()
    await wrapper.get('[data-materials-tab="favorite"]').trigger('click')
    expect(wrapper.find('[data-material="sample-a"]').exists()).toBe(true)
    await wrapper.get('[data-material-check="sample-a"]').trigger('click')
    await wrapper.get('[data-materials-remove-selected]').trigger('click')
    await wrapper.get('[data-materials-confirm-remove]').trigger('click'); await flushPromises()
    expect(wrapper.find('[data-material="sample-a"]').exists()).toBe(false)
    wrapper.unmount()
  }, 15000)
})
