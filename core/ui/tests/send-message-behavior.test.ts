import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ChatThread from '../src/components/ChatThread.vue'
import type { CoreMessage } from '../src/types'
import { createFakeTransport } from './fake-transport'

vi.mock('../src/components/PluginSystemContributions.vue', () => ({ default: { render: () => null } }))
afterEach(() => { vi.useRealTimers() })

// user:“修，不要出错”+(使用真实消息组件验证计时、历史锁定和回退操作，不能只检查更新次数)。
describe('send optimization preserves message behavior', () => {
  it('runs only the current clock, pauses while waiting, and freezes completed durations', async () => {
    vi.useFakeTimers()
    const start = Date.parse('2026-10-12T02:00:00Z')
    vi.setSystemTime(start + 1000)
    const message: CoreMessage = {
      id: 'assistant:session:turn:new#2', role: 'assistant', content: 'Working.', timestamp: '',
      metadata: { timeline: true, started_at: new Date(start).toISOString() },
      parts: [{ id: 'reasoning', partType: 'reasoning', status: 'completed', content: 'Checking.' }],
    }
    const old: CoreMessage = { ...message, id: 'assistant:history', metadata: { ...message.metadata, duration_ms: 5000 } }
    const wrapper = mount(ChatThread, { props: { messages: [old, message], transport: createFakeTransport(),
      turnActive: true, turnStatus: 'running', activeTurnId: 'session:turn:new',
    } })
    const summaries = () => wrapper.findAll('.process-summary-text').map(el => el.text())
    try {
      expect(summaries()).toEqual(['耗时 5 s', '耗时 1 s'])
      await vi.advanceTimersByTimeAsync(3000)
      expect(summaries()).toEqual(['耗时 5 s', '耗时 4 s'])
      await wrapper.setProps({ turnStatus: 'waiting' })
      const waiting = summaries()
      await vi.advanceTimersByTimeAsync(3000)
      expect(summaries()).toEqual(waiting)
      await wrapper.setProps({ turnStatus: 'running' })
      await vi.advanceTimersByTimeAsync(1000)
      expect(summaries()).toEqual(['耗时 5 s', '耗时 8 s'])
      await wrapper.setProps({ turnActive: false, turnStatus: 'completed', messages: [old, {
        ...message, metadata: { ...message.metadata, duration_ms: 8000 },
      }] })
      await vi.advanceTimersByTimeAsync(5000)
      expect(summaries()).toEqual(['耗时 5 s', '耗时 8 s'])
    } finally { wrapper.unmount() }
  })

  it('preserves rollback events when a lock collection is replaced, locked and unlocked', async () => {
    const message: CoreMessage = { id: 'assistant:turn-actions', role: 'assistant', content: 'Done.', timestamp: '', parts: [] }
    const wrapper = mount(ChatThread, { props: { messages: [message], transport: createFakeTransport(), messageActions: true } })
    try {
      await wrapper.setProps({ lockedMessageIds: new Set() })
      await wrapper.get('[data-message-rollback]').trigger('click')
      expect(wrapper.emitted('rollback-message')).toEqual([[{ turnId: 'turn-actions', content: 'Done.' }]])
      await wrapper.setProps({ lockedMessageIds: new Set([message.id]) })
      expect(wrapper.find('[data-message-rollback]').exists()).toBe(false)
      await wrapper.setProps({ lockedMessageIds: new Set() })
      expect(wrapper.find('[data-message-rollback]').exists()).toBe(true)
    } finally { wrapper.unmount() }
  })
})
