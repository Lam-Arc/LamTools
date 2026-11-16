import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'

// user:“直接渲染项目真实组件…交互测试”+(搜索只处理本地示例，不打开实际会话)。
describe('global search gallery', () => {
  it('shows and activates local recent tasks using keyboard', async () => {
    const wrapper = mount(Gallery, { attachTo: document.body })
    const gallerySearch = wrapper.get('input[aria-label="搜索组件"]')
    ;(gallerySearch.element as HTMLElement).focus()
    await gallerySearch.setValue('SearchShell'); await flushPromises()
    await vi.waitFor(() => expect(wrapper.find('.search-field-input').exists()).toBe(true), { timeout: 10000 })
    expect(document.activeElement).toBe(gallerySearch.element)
    expect(wrapper.get('.search-view').text()).toContain('示例任务')
    await wrapper.get('.search-field-input').trigger('keydown', { key: 'Enter' })
    expect(wrapper.text()).toContain('本地打开：sample-session')
    wrapper.unmount()
  }, 15000)
})
