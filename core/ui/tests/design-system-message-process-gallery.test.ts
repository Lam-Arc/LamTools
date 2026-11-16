import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'

// user:“参数调整、变体对比及交互测试”+(消息展厅比较运行中与已完成的工具过程)。
describe('message process gallery', () => {
  it('shows live process and allows inspecting completed process', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('MessageView'); await flushPromises()
    await vi.waitFor(() => expect(wrapper.find('[data-gallery-process] .process-summary').exists()).toBe(true))
    const sample = wrapper.get('[data-gallery-process]')
    expect(sample.get('.process-summary').attributes('aria-expanded')).toBe('false')
    await sample.get('.process-summary').trigger('click')
    expect(sample.get('.process-summary').attributes('aria-expanded')).toBe('true')
    expect(sample.find('.process-stream').exists()).toBe(true)
    await wrapper.get('[data-message-live]').setValue(true)
    expect(sample.get('.process-summary').attributes('aria-expanded')).toBe('true')
    expect(sample.get('.process-stream').classes()).toContain('process-stream--live')
    wrapper.unmount()
  })
})
