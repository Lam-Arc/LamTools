import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'
import SundayProgress from '../src/components/SundayProgress.vue'
describe('progress gallery', () => {
  it('renders the real progress component and compares known and unknown totals', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('SundayProgress')
    const progress = wrapper.getComponent(SundayProgress)
    expect(progress.attributes('aria-valuenow')).toBe('40')
    await wrapper.get('input[aria-label="模拟未知总量"]').setValue(true)
    expect(progress.attributes('aria-valuenow')).toBeUndefined()
    expect(progress.attributes('aria-valuetext')).toBe('处理中')
    await wrapper.get('[data-source="SundayProgress"]').trigger('click')
    expect(wrapper.get('[data-source-content="SundayProgress"]').text()).toContain('progressMetrics')
    wrapper.unmount()
  })
})
