import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import PluginMarket from '../src/components/PluginMarket.vue'

// user:“交互测试”+(展厅可注入本地链接处理，不触发真实外部打开)。
describe('plugin market isolated repository action', () => {
  it('routes repository links through an injected handler', async () => {
    const openRepository = vi.fn()
    const requestRpc = vi.fn(async () => ({ plugins: [{ id: 'sample', title: '示例', description: '', category: '工具', capabilities: [], version: '1', installed_version: '', update_available: false, installable: true, repository_url: 'https://example.invalid/sample' }] }))
    const wrapper = mount(PluginMarket, { props: { requestRpc, openRepository } })
    await flushPromises()
    await wrapper.get('.market-meta button').trigger('click')
    expect(openRepository).toHaveBeenCalledWith('https://example.invalid/sample')
    wrapper.unmount()
  })
})
