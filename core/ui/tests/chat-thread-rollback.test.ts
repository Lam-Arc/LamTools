import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import ChatThread from '../src/components/ChatThread.vue'
import type { CoreMessage } from '../src/types'

const messages: CoreMessage[] = [
  {
    id: 'assistant:turn-1',
    role: 'assistant',
    content: '第一条回复',
    timestamp: '',
    parts: [],
  },
  {
    id: 'assistant:waiting:placeholder',
    role: 'assistant',
    content: '',
    timestamp: '',
    parts: [],
    metadata: { initialWaiting: true },
  },
  {
    id: 'user-1',
    role: 'user',
    content: '用户消息',
    timestamp: '',
  },
]

describe('ChatThread assistant message actions', () => {
  it('hides the action row by default', () => {
    const wrapper = mount(ChatThread, { props: { messages } })
    expect(wrapper.find('[data-assistant-actions]').exists()).toBe(false)
  })

  it('shows copy/fork/rollback actions only for assistant turns with content', async () => {
    const wrapper = mount(ChatThread, {
      props: { messages, messageActions: true },
    })

    // Only assistant:turn-1 is actionable; the waiting placeholder is excluded.
    expect(wrapper.findAll('[data-assistant-actions]')).toHaveLength(1)
    expect(wrapper.get('[data-message-copy]').attributes('aria-label')).toBe('复制回复')
    expect(wrapper.get('[data-message-fork]').attributes('aria-label')).toBe('从此处另开会话')
    expect(wrapper.get('[data-message-rollback]').attributes('aria-label')).toBe('回退到这条回复')
  })

  it('emits the turn payload for fork and rollback', async () => {
    const wrapper = mount(ChatThread, {
      props: { messages, messageActions: true },
    })

    await wrapper.get('[data-message-rollback]').trigger('click')
    expect(wrapper.emitted('rollback-message')).toEqual([[{ turnId: 'turn-1', content: '第一条回复' }]])

    await wrapper.get('[data-message-fork]').trigger('click')
    expect(wrapper.emitted('fork-message')).toEqual([[{ turnId: 'turn-1', content: '第一条回复' }]])
  })

  it('copies the reply to the clipboard and shows a transient copied state', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    const wrapper = mount(ChatThread, { props: { messages, messageActions: true } })

    await wrapper.get('[data-message-copy]').trigger('click')
    await vi.waitFor(() => expect(writeText).toHaveBeenCalledWith('第一条回复'))
    expect(wrapper.get('[data-message-copy]').attributes('aria-label')).toBe('已复制')
  })

  it('keeps fork and rollback enabled without a checkpoint', async () => {
    const wrapper = mount(ChatThread, { props: { messages, messageActions: true } })

    expect(wrapper.get('[data-message-fork]').attributes('disabled')).toBeUndefined()
    expect(wrapper.get('[data-message-rollback]').attributes('disabled')).toBeUndefined()
    expect(wrapper.get('[data-message-fork]').attributes('title')).toBe('从此处另开会话')
  })
})
