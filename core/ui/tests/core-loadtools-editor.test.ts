import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import CoreLoadToolsEditor from '../src/components/CoreLoadToolsEditor.vue'

type RequestRpc = (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>

function createRequestRpc(initialModes: Record<string, { description: string; tools: string[] }> = {
  consider: { description: '思考与规划', tools: ['read_file'] },
}) {
  return vi.fn<RequestRpc>(async (method, params) => {
    if (method === 'config.loadtools.get') {
      return {
        modes: initialModes,
        catalog: [{ name: 'read_file', category: 'file_read' }],
        source: 'builtin',
      }
    }
    if (method === 'config.loadtools.set') {
      return { modes: params?.modes || {} }
    }
    return {}
  })
}

describe('CoreLoadToolsEditor', () => {
  it('removes the global overview while keeping title, state actions, and the rail create entry', async () => {
    const requestRpc = createRequestRpc()
    const wrapper = mount(CoreLoadToolsEditor, { props: { requestRpc } })
    await flushPromises()

    expect(wrapper.find('.loadtools-overview-bar').exists()).toBe(false)
    expect(wrapper.get('h1').text()).toBe('工具模式')
    expect(wrapper.get('.loadtools-title-copy p').text()).toBe('为不同工作模式配置模型可用的工具。')
    expect(wrapper.find('.loadtools-refresh').exists()).toBe(true)
    expect(wrapper.find('.loadtools-save').exists()).toBe(true)
    expect(wrapper.find('.mode-rail-footer .mode-create-btn').exists()).toBe(true)
  })

  it('keeps the rail create action functional and preserves save payload semantics', async () => {
    const requestRpc = createRequestRpc()
    const wrapper = mount(CoreLoadToolsEditor, { props: { requestRpc } })
    await flushPromises()

    await wrapper.get('.mode-rail-footer .mode-create-btn').trigger('click')
    expect(wrapper.get('.mode-name-input').element).toHaveProperty('value', 'new-mode')
    expect(wrapper.find('.loadtools-dirty').exists()).toBe(true)
    expect(wrapper.get('.loadtools-save').attributes('disabled')).toBeUndefined()

    await wrapper.get('.loadtools-save').trigger('click')
    await flushPromises()

    expect(requestRpc).toHaveBeenCalledWith('config.loadtools.set', {
      modes: expect.objectContaining({
        'new-mode': { description: '', tools: [] },
      }),
    })
    expect(wrapper.find('.loadtools-dirty').exists()).toBe(false)
  })

  it('keeps the empty state and both contextual create entries', async () => {
    const requestRpc = createRequestRpc({})
    const wrapper = mount(CoreLoadToolsEditor, { props: { requestRpc } })
    await flushPromises()

    expect(wrapper.find('.mode-empty').exists()).toBe(true)
    expect(wrapper.find('.mode-rail-footer .mode-create-btn').exists()).toBe(true)
    expect(wrapper.find('.mode-empty .small-btn').exists()).toBe(true)

    await wrapper.get('.mode-empty .small-btn').trigger('click')
    expect(wrapper.find('.mode-empty').exists()).toBe(false)
    expect(wrapper.find('.mode-detail').exists()).toBe(true)
  })
})
