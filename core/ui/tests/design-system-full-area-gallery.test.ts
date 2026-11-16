import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'

describe('task and schedule previews', () => {
  it('opens both real forms using isolated example services', async () => {
    const wrapper = mount(Gallery)
    const search = wrapper.get('input[aria-label="搜索组件"]')
    await search.setValue('CoreSuperAgentPanel')
    await vi.waitFor(() => expect(wrapper.find('.sa-view').exists()).toBe(true), { timeout: 5000 })
    await wrapper.get('.sa-view .primary-button').trigger('click')
    expect(wrapper.get('.sa-view textarea').exists()).toBe(true)
    await search.setValue('CoreArrangeManager')
    await vi.waitFor(() => expect(wrapper.find('.arrange-view').exists()).toBe(true), { timeout: 5000 })
    await flushPromises()
    await wrapper.get('.arrange-view .primary-button').trigger('click')
    expect(wrapper.get('.arrange-view .form-tabs').exists()).toBe(true)
    wrapper.unmount()
  })
})
