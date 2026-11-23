import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import DirectCallView from '../src/components/DirectCallView.vue'

// user:“确保视觉、功能和交互不退化”+(历史筛选只显示最近一次请求，旧响应不能覆盖)。
it('ignores stale history responses after switching filters', async () => {
  const requests: Array<{ filter: string; finish: (value: unknown) => void }> = []
  const rpc = vi.fn((method: string, params?: Record<string, unknown>) => {
    if (method === 'direct.catalog') return Promise.resolve({ models: [{ model_record_id: 'sample', model_id: 'sample', display_name: '示例', provider_id: 'demo', provider_name: '示例', output_type: 'text', has_api_key: true }] })
    if (method === 'direct.list') return new Promise(resolve => requests.push({ filter: String(params?.output_type || ''), finish: resolve }))
    return Promise.resolve({})
  })
  const wrapper = mount(DirectCallView, { props: { requestRpc: rpc } })
  requests[0].finish({ calls: [] }); await flushPromises()
  await wrapper.findAll('[role="tab"]').find(tab => tab.text() === '文本')!.trigger('click')
  await wrapper.findAll('[role="tab"]').find(tab => tab.text() === '图片')!.trigger('click')
  expect(requests.map(request => request.filter)).toEqual(['', 'text', 'image'])
  requests[2].finish({ calls: [{ id: 'image', display_name: '图片结果', status: 'completed', created_at: '2026-01-01', results: [], prompts: [] }] }); await flushPromises()
  requests[1].finish({ calls: [{ id: 'old', display_name: '旧记录', status: 'completed', created_at: '2026-01-01', results: [], prompts: [] }] }); await flushPromises()
  expect(wrapper.find('[data-direct-history="image"]').exists()).toBe(true)
  expect(wrapper.find('[data-direct-history="old"]').exists()).toBe(false)
  wrapper.unmount()
})

it('does not request the same history page twice', async () => {
  const records = Array.from({ length: 20 }, (_, index) => ({ id: `call-${index}`, display_name: '示例', status: 'completed', created_at: '2026-01-01', results: [], prompts: [] }))
  let finish!: (value: unknown) => void
  const rpc = vi.fn((method: string, params?: Record<string, unknown>) => {
    if (method === 'direct.catalog') return Promise.resolve({ models: [{ model_record_id: 'sample', model_id: 'sample', display_name: '示例', provider_id: 'demo', provider_name: '示例', output_type: 'text', has_api_key: true }] })
    if (method === 'direct.list' && !params?.offset) return Promise.resolve({ calls: records })
    if (method === 'direct.list') return new Promise(resolve => { finish = resolve })
    return Promise.resolve({})
  })
  const wrapper = mount(DirectCallView, { props: { requestRpc: rpc } }); await flushPromises()
  const more = wrapper.get('[data-direct-history-more]')
  await more.trigger('click'); await more.trigger('click')
  expect(rpc.mock.calls.filter(([method, params]) => method === 'direct.list' && params?.offset === 20)).toHaveLength(1)
  expect(more.attributes('disabled')).toBeDefined()
  finish({ calls: [] }); await flushPromises(); wrapper.unmount()
})

it('shows a history loading error when the current filter fails', async () => {
  const rpc = vi.fn(async (method: string, params?: Record<string, unknown>) => {
    if (method === 'direct.catalog') return { models: [{ model_record_id: 'sample', model_id: 'sample', display_name: '示例', provider_id: 'demo', provider_name: '示例', output_type: 'text', has_api_key: true }] }
    if (method === 'direct.list' && params?.output_type === 'image') throw new Error('示例历史读取失败')
    return { calls: [] }
  })
  const wrapper = mount(DirectCallView, { props: { requestRpc: rpc } }); await flushPromises()
  await wrapper.findAll('[role="tab"]').find(tab => tab.text() === '图片')!.trigger('click'); await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('示例历史读取失败')
  await wrapper.findAll('[role="tab"]').find(tab => tab.text() === '文本')!.trigger('click'); await flushPromises()
  expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  wrapper.unmount()
})
