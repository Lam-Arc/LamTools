import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ProjectVisualPicker from '../src/components/ProjectVisualPicker.vue'
describe('project visual picker keyboard navigation', () => {
  it('moves and selects icons and colors with arrow and boundary keys', async () => {
    const wrapper = mount(ProjectVisualPicker, { attachTo: document.body, props: { iconKey: 'folder', colorKey: 'gray' } })
    const firstIcon = wrapper.get('[data-project-icon-option="folder"]')
    const code = wrapper.get('[data-project-icon-option="code"]')
    expect(firstIcon.attributes('tabindex')).toBe('0')
    expect(code.attributes('tabindex')).toBe('-1')
    firstIcon.element.focus(); await firstIcon.trigger('keydown', { key: 'ArrowRight' })
    expect(wrapper.emitted('update:icon-key')?.[0]).toEqual(['code'])
    expect(document.activeElement).toBe(code.element)
    const gray = wrapper.get('[data-project-color-option="gray"]')
    gray.element.focus(); await gray.trigger('keydown', { key: 'End' })
    expect(wrapper.emitted('update:color-key')?.[0]).toEqual(['prism'])
    expect(document.activeElement).toBe(wrapper.get('[data-project-color-option="prism"]').element)
    await wrapper.setProps({ disabled: true })
    expect((code.element as HTMLButtonElement).disabled).toBe(true)
    wrapper.unmount()
  })
  it('keeps a tab entry when stored option keys are unknown', () => {
    const wrapper = mount(ProjectVisualPicker, { props: { iconKey: 'unknown' as any, colorKey: 'unknown' as any } })
    expect(wrapper.get('[data-project-icon-option="folder"]').attributes('tabindex')).toBe('0')
    expect(wrapper.get('[data-project-color-option="gray"]').attributes('tabindex')).toBe('0')
    wrapper.unmount()
  })
})
