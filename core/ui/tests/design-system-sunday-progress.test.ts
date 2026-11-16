import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import SundayProgress from '../src/components/SundayProgress.vue'
describe('shared progress component', () => {
  it('normalizes values and supports indeterminate progress', async () => {
    const wrapper = mount(SundayProgress, { props: { value: 150, max: 100, label: '任务进度' } })
    expect(wrapper.attributes('aria-label')).toBe('任务进度')
    expect(wrapper.attributes('aria-valuenow')).toBe('100')
    expect(wrapper.get('.sunday-progress__fill').attributes('style')).toContain('100%')
    await wrapper.setProps({ value: -3, max: 0 })
    expect(wrapper.attributes('aria-valuenow')).toBe('0')
    expect(wrapper.attributes('aria-valuemax')).toBe('100')
    await wrapper.setProps({ indeterminate: true, valueText: '下载中' })
    expect(wrapper.attributes('aria-valuenow')).toBeUndefined()
    expect(wrapper.attributes('aria-valuetext')).toBe('下载中')
    wrapper.unmount()
  })
})
