import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'

describe('plugin management gallery', () => {
  it('previews and searches isolated example plugins', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('CorePluginSystemEditor')
    await vi.waitFor(() => expect(wrapper.find('[data-plugin-search]').exists()).toBe(true), { timeout: 5000 })
    await wrapper.get('[data-plugin-search]').setValue('alpha')
    expect(wrapper.findAll('.plugin-card')).toHaveLength(1)
    expect(wrapper.text()).toContain('alpha')
    await wrapper.get('button[aria-label="清除搜索"]').trigger('click')
    expect(wrapper.findAll('.plugin-card')).toHaveLength(2)
    const toggle = wrapper.findAll('.plugin-card')[0].get('input[role="switch"]')
    await toggle.setValue(false)
    await flushPromises()
    expect((toggle.element as HTMLInputElement).checked).toBe(false)
    wrapper.unmount()
  })
})
