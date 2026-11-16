import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'
import RightSidebarChecklist from '../src/components/RightSidebarChecklist.vue'

describe('composite preview search', () => {
  it('finds and correctly marks a component shown within another specimen', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('RightSidebarChecklist')
    expect(wrapper.findComponent(RightSidebarChecklist).exists()).toBe(true)
    expect(wrapper.text()).toContain('RuntimeChecklistCard')
    await wrapper.get('[data-show-inventory]').trigger('click')
    expect(wrapper.get('[data-inventory-path="core/ui/src/components/RightSidebarChecklist.vue"]').text()).toContain('已有预览')
    await wrapper.get('[data-source="RuntimeChecklistCard"]').trigger('click')
    expect(wrapper.get('[data-source-content="RuntimeChecklistCard"]').text()).toContain('RightSidebarChecklist.vue')
    wrapper.unmount()
  })
  it('opens the corresponding specimen from the source inventory', async () => {
    const wrapper = mount(Gallery, { attachTo: document.body })
    await wrapper.get('input[aria-label="搜索组件"]').setValue('RightSidebarChecklist')
    await wrapper.get('[data-show-inventory]').trigger('click')
    await wrapper.get('[data-inventory-path="core/ui/src/components/RightSidebarChecklist.vue"] button').trigger('click')
    expect((wrapper.get('input[aria-label="搜索组件"]').element as HTMLInputElement).value).toBe('RuntimeChecklistCard')
    expect(document.activeElement?.textContent).toBe('RuntimeChecklistCard')
    wrapper.unmount()
  })
})
