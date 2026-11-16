import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'
import CoreProjectPicker from '../src/components/CoreProjectPicker.vue'
describe('project picker gallery', () => {
  it('selects an example project without touching real projects and locates its source', async () => {
    const wrapper = mount(Gallery, { global: { stubs: { Teleport: true } } })
    await wrapper.get('input[aria-label="搜索组件"]').setValue('CoreProjectPicker')
    await wrapper.get('[data-project-picker-preview-open]').trigger('click')
    const picker = wrapper.getComponent(CoreProjectPicker)
    await picker.get('[data-project-picker-item="sample-project"]').trigger('click')
    expect(wrapper.get('[data-project-picker-preview-result]').text()).toContain('sample-project')
    await wrapper.get('[data-source="CoreProjectPicker"]').trigger('click')
    expect(wrapper.get('[data-source-content="CoreProjectPicker"]').text()).toContain('trapDialogTab')
    wrapper.unmount()
  })
})
