import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ChatThread from '../src/components/ChatThread.vue'
import type { CoreMessage } from '../src/types'
import { createFakeTransport } from './fake-transport'

vi.mock('../src/components/PluginSystemContributions.vue', () => ({ default: { render: () => null } }))
afterEach(() => { vi.useRealTimers() })

// user:“修，不要出错”+(使用真实消息组件验证计时、历史锁定和回退操作，不能只检查更新次数)。
describe('send optimization preserves message behavior', () => {
  // user:“分叉/编辑 稳定性/速度 找优化点进行优化”+(拒绝时保留编辑内容，确认收到前拦截重复提交)。
  it('keeps the edit draft on refusal and closes only after acceptance', async () => {
    const message: CoreMessage = { id: 'source:turn:past:user', role: 'user', content: 'original', timestamp: '' }
    const wrapper = mount(ChatThread, { props: {
      messages: [message], transport: createFakeTransport(), messageActions: true,
      readEditBasis: () => ({ threadId: 'source', revision: 12 }),
    } })
    try {
      await wrapper.get('[data-user-edit]').trigger('click')
      const edit = () => wrapper.get<HTMLTextAreaElement>('.user-edit-input textarea, textarea.user-edit-input')
      await edit().setValue('keep my change')
      await wrapper.get('[data-user-edit-confirm]').trigger('click')
      await wrapper.get('[data-user-edit-confirm]').trigger('click')
      const sent = () => (wrapper.emitted('edit-message') ?? []) as Array<[{ content: string; onSettled(ok: boolean): void }]>
      expect(sent()).toHaveLength(1)
      sent()[0][0].onSettled(false)
      await wrapper.vm.$nextTick()
      expect(edit().element.value).toBe('keep my change')
      await wrapper.get('[data-user-edit-confirm]').trigger('click')
      expect(sent()[1][0].content).toBe('keep my change')
      sent()[1][0].onSettled(true)
      await wrapper.vm.$nextTick()
      expect(wrapper.find('[data-user-edit-confirm]').exists()).toBe(false)
    } finally { wrapper.unmount() }
  })

  it('submits historical edits with the revision captured when the editor opened', async () => {
    let revision = 12
    const message: CoreMessage = { id: 'source:turn:past:user', role: 'user', content: 'original', timestamp: '' }
    const wrapper = mount(ChatThread, { props: {
      messages: [message], transport: createFakeTransport(), messageActions: true,
      readEditBasis: () => ({ threadId: 'source', revision }),
    } })
    try {
      await wrapper.get('[data-user-edit]').trigger('click')
      revision = 17
      await wrapper.get('[data-user-edit-confirm]').trigger('click')
      expect(wrapper.emitted('edit-message')?.[0]?.[0]).toMatchObject({ basis: { threadId: 'source', revision: 12 } })
    } finally { wrapper.unmount() }
  })

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
