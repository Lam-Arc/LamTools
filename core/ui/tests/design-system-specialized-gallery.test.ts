import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'

describe('specialized component specimens', () => {
  it('keeps the thinking slider distinct and supports its real keyboard interaction', async () => {
    const wrapper = mount(Gallery, { attachTo: document.body })
    await wrapper.get('input[aria-label="搜索组件"]').setValue('ThinkingIntensitySlider')
    const slider = wrapper.get('[role="slider"]')
    expect(slider.attributes('aria-orientation')).toBe('vertical')
    await slider.trigger('keydown', { key: 'End' })
    expect(slider.attributes('aria-valuetext')).toBe('最高')
    await wrapper.get('input[aria-label="禁用支持此状态的控件"]').setValue(true)
    expect(slider.attributes('aria-disabled')).toBe('true')
    wrapper.unmount()
  })
})
