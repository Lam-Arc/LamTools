import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'
import UiSelect from '../src/components/UiSelect.vue'

describe('design token specimen', () => {
  it('exposes the real shared theme, spacing and radius tokens', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('DesignTokens')
    expect(wrapper.text()).toContain('--theme-main-text')
    expect(wrapper.text()).toContain('--space-2')
    expect(wrapper.text()).toContain('--radius-sm')
    expect(wrapper.text()).toContain('src/styles/variables.css')
    expect(wrapper.text()).toContain('--dur-fast')
    const dark = wrapper.get('[data-token-value="--theme-main-text"]').text()
    wrapper.get('[data-gallery-theme]').getComponent(UiSelect).vm.$emit('update:modelValue', 'light')
    await wrapper.vm.$nextTick()
    expect(wrapper.get('[data-token-value="--theme-main-text"]').text()).not.toBe(dark)
    wrapper.unmount()
  })
})
