import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'
import ThemeAreaEditor from '../src/components/ThemeAreaEditor.vue'
describe('theme area gallery', () => {
  it('uses the real editor with local keyboard-adjustable values', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('ThemeAreaEditor')
    const editor = wrapper.getComponent(ThemeAreaEditor)
    await editor.get('[data-theme-fill-mode="solid"]').trigger('keydown', { key: 'ArrowRight' })
    expect(editor.get('[data-theme-fill-mode="gradient"]').attributes('aria-checked')).toBe('true')
    await editor.get('[data-theme-glass-level="off"]').trigger('keydown', { key: 'End' })
    expect(editor.get('[data-theme-glass-level="low"]').attributes('aria-checked')).toBe('true')
    await wrapper.get('[data-source="ThemeAreaEditor"]').trigger('click')
    expect(wrapper.get('[data-source-content="ThemeAreaEditor"]').text()).toContain('radioGroupKeyboard')
    wrapper.unmount()
  })
})
