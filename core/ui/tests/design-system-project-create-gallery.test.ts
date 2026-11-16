import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'
import CoreProjectCreate from '../src/components/CoreProjectCreate.vue'
describe('project creation gallery', () => {
  it('submits only a local example with keyboard-selected appearance', async () => {
    const wrapper = mount(Gallery, { global: { stubs: { Teleport: true } } })
    await wrapper.get('input[aria-label="搜索组件"]').setValue('CoreProjectCreate')
    await wrapper.get('[data-project-create-preview-open]').trigger('click')
    const form = wrapper.getComponent(CoreProjectCreate)
    await form.get('[data-project-root]').setValue('E:\\sample')
    await form.get('[data-project-name]').setValue('示例项目')
    await form.get('[data-project-icon-option="folder"]').trigger('keydown', { key: 'ArrowRight' })
    await form.get('form').trigger('submit')
    expect(wrapper.get('[data-project-create-preview-result]').text()).toContain('示例项目')
    expect(wrapper.get('[data-project-create-preview-result]').text()).toContain('code')
    wrapper.unmount()
  })
})
