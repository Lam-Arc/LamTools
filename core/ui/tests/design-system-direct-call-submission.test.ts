import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import DirectCallView from '../src/components/DirectCallView.vue'

// user:“确保视觉、功能和交互不退化”+(请求尚未返回时不能重复启动同一次调用)。
it('prevents duplicate submissions before the start request resolves', async () => {
  let finish!: (value: unknown) => void
  const rpc = vi.fn((method: string) => {
    if (method === 'direct.catalog') return Promise.resolve({ models: [{ model_record_id: 'sample', model_id: 'sample', display_name: '示例', provider_id: 'demo', provider_name: '示例', output_type: 'text', has_api_key: true }] })
    if (method === 'direct.list') return Promise.resolve({ calls: [] })
    if (method === 'direct.run') return new Promise(resolve => { finish = resolve })
    return Promise.resolve({})
  })
  const wrapper = mount(DirectCallView, { props: { requestRpc: rpc } }); await flushPromises()
  await wrapper.get('[data-direct-input]').setValue('示例')
  const run = wrapper.get('[data-direct-run]')
  await run.trigger('click'); await run.trigger('click')
  expect(rpc.mock.calls.filter(([method]) => method === 'direct.run')).toHaveLength(1)
  finish({ call: { id: 'one', finished: true, results: [], prompts: [], params: {} } }); await flushPromises()
  wrapper.unmount()
})

it('can run an isolated preview without reading or writing remembered parameters', async () => {
  localStorage.setItem('lamtools.direct.params', JSON.stringify({ sample: { temperature: 0.1 } }))
  const model = { model_record_id: 'sample', model_id: 'sample', display_name: '示例', provider_id: 'demo', provider_name: '示例', output_type: 'text', has_api_key: true }
  const call = { id: 'one', finished: true, results: [], prompts: [], params: {} }
  const rpc = vi.fn(async (method: string) => method === 'direct.catalog' ? { models: [model] } : method === 'direct.list' ? { calls: [] } : { call })
  const wrapper = mount(DirectCallView, { props: { requestRpc: rpc, persistParameters: false } }); await flushPromises()
  await wrapper.get('[data-direct-input]').setValue('示例')
  await wrapper.get('[data-direct-run]').trigger('click'); await flushPromises()
  expect(rpc.mock.calls.find(([method]) => method === 'direct.run')?.[1]).toMatchObject({ params: { temperature: 0.7 } })
  expect(JSON.parse(localStorage.getItem('lamtools.direct.params')!).sample.temperature).toBe(0.1)
  wrapper.unmount(); localStorage.removeItem('lamtools.direct.params')
})

it('does not start polling when a pending submission resolves after unmount', async () => {
  vi.useFakeTimers()
  let finish!: (value: unknown) => void
  const model = { model_record_id: 'sample', model_id: 'sample', display_name: '示例', provider_id: 'demo', provider_name: '示例', output_type: 'text', has_api_key: true }
  const rpc = vi.fn((method: string) => method === 'direct.catalog' ? Promise.resolve({ models: [model] }) : method === 'direct.list' ? Promise.resolve({ calls: [] }) : method === 'direct.run' ? new Promise(resolve => { finish = resolve }) : Promise.resolve({}))
  const wrapper = mount(DirectCallView, { props: { requestRpc: rpc, persistParameters: false } }); await flushPromises()
  await wrapper.get('[data-direct-input]').setValue('示例')
  await wrapper.get('[data-direct-run]').trigger('click')
  wrapper.unmount()
  finish({ call: { id: 'one', finished: false, results: [], prompts: [], params: {} } }); await flushPromises()
  await vi.advanceTimersByTimeAsync(1000)
  expect(rpc.mock.calls.some(([method]) => method === 'direct.get')).toBe(false)
  vi.useRealTimers()
})

it('remembers parameters for the model used to start the call', async () => {
  let finish!: (value: unknown) => void
  const model = (id: string) => ({ model_record_id: id, model_id: id, display_name: id, provider_id: 'demo', provider_name: '示例', output_type: 'text', has_api_key: true })
  const rpc = vi.fn((method: string) => method === 'direct.catalog' ? Promise.resolve({ models: [model('first'), model('second')] }) : method === 'direct.list' ? Promise.resolve({ calls: [] }) : method === 'direct.run' ? new Promise(resolve => { finish = resolve }) : Promise.resolve({}))
  localStorage.removeItem('lamtools.direct.params')
  const wrapper = mount(DirectCallView, { props: { requestRpc: rpc } }); await flushPromises()
  await wrapper.get('[data-direct-input]').setValue('示例')
  await wrapper.get('[data-direct-run]').trigger('click')
  await wrapper.get('[data-direct-model="second"]').trigger('click')
  finish({ call: { id: 'one', finished: true, results: [], prompts: [], params: {} } }); await flushPromises()
  const remembered = JSON.parse(localStorage.getItem('lamtools.direct.params')!)
  expect(remembered.first).toBeDefined()
  expect(remembered.second).toBeUndefined()
  wrapper.unmount(); localStorage.removeItem('lamtools.direct.params')
})

it('ignores a start response from a previous project', async () => {
  let finish!: (value: unknown) => void
  const model = { model_record_id: 'sample', model_id: 'sample', display_name: '示例', provider_id: 'demo', provider_name: '示例', output_type: 'text', has_api_key: true }
  const rpc = vi.fn((method: string) => method === 'direct.catalog' ? Promise.resolve({ models: [model] }) : method === 'direct.list' ? Promise.resolve({ calls: [] }) : method === 'direct.run' ? new Promise(resolve => { finish = resolve }) : Promise.resolve({}))
  const wrapper = mount(DirectCallView, { props: { requestRpc: rpc, projectId: 'a', persistParameters: false } }); await flushPromises()
  await wrapper.get('[data-direct-input]').setValue('示例')
  await wrapper.get('[data-direct-run]').trigger('click')
  await wrapper.setProps({ projectId: 'b' }); await flushPromises()
  finish({ call: { id: 'old', finished: false, results: [], prompts: [], params: {} } }); await flushPromises()
  expect(wrapper.find('[data-direct-results]').exists()).toBe(false)
  wrapper.unmount()
})
