import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import MessageView from '../src/components/MessageView.vue'
import type { CoreMessage } from '../src/types'
import { createFakeTransport } from './fake-transport'

// user:“确保视觉、功能和交互不退化”+(历史过程摘要向辅助技术暴露真实展开状态)。
describe('message process disclosure', () => {
  it('exposes collapsed and expanded states as the parent updates the view', async () => {
    const msg: CoreMessage = { id: 'm', role: 'assistant', content: '完成', timestamp: '', parts: [
      { id: 'tool', partType: 'tool_call', status: 'completed', content: '', label: '读取文件', toolName: 'read_file' },
      { id: 'answer', partType: 'model_text', status: 'completed', content: '完成', label: '正文' },
    ] }
    const wrapper = mount(MessageView, { props: { msg, transport: createFakeTransport(), processExpandedIds: new Set() } })
    const disclosure = wrapper.get('.process-summary')
    expect(disclosure.attributes('aria-expanded')).toBe('false')
    await disclosure.trigger('click'); expect(wrapper.emitted('toggle-process')).toEqual([['m']])
    await wrapper.setProps({ processExpandedIds: new Set(['m']) })
    expect(disclosure.attributes('aria-expanded')).toBe('true')
    expect(wrapper.find('.process-stream').exists()).toBe(true)
    wrapper.unmount()
  })
})
