import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'
import LibraryConfirmDialog from '../src/components/LibraryConfirmDialog.vue'
describe('library confirmation gallery', () => {
  it('renders a real confirmation, dismisses it and exposes its source', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('LibraryConfirmDialog')
    await wrapper.get('[data-library-confirm-open]').trigger('click')
    const dialog = wrapper.getComponent(LibraryConfirmDialog)
    expect(dialog.text()).toContain('无法恢复')
    await dialog.get('.library-button--danger').trigger('click')
    expect(wrapper.get('[data-library-confirm-result]').text()).toContain('已确认')
    await wrapper.get('[data-source="LibraryConfirmDialog"]').trigger('click')
    expect(wrapper.get('[data-source-content="LibraryConfirmDialog"]').text()).toContain('dialog-dimmer')
    wrapper.unmount()
  })
})
