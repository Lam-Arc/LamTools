import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'
import CorePendingDecisionPanel from '../src/components/CorePendingDecisionPanel.vue'
describe('pending decision gallery', () => {
  it('switches real queued requests, simulates disconnection and records local actions', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('CorePendingDecisionPanel')
    const panel = wrapper.getComponent(CorePendingDecisionPanel)
    await panel.get('[data-pending-decision-item="sample-question"]').trigger('click')
    expect(panel.get('[data-pending-decision-subject]').text()).toContain('预览')
    await wrapper.get('input[aria-label="模拟通道断开"]').setValue(true)
    const guide = panel.get('[data-pending-decision-guide]')
    await guide.setValue('先展示方案')
    expect((panel.get('[data-pending-decision-guide-submit]').element as HTMLButtonElement).disabled).toBe(true)
    await wrapper.get('input[aria-label="模拟通道断开"]').setValue(false)
    await guide.trigger('keydown', { key: 'Enter' })
    expect(wrapper.get('[data-decision-gallery-result]').text()).toContain('先展示方案')
    await wrapper.get('[data-source="CorePendingDecisionPanel"]').trigger('click')
    expect(wrapper.get('[data-source-content="CorePendingDecisionPanel"]').text()).toContain('channelReady')
    wrapper.unmount()
  })
})
