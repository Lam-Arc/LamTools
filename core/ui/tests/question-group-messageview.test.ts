import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import MessageView from '@/components/MessageView.vue'
import type { CoreMessage, MessagePart } from '@/types.ts'

/**
 * user:“连纯文本都没有”+(投影与组件都已验证，若界面仍空白，只剩 MessageView 的
 * 模板分支没命中。这个测试直接挂载会话气泡，喂一条带 questionGroup 分片的消息。)
 */

const QUESTIONS = [
  {
    id: 'q1',
    title: '要不要继续？',
    description: '',
    type: 'single',
    required: true,
    options: [
      { label: '继续', description: '' },
      { label: '停止', description: '' },
    ],
    placeholder: '',
  },
]

const part = {
  id: 'p1',
  partType: 'questionGroup',
  status: 'pending',
  content: '需要你回答：1. 要不要继续？',
  metadata: { questions: QUESTIONS, question_group_id: 'g1' },
} as unknown as MessagePart

function messageWith(parts: MessagePart[]): CoreMessage {
  return {
    id: 'm1',
    role: 'assistant',
    content: '',
    parts,
    turnId: 'turn-1',
    timestamp: 0,
  } as unknown as CoreMessage
}

describe('MessageView question group render', () => {
  it('renders the group component for a questionGroup part', () => {
    const wrapper = mount(MessageView, {
      props: { msg: messageWith([part]), turnActive: true },
      global: { stubs: { teleport: true } },
    })
    expect(wrapper.find('[data-question-group]').exists()).toBe(true)
  })

  /**
   * user:“这个东西是否会被折叠进过程行？”+(不会被：提问卡固定在消息主体里渲染，
   * 过程流的折叠只管它自己内部的推理/工具行。这条测试盯住两件事——完成态过程区
   * 收起时卡片照样在；展开过程区时卡片也不属于过程流。)
   */
  it('stays outside the collapsible process stream', () => {
    const toolPart = {
      id: 'p2',
      partType: 'tool_call',
      status: 'completed',
      toolName: 'read_file',
      label: 'read_file',
    } as unknown as MessagePart

    const collapsed = mount(MessageView, {
      props: { msg: messageWith([toolPart, part]), turnActive: false, turnStatus: 'idle' },
      global: { stubs: { teleport: true } },
    })
    // 完成态默认收起：过程流整块不渲染，提问卡必须照旧可见
    expect(collapsed.find('.process-stream').exists()).toBe(false)
    expect(collapsed.find('.question-group-block [data-question-group]').exists()).toBe(true)

    const expanded = mount(MessageView, {
      props: {
        msg: messageWith([toolPart, part]),
        turnActive: false,
        turnStatus: 'idle',
        processExpandedIds: new Set(['m1']),
      },
      global: { stubs: { teleport: true } },
    })
    // 展开过程流后，卡片仍然在过程流之外
    expect(expanded.find('.process-stream').exists()).toBe(true)
    expect(expanded.find('.question-group-block').exists()).toBe(true)
    expect(expanded.find('.process-stream .question-group-block').exists()).toBe(false)
    expect(expanded.find('.process-stream [data-question-group]').exists()).toBe(false)
  })
})
