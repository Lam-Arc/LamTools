import { defineComponent, h } from 'vue'
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

let renderCount = 0
let lastRenderedIds: string[] = []

vi.mock('../src/components/MessageView.vue', () => ({
  default: defineComponent({
    name: 'MessageViewMock',
    props: {
      msg: { type: Object, required: true },
      assistantLabel: { type: String, default: 'Assistant' },
      processExpandedIds: { type: Set, default: () => new Set() },
      typingMessageIds: { type: Set, default: () => new Set() },
      messageActions: { type: Boolean, default: false },
    },
    setup(props, { slots }) {
      return () => {
        renderCount += 1
        lastRenderedIds.push(props.msg.id)
        const product = slots['message-product']?.({ message: props.msg })
        if (product) return h('div', {}, product)
        return h('div', { 'data-message-id': props.msg.id })
      }
    },
  }),
}))

import ChatThread from '../src/components/ChatThread.vue'

/**
 * MessageView isolation contract: with stable message references (guaranteed
 * by the projection cache), re-rendering the thread must not re-render
 * untouched messages. Only the changed message's MessageView re-renders.
 */
describe('ChatThread → MessageView isolation', () => {
  beforeEach(() => {
    renderCount = 0
    lastRenderedIds = []
  })

  it('re-renders only the changed message when the array is replaced with stable references', async () => {
    const m1 = { id: 'assistant:1', role: 'assistant' as const, content: 'a', timestamp: '', parts: [] }
    const m2 = { id: 'assistant:2', role: 'assistant' as const, content: 'b', timestamp: '', parts: [] }
    const wrapper = mount(ChatThread, { props: { messages: [m1, m2] } })

    // Initial mount rendered both messages.
    expect(lastRenderedIds).toEqual(['assistant:1', 'assistant:2'])
    renderCount = 0
    lastRenderedIds = []

    // New array, same m1 reference, m2 replaced with new content.
    await wrapper.setProps({ messages: [m1, { ...m2, content: 'b2' }] })
    expect(lastRenderedIds).toEqual(['assistant:2'])
    expect(renderCount).toBe(1)
  })

  it('re-renders nothing when the same message objects are passed again', async () => {
    const m1 = { id: 'assistant:1', role: 'assistant' as const, content: 'a', timestamp: '', parts: [] }
    const wrapper = mount(ChatThread, { props: { messages: [m1] } })

    renderCount = 0
    await wrapper.setProps({ messages: [m1] })
    expect(renderCount).toBe(0)
  })

  it('renders the message-product slot instead of MessageView when provided', () => {
    const m1 = { id: 'assistant:1', role: 'assistant' as const, content: 'a', timestamp: '', parts: [] }
    const wrapper = mount(ChatThread, {
      props: { messages: [m1] },
      slots: { 'message-product': '<div data-product-override>custom</div>' },
    })
    expect(wrapper.find('[data-product-override]').exists()).toBe(true)
    expect(wrapper.find('[data-message-id]').exists()).toBe(false)
  })

  it('does not re-render historical messages when a new message arrives (Set reference changes)', async () => {
    // A new message mutates processExpandedIds (fresh Set with the new id).
    // The per-message v-memo key (has(msg.id)) must keep historical messages
    // cached — only the brand-new message mounts.
    const m1 = { id: 'assistant:1', role: 'assistant' as const, content: 'a', timestamp: '', parts: [] }
    const m2 = { id: 'assistant:2', role: 'assistant' as const, content: 'b', timestamp: '', parts: [] }
    const wrapper = mount(ChatThread, {
      props: { messages: [m1], processExpandedIds: new Set(['assistant:1']) },
    })

    renderCount = 0
    lastRenderedIds = []
    await wrapper.setProps({
      messages: [m1, m2],
      processExpandedIds: new Set(['assistant:1', 'assistant:2']),
    })
    expect(lastRenderedIds).toEqual(['assistant:2'])
    expect(renderCount).toBe(1)
  })
})
