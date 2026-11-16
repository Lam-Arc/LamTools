import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'

describe('gallery source inventory', () => {
  it('finds project components that do not yet have a specimen and identifies their location', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('WorkspaceShell')
    await wrapper.get('[data-show-inventory]').trigger('click')
    expect(wrapper.text()).toContain('core/ui/src/components/WorkspaceShell.vue')
    expect(wrapper.text()).toContain('待接入预览')
    wrapper.unmount()
  })
  it('marks covered components as previewable', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('SundayRange')
    await wrapper.get('[data-show-inventory]').trigger('click')
    expect(wrapper.get('[data-inventory-path="core/ui/src/components/SundayRange.vue"]').text()).toContain('已有预览')
    await wrapper.get('input[aria-label="搜索组件"]').setValue('CaptureEditor')
    expect(wrapper.get('[data-inventory-path="core/ui/src/pet/ui/CaptureEditor.vue"]').text()).toContain('已有预览')
    await wrapper.get('input[aria-label="搜索组件"]').setValue('PingRing')
    expect(wrapper.get('[data-inventory-path="core/ui/src/pet/ui/PingRing.vue"]').text()).toContain('已有预览')
    wrapper.unmount()
  })

})
