import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'

// user:“参数调整、变体对比及交互测试”+(消息问题卡可切换只读和可回答，不连接真实会话)。
describe('message question gallery', () => {
  it('compares read-only and editable question controls', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('MessageView'); await flushPromises()
    await vi.waitFor(() => expect(wrapper.find('[data-question-group]').exists()).toBe(true))
    expect(wrapper.get('.question-group__choice').attributes('disabled')).toBeDefined()
    await wrapper.get('[data-message-readonly]').setValue(false)
    expect(wrapper.get('.question-group__choice').attributes('disabled')).toBeUndefined()
    await wrapper.get('.question-group__choice').trigger('click')
    expect(wrapper.get('[data-question-submit]').attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })
})
