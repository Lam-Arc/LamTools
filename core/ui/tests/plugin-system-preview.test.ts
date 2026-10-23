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

  it('opens the config panel from the plugin row', async () => {
    const rpc = makeRpc()
    const wrapper = mount(CorePluginSystemEditor, { props: { requestRpc: rpc } })
    await flushPromises()

    await wrapper.find('button[data-config-for="hello"]').trigger('click')
    await flushPromises()

    expect(rpc).toHaveBeenCalledWith('plugin.system.config.get', { name: 'hello' })
    expect(wrapper.text()).toContain('这个插件没有可配置项')
  })

  it('summarizes declared capabilities and declaration errors', async () => {
    const rpc = vi.fn(async (method: string) => {
      if (method !== 'plugin.system.list') return {}
      return {
        plugins: [
          {
            ...PLUGIN,
            capabilities: {
              tools: ['demo_echo'],
              skills: ['demo-skill'],
              hooks: [],
              mcp: [],
              commands: [],
              context: [],
            },
          },
          {
            ...PLUGIN,
            name: 'broken',
            capability_error: 'tool is missing handler',
          },
        ],
        errors: [],
      }
    })
    const wrapper = mount(CorePluginSystemEditor, { props: { requestRpc: rpc } })

    await flushPromises()

    expect(wrapper.text()).toContain('工具 1 · 技能 1')
    expect(wrapper.text()).toContain('声明错误')
  })
})
