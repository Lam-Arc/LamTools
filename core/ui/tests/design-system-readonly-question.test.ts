import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import MessageView from '../src/components/MessageView.vue'
import type { CoreMessage } from '../src/types'
import { createFakeTransport } from './fake-transport'

// user:“确保视觉、功能和交互不退化”+(跨会话只读时问题选项及键盘提交不可操作)。
describe('read-only question messages', () => {
  it('blocks question selection and submission until decisions are enabled', async () => {
    const msg: CoreMessage = { id: 'question', role: 'assistant', content: '', timestamp: '', parts: [{
      id: 'part', partType: 'questionGroup', status: 'pending', content: '', metadata: { question_group_id: 'group', questions: [{ id: 'q', title: '继续？', type: 'single', required: true, options: [{ label: '继续', description: '' }] }] },
    }] }
    const wrapper = mount(MessageView, { attachTo: document.body, props: { msg, transport: createFakeTransport(), decisionsDisabled: true } })
    const choice = wrapper.get('.question-group__choice')
    expect(choice.attributes('disabled')).toBeDefined()
    expect(wrapper.get('.question-group__entry').attributes('disabled')).toBeDefined()
    await choice.trigger('click'); await wrapper.get('[data-question-group]').trigger('keydown', { key: 'Enter', ctrlKey: true })
    expect(wrapper.emitted('question-submit')).toBeUndefined()
    await wrapper.setProps({ decisionsDisabled: false })
    expect(choice.attributes('disabled')).toBeUndefined()
    await choice.trigger('click')
    expect(wrapper.get('[data-question-submit]').attributes('disabled')).toBeUndefined()
    await wrapper.get('[data-question-submit]').trigger('click')
    expect(wrapper.emitted('question-submit')?.[0]?.[0]).toMatchObject({ partId: 'part', groupId: 'group', answers: { q: '继续' } })
    wrapper.unmount()
  })
})
