import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import CoreExecutionControls from '../src/components/CoreExecutionControls.vue'

// user:“确保视觉、功能和交互不退化”+(运行状态禁用输入控件时，已打开的选项不能继续修改设置)。
describe('execution controls disabled while open', () => {
  const props = { modelValue: 'a', modelOptions: [{ value: 'a', label: '示例 A' }, { value: 'b', label: '示例 B' }], thinkingMode: 'high', thinkingModeOptions: [{ value: 'high' as const, label: '高' }], activeMode: 'normal', modeOptions: [{ value: 'normal', label: '标准' }], permissionPreset: 'ask' }
  it('closes an open permission menu when disabled', async () => {
    const wrapper = mount(CoreExecutionControls, { props })
    await wrapper.get('.core-runtime-menu__trigger').trigger('click')
    await wrapper.get('[data-runtime-section="permission"]').trigger('click')
    expect(wrapper.find('[data-runtime-permission-option="full_access"]').exists()).toBe(true)
    await wrapper.setProps({ disabled: true })
    expect(wrapper.find('[data-runtime-permission-option="full_access"]').exists()).toBe(false)
    expect(wrapper.emitted('update:permissionPreset')).toBeUndefined()
    wrapper.unmount()
  })
  it('closes an open model menu when disabled', async () => {
    const wrapper = mount(CoreExecutionControls, { props })
    await wrapper.get('.core-model-thinking-menu__trigger').trigger('click')
    expect(wrapper.find('[data-model-thinking-model-option="b"]').exists()).toBe(true)
    await wrapper.setProps({ disabled: true })
    expect(wrapper.find('[data-model-thinking-card]').exists()).toBe(false)
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    wrapper.unmount()
  })
})
