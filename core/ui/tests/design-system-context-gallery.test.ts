import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'

// user:“直接渲染项目真实组件…交互测试”+(上下文设置只保存到展厅示例)。
describe('context settings gallery', () => {
  it('edits and saves zero priority in local settings', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('CoreSettings'); await flushPromises()
    await vi.waitFor(() => expect(wrapper.find('.lc-priority').exists()).toBe(true), { timeout: 10000 })
    const priority = wrapper.get('.lc-priority')
    await priority.setValue('0')
    const card = wrapper.findAll('.setting-card').find(item => item.text().includes('全局上下文加载'))!
    await card.findAll('button').find(button => button.text() === '保存')!.trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('本地优先级：0')
    expect(priority.element).toHaveProperty('value', '0')
    wrapper.unmount()
  })
})
