import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'

// user:“直接渲染项目真实组件…交互测试”+(插件区域审批与失败只作用于本地示例)。
describe('plugin region gallery', () => {
  it('shows action input, local failure, and approval decision', async () => {
    const wrapper = mount(Gallery, { attachTo: document.body })
    await wrapper.get('input[aria-label="搜索组件"]').setValue('PluginRegionBlocks'); await flushPromises()
    await vi.waitFor(() => expect(wrapper.find('[data-action="sample-run"]').exists()).toBe(true))
    await wrapper.get('[data-action="sample-run"]').trigger('click')
    await wrapper.get('.plugin-action-form input[type="text"]').setValue('示例参数')
    await wrapper.get('[data-region-fail]').setValue(true)
    await wrapper.get('.plugin-action-form').trigger('submit'); await flushPromises()
    expect(wrapper.get('.plugin-action-error').text()).toContain('示例执行失败')
    await wrapper.get('[data-region-fail]').setValue(false)
    await wrapper.get('.plugin-action-form').trigger('submit'); await flushPromises()
    expect(document.querySelector('[role="dialog"]')).toBeTruthy()
    ;(document.querySelector('.core-confirm__submit') as HTMLButtonElement).click(); await flushPromises()
    expect(wrapper.text()).toContain('本地授权：approve')
    wrapper.unmount()
  })
})
