import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'
import UiSelect from '../src/components/UiSelect.vue'

describe('composer action specimen', () => {
  it('switches between actual send, stop and resume states and honors disabled', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('CoreSendStopButton')
    const mode = wrapper.get('[data-gallery-action-mode]').getComponent(UiSelect)
    expect(wrapper.get('.core-send-stop-button').attributes('aria-label')).toBe('发送')
    mode.vm.$emit('update:modelValue', 'stop')
    await wrapper.vm.$nextTick()
    expect(wrapper.get('.core-send-stop-button').attributes('aria-label')).toBe('停止运行')
    mode.vm.$emit('update:modelValue', 'resume')
    await wrapper.vm.$nextTick()
    expect(wrapper.get('.core-send-stop-button').attributes('aria-label')).toBe('继续运行')
    await wrapper.get('input[aria-label="禁用支持此状态的控件"]').setValue(true)
    expect((wrapper.get('.core-send-stop-button').element as HTMLButtonElement).disabled).toBe(true)
    wrapper.unmount()
  })
})
