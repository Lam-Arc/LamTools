import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import CorePluginsEditor from '../src/components/CorePluginsEditor.vue'
import { createFakeTransport } from './fake-transport'

afterEach(() => vi.useRealTimers())

function plugin(state = 'failed') {
  return {
    name: 'example', version: '1.0', root: 'bundled://example', description: 'Example',
    enabled: true, available: state === 'ready',
    backend: { state, available: state === 'ready', error: state === 'failed' ? { message: 'startup exploded' } : null },
    skills: [], hooks: [], mcp: [], tools: [], skill_names: [], hook_summary: [],
    dependencies: [], deps_status: 'none', config_schema: '',
  }
}

describe('plugin backend state', () => {
  it('shows an enabled but failed backend, preserves its diagnostic, and retries enable', async () => {
    let record = plugin()
    const rpc = vi.fn(async (method: string) => {
      if (method === 'plugin.list') return { plugins: [record], errors: [] }
      if (method === 'plugin.enable') {
        record = plugin('ready')
        return { enabled: true, available: true }
      }
      return {}
    })
    const wrapper = mount(CorePluginsEditor, { props: { requestRpc: rpc, transport: createFakeTransport() } })
    try {
      await flushPromises()
      expect(wrapper.find('[role="alert"]').text()).toContain('startup exploded')
      const retry = wrapper.findAll('button').find(button => button.text().includes('重试启动'))!
      expect(retry.exists()).toBe(true)
      await retry.trigger('click')
      await flushPromises()
      expect(rpc).toHaveBeenCalledWith('plugin.enable', { name: 'example' })
      expect(wrapper.text()).toContain('已就绪')
      expect(wrapper.text()).not.toContain('startup exploded')
    } finally { wrapper.unmount() }
  })

  it('does not present a failed retry as successful even if RPC resolves an error payload', async () => {
    const rpc = vi.fn(async (method: string) => method === 'plugin.list'
      ? { plugins: [plugin()], errors: [] }
      : { error: 'startup exploded again', available: false })
    const wrapper = mount(CorePluginsEditor, { props: { requestRpc: rpc, transport: createFakeTransport() } })
    try {
      await flushPromises()
      await wrapper.findAll('button').find(button => button.text().includes('重试启动'))!.trigger('click')
      await flushPromises()
      expect(wrapper.text()).toContain('startup exploded again')
      expect(wrapper.findAll('button').some(button => button.text().includes('重试启动'))).toBe(true)
    } finally { wrapper.unmount() }
  })

  it('refreshes a backend crash while open and stops polling on unmount', async () => {
    const rpc = vi.fn().mockResolvedValue({ plugins: [plugin('ready')], errors: [] })
    const wrapper = mount(CorePluginsEditor, { props: { requestRpc: rpc, transport: createFakeTransport() } })
    await flushPromises()
    // The interval uses the browser clock; allow one real refresh cycle.
    rpc.mockResolvedValue({ plugins: [plugin()], errors: [] })
    await vi.waitFor(() => expect(wrapper.text()).toContain('startup exploded'), { timeout: 3000 })
    wrapper.unmount()
    const calls = rpc.mock.calls.length
    await new Promise(resolve => setTimeout(resolve, 50))
    expect(rpc.mock.calls.length).toBe(calls)
  })
})
