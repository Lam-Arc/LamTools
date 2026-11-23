import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import DirectCallView from '../src/components/DirectCallView.vue'

// user:“确保视觉、功能和交互不退化”+(切换项目后旧项目的模型列表不能覆盖当前项目)。
it('keeps the latest project catalog when responses arrive out of order', async () => {
  const pending: Array<{ project: unknown; finish: (value: unknown) => void }> = []
  const rpc = vi.fn((method: string, params?: Record<string, unknown>) => {
    if (method === 'direct.catalog') return new Promise(resolve => pending.push({ project: params?.project_id, finish: resolve }))
    if (method === 'direct.list') return Promise.resolve({ calls: [] })
    return Promise.resolve({})
  })
  const model = (id: string) => ({ model_record_id: id, model_id: id, display_name: id, provider_id: 'demo', provider_name: '示例', output_type: 'text', has_api_key: true })
  const wrapper = mount(DirectCallView, { props: { requestRpc: rpc, projectId: 'old' } })
  await wrapper.setProps({ projectId: 'new' })
  expect(pending.map(request => request.project)).toEqual(['old', 'new'])
  pending[1].finish({ models: [model('new-model')] }); await flushPromises()
  pending[0].finish({ models: [model('old-model')] }); await flushPromises()
  expect(wrapper.find('[data-direct-model="new-model"]').exists()).toBe(true)
  expect(wrapper.find('[data-direct-model="old-model"]').exists()).toBe(false)
  wrapper.unmount()
})
