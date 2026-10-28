import { defineComponent, h } from 'vue'
import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createFakeTransport } from './fake-transport'
import type { CoreMessage } from '../src/types'

const rendered: string[] = []
vi.mock('../src/components/MessageView.vue', () => ({
  default: defineComponent({
    props: ['msg', 'turnActive', 'turnStatus', 'activeTurnId', 'lockedMessageIds'],
    setup(props) {
      return () => {
        rendered.push(props.msg.id)
        return h('div', { 'data-id': props.msg.id, 'data-active': String(props.turnActive), 'data-status': props.turnStatus })
      }
    },
  }),
}))
vi.mock('../src/components/PluginSystemContributions.vue', () => ({ default: { render: () => null } }))
import ChatThread from '../src/components/ChatThread.vue'

const historical: CoreMessage[] = Array.from({ length: 200 }, (_, i) => ({
  id: `assistant:history-${i}`, role: 'assistant', content: `History ${i}`, timestamp: '', parts: [],
}))
const current: CoreMessage = { id: 'assistant:session:turn:new#2', role: 'assistant', content: 'Current', timestamp: '', parts: [] }
const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); rendered.length = 0 })

// user:“修，不要出错”+(发送、等待、停止与换轮不能重绘未改变的历史，也不能丢失当前轮状态)。
describe('send-time message isolation', () => {
  function mountThread() {
    const wrapper = mount(ChatThread, { props: {
      messages: [...historical, current], transport: createFakeTransport(),
      lockedMessageIds: new Set<string>(),
    } })
    wrappers.push(wrapper)
    rendered.length = 0
    return wrapper
  }

  it('updates only the current assistant segment across send, wait and stop', async () => {
    const wrapper = mountThread()
    for (const [turnActive, turnStatus] of [[true, 'running'], [true, 'waiting'], [true, 'running'], [false, 'completed']] as const) {
      rendered.length = 0
      await wrapper.setProps({ turnActive, turnStatus, activeTurnId: 'session:turn:new', lockedMessageIds: new Set() })
      expect(rendered).toEqual([current.id])
      expect(wrapper.get(`[data-id="${current.id}"]`).attributes('data-active')).toBe(String(turnActive))
      if (turnActive) expect(wrapper.get(`[data-id="${current.id}"]`).attributes('data-status')).toBe(turnStatus)
    }
    expect(wrapper.findAll('[data-id]')).toHaveLength(201)
  })

  it('updates previous and next active segments when switching turns', async () => {
    const wrapper = mountThread()
    await wrapper.setProps({ turnActive: true, turnStatus: 'running', activeTurnId: 'session:turn:new' })
    rendered.length = 0
    await wrapper.setProps({ activeTurnId: 'history-20' })
    expect(rendered).toEqual(['assistant:history-20', current.id])
  })

  it('updates only rows whose compaction lock or content actually changes', async () => {
    const wrapper = mountThread()
    await wrapper.setProps({ lockedMessageIds: new Set([historical[0].id]) })
    expect(rendered).toEqual([historical[0].id])
    rendered.length = 0
    await wrapper.setProps({ messages: [historical[0], { ...historical[1], content: 'Changed' }, ...historical.slice(2), current] })
    expect(rendered).toEqual([historical[1].id])
  })
})
