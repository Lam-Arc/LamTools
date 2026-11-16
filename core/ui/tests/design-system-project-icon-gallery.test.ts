import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'
import UiSelect from '../src/components/UiSelect.vue'
import ProjectVisualIcon from '../src/components/ProjectVisualIcon.vue'

describe('project icon gallery', () => {
  it('previews real icons, changes icon and color, and reveals source', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('ProjectVisualIcon')
    const icon = wrapper.getComponent(ProjectVisualIcon)
    expect(icon.props('iconKey')).toBe('folder')
    wrapper.get('[data-gallery-project-icon]').getComponent(UiSelect).vm.$emit('update:modelValue', 'rocket')
    wrapper.get('[data-gallery-project-color]').getComponent(UiSelect).vm.$emit('update:modelValue', 'ocean')
    await wrapper.vm.$nextTick()
    expect(icon.props('iconKey')).toBe('rocket')
    expect(icon.props('colorKey')).toBe('ocean')
    expect(icon.classes()).toContain('project-visual-icon--gradient')
    await wrapper.get('[data-source="ProjectVisualIcon"]').trigger('click')
    expect(wrapper.get('[data-source-content="ProjectVisualIcon"]').text()).toContain('iconComponents')
    wrapper.unmount()
  })
})
