import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'

// user:“提高前端一致性与开发效率”+(首次打开不初始化大型预览，搜索和手动加载仍可操作)。
describe('gallery preview loading', () => {
  it('defers heavy previews until requested or searched', async () => {
    const wrapper = mount(Gallery); await flushPromises()
    expect(wrapper.find('.plugin-config-panel').exists()).toBe(false)
    expect(wrapper.find('[data-message-readonly]').exists()).toBe(false)
    expect(wrapper.find('[data-settings-preview-permissions]').exists()).toBe(false)
    await wrapper.get('[data-load-preview="PluginConfigPanel"]').trigger('click')
    await vi.waitFor(() => expect(wrapper.find('.plugin-config-panel').exists()).toBe(true), { timeout: 10000 })
    await wrapper.get('input[aria-label="搜索组件"]').setValue('MessageView')
    await vi.waitFor(() => expect(wrapper.find('[data-message-readonly]').exists()).toBe(true), { timeout: 10000 })
    wrapper.unmount()
  })
})
