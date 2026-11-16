import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'
import LibraryNameDialog from '../src/components/LibraryNameDialog.vue'
describe('library name gallery', () => {
  it('edits and submits an in-memory example and shows its source', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('LibraryNameDialog')
    await wrapper.get('[data-library-name-open]').trigger('click')
    const dialog = wrapper.getComponent(LibraryNameDialog)
    await dialog.get('input').setValue('示例文件夹')
    await dialog.get('.library-button--primary').trigger('click')
    expect(wrapper.get('[data-library-name-result]').text()).toContain('示例文件夹')
    await wrapper.get('[data-source="LibraryNameDialog"]').trigger('click')
    expect(wrapper.get('[data-source-content="LibraryNameDialog"]').text()).toContain('dialog-field')
    wrapper.unmount()
  })
})
