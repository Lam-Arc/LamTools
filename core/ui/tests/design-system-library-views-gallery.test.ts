import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'

// user:“直接渲染项目真实组件”+(展厅中的记忆与方案使用隔离的示例数据)。
describe('library views gallery', () => {
  it('renders real memory and plan views with local examples', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('MemoryView')
    await flushPromises()
    await vi.waitFor(() => expect(wrapper.find('[data-memory-tier="global"]').exists()).toBe(true))
    await wrapper.get('[data-memory-tier="global"]').trigger('click')
    await vi.waitFor(() => expect(wrapper.find('[data-memory-entry]').exists()).toBe(true))
    await wrapper.get('input[aria-label="搜索组件"]').setValue('PlanLibraryView')
    await flushPromises()
    await vi.waitFor(() => expect(wrapper.find('[data-library-entry]').exists()).toBe(true))
    wrapper.unmount()
  }, 15000)

  it('creates folders and files inside the isolated real views', async () => {
    const wrapper = mount(Gallery)
    const search = wrapper.get('input[aria-label="搜索组件"]')
    await search.setValue('MemoryView'); await flushPromises()
    await vi.waitFor(() => expect(wrapper.find('[data-memory-tier="global"]').exists()).toBe(true))
    await wrapper.get('[data-memory-tier="global"]').trigger('click'); await flushPromises()
    await wrapper.get('[data-memory-create-folder]').trigger('click')
    await wrapper.get('[data-memory-dialog-input]').setValue('本地目录')
    await wrapper.get('[data-memory-dialog-submit]').trigger('click'); await flushPromises()
    expect(wrapper.find('[data-memory-folder="本地目录"]').exists()).toBe(true)
    await wrapper.get('[data-memory-create-file]').trigger('click')
    await wrapper.get('[data-memory-dialog-input]').setValue('本地记忆')
    await wrapper.get('[data-memory-dialog-submit]').trigger('click'); await flushPromises()
    expect(wrapper.find('[data-memory-editor]').exists()).toBe(true)
    await search.setValue('PlanLibraryView'); await flushPromises()
    await vi.waitFor(() => expect(wrapper.find('[data-library-create-folder]').exists()).toBe(true))
    await wrapper.get('[data-library-create-folder]').trigger('click')
    await wrapper.get('[data-library-dialog-input]').setValue('本地目录')
    await wrapper.get('[data-library-dialog-submit]').trigger('click'); await flushPromises()
    expect(wrapper.find('[data-library-folder="本地目录"]').exists()).toBe(true)
    await wrapper.get('[data-library-create]').trigger('click')
    await wrapper.get('[data-library-dialog-input]').setValue('本地方案')
    await wrapper.get('[data-library-dialog-submit]').trigger('click'); await flushPromises()
    expect(wrapper.find('[data-library-reader]').exists()).toBe(true)
    wrapper.unmount()
  }, 15000)
})
