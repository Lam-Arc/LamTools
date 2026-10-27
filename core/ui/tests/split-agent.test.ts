import { mount, flushPromises } from '@vue/test-utils'
import { defineComponent, h, reactive } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { useSplitAgent } from '../src/split/useSplitAgent'
import type { CoreMessage } from '../src/types'
import type { LamToolsTransport } from '../src/transport'
vi.mock('../src/agents/subAgentProjection', () => ({ selectCoreSubAgentRun: (messages: CoreMessage[]) => messages.length ? { id: 'child', name: 'same-name', status: 'completed', task: messages[0].content, timeline: [] } : undefined }))
vi.mock('../src/appServer/workbenchProjection', () => ({ selectCoreWorkbenchMessages: () => [{ id: 'source', role: 'assistant', content: 'source thread', timestamp: '' }] }))
describe('Split Pane agent origin', () => {
  it('reads the source thread after switching main chat and ignores same-named agents there', async () => {
    const request = vi.fn(async () => ({ snapshot: { thread_id: 'source', snapshot_seq: 1 } }))
    const props = reactive({ tab: { id: 'a', kind: 'agent' as const, resource: 'child', title: 'same-name', sessionId: 'source' }, visible: true, messages: [{ id: 'm', role: 'assistant' as const, content: 'live source', timestamp: '' }], activeSessionId: 'source', transport: { request } as unknown as LamToolsTransport })
    let agent!: ReturnType<typeof useSplitAgent>
    const wrapper = mount(defineComponent({ setup() { agent = useSplitAgent(props); return () => h('div', agent.run.value?.task) } }))
    expect(wrapper.text()).toBe('live source')
    expect(request).not.toHaveBeenCalled()
    props.activeSessionId = 'another'; props.messages = [{ id: 'other', role: 'assistant', content: 'wrong same-name agent', timestamp: '' }]
    await flushPromises()
    expect(request).toHaveBeenCalledWith(expect.objectContaining({ method: 'thread/read', params: { thread_id: 'source' } }))
    expect(wrapper.text()).toBe('source thread')
    wrapper.unmount()
  })
  it('does not poll hidden background tabs', async () => {
    const request = vi.fn()
    const wrapper = mount(defineComponent({ setup() { useSplitAgent({ tab: { id: 'a', kind: 'agent', resource: 'child', title: 'same', sessionId: 'source' }, visible: false, messages: [], activeSessionId: 'other', transport: { request } as unknown as LamToolsTransport }); return () => h('div') } }))
    await flushPromises(); expect(request).not.toHaveBeenCalled(); wrapper.unmount()
  })
  // user:“审查分屏代码，并优化”+(切回来源聊天后不再显示上一次历史读取失败，内容改由实时消息驱动)。
  it('clears a stale source-history error once that chat becomes the main session', async () => {
    const request = vi.fn(async () => { throw Error('来源聊天读取失败') })
    const props = reactive({ tab: { id: 'a', kind: 'agent' as const, resource: 'child', title: 'same-name', sessionId: 'source' }, visible: true, messages: [{ id: 'm', role: 'assistant' as const, content: 'live source', timestamp: '' }], activeSessionId: 'other', transport: { request } as unknown as LamToolsTransport })
    let agent!: ReturnType<typeof useSplitAgent>
    const wrapper = mount(defineComponent({ setup() { agent = useSplitAgent(props); return () => h('div') } }))
    await flushPromises()
    expect(agent.error.value).toContain('来源聊天读取失败')
    props.activeSessionId = 'source'
    await flushPromises()
    expect(agent.error.value).toBe('')
    wrapper.unmount()
  })
})
