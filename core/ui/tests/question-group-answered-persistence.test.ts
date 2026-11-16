import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

import CoreQuestionGroup from '@/components/CoreQuestionGroup.vue'
import { resetAnsweredGroups } from '@/helpers/questionGroupAnswered.ts'
import type { MessagePart } from '@/types.ts'

const QUESTION = {
  id: 'q1',
  title: '要不要继续？',
  description: '',
  type: 'single',
  required: true,
  options: [{ label: '继续', description: '' }, { label: '停止', description: '' }],
  placeholder: '',
}

function partWith(id: string): MessagePart {
  return {
    id,
    partType: 'questionGroup',
    status: 'waiting',
    content: '',
    metadata: { question_group_id: 'group-persist', questions: [QUESTION] },
  } as unknown as MessagePart
}

function choice(wrapper: ReturnType<typeof mount>, label: string) {
  return wrapper.findAll('.question-group__choice').find(node => node.text().includes(label))!
}

afterEach(() => {
  vi.useRealTimers()
})

/**
 * user:“我这一张卡明明回答了，我看见它折叠了，随后又出现在我的回答下方，且变成了未回答，
 * 但是根据模型的回复它确实收到了我的回答”+(已回答此前只存在组件本地态：卡片一旦因位置
 * 换算或重复投影被重新挂载，就退回未回答。同一问组重新挂上来必须仍然是「已回答」。)
 */
describe('CoreQuestionGroup answered persistence', () => {
  it('stays answered when the same question group is mounted again', async () => {
    vi.useFakeTimers()
    const first = mount(CoreQuestionGroup, { props: { part: partWith('p1') } })
    await choice(first, '继续').trigger('click')
    await first.find('[data-question-submit]').trigger('click')
    expect(first.attributes('data-state')).toBe('answered')
    first.unmount()

    // 分片 id 变了（重新投影），问组 id 没变：仍然算已回答
    const second = mount(CoreQuestionGroup, { props: { part: partWith('p2') } })
    await second.vm.$nextTick()
    expect(second.attributes('data-state')).toBe('answered')
    await vi.advanceTimersByTimeAsync(900)
    expect(second.text()).toContain('已回答 1 个问题')
    second.unmount()
  })

  it('does not leak the answered state to a different question group', async () => {
    const other = mount(CoreQuestionGroup, {
      props: {
        part: {
          id: 'p9',
          partType: 'questionGroup',
          status: 'waiting',
          content: '',
          metadata: { question_group_id: 'group-other', questions: [QUESTION] },
        } as unknown as MessagePart,
      },
    })
    await other.vm.$nextTick()
    expect(other.attributes('data-state')).toBe('pending')
    other.unmount()
  })
})
