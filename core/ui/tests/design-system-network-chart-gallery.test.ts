import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'

// user:“直接渲染项目真实组件…参数调整、变体对比”+(网络图表在空采样与本地示例间切换)。
describe('network chart gallery', () => {
  it('shows actual chart and waiting states with local sample data', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('SpeedChart')
    expect(wrapper.get('[data-network-chart] svg[role=img]').attributes('aria-label')).toContain('速度趋势')
    expect(wrapper.get('.nx-chart-download').attributes('d')).toMatch(/^M/)
    await wrapper.get('[data-network-chart-empty]').setValue(true)
    expect(wrapper.find('[data-network-chart] svg[role=img]').exists()).toBe(false)
    expect(wrapper.text()).toContain('正在收集网速变化')
    wrapper.unmount()
  })
})
