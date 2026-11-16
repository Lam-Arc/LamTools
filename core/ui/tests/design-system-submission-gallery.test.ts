import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'
import UiSelect from '../src/components/UiSelect.vue'
import CoreSubmissionStatus from '../src/components/CoreSubmissionStatus.vue'

describe('submission status gallery', () => {
  it('changes the real status and exercises the retry action', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('CoreSubmissionStatus')
    const status = wrapper.getComponent(CoreSubmissionStatus)
    expect(status.get('[role=status]').attributes('data-state')).toBe('sending')
    wrapper.get('[data-gallery-submission-state]').getComponent(UiSelect).vm.$emit('update:modelValue', 'failed')
    await wrapper.vm.$nextTick()
    expect(status.get('[role=status]').attributes('data-state')).toBe('failed')
    await status.get('[data-submission-retry]').trigger('click')
    expect(wrapper.text()).toContain('重试 1 次')
    await status.get('[data-submission-edit]').trigger('click')
    expect(wrapper.text()).toContain('编辑 1 次')
    await wrapper.get('[data-source="CoreSubmissionStatus"]').trigger('click')
    expect(wrapper.get('[data-source-content="CoreSubmissionStatus"]').text()).toContain('visibleStates')
    wrapper.unmount()
  })
})
