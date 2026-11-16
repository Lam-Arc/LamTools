import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'

// user:“源码定位”+(对话框展厅展示实际共用的遮罩交互源码)。
describe('dialog gallery source', () => {
  it('shows the outside pointer helper only for dialogs that use it', async () => {
    const wrapper = mount(Gallery)
    for (const name of ['LibraryNameDialog', 'LibraryConfirmDialog', 'CoreConfirmDialog', 'CoreProjectCreate', 'CoreProjectPicker', 'CoreUpdateCard']) {
      await wrapper.get('input[aria-label="搜索组件"]').setValue(name)
      await wrapper.get(`[data-source="${name}"]`).trigger('click')
      const source = wrapper.get(`[data-source-content="${name}"]`).text()
      expect(source.includes('/* src/composables/useOutsidePointerDismiss.ts */')).toBe(name !== 'CoreUpdateCard')
    }
    wrapper.unmount()
  })
})
