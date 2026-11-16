import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'
import LibraryViewToggle from '../src/components/LibraryViewToggle.vue'
describe('library view toggle gallery', () => {
  it('switches the real control and shows the local result and source', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('LibraryViewToggle')
    const toggle = wrapper.getComponent(LibraryViewToggle)
    await toggle.get('[aria-label="列表视图"]').trigger('click')
    expect(toggle.get('[aria-label="列表视图"]').attributes('aria-pressed')).toBe('true')
    expect(wrapper.get('[data-library-view-result]').text()).toContain('列表')
    await wrapper.get('[data-source="LibraryViewToggle"]').trigger('click')
    expect(wrapper.get('[data-source-content="LibraryViewToggle"]').text()).toContain('aria-pressed')
    wrapper.unmount()
  })
})
