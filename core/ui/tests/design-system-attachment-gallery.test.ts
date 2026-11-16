import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'

// user:“直接渲染项目真实组件，支持…交互测试、参数调整、变体对比”+(附件展厅展示不同状态并只修改示例数据)。
describe('attachment tray gallery', () => {
  it('shows real attachment variants and supports local retry and removal', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('AttachmentTray')
    expect(wrapper.findAll('.attachment-entry')).toHaveLength(4)
    expect(wrapper.get('[data-attachment-preview="gallery-image"]').exists()).toBe(true)
    expect(wrapper.get('[data-attachment-preview="gallery-uploading"]').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('上传中')
    expect(wrapper.get('[data-attachment-preview="gallery-failed"]').attributes('disabled')).toBeDefined()
    await wrapper.get('[data-attachment-retry="gallery-failed"]').trigger('click')
    expect(wrapper.find('[data-attachment-retry="gallery-failed"]').exists()).toBe(false)
    await wrapper.get('[data-attachment-remove="gallery-image"]').trigger('click')
    expect(wrapper.findAll('.attachment-entry')).toHaveLength(3)
    await wrapper.get('[data-attachment-reset]').trigger('click')
    expect(wrapper.findAll('.attachment-entry')).toHaveLength(4)
    wrapper.unmount()
  })
})
