import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { describe, expect, it } from 'vitest'

import ChatThread from '../src/components/ChatThread.vue'
import type { CoreMessage } from '../src/types'
import { createFakeTransport } from './fake-transport'

const testTransport = createFakeTransport()

function mountChatThread(props: any = {}) {
  return mount(ChatThread, {
    props: { transport: testTransport, ...props },
  })
}

const userMessage: CoreMessage = {
  id: 'turn-1:user',
  role: 'user',
  content: '帮我写一份季度报告',
  timestamp: '',
}

const assistantMessage: CoreMessage = {
  id: 'assistant:turn-1',
  role: 'assistant',
  content: '好的，这是报告',
  timestamp: '',
  parts: [],
}

describe('message action availability', () => {
  it('offers edit/fork/rollback on a user message with no checkpoint', async () => {
    // Regression: the edit entry used to disappear whenever the turn had no
    // (recent enough) checkpoint. A normal user message must always expose all
    // three entries — no checkpoint, no pending change and no fork node needed.
    const wrapper = mountChatThread({ messages: [userMessage], messageActions: true })

    expect(wrapper.find('[data-user-edit]').exists()).toBe(true)
    expect(wrapper.find('[data-user-fork]').exists()).toBe(true)
    expect(wrapper.find('[data-user-rollback]').exists()).toBe(true)
  })

  it('anchors fork/rollback on the clicked user message turn', async () => {
    const wrapper = mountChatThread({ messages: [userMessage], messageActions: true })

    await wrapper.get('[data-user-fork]').trigger('click')
    await wrapper.get('[data-user-rollback]').trigger('click')

    expect(wrapper.emitted('fork-message')).toEqual([[{ turnId: 'turn-1', content: '帮我写一份季度报告' }]])
    expect(wrapper.emitted('rollback-message')).toEqual([[{ turnId: 'turn-1', content: '帮我写一份季度报告' }]])
  })

  it('hides all three entries for a message before the compaction boundary', () => {
    const wrapper = mountChatThread({
      messages: [userMessage],
      messageActions: true,
      lockedMessageIds: new Set(['turn-1:user']),
    })

    expect(wrapper.find('[data-user-edit]').exists()).toBe(false)
    expect(wrapper.find('[data-user-fork]').exists()).toBe(false)
    expect(wrapper.find('[data-user-rollback]').exists()).toBe(false)
    // Copy stays available; only history-mutating entries are excluded.
    expect(wrapper.find('[data-user-copy]').exists()).toBe(true)
  })

  it('hides assistant fork/rollback before the compaction boundary', () => {
    const wrapper = mountChatThread({
      messages: [assistantMessage],
      messageActions: true,
      lockedMessageIds: new Set(['assistant:turn-1']),
    })

    expect(wrapper.find('[data-assistant-actions]').exists()).toBe(false)
  })

  it('keeps assistant fork/rollback without any checkpoint data', () => {
    const wrapper = mountChatThread({ messages: [assistantMessage], messageActions: true })

    expect(wrapper.find('[data-message-fork]').exists()).toBe(true)
    expect(wrapper.find('[data-message-rollback]').exists()).toBe(true)
  })
})

describe('inline message editing', () => {
  it('opens the editor on the message it belongs to and lands the caret at the end', async () => {
    const wrapper = mount(ChatThread, {
      props: { transport: testTransport, messages: [userMessage], messageActions: true },
      attachTo: document.body,
    })

    await wrapper.get('[data-user-edit]').trigger('click')
    await nextTick()
    await nextTick()

    // The stack carries the editing state, which is what widens the bubble to
    // the message column instead of the textarea's intrinsic `cols` width.
    expect(wrapper.get('.user-stack').classes()).toContain('user-stack--editing')
    const el = wrapper.get('textarea.user-edit-input').element as HTMLTextAreaElement
    expect(el.value).toBe('帮我写一份季度报告')
    expect(document.activeElement).toBe(el)
    expect([el.selectionStart, el.selectionEnd]).toEqual([el.value.length, el.value.length])

    wrapper.unmount()
  })

  it('drops the editing state when the edit is cancelled', async () => {
    const wrapper = mountChatThread({ messages: [userMessage], messageActions: true })

    await wrapper.get('[data-user-edit]').trigger('click')
    await nextTick()
    expect(wrapper.find('.user-stack--editing').exists()).toBe(true)

    await wrapper.get('[data-user-edit-cancel]').trigger('click')
    await nextTick()
    expect(wrapper.find('.user-stack--editing').exists()).toBe(false)
    expect(wrapper.find('textarea.user-edit-input').exists()).toBe(false)
    expect(wrapper.get('.user-bubble').text()).toBe('帮我写一份季度报告')
  })
})
