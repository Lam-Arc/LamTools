import { mount, flushPromises } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'

// user:“直接渲染项目真实组件…变体对比及交互测试”+(消息预览仅使用本地示例)。
describe('message gallery', () => {
  it('compares real user and assistant messages and expands long user text', async () => {
    const wrapper = mount(Gallery, { attachTo: document.body })
    await wrapper.get('input[aria-label="搜索组件"]').setValue('MessageView')
    await flushPromises()
    await vi.waitFor(() => expect(wrapper.findAll('.message-view')).toHaveLength(4))
    expect(wrapper.get('.user-bubble').text()).toContain('示例问题')
    expect(wrapper.get('.assistant-answer').text()).toContain('示例回答')
    const fold = wrapper.get('[data-user-bubble-fold]')
    expect(fold.attributes('aria-expanded')).toBe('false')
    await fold.trigger('click')
    expect(fold.attributes('aria-expanded')).toBe('true')
    wrapper.unmount()
  })
})
