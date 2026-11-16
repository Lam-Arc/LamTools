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

  /**
   * user:“question 出现时是否将其它的东西都折叠起来了？能否按正常位置出现？”
   * +(卡片曾经被顶到消息最前面，正文反而落在它后面。现在按被问到的位置跟在正文后。)
   */
  it('places the question card after the answer, where it was asked', () => {
    const wrapper = mount(MessageView, {
      props: {
        msg: {
          id: 'm1',
          role: 'assistant',
          content: '这是正文结论。',
          parts: [part],
          turnId: 'turn-1',
          timestamp: 0,
        } as unknown as CoreMessage,
        turnActive: false,
        turnStatus: 'paused',
      },
      global: { stubs: { teleport: true } },
    })

    const root = wrapper.element as HTMLElement
    const order = Array.from(root.querySelectorAll('.assistant-answer, .question-group-block'))
      .map(node => (node.classList.contains('question-group-block') ? 'card' : 'answer'))
    expect(order).toEqual(['answer', 'card'])
  })

  /**
   * user:“暂停不折东西，只有正常完成才折，中断也不折”+(回合状态随消息下发，
   * 过程区按它决定折叠：paused / interrupted 保持展开，completed 才收起。)
   */
  it('folds the process stream only when the turn completed normally', () => {
    const toolPart = {
      id: 'p2',
      partType: 'tool_call',
      status: 'completed',
      toolName: 'read_file',
      label: 'read_file',
    } as unknown as MessagePart

    const withStatus = (turnStatus: string) => mount(MessageView, {
      props: {
        msg: {
          ...messageWith([toolPart, part]),
          metadata: { turnStatus },
        } as unknown as CoreMessage,
        turnActive: false,
        turnStatus: 'idle',
      },
      global: { stubs: { teleport: true } },
    })

    expect(withStatus('paused').find('.process-stream').exists()).toBe(true)
    expect(withStatus('interrupted').find('.process-stream').exists()).toBe(true)
    expect(withStatus('failed').find('.process-stream').exists()).toBe(true)
    expect(withStatus('completed').find('.process-stream').exists()).toBe(false)
  })

  /**
   * user:“这个询问框始终被挂在最下，而不是它的正确位置即对应步的最下方”
   * +(卡片跟着它在分片序列里的位置走：问在正文之前就排正文前，问在正文之后就排正文后，
   * 回合恢复后续写的正文不会再把卡片挤到最下面。)
   */
  it('puts the card before the answer when the question came first', () => {
    const text1 = { id: 't1', partType: 'model_text', status: 'completed', content: '第一段' } as unknown as MessagePart
    const text2 = { id: 't2', partType: 'model_text', status: 'completed', content: '第二段' } as unknown as MessagePart

    const beforeAnswer = mount(MessageView, {
      props: {
        msg: {
          id: 'm1',
          role: 'assistant',
          content: '第二段',
          parts: [text1, part, text2],
          processParts: [text1, part],
          answerPart: text2,
          answerText: '第二段',
          turnId: 'turn-1',
          timestamp: 0,
        } as unknown as CoreMessage,
        turnActive: false,
        turnStatus: 'idle',
      },
      global: { stubs: { teleport: true } },
    })

    const orderOf = (wrapper: ReturnType<typeof mount>) => Array.from(
      (wrapper.element as HTMLElement).querySelectorAll('.assistant-answer, .question-group-block'),
    ).map(node => (node.classList.contains('question-group-block') ? 'card' : 'answer'))

    expect(orderOf(beforeAnswer)).toEqual(['card', 'answer'])

    const afterAnswer = mount(MessageView, {
      props: {
        msg: {
          id: 'm1',
          role: 'assistant',
          content: '第二段',
          parts: [text1, text2, part],
          processParts: [text1, part],
          answerPart: text2,
          answerText: '第二段',
          turnId: 'turn-1',
          timestamp: 0,
        } as unknown as CoreMessage,
        turnActive: false,
        turnStatus: 'idle',
      },
      global: { stubs: { teleport: true } },
    })

    expect(orderOf(afterAnswer)).toEqual(['answer', 'card'])
  })
})
