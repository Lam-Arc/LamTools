import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'

// user:“直接渲染项目真实组件…交互测试”+(插件配置表单读写内存示例，不加载插件面板)。
describe('plugin configuration gallery', () => {
  it('edits and saves local configuration and displays failures', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('PluginConfigPanel'); await flushPromises()
    await vi.waitFor(() => expect(wrapper.find('.plugin-config-panel input[type="text"]').exists()).toBe(true))
    await wrapper.get('.plugin-config-panel input[type="text"]').setValue('新名称')
    await wrapper.get('.plugin-config-panel form').trigger('submit'); await flushPromises()
    expect(wrapper.get('.config-notice').text()).toContain('已保存')
    await wrapper.get('[data-config-fail]').setValue(true)
    await wrapper.get('.plugin-config-panel form').trigger('submit'); await flushPromises()
    expect(wrapper.get('.config-error').text()).toContain('示例保存失败')
    wrapper.unmount()
  })
})
