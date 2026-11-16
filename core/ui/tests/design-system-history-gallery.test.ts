import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'
import HistoryLoadingIndicator from '../src/components/HistoryLoadingIndicator.vue'

describe('history loading preview', () => {
  it('displays the real loading indicator and lets visitors control its active state', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('HistoryLoadingIndicator')
    const indicator = wrapper.getComponent(HistoryLoadingIndicator)
    expect(indicator.props('active')).toBe(false)
    await wrapper.get('input[aria-label="显示加载状态"]').setValue(true)
    expect(indicator.props('active')).toBe(true)
    expect(indicator.get('[role=status]').attributes('aria-hidden')).toBe('false')
    await wrapper.get('input[aria-label="显示加载状态"]').setValue(false)
    expect(indicator.get('[role=status]').attributes('aria-hidden')).toBe('true')
    await wrapper.get('[data-source="HistoryLoadingIndicator"]').trigger('click')
    expect(wrapper.get('[data-source-content="HistoryLoadingIndicator"]').text()).toContain('prefers-reduced-motion')
    wrapper.unmount()
  })
})
