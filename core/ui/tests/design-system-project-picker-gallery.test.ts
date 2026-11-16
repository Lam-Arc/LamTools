import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'
import ProjectVisualPicker from '../src/components/ProjectVisualPicker.vue'
describe('project visual picker gallery', () => {
  it('previews real keyboard selection and honors disabled state', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('ProjectVisualPicker')
    const picker = wrapper.getComponent(ProjectVisualPicker)
    await picker.get('[data-project-icon-option="folder"]').trigger('keydown', { key: 'ArrowRight' })
    expect(picker.get('[data-project-icon-option="code"]').attributes('aria-checked')).toBe('true')
    await picker.get('[data-project-color-option="gray"]').trigger('keydown', { key: 'End' })
    expect(picker.get('[data-project-color-option="prism"]').attributes('aria-checked')).toBe('true')
    await wrapper.get('input[aria-label="禁用支持此状态的控件"]').setValue(true)
    expect((picker.get('[data-project-icon-option="code"]').element as HTMLButtonElement).disabled).toBe(true)
    await wrapper.get('[data-source="ProjectVisualPicker"]').trigger('click')
    expect(wrapper.get('[data-source-content="ProjectVisualPicker"]').text()).toContain('radioGroupKeyboard')
    wrapper.unmount()
  })
})
