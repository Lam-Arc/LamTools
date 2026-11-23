import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'
import UiSelect from '../src/components/UiSelect.vue'

describe('gallery shared filter controls', () => {
  it('uses actual shared selectors and checkboxes to filter specimens and change theme', async () => {
    const wrapper = mount(Gallery, { global: { stubs: { Teleport: true } } })
    await wrapper.get('[data-gallery-category] .ui-select-trigger').trigger('click')
    await wrapper.findAll('.ui-select-option').find(option => option.text() === '开关')!.trigger('click')
    expect(wrapper.text()).toContain('SundaySwitch')
    expect(wrapper.find('[data-source="SundayRange"]').exists()).toBe(false)
    await wrapper.get('[data-gallery-theme] .ui-select-trigger').trigger('click')
    await wrapper.findAll('.ui-select-option').find(option => option.text() === '浅色')!.trigger('click')
    expect(wrapper.get('[data-gallery-theme] .ui-select-trigger').text()).toBe('浅色')
    expect(wrapper.get('input[aria-label="禁用支持此状态的控件"]').classes()).toContain('sunday-checkbox')
    wrapper.unmount()
  })
  it('uses shared selectors for specimen parameters', async () => {
    const wrapper = mount(Gallery, { global: { stubs: { Teleport: true } } })
    await wrapper.get('input[aria-label="搜索组件"]').setValue('CoreSendStopButton')
    await wrapper.get('[data-gallery-action-mode] .ui-select-trigger').trigger('click')
    await wrapper.findAll('.ui-select-option').find(option => option.text() === '运行中')!.trigger('click')
    expect(wrapper.get('.core-send-stop-button').attributes('aria-label')).toBe('停止运行')
    await wrapper.get('input[aria-label="搜索组件"]').setValue('UiSelect')
    await wrapper.get('[data-gallery-direction] .ui-select-trigger').trigger('click')
    await wrapper.findAll('.ui-select-option').find(option => option.text() === '向上')!.trigger('click')
    expect(wrapper.get('[data-select-preview]').getComponent(UiSelect).props('direction')).toBe('up')
    wrapper.unmount()
  })

})
