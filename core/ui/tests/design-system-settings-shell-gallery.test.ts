import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'
import SettingsShell from '../src/components/SettingsShell.vue'
describe('settings shell gallery', () => {
  it('navigates the real shell, toggles its navigation and shows its source', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('SettingsShell')
    const shell = wrapper.getComponent(SettingsShell)
    expect(shell.get('[data-settings-section="general"]').attributes('aria-current')).toBe('page')
    await shell.get('[data-settings-section="appearance"]').trigger('click')
    expect(shell.get('[data-settings-section="appearance"]').attributes('aria-current')).toBe('page')
    expect(shell.text()).toContain('界面示例')
    await wrapper.get('input[aria-label="隐藏预览导航"]').setValue(true)
    expect(shell.find('.settings-sidebar').exists()).toBe(false)
    await wrapper.get('[data-source="SettingsShell"]').trigger('click')
    expect(wrapper.get('[data-source-content="SettingsShell"]').text()).toContain('beforeSectionChange')
    wrapper.unmount()
  })
})
