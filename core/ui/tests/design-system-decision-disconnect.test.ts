import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import CorePendingDecisionPanel from '../src/components/CorePendingDecisionPanel.vue'
import type { CorePendingDecision } from '../src/appServer/pendingDecisions'
const item: CorePendingDecision = { partId: 'example', requestId: 'req', isQuestion: false, kindLabel: '确认', subject: '执行示例命令？', title: '确认', detail: '', facts: [], options: [{ id: 'approve', label: '批准', wireResponse: 'approve' }], status: 'pending', submitting: false, canGuide: true, subAgentName: '', subAgentSessionId: '', decisionId: 'd', sequence: 1, lifecycle: 'appearing', deliveredBy: '', projectId: '' }
describe('decision draft during disconnection', () => {
  it('keeps typed guidance until the channel reconnects and accepts submission', async () => {
    const wrapper = mount(CorePendingDecisionPanel, { props: { items: [item], channelReady: false } })
    const guide = wrapper.get('[data-pending-decision-guide]')
    await guide.setValue('请先展示计划')
    expect((wrapper.get('[data-pending-decision-guide-submit]').element as HTMLButtonElement).disabled).toBe(true)
    await guide.trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('decision-select')).toBeUndefined()
    expect((guide.element as HTMLTextAreaElement).value).toBe('请先展示计划')
    await wrapper.setProps({ channelReady: true })
    await guide.trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('decision-select')?.[0]?.[0]).toMatchObject({ partId: 'example', response: '请先展示计划' })
    wrapper.unmount()
  })
})
