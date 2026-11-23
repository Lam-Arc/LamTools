import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

import CoreQuestionGroup from '@/components/CoreQuestionGroup.vue'
import { questionGroupCopyText } from '@/helpers/questionGroupCopy.ts'
import type { MessagePart } from '@/types.ts'

/**
 * user:“询问卡右上角加一个复制图标按钮”+(复制这张卡现在的样子：分组、题目、题型、
 * 选项，以及已经填过的答案；收起成摘要胶囊之后也还能复制。)
 */

// 剪贴板本身由 helpers/clipboard 统一处理（其它界面已经用它），这里只钉住「复制什么」。
const { copyTextMock } = vi.hoisted(() => ({ copyTextMock: vi.fn(async (_text: string) => {}) }))
vi.mock('@/helpers/clipboard.ts', () => ({ copyText: copyTextMock }))

const SINGLE = {
  id: 'q1',
  title: '要不要继续？',
  description: '这一步不可撤销',
  type: 'single',
  required: true,
  options: [{ label: '继续', description: '' }, { label: '停止', description: '' }],
  placeholder: '',
}

const TEXT = {
  id: 'q2',
  title: '补充说明',
  description: '',
  type: 'text',
  required: false,
  options: [],
  placeholder: '可留空',
}

function partWith(metadata: Record<string, unknown>, status = 'pending'): MessagePart {
  return { id: 'p1', partType: 'questionGroup', status, content: '需要你回答', metadata } as unknown as MessagePart
}

const copiedText = (index = 0) => String(copyTextMock.mock.calls[index]?.[0] ?? '')

afterEach(() => {
  vi.useRealTimers()
  copyTextMock.mockReset()
})

describe('question card copy text', () => {
  it('writes sections, questions, options and only the answers that exist', () => {
    const text = questionGroupCopyText([
      { section: '必答', sectionHint: '填写后才能继续', title: '要不要继续？', typeLabel: '单选', description: '这一步不可撤销', options: ['继续', '停止'], answer: '继续' },
      { section: '可选', sectionHint: '可留空', title: '补充说明', typeLabel: '自由输入', options: [] },
    ])
    expect(text).toBe([
      '必答 · 填写后才能继续',
      '- 要不要继续？（单选）',
      '  说明：这一步不可撤销',
      '  选项：继续、停止',
      '  回答：继续',
      '',
      '可选 · 可留空',
      '- 补充说明（自由输入）',
    ].join('\n'))
  })

  it('keeps a multi-line free-text answer together under one 回答 line', () => {
    const text = questionGroupCopyText([
      { section: '可选', title: '补充说明', typeLabel: '自由输入', answer: '第一行\n第二行' },
    ])
    expect(text).toContain('  回答：第一行\n    第二行')
  })
})

describe('question card copy button', () => {
  it('sits at the card corner and copies the answers picked so far', async () => {
    const wrapper = mount(CoreQuestionGroup, { props: { part: partWith({ questions: [SINGLE, TEXT] }) } })
    expect(wrapper.find('[data-question-copy]').exists()).toBe(true)
    // 只有一处按钮，且不会被塞进别的按钮里（摘要胶囊本身是按钮）。
    expect(wrapper.findAll('[data-question-copy]')).toHaveLength(1)
    expect(wrapper.find('[data-question-open] [data-question-copy]').exists()).toBe(false)

    await wrapper.findAll('.question-group__choice').find(node => node.text().startsWith('继续'))!.trigger('click')
    await wrapper.find('[data-question-copy]').trigger('click')
    await new Promise(resolve => setTimeout(resolve, 0))

    expect(copiedText()).toBe([
      '必答 · 填写后才能继续',
      '- 要不要继续？（单选）',
      '  说明：这一步不可撤销',
      '  选项：继续、停止',
      '  回答：继续',
      '',
      '可选 · 可留空',
      '- 补充说明（自由输入）',
    ].join('\n'))
    expect(wrapper.find('[data-question-copy]').attributes('title')).toBe('已复制')
  })

  it('still copies after the card collapses into the summary pill', async () => {
    vi.useFakeTimers()
    const wrapper = mount(CoreQuestionGroup, { props: { part: partWith({ questions: [SINGLE] }) } })
    await wrapper.findAll('.question-group__choice').find(node => node.text().startsWith('继续'))!.trigger('click')
    await wrapper.find('[data-question-submit]').trigger('click')
    await vi.advanceTimersByTimeAsync(900)
    expect(wrapper.find('[data-question-open]').exists()).toBe(true)

    const button = wrapper.find('[data-question-copy]')
    expect(button.exists()).toBe(true)
    expect(button.classes()).toContain('question-group__copy--inline')
    await button.trigger('click')
    await vi.advanceTimersByTimeAsync(0)
    expect(copiedText()).toContain('回答：继续')
  })

  it('only turns red when the clipboard refuses', async () => {
    copyTextMock.mockRejectedValueOnce(new Error('denied'))
    const wrapper = mount(CoreQuestionGroup, { props: { part: partWith({ questions: [SINGLE] }) } })
    await wrapper.find('[data-question-copy]').trigger('click')
    await new Promise(resolve => setTimeout(resolve, 0))
    const button = wrapper.find('[data-question-copy]')
    expect(button.classes()).toContain('is-error')
    expect(button.attributes('title')).toBe('复制失败')
    // 失败不额外加提示元素：还是那一个按钮。
    expect(wrapper.findAll('.question-group__copy')).toHaveLength(1)
  })

  it('falls back to the answers the backend already recorded', async () => {
    const wrapper = mount(CoreQuestionGroup, { props: { part: partWith({ questions: [{ ...SINGLE, answer: '停止' }] }) } })
    await wrapper.find('[data-question-copy]').trigger('click')
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(copiedText()).toContain('回答：停止')
  })
})
