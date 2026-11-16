import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'

describe('model catalog specimen', () => {
  it('renders the real catalog with local sample data and supports search', async () => {
    const wrapper = mount(Gallery, { attachTo: document.body })
    await wrapper.get('input[aria-label="搜索组件"]').setValue('CoreModelCatalog')
    await vi.waitFor(() => expect(wrapper.find('[data-model-catalog]').exists()).toBe(true))
    expect(wrapper.get('[data-model-catalog]').text()).toContain('示例模型')
    await wrapper.get('[data-model-catalog-search]').setValue('不存在的模型')
    expect(wrapper.find('[data-model-card="example-model"]').exists()).toBe(false)
    await wrapper.get('[data-model-catalog-search]').setValue('示例模型')
    expect(wrapper.find('[data-model-card="example-model"]').exists()).toBe(true)
    wrapper.unmount()
  })
  it('loads the large composite preview on demand without contacting a service', async () => {
    const wrapper = mount(Gallery)
    expect(wrapper.find('[data-model-catalog]').exists()).toBe(false)
    await wrapper.get('[data-load-catalog]').trigger('click')
    await vi.waitFor(() => expect(wrapper.find('[data-model-catalog]').exists()).toBe(true))
    expect(wrapper.get('[data-model-catalog]').text()).toContain('示例模型')
    wrapper.unmount()
  })

})
