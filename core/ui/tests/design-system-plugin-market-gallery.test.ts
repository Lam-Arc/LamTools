import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'

// user:“直接渲染项目真实组件…交互测试”+(插件安装与失败只影响展厅示例)。
describe('plugin market gallery', () => {
  it('simulates installation, failure and repository access without external effects', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('PluginMarket'); await flushPromises()
    await vi.waitFor(() => expect(wrapper.find('[data-market-action="sample"]').exists()).toBe(true))
    await wrapper.get('.market-meta button').trigger('click')
    expect(wrapper.text()).toContain('本地链接示例')
    await wrapper.get('[data-market-fail]').setValue(true)
    await wrapper.get('[data-market-action="sample"]').trigger('click'); await flushPromises()
    expect(wrapper.get('.market-error').text()).toContain('示例安装失败')
    await wrapper.get('[data-market-fail]').setValue(false)
    await wrapper.get('[data-market-action="sample"]').trigger('click'); await flushPromises()
    expect(wrapper.get('[data-market-action="sample"]').text()).toContain('已安装')
    await wrapper.get('[data-market-reset]').trigger('click'); await flushPromises()
    expect(wrapper.get('[data-market-action="sample"]').text()).toContain('安装')
    expect(wrapper.get('[data-market-action="sample"]').attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })
})
