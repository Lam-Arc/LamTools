import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import CorePluginSystemEditor from '../src/components/CorePluginSystemEditor.vue'

const PLUGIN = {
  name: 'hello',
  version: '0.1.0',
  description: '',
  enabled: true,
  scope: 'global',
  root: '/plugins/hello',
}

function makeRpc() {
  return vi.fn(async (method: string) => {
    if (method === 'plugin.system.list') return { plugins: [PLUGIN], errors: [] }
    return {}
  })
}

describe('plugin system preview', () => {
  it('lists the minimal plugin returned by the new host', async () => {
    const rpc = makeRpc()
    const wrapper = mount(CorePluginSystemEditor, { props: { requestRpc: rpc } })

    await flushPromises()

    expect(rpc).toHaveBeenCalledWith('plugin.system.list', {})
    expect(wrapper.text()).toContain('hello')
    expect(wrapper.text()).toContain('0.1.0')
  })

  it('disables an enabled plugin and refreshes the list', async () => {
    const rpc = makeRpc()
    const wrapper = mount(CorePluginSystemEditor, { props: { requestRpc: rpc } })
    await flushPromises()

    await wrapper.find('button.small-btn').trigger('click')
    await flushPromises()

    expect(rpc).toHaveBeenCalledWith('plugin.system.disable', { name: 'hello' })
    expect(rpc.mock.calls.filter(([method]) => method === 'plugin.system.list')).toHaveLength(2)
  })
})
