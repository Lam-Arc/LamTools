import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

import CoreQuestionGroup from '@/components/CoreQuestionGroup.vue'
import type { MessagePart } from '@/types.ts'

/**
 * user:“无，依旧不显示”+(投影已经产出 questionGroup 分片，若界面仍空白，只剩组件
 * 自身在 setup/模板抛错这一种可能——Vue 会静默跳过出错的组件。这个测试直接挂载它。)
 *
 * user:“样式就到这里”+(外观按定稿的提问卡落地：无抬头、无编号、题型标签、一项一行、
 * 提交后收起为摘要胶囊、点开可追加并取消。这些都在下面钉住。)
 */

const SINGLE = {
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
}

const OPTIONAL_SINGLE = {
  id: 'q2',
  title: '用哪份文档？',
  description: '',
  type: 'single',
  required: false,
  options: [{ label: '旧版', description: '' }, { label: '新版', description: '' }],
  placeholder: '',
}

const MULTIPLE = {
  id: 'q3',
  title: '一并调整哪些部分？',
  description: '',
  type: 'multiple',
  required: false,
  options: [{ label: '样式', description: '' }, { label: '文案', description: '' }],
  placeholder: '',
}

const TEXT = {
  id: 'q4',
  title: '补充说明',
  description: '',
  type: 'text',
  required: false,
  options: [],
  placeholder: '可留空',
}

function partWith(metadata: Record<string, unknown>, status = 'pending'): MessagePart {
  return {
    id: 'p1',
    partType: 'questionGroup',
    status,
    content: '需要你回答：1. 要不要继续？',
    metadata,
  } as unknown as MessagePart
}

const choice = (wrapper: ReturnType<typeof mount>, label: string) =>
  wrapper.findAll('.question-group__choice').find(node => node.text().startsWith(label))!

afterEach(() => {
  vi.useRealTimers()
})

describe('CoreQuestionGroup', () => {
  it('renders questions carried directly in metadata', () => {
    const wrapper = mount(CoreQuestionGroup, { props: { part: partWith({ questions: [SINGLE] }) } })
    expect(wrapper.text()).toContain('要不要继续？')
    expect(wrapper.text()).toContain('继续')
    expect(wrapper.find('[data-question-submit]').exists()).toBe(true)
  })

  it('renders questions carried inside metadata.payload', () => {
    const wrapper = mount(CoreQuestionGroup, {
      props: { part: partWith({ payload: { questions: [SINGLE] } }) },
    })
    expect(wrapper.text()).toContain('要不要继续？')
  })

  it('splits required questions ahead of optional ones', () => {
    const wrapper = mount(CoreQuestionGroup, {
      props: { part: partWith({ questions: [OPTIONAL_SINGLE, SINGLE] }) },
    })
    const titles = wrapper.findAll('.question-group__ghead b').map(node => node.text())
    expect(titles).toEqual(['必答', '可选'])
    const text = wrapper.text()
    expect(text.indexOf('要不要继续？')).toBeLessThan(text.indexOf('用哪份文档？'))
  })

  it('labels each question with its answer kind instead of a number', () => {
    const wrapper = mount(CoreQuestionGroup, {
      props: { part: partWith({ questions: [SINGLE, MULTIPLE, TEXT] }) },
    })
    const tags = wrapper.findAll('.question-group__tag').map(node => node.text())
    expect(tags).toEqual(['单选', '多选', '自由输入'])
    // 定稿去掉了数字编号与「必答」重复标签
    expect(wrapper.find('.question-group__index').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('共 3 题')
  })

  it('shows an explicit empty state instead of a blank card', () => {
    const wrapper = mount(CoreQuestionGroup, { props: { part: partWith({}) } })
    expect(wrapper.text()).toContain('没有收到问题数据')
  })

  it('keeps the card and rows in place while picking options', async () => {
    const wrapper = mount(CoreQuestionGroup, { props: { part: partWith({ questions: [SINGLE] }) } })
    const card = wrapper.find('.question-group').element
    const row = choice(wrapper, '继续').element

    await choice(wrapper, '继续').trigger('click')
    expect(choice(wrapper, '继续').attributes('aria-pressed')).toBe('true')
    expect(wrapper.find('.question-group').element).toBe(card)
    expect(choice(wrapper, '继续').element).toBe(row)

    // 单选换选：新选项选中、旧选项自动取消，节点不重建
    await choice(wrapper, '停止').trigger('click')
    expect(choice(wrapper, '停止').attributes('aria-pressed')).toBe('true')
    expect(choice(wrapper, '继续').attributes('aria-pressed')).toBe('false')
    expect(wrapper.find('.question-group').element).toBe(card)
    expect(choice(wrapper, '继续').element).toBe(row)
  })

  it('blocks submit until every required question is answered', async () => {
    const wrapper = mount(CoreQuestionGroup, {
      props: { part: partWith({ questions: [SINGLE, OPTIONAL_SINGLE] }) },
    })
    const submit = wrapper.find('[data-question-submit]')
    expect(submit.attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('还差 1 道必答')

    await choice(wrapper, '继续').trigger('click')
    expect(wrapper.find('[data-question-submit]').attributes('disabled')).toBeUndefined()
    expect(wrapper.text()).not.toContain('还差')
  })

  it('submits a standard answer message, then collapses into a summary pill', async () => {
    vi.useFakeTimers()
    const wrapper = mount(CoreQuestionGroup, { props: { part: partWith({ questions: [SINGLE] }) } })

    await choice(wrapper, '继续').trigger('click')
    await wrapper.find('[data-question-submit]').trigger('click')

    const emitted = wrapper.emitted('submit')
    expect(emitted).toBeTruthy()
    const payload = emitted![0][0] as { text: string; answers: Record<string, string>; partId: string }
    expect(payload.text).toBe('Q1 要不要继续？：继续')
    expect(payload.answers).toEqual({ q1: '继续' })
    expect(payload.partId).toBe('p1')
    expect(wrapper.attributes('data-state')).toBe('answered')

    await vi.advanceTimersByTimeAsync(900)
    expect(wrapper.find('[data-question-open]').exists()).toBe(true)
    expect(wrapper.text()).toContain('已回答 1 个问题')
  })

  it('reopens the closed card for appending, and cancel restores the last answers', async () => {
    vi.useFakeTimers()
    const wrapper = mount(CoreQuestionGroup, { props: { part: partWith({ questions: [SINGLE] }) } })

    await choice(wrapper, '继续').trigger('click')
    await wrapper.find('[data-question-submit]').trigger('click')
    await vi.advanceTimersByTimeAsync(900)

    await wrapper.find('[data-question-open]').trigger('click')
    expect(wrapper.find('.question-group__choice').exists()).toBe(true)
    expect(wrapper.find('[data-question-cancel]').exists()).toBe(true)
    expect(wrapper.find('[data-question-submit]').text()).toBe('保存')

    // 改选另一项，再取消：回到胶囊，且不保留这次改动
    await choice(wrapper, '停止').trigger('click')
    expect(choice(wrapper, '停止').attributes('aria-pressed')).toBe('true')
    await wrapper.find('[data-question-cancel]').trigger('click')
    expect(wrapper.find('[data-question-open]').exists()).toBe(true)

    await wrapper.find('[data-question-open]').trigger('click')
    expect(choice(wrapper, '继续').attributes('aria-pressed')).toBe('true')
    expect(choice(wrapper, '停止').attributes('aria-pressed')).toBe('false')
  })

  it('emits skip without closing itself, because the host owns the close', async () => {
    const wrapper = mount(CoreQuestionGroup, { props: { part: partWith({ questions: [SINGLE] }) } })
    const skip = wrapper.find('[data-question-skip]')
    expect(skip.exists()).toBe(true)

    await skip.trigger('click')

    expect(wrapper.emitted('skip')).toBeTruthy()
    // user:“跳过等于 done”+(卡片不改自己的状态：跳过要走恢复请求，由后端关组并继续，
    // 前端先收起会让界面说「已跳过」而回合仍停在暂停。)
    expect(wrapper.attributes('data-state')).toBe('pending')
    expect(wrapper.find('[data-question-open]').exists()).toBe(false)
    expect(wrapper.emitted('submit')).toBeFalsy()
  })

  it('offers no skip when nothing is required', () => {
    const wrapper = mount(CoreQuestionGroup, {
      props: { part: partWith({ questions: [OPTIONAL_SINGLE] }) },
    })
    expect(wrapper.find('[data-question-skip]').exists()).toBe(false)
  })

  it('keeps options disabled while the turn is still running', () => {
    const wrapper = mount(CoreQuestionGroup, {
      props: { part: partWith({ questions: [SINGLE] }, 'running') },
    })
    expect(wrapper.find('.question-group__choice').attributes('disabled')).toBeDefined()
    expect(wrapper.classes()).not.toContain('question-group--waiting')
  })
})
