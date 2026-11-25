import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import AdvancedView from '../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/AdvancedView.vue'
import UiSelect from '../src/components/UiSelect.vue'

describe('network schedule shared selects', () => {
  it('saves the sampling interval and applies the chosen schedule interval', async () => {
    const run = vi.fn(async () => ({}))
    const session = { state: { revision: 3, settings: { sample_seconds: 5 }, automations: [] }, busy: '', run }
    const wrapper = mount(AdvancedView, { props: { session } })
    const sampling = wrapper.get('[data-network-sampling]').getComponent(UiSelect)
    sampling.vm.$emit('update:modelValue', '5')
    expect(run).not.toHaveBeenCalled()
    sampling.vm.$emit('update:modelValue', '10')
    await wrapper.vm.$nextTick()
    expect(run).toHaveBeenCalledWith('settings.update', { revision: 3, settings: { sample_seconds: 10 } }, '更新频率已保存')
    await wrapper.get('[data-add-schedule]').trigger('click')
    const interval = wrapper.get('[data-network-interval]').getComponent(UiSelect)
    interval.vm.$emit('update:modelValue', '60')
    await wrapper.get('form').trigger('submit')
    expect(run).toHaveBeenCalledWith('automation.save', { revision: 3, automations: [expect.objectContaining({ interval_minutes: 60 })] }, '定时检查已更新')
    wrapper.unmount()
  })
})
