import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import CorePetEditor from '../src/components/CorePetEditor.vue'
import { CORE_SETTINGS_SECTIONS } from '../src/components/settingsSections.ts'

describe('主界面桌宠设置入口', () => {
  it('设置导航里有独立的桌宠页', () => {
    expect(CORE_SETTINGS_SECTIONS.some(section => section.id === 'pet')).toBe(true)
  })

  it('浏览器预览下说明仅桌面版可用，不假装已经读写配置', async () => {
    const wrapper = mount(CorePetEditor)
    await flushPromises()
    expect(wrapper.text()).toContain('桌宠设置仅在桌面版可用')
    wrapper.unmount()
  })
})
