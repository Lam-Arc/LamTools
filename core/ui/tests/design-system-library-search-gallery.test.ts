import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'
import LibrarySearchField from '../src/components/LibrarySearchField.vue'
describe('library search gallery', () => {
  it('filters a local example using the real search field and exposes source', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('LibrarySearchField')
    const field = wrapper.getComponent(LibrarySearchField)
    expect(wrapper.findAll('[data-library-search-example]')).toHaveLength(3)
    await field.get('input').setValue('设计')
    expect(wrapper.findAll('[data-library-search-example]')).toHaveLength(1)
    expect(wrapper.get('[data-library-search-example]').text()).toContain('设计')
    await wrapper.get('[data-source="LibrarySearchField"]').trigger('click')
    expect(wrapper.get('[data-source-content="LibrarySearchField"]').text()).toContain('type="search"')
    wrapper.unmount()
  })
})
